"""快讯(1-6h)与趋势(3-7d)双档桶。全部阈值来自 config.thresholds。"""

def _age_hours(t: dict) -> float:
    return float(t.get("age_hours", 0))

def pick_fast(topics: list, cfg: dict) -> list:
    f = cfg["thresholds"]["fast"]
    out = []
    for t in topics:
        if _age_hours(t) > f["max_age_h"]:
            continue
        reasons = []
        if t.get("G", 0) >= f["g_min"] and t.get("heat", 0) >= f["heat_min"]:
            reasons.append(f"增速G={t['G']}(≥{f['g_min']})热度={t.get('heat')}")
        if t.get("rank_delta", 0) >= f["rank_delta_min"]:
            reasons.append(f"位次升{t['rank_delta']}位(≥{f['rank_delta_min']})")
        if t.get("heat", 0) >= f["heat_min"] and t.get("is_new", False):
            reasons.append(f"新话题热度={t['heat']}(≥{f['heat_min']})")
        if reasons:
            out.append(dict(t, reason="；".join(reasons)))
    boost = (cfg.get("score_params") or {}).get("track_boost") or {}
    out.sort(key=lambda x: x.get("score", 0) * boost.get(x.get("track"), 1.0),
             reverse=True)
    return out[: f["top_n"]]

def pick_trend(topics: list, cfg: dict, day_series: dict) -> list:
    tr = cfg["thresholds"]["trend"]
    out = []
    for t in topics:
        series = day_series.get(t["key"], [])
        if len(series) < tr["min_days"] or t.get("score", 0) < tr["score_min"]:
            continue
        if t.get("n_sources", 1) < tr["min_sources"]:
            continue
        slope = (series[-1] - series[0]) / max(len(series) - 1, 1)
        if slope <= tr["slope_min"]:
            continue
        out.append(dict(t, slope=round(slope, 2),
                        reason=f"{len(series)}日斜率+{round(slope,2)}，{t['n_sources']}源，score={t['score']}"))
    boost = (cfg.get("score_params") or {}).get("track_boost") or {}
    out.sort(key=lambda x: x.get("score", 0) * boost.get(x.get("track"), 1.0),
             reverse=True)
    return out[: tr["top_n"]]
