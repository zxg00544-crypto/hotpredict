"""快讯(1-6h)与趋势(3-7d)双档桶。全部阈值来自 config.thresholds。"""

def _age_hours(t: dict) -> float:
    return float(t.get("age_hours", 0))

def _mark_breaking(t: dict, f: dict) -> bool:
    """⚡突发信号（独立于 A/B/C）：新话题≤2h 且命中任一铁信号——
    跨源共振(n_sources≥top级) / 登顶(top_rank内) / 真热度(heat_high以上)。
    不用 rank_delta：实测榜位抖动使 10/10 话题都>=15，全是噪声。"""
    b = f.get("breaking") or {}
    if not b:
        return False
    if _age_hours(t) > float(b.get("max_age_h", 2)):
        return False
    if not t.get("is_new", False):
        return False
    hit = ""
    if t.get("n_sources", 1) >= b.get("min_sources", 2):
        hit = f"{t['n_sources']}源共振"
    elif t.get("rank", 999) <= b.get("top_rank", 5):
        hit = f"登顶rank={t['rank']}"
    elif t.get("heat", 0) >= b.get("heat_high", 200):
        hit = f"真热度={t['heat']:.0f}"
    if hit:
        t["breaking"] = True
        t["breaking_hit"] = hit
        return True
    return False

def pick_fast(topics: list, cfg: dict) -> list:
    f = cfg["thresholds"]["fast"]
    out = []
    for t in topics:
        if _age_hours(t) > f["max_age_h"]:
            continue
        breaking = _mark_breaking(t, f)
        reasons = []
        if t.get("G", 0) >= f["g_min"] and t.get("heat", 0) >= f["heat_min"]:
            reasons.append(f"增速G={t['G']}(≥{f['g_min']})热度={t.get('heat')}")
        if t.get("rank_delta", 0) >= f["rank_delta_min"]:
            reasons.append(f"位次升{t['rank_delta']}位(≥{f['rank_delta_min']})")
        if t.get("heat", 0) >= f["heat_min"] and t.get("is_new", False):
            reasons.append(f"新话题热度={t['heat']}(≥{f['heat_min']})")
        if breaking:
            reasons.insert(0, f"⚡突发({t.get('breaking_hit','')}"
                              f"/≤{f.get('breaking',{}).get('max_age_h',2)}h)")
        if reasons:
            out.append(dict(t, reason="；".join(reasons)))
    boost = (cfg.get("score_params") or {}).get("track_boost") or {}
    # ⚡突发置顶，其余按 track_boost 提权后的分数降序
    out.sort(key=lambda x: (not x.get("breaking", False),
                            -(x.get("score", 0) * boost.get(x.get("track"), 1.0))))
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
