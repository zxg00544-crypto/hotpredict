"""LLM 评级 + 资格校验 + 失败降级。调用走 probe_llm.llm_client_call，禁止另写 HTTP。"""
import json, re
from probe_llm import llm_client_call
from llm_judge.prompt import build_messages

VALID = {"A", "B", "C"}

def _parse_rating_ex(text: str):
    """返回 (obj, err)：成功时 err=None；失败时 obj=None 并给机器可读原因。"""
    if not text:
        return None, "empty"
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None, "no_json_brace"
    try:
        obj = json.loads(m.group(0))
    except Exception as e:
        return None, f"json_error:{type(e).__name__}"
    rating = str(obj.get("rating", "")).strip().upper()
    if rating not in VALID:
        return None, f"bad_rating:{rating[:16]}"
    obj["rating"] = rating
    try:
        obj["genre_score"] = int(obj.get("genre_score", 0))
        obj["fit_score"] = int(obj.get("fit_score", 0))
    except (TypeError, ValueError):
        return None, "bad_score"
    return obj, None

def parse_rating(text: str):
    obj, _ = _parse_rating_ex(text)
    return obj

def judge_topic(pack: dict, cfg: dict):
    res = llm_client_call(build_messages(pack), cfg)
    if not res:
        print(f"[judge] llm_none title={str(pack.get('title'))[:60]}", flush=True)
        return None
    obj, err = _parse_rating_ex(res.get("content"))
    if obj is None:
        head = str(res.get("content") or "")[:120]
        print(f"[judge] parse_fail reason={err} model={res.get('model', '')} "
              f"title={str(pack.get('title'))[:60]} head={head}", flush=True)
        return None
    valid_tracks = set((cfg.get("tracks") or {}).keys()) | {"其他"}
    if obj.get("track") not in valid_tracks:
        obj.pop("track", None)
    obj["model"] = res.get("model", "")
    return obj
