"""热点流水线：collect -> store -> score -> judge -> render -> notify。
多轮同库同 topic 靠 db UNIQUE(topic_key,source,fetched_at) 去重，斜率读历史窗口。"""
import argparse, datetime, json, os, time, yaml
from collections import defaultdict
from db import init_db, save_signals, history, prune
from collectors.registry import get_collectors
from scoring.score import aggregate_topics, composite
from scoring.buckets import pick_fast, pick_trend
from llm_judge.prompt import build_pack, pick_track
from llm_judge.judge import judge_topic
from render.report import render_daily
from render.board import render_board
from render.notifier import notify
from render.push_policy import load_state, save_state, plan_push
from llm_judge.cluster import assign_event_ids

ROOT = os.path.dirname(os.path.abspath(__file__))

def _now_hour() -> int:
    return datetime.datetime.now().hour

def load_cfg(path=None) -> dict:
    with open(path or os.path.join(ROOT, "config.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f)

def _age_hours(conn, key: str) -> float:
    rows = history(conn, key, hours=24 * 30)
    if not rows:
        return 0.0
    try:
        first = datetime.datetime.fromisoformat(rows[0]["fetched_at"])
        return max(0.0, (datetime.datetime.now() - first).total_seconds() / 3600.0)
    except Exception:
        return 0.0

def _rank_delta(conn, s) -> int:
    row = conn.execute(
        "SELECT rank FROM signals WHERE topic_key=? AND source=? "
        "ORDER BY fetched_at DESC LIMIT 1",
        (s.topic_key, s.source)).fetchone()
    if not row or row[0] is None or s.rank is None:
        return 0
    return max(0, int(row[0]) - int(s.rank))

def _day_series(conn, key: str, window_days: int) -> list:
    rows = history(conn, key, hours=window_days * 24)
    buckets = defaultdict(float)
    for r in rows:
        buckets[str(r["fetched_at"])[:10]] += r["engagement"]
    return [buckets[d] for d in sorted(buckets)]

def _grade(t: dict, cfg: dict, age_label: str, enabled: bool) -> tuple:
    """返回 (fallback_count, 该话题是否降级)。enabled=False 只机械分档不调 LLM。"""
    t.setdefault("track", pick_track(t.get("title", ""), cfg.get("tracks", {})))
    if not enabled:
        return 0, True
    pack = build_pack(t, age_label)
    r = judge_topic(pack, cfg)
    if r is None:
        for k in ("rating", "hook_reason", "angle", "track"):
            t[k] = ""
        t["act_now"] = False
        return 0, True
    t.update(r)
    used_backup = r.get("model") != cfg.get("llm", {}).get("model")
    return (1 if used_backup else 0), False

def run_round(cfg: dict) -> dict:
    date_str = datetime.date.today().isoformat()
    db_path = cfg.get("db_path") or os.path.join(ROOT, "热点.db")
    out_dir = cfg.get("out_dir") or ROOT
    conn = init_db(db_path)

    signals, failed = [], []
    for mod in get_collectors(cfg):
        try:
            got = mod(cfg)
            for s in got:
                s.rank_delta = _rank_delta(conn, s)
            signals.extend(got)
            save_signals(conn, got)
        except Exception as e:
            failed.append(f"{mod.__module__}: {type(e).__name__}")
    prune(conn)
    sources = sorted({s.source for s in signals})

    topics = aggregate_topics(signals) if signals else []
    for t in topics:
        t["age_hours"] = _age_hours(conn, t["key"])
        t["hist"] = history(conn, t["key"], hours=168)
        t["url"] = t["signals"][0].url if t["signals"] else ""
        t["tracks"] = cfg.get("tracks", {})
        t["is_new"] = t["age_hours"] <= cfg["thresholds"]["fast"]["max_age_h"]
        t["track"] = pick_track(t.get("title", ""), cfg.get("tracks", {}))
        t.update(composite(t, t["hist"], cfg))

    fast = pick_fast(topics, cfg)
    window = cfg.get("thresholds", {}).get("trend", {}).get("window_days", 7)
    series = {t["key"]: _day_series(conn, t["key"], window) for t in topics}
    trend = pick_trend(topics, cfg, series)

    use_llm = bool(cfg.get("use_llm", True))
    fb, degraded = 0, not use_llm
    for bucket, label in ((fast, "快讯档"), (trend, "趋势推荐")):
        for t in bucket:
            f, d = _grade(t, cfg, label, use_llm)
            fb += f
            degraded = degraded or d

    state_path = os.path.join(out_dir, "states", "push_state.json")
    st = load_state(state_path)
    # 事件级去重（2026-10-03）：同事件不同标题只推一次。保守合并；
    # --no-llm 或 LLM 失败自动降级本地聚类，永不比只按 key 去重更糟。
    eids = assign_event_ids(fast, st.get("pushed_events") or {}, cfg,
                            enabled=use_llm)
    for t in fast:
        t["event_id"] = eids.get(t.get("key"), "e:" + (t.get("key") or ""))

    meta = {"llm_model": cfg.get("llm", {}).get("model", "-") if use_llm else "已禁用(--no-llm)",
            "llm_fallback_count": fb, "degraded": degraded,
            "sources": sources, "db_path": db_path}
    md = render_daily(date_str, fast, trend, meta)
    board = render_board({"date": date_str, "fast": fast, "trend": trend, "meta": meta})

    report_path = os.path.join(out_dir, "日报", date_str + ".md")
    board_path = os.path.join(out_dir, "看板", date_str + ".html")
    os.makedirs(os.path.dirname(report_path), exist_ok=True)
    os.makedirs(os.path.dirname(board_path), exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(md)
    with open(board_path, "w", encoding="utf-8") as f:
        f.write(board)

    pushes = [{"kind": k, "result": notify(t, c, cfg)}
              for k, t, c in plan_push(st, date_str, fast, trend,
                                       degraded, failed, board_path,
                                       hour=_now_hour(),
                                       breaking_cap=cfg.get("thresholds", {})
                                       .get("fast", {}).get("breaking", {})
                                       .get("max_push_per_day", 6))]
    save_state(state_path, st)
    conn.close()
    return {"status": "ok", "date": date_str, "report_path": report_path,
            "board_path": board_path, "fast": len(fast), "trend": len(trend),
            "signals": len(signals), "failed_sources": failed,
            "degraded": degraded, "push": pushes}

def main():
    ap = argparse.ArgumentParser(description="热点预测调度流水线")
    ap.add_argument("--dry-run", action="store_true", help="只出日报和看板（推送仍执行，无key默认跳过）")
    ap.add_argument("--no-llm", action="store_true", help="禁用LLM（纯机械评分，日报标降级）")
    ap.add_argument("--config", default=os.path.join(ROOT, "config.yaml"))
    ap.add_argument("--loop", type=int, default=0, help=">0 则按该秒数循环执行")
    a = ap.parse_args()
    cfg = load_cfg(a.config)
    cfg["dry_run"] = a.dry_run
    cfg["use_llm"] = not a.no_llm
    while True:
        try:
            print(json.dumps(run_round(cfg), ensure_ascii=False, default=str))
        except Exception as e:
            print(json.dumps({"status": "error", "error": f"{type(e).__name__}: {e}"},
                             ensure_ascii=False))
        if not a.loop:
            break
        time.sleep(a.loop)

if __name__ == "__main__":
    main()
