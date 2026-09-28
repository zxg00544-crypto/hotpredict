"""微博热搜（需 Cookie，registry 验证后才注册本源）。"""
import time, requests
from collectors.base import Signal, topic_key
from probe import UA

CID = "106003type%3D25%26t%3D3%26disable_hot%3D1%26filter_type%3Drealtimehot"

def parse_container(payload: dict, fetched_at: str) -> list[Signal]:
    out, i = [], 0
    for card in payload.get("data", {}).get("cards", []):
        for g in card.get("card_group", []):
            title = g.get("desc", "")
            if not title:
                continue
            i += 1
            out.append(Signal(topic_key=topic_key(title), source="weibo", title=title,
                              url="https://s.weibo.com/weibo?q=" + title,
                              heat=float(g.get("num", 0) or max(0, 200 - i * 5)),
                              rank=i, rank_delta=0,
                              engagement=float(g.get("num", 0) or 0),
                              author_weight=0.7, fetched_at=fetched_at, raw=dict(g)))
    return out

def fetch(cfg: dict) -> list[Signal]:
    h = dict(UA); h["Cookie"] = cfg["weibo_cookie"]
    r = requests.get("https://m.weibo.cn/api/container/getIndex?containerid=" + CID,
                     headers=h, timeout=10)
    r.raise_for_status()
    return parse_container(r.json(), time.strftime("%Y-%m-%dT%H:%M:%S"))
