"""LLM 探针与 OpenAI 兼容调用。key 只在内存里，不写日志不落盘。"""
import json, os, sys, time, requests
import yaml

# agnes 限速诊断（2026-10-04）：日 text 用尽后降为 1 请求/分钟（429 + Retry-After）；
# 另有 free user rate limit 429（无/小 Retry-After，窗口实测 60~244s 不等）。
# 统一策略：429 共享冷却 max(Retry-After,60s)+1s 且不消耗普通 retries，
# 单模型冷却总等待 wait_budget_s(245s) 封顶，防病态打转拖垮整轮。
_last_call_ts = 0.0
_next_ok_ts = 0.0


def load_cfg(path="config.yaml"):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_llm_cfg(cfg: dict) -> dict:
    l = cfg["llm"]
    path = l.get("config_path")
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            prov = json.load(f)["provider"][l["provider"]]
        base_url = prov["options"]["baseURL"].rstrip("/")
        api_key = prov["options"]["apiKey"]
    elif l.get("api_key"):
        base_url = (l.get("base_url") or "https://api.deepseek.com").rstrip("/")
        api_key = l["api_key"]
    else:
        raise ValueError("llm.api_key missing and config_path not found")
    return {"base_url": base_url,
            "api_key": api_key,
            "model": l["model"],
            "fallback_models": l.get("fallback_models") or [],
            "timeout_topic": l.get("timeout_topic", 15),
            "retries": l.get("retries", 2)}

def pick_model(llm: dict) -> list:
    return [llm["model"]] + list(llm.get("fallback_models") or [])

def chat(messages, llm_cfg, model, json_mode=True):
    body = {"model": model, "messages": messages, "temperature": 0.2}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    r = requests.post(llm_cfg["base_url"] + "/chat/completions",
                      headers={"Authorization": "Bearer " + llm_cfg["api_key"],
                               "Content-Type": "application/json"},
                      json=body, timeout=llm_cfg["timeout_topic"])
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def _retry_after_sec(e) -> int:
    try:
        v = e.response.headers.get("Retry-After")
        return int(float(v)) if v else 60
    except Exception:
        return 60

def llm_client_call(messages, cfg, json_mode=True):
    """按备选链依次尝试；返回 {'content':str,'model':str} 或 None。
    429/503：共享冷却 max(Retry-After,60s)+1s，不消耗普通 retries；
    单模型冷却总等待超 wait_budget_s（默认245s，实测窗口需60~244s）则换下一模型，
    链尾仍超预算返回 None，防病态打转拖垮整轮。"""
    global _last_call_ts, _next_ok_ts
    try:
        llm = load_llm_cfg(cfg)
    except Exception:
        return None
    lcfg = cfg.get("llm") or {}
    pace = float(lcfg.get("pace_s", 2))
    wait_budget = float(lcfg.get("wait_budget_s", 245))
    for model in pick_model(llm):
        attempts_left = llm["retries"] + 1
        total_cool = 0.0
        while attempts_left > 0:
            now = time.time()
            cool = max(0.0, _next_ok_ts - now)
            pace_wait = max(0.0, _last_call_ts + pace - now)
            wait = max(cool, pace_wait)
            if wait > 0:
                if cool > 0:
                    if total_cool + cool > wait_budget:
                        break
                    total_cool += cool
                time.sleep(min(wait, 90))
            _last_call_ts = time.time()
            try:
                return {"content": chat(messages, llm, model, json_mode), "model": model}
            except requests.HTTPError as e:
                code = getattr(getattr(e, "response", None), "status_code", None)
                if code in (429, 503):
                    ra = max(_retry_after_sec(e), 60) + 1
                    _next_ok_ts = time.time() + ra
                    continue
                attempts_left -= 1
                continue
            except Exception:
                attempts_left -= 1
                continue
    return None

if __name__ == "__main__":
    cfg = load_cfg(sys.argv[1] if len(sys.argv) > 1 else "config.yaml")
    res = llm_client_call([{"role": "user",
                            "content": "只输出JSON：{\"ok\": true}"}], cfg)
    if res is None:
        print("LLM PROBE FAIL all models exhausted")
        sys.exit(1)
    try:
        json.loads(res["content"])
        print("LLM PROBE PASS model=" + res["model"])
    except Exception as e:
        print("LLM PROBE FAIL json: " + str(e))
        sys.exit(1)
