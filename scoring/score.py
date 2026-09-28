"""复合评分：G增速0.35 / E热度0.25 / A作者0.15 / R共振0.15 / K位次0.10。阈值全在 config。"""
from collections import defaultdict

def aggregate_topics(signals) -> list[dict]:
    groups = defaultdict(list)
    for s in signals:
        groups[s.topic_key].append(s)
    out = []
    for key, ss in groups.items():
        out.append({
            "key": key,
            "title": max(ss, key=lambda x: len(x.title)).title,
            "sources": sorted({s.source for s in ss}),
            "n_sources": len({s.source for s in ss}),
            "signals": ss,
            "engagement": sum(s.engagement for s in ss),
            "heat": max((s.heat for s in ss), default=0.0),
            "rank": min((s.rank for s in ss if s.rank > 0), default=999),
            "author_weight": max((s.author_weight for s in ss), default=0.3),
            "rank_delta": max((s.rank_delta for s in ss), default=0),
            "first_seen": min(s.fetched_at for s in ss),
            "last_seen": max(s.fetched_at for s in ss),
        })
    return out

def _growth(hist: list, rank_delta: int, p: dict) -> float:
    if len(hist) >= 2:
        best = 0.0
        for prev, cur in zip(hist, hist[1:]):
            base = max(prev.get("engagement") or 0, 1.0)
            best = max(best, ((cur.get("engagement") or 0) - base) / base)
        return max(0.0, min(100.0, best * p["growth_scale"]))
    # 新话题用位次变化估计
    return max(0.0, min(100.0, rank_delta / 10.0 * p["new_topic_rank_delta_per_10"]))

def composite(topic: dict, hist: list, cfg: dict) -> dict:
    w, p = cfg["weights"], cfg["score_params"]
    G = _growth(hist, topic.get("rank_delta", 0), p)
    E = 100.0 if topic["heat"] <= 0 else max(0.0, min(100.0, topic["engagement"] / topic["heat"] * 100.0))
    A = max(0.0, min(100.0, topic["author_weight"] * 100.0))
    R = float(p["resonance_map"].get(min(topic["n_sources"], 4), 100))
    rank_score = 100.0 if topic["rank"] >= 999 else max(0.0, (200 - topic["rank"]) / 200 * 100.0)
    if topic.get("rank_delta", 0) > 0:
        rank_score = min(100.0, rank_score + p["rank_bonus_on_rise"])
    K = rank_score
    score = (w["growth"] * G + w["engagement"] * E + w["author"] * A +
             w["resonance"] * R + w["rank"] * K)
    return {"score": round(min(100.0, score), 2),
            "G": round(G, 2), "E": round(E, 2), "A": round(A, 2),
            "R": round(R, 2), "K": round(K, 2)}
