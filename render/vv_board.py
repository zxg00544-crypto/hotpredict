# -*- coding: utf-8 -*-
"""大V动向独立板块（阶段一，2026-10-05 用户批准）。

只读 signals 表出独立文件 + 钉钉 TopN（push_top），不参与评分/推送管道（不改
scoring/buckets/push_policy）。筛选：近 window_hours 内大V源 → heat 降序
→ 每人（微博 uid）≤3 → url 去重 → Top N。节流三闸：同 sig 不重推、
每日 max_push_per_day 次上限、跨日重置。

signals 表无 raw 列，取不到 screen_name，"每人"用 url 第三段 uid 判定：
https://weibo.com/{uid}/{bid}。vv 参数全部带代码内默认值（云端 config 来自
secret，本地 config.yaml 的键云端不会有）。

窗口按 published_at 发布时间过滤；解析失败回退抓取时间（2026-10-07 用户定）。"""
import datetime
import re
from email.utils import parsedate_to_datetime

from urlclean import clean_url

DEFAULTS = {"window_hours": 72, "per_author": 2, "file_top": 10,
            "push_top": 10, "max_push_per_day": 3,
            "min_distinct": 6, "min_chars": 5}
VV_SOURCES = ("weibo_v",)
EMPTY_MSG = "今日暂无大V博文"


def vv_cfg(cfg: dict) -> dict:
    """合并 config.vv 与默认值；缺键/空块/坏值一律回落默认。"""
    c = dict(DEFAULTS)
    for k, v in (cfg.get("vv") or {}).items():
        if k in DEFAULTS:
            try:
                c[k] = int(v)
            except (TypeError, ValueError):
                c[k] = DEFAULTS[k]
    return c


def _uid(url: str) -> str:
    parts = (url or "").split("/")
    if len(parts) >= 5 and "weibo.com" in (parts[2] or ""):
        return parts[3]
    return url or ""


def _published_dt(s):
    """解析微博 RFC822 风格发布时间；失败/空 → None（回退抓取时间口径）。

    用 email.utils.parsedate_to_datetime（locale 无关），勿用 strptime 的
    %a %b——Windows 中文 locale 下会解析失败。"""
    if not s:
        return None
    try:
        return parsedate_to_datetime(str(s))
    except (TypeError, ValueError):
        return None


def fetch_rows(conn, window_hours: int) -> list:
    """近 N 小时大V信号，按 heat 降序；只取可入表展示的列。

    窗口按 published_at 发布时间过滤：解析成功且早于窗口 → 丢弃；解析失败
    → 保留（回退抓取时间口径）。SQL 的 fetched_at 仍作廉价预筛兼停摆兜底。
    """
    cutoff = (datetime.datetime.now().astimezone()
              - datetime.timedelta(hours=int(window_hours)))
    cutoff_iso = cutoff.isoformat()
    marks = ",".join("?" * len(VV_SOURCES))
    rows = conn.execute(
        "SELECT title,url,heat,fetched_at,published_at,topic_key FROM signals "
        f"WHERE source IN ({marks}) AND fetched_at>=? "
        "ORDER BY heat DESC",
        (*VV_SOURCES, cutoff_iso)).fetchall()
    out = []
    for r in rows:
        pub = _published_dt(r["published_at"])
        if pub is not None and pub.tzinfo is not None and pub < cutoff:
            continue
        out.append(dict(r))
    return out


_REPOST_ONLY = ("转发微博", "轉發微博", "Repost")


def _is_junk(title, min_chars: int) -> bool:
    """过滤空转发与过短内容（2026-11-06 用户指令）。"""
    t = re.sub(r"<[^>]+>", " ", str(title or ""))
    t = re.sub(r"\s+", " ", t).strip()
    if not t:
        return True
    if t in _REPOST_ONLY:
        return True
    return len(t) < int(min_chars)


