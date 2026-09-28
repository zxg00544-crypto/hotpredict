"""微博大V发言时间线（config.weibo_v_vvs 名单，需 Cookie，逐博拉取）。"""
import re, time, requests
from collectors.base import Signal, topic_key
from probe import UA

def _strip(html: str) -> str:
    t = re.sub(r"<[^>]+>", " ", html or "")
    return re.sub(r"\s+", " ", t).strip()

def parse_feed(uid: int, payload: dict, fetched_at: str) -> list[Signal]:
    out, i = [], 0
    for card in (payload.get("data") or {}).get("cards", []):
        if card.get("card_type") != 9:
            continue
        mb = card.get("mblog") or {}
        text = _strip(mb.get("text") or "")
        if not text:
            continue
        i += 1
        att = float(mb.get("attitudes_count") or 0)
        com = float(mb.get("comments_count") or 0)
        rep = float(mb.get("reposts_count") or 0)
        heat = att + com * 2 + rep * 3
        u = mb.get("user") or {}
        uid_s = str(u.get("id") or uid)
        bid = mb.get("bid") or mb.get("id")
        out.append(Signal(topic_key=topic_key(text[:48]), source="weibo_v",
                          title=text[:48],
                          url=f"https://weibo.com/{uid_s}/{bid}",
                          heat=heat, rank=i, rank_delta=0, engagement=heat,
                          author_weight=1.0,
                          published_at=str(mb.get("created_at") or ""),
                          fetched_at=fetched_at,
                          raw={"screen_name": u.get("screen_name") or "", "uid": uid_s}))
    return out

def fetch(cfg: dict) -> list[Signal]:
    cookie = str(cfg.get("weibo_cookie") or "").strip()
    if not cookie:
        return []
    h = dict(UA); h["Cookie"] = cookie
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    out = []
    for vv in cfg.get("weibo_v_vvs") or []:
        uid = int(vv["uid"])
        url = (f"https://m.weibo.cn/api/container/getIndex?type=uid&value={uid}"
               f"&containerid=107603{uid}")
        try:
            r = requests.get(url, headers=h, timeout=10)
            r.raise_for_status()
            if r.json().get("ok") == 1:
                out.extend(parse_feed(uid, r.json(), now))
        except Exception:
            continue
        time.sleep(0.4)
    return out
