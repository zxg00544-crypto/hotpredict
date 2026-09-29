# -*- coding: utf-8 -*-
"""热点预判 换电脑双版本打包器（设计 docs/2026-09-29-项目打包-design.md）。

用法: python -X utf8 tools/make_package.py [YYYYMMDD]
只读源目录，只写 打包\\。真实密钥零进包：模板脱敏 + 成品扫描双保险。
"""
import datetime
import json
import os
import shutil
import sys
import tempfile
import zipfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "打包")

# 设计红线：config.yaml 须脱敏的 6 键
CONFIG_SECRET_KEYS = {
    "weibo_cookie": "微博cookie",
    "api_key": "LLM api_key",
    "serverchan_sendkey": "Server酱sendkey",
    "dingtalk_webhook": "钉钉webhook",
    "dingtalk_secret": "钉钉secret",
    "dingtalk_keyword": "钉钉keyword",
}
SECRETS_JSON_KEYS = {
    "SecretId": "腾讯云SecretId",
    "SecretKey": "腾讯云SecretKey",
}

# 机路径占位：非密钥，但会暴露本机目录结构（换机后需改）。独立于 CONFIG_SECRET_KEYS，
# 走同一【行块】替换逻辑，避免多行值透传的同类缺陷复现。
MACHINE_PATH_KEYS = {
    "config_path": "本机opencode配置路径(仅本地取key用,新机器请改)",
}

DIRS_COMMON = ["collectors", "scoring", "llm_judge", "render", "tests", "docs"]
DIRS_LOCAL = ["日报", "看板", "states"]
DIRS_CLOUD = ["deploy"]
FILES_COMMON = [
    "main.py", "db.py", "scf_handler.py", "probe.py", "probe_llm.py",
    ".gitignore",
    "requirements.txt", "修订交接文档.md",
]
EXCLUDE_NAMES = {"__pycache__", "build", "fn.zip"}
EXCLUDE_FILES = {"config.yaml", "secrets_tencent.json"}


def _secret_key_line_spans(text: str) -> list:
    """返回需替换的键所在【行块】span 列表（start, end_exclusive）。

    覆盖 6 密钥键 + 机路径键（MACHINE_PATH_KEYS）。
    行块 = 键行 + 其后所有属于同一多行标量的缩进续行。判定续行用 YAML 规范：
    plain scalar 续行必须比键行缩进更深；当键行值为空（`key:` 或 `key: |` 块标量）
    时，紧随的更深缩进行全部属于该键。用键行缩进做下界，避免吞掉同级/更浅的下一键。
    """
    lines = text.splitlines()
    n = len(lines)
    spans = []
    i = 0
    while i < n:
        line = lines[i]
        if line.strip():
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if ":" in stripped:
                key, _, _val = stripped.partition(":")
                key = key.strip().strip("\"'")
                if key in CONFIG_SECRET_KEYS or key in MACHINE_PATH_KEYS:
                    j = i + 1
                    while j < n:
                        nl = lines[j]
                        if not nl:
                            break
                        nl_stripped = nl.lstrip()
                        nl_indent = len(nl) - len(nl_stripped)
                        if nl_indent <= indent:
                            break
                        j += 1
                    spans.append((i, j))
                    i = j
                    continue
        i += 1
    return spans


def sanitize_yaml(text: str) -> str:
    """脱敏 YAML。密钥键/机路径键整行块替换（含其后缩进续行，防多行标量把值透传）。

    注：不使用 yaml.safe_load→dump 方案（会丢注释/改格式，见 design）。
    """
    lines = text.splitlines()
    spans = dict(_secret_key_line_spans(text))
    labels = dict(CONFIG_SECRET_KEYS)
    labels.update(MACHINE_PATH_KEYS)
    out = []
    i = 0
    n = len(lines)
    while i < n:
        if i in spans:
            line = lines[i]
            stripped = line.lstrip()
            indent = line[: len(line) - len(stripped)]
            key = stripped.partition(":")[0].strip().strip("\"'")
            out.append("%s%s: <填写:%s>" % (indent, key, labels[key]))
            i = spans[i]
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out) + ("\n" if text.endswith("\n") else "")


def sanitize_secrets_json(text: str) -> str:
    data = json.loads(text)
    for k, label in SECRETS_JSON_KEYS.items():
        if k in data:
            data[k] = "<填写:%s>" % label
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def _iter_files(version: str):
    assert version in ("local", "cloud"), version
    dirs = list(DIRS_COMMON) + (DIRS_LOCAL if version == "local" else DIRS_CLOUD)
    for name in FILES_COMMON:
        yield name
    yield "README-本地版.md" if version == "local" else "README-云端版.md"
    for d in dirs:
        base = os.path.join(ROOT, d)
        if not os.path.isdir(base):
            continue
        for dp, dns, fns in os.walk(base):
            dns[:] = [x for x in dns if x not in EXCLUDE_NAMES]
            rel = os.path.relpath(dp, ROOT).replace("\\", "/")
            for fn in sorted(fns):
                if fn.endswith(".pyc") or fn in EXCLUDE_FILES or fn in EXCLUDE_NAMES:
                    continue
                yield (rel + "/" + fn).replace("//", "/")
    if version == "local":
        yield "热点.db"
        yield "install_schedule.ps1"
        yield "run_once.ps1"