def select_top(rows: list, c: dict) -> list:
    """过滤空转发 → url 去重 → 先每号 1 条保多样性（至少 min_distinct 个号）
    → 再按 heat 补满且每人≤per_author → 截断 file_top，最终按 heat 降序。"""
    limit = int(c.get("file_top", DEFAULTS["file_top"]))
    per_limit = int(c.get("per_author", DEFAULTS["per_author"]))
    min_distinct = int(c.get("min_distinct", DEFAULTS["min_distinct"]))
    min_chars = int(c.get("min_chars", DEFAULTS["min_chars"]))

    rows = sorted(rows, key=lambda r: float(r.get("heat") or 0), reverse=True)
    cands, seen = [], set()
    for r in rows:
        u = clean_url(r.get("url") or "")
        if not u or u in seen:
            continue
        if _is_junk(r.get("title"), min_chars):
            continue
        seen.add(u)
        cands.append({**r, "url": u})

    # 第一轮：每个账号只取热度最高 1 条，凑满 min_distinct 个不同账号
    out, per, used = [], {}, set()
    cap_first = min(limit, min_distinct)
    for r in cands:
        if len(out) >= cap_first:
            break
        a = _uid(r["url"])
        if a in per:
            continue
        per[a] = 1
        used.add(id(r))
        out.append(r)

    # 第二轮：按 heat 补满剩余名额，仍受每人上限约束
    for r in cands:
        if len(out) >= limit:
            break
        if id(r) in used:
            continue
        a = _uid(r["url"])
        if per.get(a, 0) >= per_limit:
            continue
        per[a] = per.get(a, 0) + 1
        out.append(r)

    out.sort(key=lambda r: float(r.get("heat") or 0), reverse=True)
    return out[:limit]


def _author(url: str) -> str:
    return _uid(url) or "-"


def _cell(text) -> str:
    return str(text or "").replace("|", "¦").replace("\n", " ").strip()


def render_vv(items: list, date_str: str, meta: dict) -> str:
    hours = int(meta.get("window_hours", DEFAULTS["window_hours"]))
    per = int(meta.get("per_author", DEFAULTS["per_author"]))
    head = [f"# 大V动向 {date_str}", ""]
    if not items:
        return "\n".join(head + [EMPTY_MSG, ""])
    head[0] = f"# 大V动向 {date_str}（Top{len(items)}，近{hours}h）"
    lines = head + ["", "| # | 账号 | 博文 | 互动heat | 时间 |",
                    "|---|------|------|---------|------|"]
    for i, it in enumerate(items, 1):
        when = str(it.get("published_at") or it.get("fetched_at") or "")[:19]
        lines.append(f"| {i} | {_author(it.get('url'))} | "
                     f"{_cell(it.get('title'))} | {int(it.get('heat') or 0)} | "
                     f"{when} |")
    srcs = ", ".join(meta.get("sources") or []) or "无"
    lines += ["", f"- 数据源：{srcs} · 窗口{hours}h · 每人≤{per}条"
                  f" · 生成 {date_str}"]
    return "\n".join(lines) + "\n"


def plan_vv_push(items: list, state: dict, date_str: str, c: dict) -> tuple:
    """返回 (是否推送, 标题, 内容)。空数据不推；同 sig 不重推；每日封顶。
    state 就地更新，调用方负责 save_state。"""
    if not items:
        return False, "", ""
    maxn = int(c.get("max_push_per_day", DEFAULTS["max_push_per_day"]))
    if state.get("vv_date") != date_str:
        state["vv_date"] = date_str
        state["vv_count"] = 0
        state["vv_sig"] = ""
    sig = "|".join(str(i.get("url") or "") for i in items)
    if sig == state.get("vv_sig"):
        return False, "", ""
    if int(state.get("vv_count") or 0) >= maxn:
        return False, "", ""
    _win = int(c.get("window_hours", DEFAULTS["window_hours"]))
    _per = int(c.get("per_author", DEFAULTS["per_author"]))
    lines = [f"近{_win}h 互动量最高（每人≤{_per}条）："]
    for i, it in enumerate(items, 1):
        title = _cell(it.get("title"))
        lines.append(f"{i}. {_author(it.get('url'))} · {title} "
                     f"— {int(it.get('heat') or 0)}")
        if it.get("url"):
            lines.append(str(it["url"]))
    state["vv_sig"] = sig
    state["vv_count"] = int(state.get("vv_count") or 0) + 1
    return True, f"大V动向 Top{len(items)}", "\n".join(lines)
