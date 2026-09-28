"""SQLite 持久层：写入去重 + 轮次聚合历史查询。"""
import sqlite3, json, datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_key TEXT NOT NULL, source TEXT NOT NULL, title TEXT, url TEXT,
  heat REAL, rank INTEGER, rank_delta INTEGER, engagement REAL,
  author_weight REAL, published_at TEXT, fetched_at TEXT, raw TEXT,
  UNIQUE(topic_key, source, fetched_at)
);
CREATE INDEX IF NOT EXISTS idx_key_time ON signals(topic_key, fetched_at);
"""

def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

def save_signals(conn, signals) -> int:
    n = 0
    for s in signals:
        cur = conn.execute(
            "INSERT OR IGNORE INTO signals(topic_key,source,title,url,heat,rank,"
            "rank_delta,engagement,author_weight,published_at,fetched_at,raw) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (s.topic_key, s.source, s.title, s.url, s.heat, s.rank, s.rank_delta,
             s.engagement, s.author_weight, s.published_at, s.fetched_at,
             json.dumps(s.raw, ensure_ascii=False, default=str)))
        n += cur.rowcount
    conn.commit()
    return n

def history(conn, key: str, hours: int = 168) -> list:
    cutoff = (datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat()
    rows = conn.execute(
        "SELECT fetched_at, SUM(engagement) AS engagement, MAX(heat) AS heat, "
        "MIN(rank) AS rank FROM signals "
        "WHERE topic_key=? AND fetched_at>=? GROUP BY fetched_at ORDER BY fetched_at",
        (key, cutoff)).fetchall()
    return [dict(r) for r in rows]
