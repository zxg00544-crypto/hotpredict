"""事件级聚类：同一事件的多条不同标题只推一次。

保守原则（2026-10-03 用户拍板）：宁可重复、不漏推。只有 LLM 标 confidence=high
且组内两两字面共享至少一个实词时才合并；拿不准一律各自独立 event_id，
绝不把两件不同的事压成一条。

三级降级，任何一级都比改动前只按 key 去重更严或持平，不会更糟：
1) LLM 批量判定（每轮 1 次调用，输入 = 本轮候选 + 今日已推事件锚点）
2) 本地保守聚类（bigram Jaccard>=0.40 或归一化后长度>=4 互为子串 + 并查集）
3) 逐条独立 event_id（event_id == "e:"+key，等价于改动前的 key 去重）
调用走 probe_llm.llm_client_call，禁止另写 HTTP。"""
import itertools
import json
import re

from probe_llm import llm_client_call

_JACCARD_MIN = 0.40      # 本地降级阈值（2026-10-03 实测：63→56，抓 4 簇 11 条）
_LEN_MIN = 4             # 互为子串判定的最短归一化长度
_EID_PREFIX = "e:"
_EID_MAX = 40            # event_id 里归一化标题的截断长度

SYSTEM = (
    "你是事件去重判定员。给你一批候选热点标题，以及今天已经推送过的事件代表标题。"
    "只输出一个 JSON 对象，不要任何解释文字。\n"
    "输出格式：{\"groups\":[{\"members\":[\"c1\",\"c2\"],\"confidence\":\"high|low\"}]}。"
    "members 里填候选编号；若这组候选其实是下面某个已推事件，members 里填对应的锚点编号"
    "(如 e1)和这些候选编号，confidence 必须是 high。\n"
    "每个候选编号必须且只能出现在一个组里，不要遗漏。\n"
    "判定规则：\n"
    "1. 只有当你能确定两条标题报道的是同一件事时才归为一组（同一政策的不同媒体标题、"
    "同一发布的不同角度快讯等）。\n"
    "2. 同一公司/同一主题但不同事件必须分开，例如「公司发布产品」与「公司完成融资」不是一件事。\n"
    "3. 主体、数字、时间任一不同，视为不同事件。\n"
    "4. 拿不准就单独成组并标 confidence=low。\n"
    "5. 保守优先：漏判重复比错判合并代价小。"
)


def _norm(s: str) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


def _shingles(s: str) -> set:
    n = _norm(s)
    if not n:
        return set()
    return {n[i:i + 2] for i in range(len(n) - 1)} or {n}


def _share_any(a: str, b: str) -> bool:
    """字面是否共享至少一个实词（中文 2-gram / 英文词）。合并的必要条件，
    挡住模型把完全无关的标题并成一组（= 漏推）。"""
    sa, sb = _shingles(a), _shingles(b)
    return bool(sa and sb and (sa & sb))


def _similar(a: str, b: str) -> bool:
    """本地保守相似判定：Jaccard>=0.40 或 归一化后长度>=4 互为子串。"""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    sa, sb = _shingles(a), _shingles(b)
    if len(sa & sb) / float(len(sa | sb)) >= _JACCARD_MIN:
        return True
    if len(na) >= _LEN_MIN and len(nb) >= _LEN_MIN and (na in nb or nb in na):
        return True
    return False


def _eid_for(title: str, key: str, tag: int) -> str:
    body = _norm(title)[:_EID_MAX] or _norm(key)[:_EID_MAX]
    return _EID_PREFIX + (body or "g%d" % tag)


def local_cluster(items: list) -> dict:
    """第 2 级降级：本地保守聚类。items: [{"key","title","score"}] -> {key: event_id}"""
    titles = [it.get("title") or it.get("key") or "" for it in items]
    n = len(items)
    par = list(range(n))

    def find(x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            par[rb] = ra

    for i, j in itertools.combinations(range(n), 2):
        if _similar(titles[i], titles[j]):
            union(i, j)

    groups = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)

    out = {}
    for tag, idxs in enumerate(groups.values()):
        rep = max(idxs, key=lambda i: float(items[i].get("score") or 0))
        eid = _eid_for(titles[rep], items[rep].get("key") or "", tag)
        for i in idxs:
            out[items[i].get("key", "")] = eid
    return out


