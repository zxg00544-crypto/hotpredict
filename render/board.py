"""单文件静态看板：无外部依赖、无 CDN、双表格分档。"""
import html as H
from urlclean import clean_url

def _rows(items: list) -> str:
    if not items:
        return "<tr><td colspan='7' class='empty'>今日暂无热点</td></tr>"
    out = []
    for t in items:
        r = t.get("rating")
        badge = ("<span class='a'>A</span>" if r == "A" else
                 "<span class='b'>B</span>" if r == "B" else "<span class='c'>C</span>")
        now = "<span class='now'>立即行动</span>" if t.get("act_now") else ""
        brk = "<span class='brk'>⚡突发</span>" if t.get("breaking") else ""
        out.append(
            f"<tr><td>{badge}</td>"
            f"<td>{brk}<a href='{H.escape(clean_url(str(t.get('url',''))))}' target='_blank'>"
            f"{H.escape(str(t.get('title','')))}</a>{now}</td>"
            f"<td>{t.get('score',0)}</td><td>{t.get('G',0)}</td>"
            f"<td>{t.get('slope','-')}</td>"
            f"<td>{H.escape(str(t.get('track','其他')))}</td>"
            f"<td>{H.escape(str(t.get('reason','')))}</td></tr>")
    return "\n".join(out)

def render_board(payload: dict) -> str:
    meta = payload.get("meta", {})
    deg = ("<div class='warn'>本轮 LLM 降级：无 A/B/C 评级，仅供参考</div>"
           if meta.get("degraded") else "")
    date = H.escape(str(payload.get("date", "")))
    sources = H.escape(", ".join(meta.get("sources") or []) or "无")
    model = H.escape(str(meta.get("llm_model", "-")))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>热点预判看板 {date}</title>
<style>
body{{font-family:'Microsoft YaHei',sans-serif;margin:24px;background:#0f1220;color:#e8eaf2}}
h1{{font-size:22px}} h2{{font-size:17px;margin-top:28px;color:#7fd1ff}}
table{{border-collapse:collapse;width:100%;background:#171b2e;font-size:14px}}
th,td{{border:1px solid #2a3050;padding:7px 9px;text-align:left;vertical-align:top}}
th{{background:#1f2540}} a{{color:#8fe3ff;text-decoration:none}}
.a{{background:#1f8f4e;color:#fff;padding:1px 7px;border-radius:9px;font-weight:700}}
.b{{background:#8a6d1a;color:#fff;padding:1px 7px;border-radius:9px;font-weight:700}}
.c{{background:#4a4f6a;color:#ddd;padding:1px 7px;border-radius:9px}}
.now{{background:#c9372c;color:#fff;padding:1px 6px;border-radius:6px;margin-left:6px;font-size:12px}}
.brk{{background:#e74c3c;color:#fff;padding:1px 6px;border-radius:6px;margin-right:6px;font-size:12px;font-weight:700}}
.warn{{background:#5a2b00;border:1px solid #d8892a;padding:9px 13px;border-radius:7px;margin:14px 0}}
.empty{{color:#7b81a0;text-align:center}} .meta{{color:#9aa0c0;font-size:13px}}
</style></head><body>
<h1>热点预判看板 · {date}</h1>
<div class="meta">模型：{model} · 采集源：{sources} ·
快讯 {len(payload.get('fast', []))} 条 · 趋势 {len(payload.get('trend', []))}</div>
{deg}
<h2>快讯档（1-6h）</h2>
<table><tr><th>评级</th><th>话题</th><th>分</th><th>增速G</th><th>斜率</th><th>赛道</th><th>入选原因</th></tr>
{_rows(payload.get('fast', []))}</table>
<h2>趋势推荐（3-7d）</h2>
<table><tr><th>评级</th><th>话题</th><th>分</th><th>增速G</th><th>斜率</th><th>赛道</th><th>入选原因</th></tr>
{_rows(payload.get('trend', []))}</table>
</body></html>"""
