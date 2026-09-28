"""知乎热榜。接口与解析同 probe.py（实测 www 端点 401，用 api.zhihu.com）。"""
import time, requests
from collectors.base import Signal, topic_key
from probe import UA

URL = "https://api.zhihu.com/topstory/hot-list"

def parse_hot_list(payload: dict, fetched_at: str) -> list[Signal]:
    out = []
    for i, item in enumerate(payload.get("data", []), 1):
        t = item.get("target") or {}
        title = t.get("title", "")
        raw_heat = "".join(ch for ch in item.get("detail_text", "") if ch.isdigit()) or "0"
        heat = float(raw_heat)
        out.append(Signal(topic_key=topic_key(title), source="zhihu", title=title,
                          url="https://www.zhihu.com/question/" + str(t.get("id", 0)),
                          heat=heat, rank=i, rank_delta=0, engagement=heat,
                          author_weight=0.6, published_at="", fetched_at=fetched_at,
                          raw={"detail_text": item.get("detail_text", "")}))
    return out

def fetch(cfg: dict) -> list[Signal]:
    r = requests.get(URL, headers=UA, timeout=10)
    r.raise_for_status()
    return parse_hot_list(r.json(), time.strftime("%Y-%m-%dT%H:%M:%S"))