def _build_messages(cands: list, anchors: dict) -> list:
    clist = [{"id": "c%d" % i, "title": (c.get("title") or "")[:80]}
             for i, c in enumerate(cands)]
    alist = [{"id": "e%d" % i, "title": (t or "")[:80]}
             for i, t in enumerate(anchors.values())]
    user = ("已推事件锚点：" + json.dumps(alist, ensure_ascii=False) + "\n"
            + "本轮候选：" + json.dumps(clist, ensure_ascii=False))
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": user}]


def _parse_groups(text: str, cands: list, anchors: dict):
    """解析 LLM 分组。成功返回 {key: event_id}，失败返回 None。
    保守三闸：confidence 必须 high、组内两两共享实词、锚点匹配还要
    候选与锚点代表标题共享实词。任一不过即拆成独立组。"""
    if not text:
        return None
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except Exception:
        return None
    raw = obj.get("groups")
    if not isinstance(raw, list):
        return None

    keys = [c.get("key", "") for c in cands]
    titles = [c.get("title") or c.get("key") or "" for c in cands]
    anchor_ids = ["e%d" % i for i in range(len(anchors))]
    anchor_eids = list(anchors.keys())
    anchor_reps = list(anchors.values())

    parent = list(range(len(cands)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    matched_anchor = {}   # idx -> anchor_eid
    seen = set()
    for g in raw:
        if not isinstance(g, dict):
            return None
        members = g.get("members") or []
        if not isinstance(members, list):
            return None
        idxs, anchors_hit = [], []
        for mid in members:
            mid = str(mid)
            if mid.startswith("c") and mid[1:].isdigit():
                i = int(mid[1:])
                if 0 <= i < len(cands):
                    idxs.append(i)
                    seen.add(i)
            elif mid in anchor_ids:
                anchors_hit.append(mid)
        if not idxs:
            continue
        if str(g.get("confidence", "")).strip().lower() != "high":
            continue                       # 保守闸1：low 一律不合并
        for i, j in itertools.combinations(idxs, 2):
            if not _share_any(titles[i], titles[j]):
                idxs = [i]                  # 保守闸2：无共享实词则拆组
                break
        if anchors_hit:
            aeid = anchor_eids[anchor_ids.index(anchors_hit[0])]
            arep = anchor_reps[anchor_ids.index(anchors_hit[0])]
            # 保守闸3：归入已推事件还须与锚点标题共享实词，否则视为未推
            if all(_share_any(titles[i], arep) for i in idxs):
                for i in idxs:
                    matched_anchor[i] = aeid
                continue
        if len(idxs) >= 2:
            rep = max(idxs, key=lambda i: float(cands[i].get("score") or 0))
            eid = _eid_for(titles[rep], keys[rep], rep)
            for i in idxs[1:]:
                union(idxs[0], i)
            for i in idxs:
                matched_anchor.setdefault(i, eid)

    if not seen:
        return None

    out = {}
    for i, k in enumerate(keys):
        if i in matched_anchor:
            out[k] = matched_anchor[i]
        elif i in seen:
            out[k] = matched_anchor.get(find(i)) or _eid_for(titles[i], keys[i], i)
        else:
            out[k] = _eid_for(titles[i], keys[i], i)
    return out


def assign_event_ids(cands: list, anchors: dict, cfg: dict, enabled: bool = True):
    """给本轮候选打 event_id。cands=[{"key","title","score"}]，
    anchors={event_id: rep_title}（今日已推事件）。返回 {key: event_id}。"""
    if not cands:
        return {}
    if not enabled:
        return local_cluster(cands)
    res = llm_client_call(_build_messages(cands, anchors), cfg)
    mapped = None
    if res:
        mapped = _parse_groups(res.get("content"), cands, anchors)
    if mapped is None:
        mapped = local_cluster(cands)
    for c in cands:
        mapped.setdefault(c.get("key", ""),
                          _eid_for(c.get("title") or "", c.get("key") or "", 0))
    return mapped
