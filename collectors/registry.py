"""按 config.platforms 开关返回启用源；weibo_v 无 Cookie 自动跳过（weibo 已免 Cookie）。"""
import importlib

_MODULES = ["zhihu", "bilibili", "weibo", "weibo_v", "hn", "reddit", "github",
            "finance_sina", "toutiao", "baidu"]

def get_collectors(cfg: dict) -> list:
    out = []
    for name in _MODULES:
        if not cfg.get("platforms", {}).get(name, False):
            continue
        if name == "weibo_v" and not str(cfg.get("weibo_cookie") or "").strip():
            continue
        out.append(importlib.import_module("collectors." + name).fetch)
    return out