def make_templates(dst: str) -> None:
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as _f:
        cfg = _f.read()
    with open(os.path.join(dst, "config.example.yaml"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sanitize_yaml(cfg))
    with open(os.path.join(ROOT, "secrets_tencent.json"), encoding="utf-8") as _f:
        sec = _f.read()
    with open(os.path.join(dst, "secrets_tencent.example.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write(sanitize_secrets_json(sec))


def real_secret_values() -> list:
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as _f:
        cfg = yaml.safe_load(_f)
    vals = [cfg.get("weibo_cookie"), (cfg.get("llm") or {}).get("api_key")]
    notify = cfg.get("notify") or {}
    for k in ("serverchan_sendkey", "dingtalk_webhook", "dingtalk_secret", "dingtalk_keyword"):
        vals.append(notify.get(k))
    with open(os.path.join(ROOT, "secrets_tencent.json"), encoding="utf-8") as _f:
        sec = json.load(_f)
    vals.extend([sec.get("SecretId"), sec.get("SecretKey")])
    return [str(v) for v in vals if v and len(str(v)) >= 8]


def _secret_fragments(real_values) -> list:
    """把每个真实值拆成可扫描片段：cookie 按 ';' 切成 键=值 对，只留长度≥12 的对。

    纯数字对（如 ALF=1234567890）不拆——保留整只 键=值 对做扫描，避免 '1793169190'
    这类公共时间戳子串误报。整值本身也作为片段保留（对单行值仍生效）。
    """
    frags = []
    seen = set()

    def add(s):
        if s and len(s) >= 12 and s not in seen:
            seen.add(s)
            frags.append(s)

    for val in real_values:
        v = str(val)
        add(v)
        if ";" in v:
            for part in v.split(";"):
                p = part.strip()
                if p:
                    add(p)
    return frags


def secret_scan(staged_root: str, real_values=None) -> list:
    if real_values is None:
        real_values = real_secret_values()
    frags = _secret_fragments(real_values)
    hits = []
    for dp, dns, fns in os.walk(staged_root):
        for fn in fns:
            full = os.path.join(dp, fn)
            rel = os.path.relpath(full, staged_root).replace("\\", "/")
            try:
                with open(full, "r", encoding="utf-8", errors="ignore") as _f:
                    body = _f.read()
            except OSError:
                continue
            for val in frags:
                if val in body:
                    hits.append(rel)
                    break
    return hits


def build(version: str, date: str) -> dict:
    label = "本地版" if version == "local" else "云端版"
    zip_path = os.path.join(OUT_DIR, "热点预判-%s-%s.zip" % (label, date))
    stage = tempfile.mkdtemp(prefix="hotpredict_pkg_")
    try:
        staged_root = os.path.join(stage, "热点预判")
        os.makedirs(staged_root, exist_ok=True)
        for rel in _iter_files(version):
            src = os.path.join(ROOT, rel.replace("/", os.sep))
            dst = os.path.join(staged_root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
        make_templates(staged_root)
        hits = secret_scan(staged_root)
        if hits:
            raise SystemExit("密钥泄漏，拒绝组包: %s" % hits)  # 只打路径与键位，不打值
        os.makedirs(OUT_DIR, exist_ok=True)
        if os.path.exists(zip_path):
            os.remove(zip_path)
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for dp, _dns, fns in os.walk(staged_root):
                for fn in sorted(fns):
                    full = os.path.join(dp, fn)
                    arc = "热点预判/" + os.path.relpath(full, staged_root).replace("\\", "/")
                    z.write(full, arc)
        return {"path": zip_path, "hits": len(hits)}
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().strftime("%Y%m%d")
    total_hits = 0
    for version in ("local", "cloud"):
        result = build(version, date)
        total_hits += result["hits"]
        with zipfile.ZipFile(result["path"]) as z:
            n = len(z.namelist())
        print("created %s (%d files, %.1f KB)" % (result["path"], n, os.path.getsize(result["path"]) / 1024))
    if total_hits == 0:
        print("secret scan: clean (0 hits, values never printed)")
    else:
        print("secret scan: %d hits (values never printed)" % total_hits)


if __name__ == "__main__":
    main()
