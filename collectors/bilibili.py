"""B站热搜/榜单。实测结构 data.trending.list（兼容旧 data.list）。"""
import time, requests
from collectors.base import Signal, topic_key
from probe import UA

def parse_square(payload: dict, fetched_at: str) -> list[Signal]:
    d = payload.get("data") or {}
    rows = d.get("list") or d.get("trending", {}).get("list", []) or []
    out = []
    for i, item in enumerate(rows, 1):
        title = item.get("keyword") or item.get("title") or ""
        if not title:
            continue
        out.append(Signal(topic_key=topic_key(title), source="bilibili", title=title,
                          url="https://search.bilibili.com/all?keyword=" + title,
                          heat=float(101 - i), rank=i, rank_delta=0,
                          engagement=float(item.get("heat", 0) or (101 - i)),
                          author_weight=0.4, fetched_at=fetched_at,
                          raw=dict(item)))
    return out

def fetch(cfg: dict) -> list[Signal]:
    r = requests.get("https://api.bilibili.com/x/web-interface/search/square?limit=30",
                     headers=UA, timeout=10)
    r.raise_for_status()
    return parse_square(r.json(), time.strftime("%Y-%m-%dT%H:%M:%S"))
