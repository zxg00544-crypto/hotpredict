"""头条热榜（社会/时政突发主力源：公开 JSON 榜单，免签）。"""
import time, requests
from collectors.base import Signal, topic_key
from probe import UA

URL = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"


def parse_board(payload: dict, fetched_at: str) -> list[Signal]:
    out = []
    for i, item in enumerate(payload.get("data") or [], 1):
        title = (item.get("Title") or item.get("title") or "").strip()
        if not title:
            continue
        # heat 与 finance_sina 同量纲（200-4*rank，首条 196<200），跨源可比且
        # 不靠绝对热度撞 breaking.heat_high=200；登顶靠 rank<=5 命中。
        heat = 200.0 - i * 4.0
        out.append(Signal(topic_key=topic_key(title), source="toutiao", title=title,
                          url=item.get("Url") or "https://www.toutiao.com/",
                          heat=heat, rank=i, rank_delta=0, engagement=heat,
                          author_weight=0.8,
                          fetched_at=fetched_at,
                          raw={"cluster_id": item.get("ClusterId"),
                               "hot": item.get("HotValue"),
                               "label": item.get("Label") or ""}))
    return out


def fetch(cfg: dict) -> list[Signal]:
    r = requests.get(URL, headers=UA, timeout=10)
    r.raise_for_status()
    return parse_board(r.json(), time.strftime("%Y-%m-%dT%H:%M:%S"))
