"""HackerNews：topstories -> 前30。engagement = score + 评论数。"""
import time, requests
from collectors.base import Signal, topic_key
from probe import UA

TOP = "https://hacker-news.firebaseio.com/v0/topstories.json"
ITEM = "https://hacker-news.firebaseio.com/v0/item/{}.json"

def parse_item(item: dict, fetched_at: str) -> Signal:
    score = item.get("score", 0) or 0
    cmts = item.get("descendants", 0) or 0
    return Signal(topic_key=topic_key(item.get("title", "")), source="hn",
                  title=item.get("title", ""), url=item.get("url") or
                  "https://news.ycombinator.com/item?id=%s" % item.get("id"),
                  heat=float(score), rank=0, rank_delta=0,
                  engagement=float(score + cmts), author_weight=0.4,
                  published_at=str(item.get("time", "")), fetched_at=fetched_at,
                  raw={"score": score, "descendants": cmts})

def fetch(cfg: dict) -> list[Signal]:
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    ids = requests.get(TOP, headers=UA, timeout=10).json()[:30]
    out = []
    for i in ids:
        it = requests.get(ITEM.format(i), headers=UA, timeout=10).json()
        if it and it.get("type") == "story":
            s = parse_item(it, ts)
            s.rank = len(out) + 1
            out.append(s)
    return out
