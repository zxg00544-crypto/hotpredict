"""Reddit（匿名 API 已 403 封禁，config 默认关闭；保留实现待 OAuth key 后启用）。"""
import time, requests
from collectors.base import Signal, topic_key
from probe import UA

def parse_popular(payload: dict, fetched_at: str) -> list[Signal]:
    out = []
    for i, ch in enumerate(payload.get("data", {}).get("children", []), 1):
        d = ch.get("data", {})
        title = d.get("title", "")
        out.append(Signal(topic_key=topic_key(title), source="reddit", title=title,
                          url="https://www.reddit.com" + d.get("permalink", ""),
                          heat=float(d.get("score", 0)), rank=i, rank_delta=0,
                          engagement=float((d.get("score", 0) or 0) +
                                           (d.get("num_comments", 0) or 0)),
                          author_weight=0.3, fetched_at=fetched_at, raw=dict(d)))
    return out

def fetch(cfg: dict) -> list[Signal]:
    r = requests.get("https://www.reddit.com/r/popular.json?limit=25",
                     headers=UA, timeout=10)
    r.raise_for_status()
    return parse_popular(r.json(), time.strftime("%Y-%m-%dT%H:%M:%S"))
