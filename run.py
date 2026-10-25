#!/usr/bin/env python3
"""AskVisible weekly runner.

Reads config.json, asks Google Gemini the configured prompts, analyses whether
your brand (and competitors) are mentioned, writes an HTML report to disk.

Delivery (email, Slack, Discord, …) is handled by whatever runs this script –
e.g. the GitHub Actions workflow in .github/workflows/weekly.yml.

Run locally:   GEMINI_API_KEY=... python run.py
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class Config:
    brand: str
    competitors: list[str]
    prompts: list[str]
    model: str = "gemini-3.8-flash"
    report_path: str = "reports/report.html"

    @classmethod
    def load(cls, path: str) -> "Config":
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return cls(
            brand=raw["brand"].strip(),
            competitors=[c.strip() for c in raw.get("competitors", []) if c.strip()],
            prompts=[p.strip() for p in raw.get("prompts", []) if p.strip()],
            model=raw.get("model", "gemini-3.8-flash"),
            report_path=raw.get("report_path", "reports/report.html"),
        )


# ---------------------------------------------------------------------------
# Gemini call
# ---------------------------------------------------------------------------

GEMINI_FALLBACK_MODELS = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-flash-latest"]


def _gemini_once(prompt: str, model: str, key: str) -> tuple[bool, str, str, int]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 1500,
            # Gemini 3.x needs this to actually return the answer instead of
            # eating the budget on hidden "thinking" tokens.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        return False, "", f"HTTP {e.code}: {detail[:200]}", e.code
    except Exception as e:
        return False, "", str(e), 0
    parts = ((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    return True, text, "", 200


def ask_gemini(prompt: str, model: str) -> tuple[bool, str, str]:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        return False, "", "GEMINI_API_KEY env var is not set"
    models = [model] + [m for m in GEMINI_FALLBACK_MODELS if m != model]
    last_err = ""
    for m in models:
        for attempt in range(2):
            ok, text, err, code = _gemini_once(prompt, m, key)
            if ok:
                return True, text, ""
            last_err = f"{m}: {err}"
            # Retry only on transient errors.
            if code in (429, 500, 502, 503, 504, 0):
                time.sleep(2 + attempt * 3)
                continue
            break  # permanent error for this model → try next model
    return False, "", last_err


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

@dataclass
class Analysis:
    brand_mentioned: bool
    brand_mention_count: int
    brand_first_position: int | None
    competitors_mentioned: dict = field(default_factory=dict)
    snippet: str = ""


def _count(text: str, needle: str) -> int:
    return len(re.findall(r"\b" + re.escape(needle) + r"\b", text, re.IGNORECASE))


def _first_list_position(text: str, brand: str) -> int | None:
    """Find brand's rank in a top-level numbered or heading list.

    We walk headings and numbered items that look like list leaders (e.g.
    "1. ", "### 1. ", "### Name"). Nested bullets are ignored because they
    cause misleading double-counting under each entry.
    """
    pos = 0
    heading_re = re.compile(r"^#{1,4}\s+(\d+[\.\)]\s+)?(.+)")
    numlead_re = re.compile(r"^(\d+)[\.\)]\s+(.+)")
    for raw in text.splitlines():
        line = raw.strip()
        heading = heading_re.match(line)
        numlead = numlead_re.match(line)
        content = None
        if heading:
            content = heading.group(2)
        elif numlead:
            content = numlead.group(2)
        if content is None:
            continue
        pos += 1
        if re.search(r"\b" + re.escape(brand) + r"\b", content, re.IGNORECASE):
            return pos
    return None


def _snippet(text: str, brand: str, around: int = 80) -> str:
    m = re.search(r"\b" + re.escape(brand) + r"\b", text, re.IGNORECASE)
    if not m:
        return ""
    start, end = max(0, m.start() - around), min(len(text), m.end() + around)
    out = text[start:end]
    if start > 0:
        out = "…" + out
    if end < len(text):
        out = out + "…"
    return out.replace("\n", " ").strip()


def analyze(text: str, brand: str, competitors: list[str]) -> Analysis:
    count = _count(text, brand)
    return Analysis(
        brand_mentioned=count > 0,
        brand_mention_count=count,
        brand_first_position=_first_list_position(text, brand) if count > 0 else None,
        competitors_mentioned={c: _count(text, c) for c in competitors},
        snippet=_snippet(text, brand) if count > 0 else "",
    )


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:720px;margin:0 auto;padding:24px;color:#111;background:#fff;line-height:1.55}
h1{font-size:22px;margin:0 0 4px}
h2{font-size:16px;margin:28px 0 10px}
.meta{color:#666;font-size:13px;margin-bottom:20px}
.row{display:flex;justify-content:space-between;padding:10px 12px;background:#f6f7f9;border-radius:8px;margin-bottom:6px;font-size:14px}
.row.hit{background:#e8f5ee;border-left:3px solid #16a34a}
.row.miss{background:#fff2f2;border-left:3px solid #dc2626}
.snippet{font-size:13px;color:#333;background:#fafafa;border-left:3px solid #d1d5db;padding:8px 12px;margin:6px 0;border-radius:4px}
details{margin:8px 0}
summary{cursor:pointer;color:#2563eb;font-size:13px}
pre{white-space:pre-wrap;font-size:12px;color:#444;background:#fafafa;padding:8px;border-radius:4px}
.pill{display:inline-block;padding:2px 8px;background:#eef;border-radius:12px;font-size:11px;color:#444;margin-right:4px}
.footer{color:#999;font-size:12px;margin-top:40px;border-top:1px solid #eee;padding-top:16px}
"""


def render_html(cfg: Config, runs: list[dict], week: str, generated_at: str) -> str:
    hits = sum(1 for r in runs if r.get("ok") and r.get("analysis", {}).get("brand_mentioned"))
    total = sum(1 for r in runs if r.get("ok"))
    comp_totals: dict = {}
    for r in runs:
        if not r.get("ok"):
            continue
        for c, n in r["analysis"]["competitors_mentioned"].items():
            if n > 0:
                comp_totals[c] = comp_totals.get(c, 0) + 1

    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>AskVisible · {html.escape(cfg.brand)} · {html.escape(week)}</title>",
        f"<style>{CSS}</style></head><body>",
        f"<h1>AskVisible — Weekly report</h1>",
        f"<div class='meta'>Brand <b>{html.escape(cfg.brand)}</b> · Week <b>{html.escape(week)}</b> · "
        f"Engine Gemini ({html.escape(cfg.model)}) · {len(cfg.prompts)} prompts</div>",
        "<h2>At a glance</h2>",
        f"<div class='row {'hit' if hits else 'miss'}'><div><b>{html.escape(cfg.brand)}</b></div>"
        f"<div>{hits}/{total} prompts mentioned you</div></div>",
    ]
    for c, n in sorted(comp_totals.items(), key=lambda x: -x[1]):
        parts.append(f"<div class='row'><div>{html.escape(c)}</div><div>{n}/{total}</div></div>")
    if not comp_totals:
        parts.append("<div class='row'><div><i>Competitors not mentioned this week.</i></div><div>0</div></div>")

    parts.append("<h2>Prompt by prompt</h2>")
    for r in runs:
        parts.append(f"<details open><summary><b>{html.escape(r['prompt'][:140])}</b></summary>")
        if not r.get("ok"):
            parts.append(f"<p style='color:#dc2626'>Error: {html.escape(r.get('error',''))[:200]}</p></details>")
            continue
        a = r["analysis"]
        if a["brand_mentioned"]:
            pos = a["brand_first_position"]
            pos_txt = f" (position {pos} in list)" if pos else ""
            parts.append(f"<p>✓ <b>{html.escape(cfg.brand)}</b> mentioned {a['brand_mention_count']}×{pos_txt}</p>")
            if a["snippet"]:
                parts.append(f"<div class='snippet'>{html.escape(a['snippet'])}</div>")
        else:
            parts.append(f"<p>✗ <b>{html.escape(cfg.brand)}</b> not mentioned.</p>")
            if a["competitors_mentioned"]:
                pills = "".join(f"<span class='pill'>{html.escape(c)}: {n}</span>" for c, n in a["competitors_mentioned"].items() if n > 0)
                if pills:
                    parts.append(f"<p>Competitors mentioned: {pills}</p>")
        parts.append(f"<details><summary>Full Gemini answer</summary><pre>{html.escape(r['text'][:4000])}</pre></details>")
        parts.append("</details>")

    parts.append(
        f"<div class='footer'>Generated {html.escape(generated_at)} · "
        f"<a href='https://askvisible.pages.dev'>askvisible.pages.dev</a> · "
        f"Edit <code>config.json</code> to change brand, competitors or prompts.</div>"
    )
    parts.append("</body></html>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    config_path = os.environ.get("ASKVISIBLE_CONFIG", "config.json")
    if not Path(config_path).exists():
        print(f"ERR: config file not found at {config_path}", file=sys.stderr)
        return 2
    cfg = Config.load(config_path)
    print(f"AskVisible · brand={cfg.brand} · {len(cfg.prompts)} prompts · model={cfg.model}")
    week = dt.datetime.utcnow().strftime("%Y-W%V")
    runs: list[dict] = []
    for i, prompt in enumerate(cfg.prompts, 1):
        print(f"  [{i}/{len(cfg.prompts)}] {prompt[:80]}")
        ok, text, err = ask_gemini(prompt, cfg.model)
        entry: dict = {"prompt": prompt, "ok": ok, "text": text, "error": err}
        if ok:
            a = analyze(text, cfg.brand, cfg.competitors)
            entry["analysis"] = {
                "brand_mentioned": a.brand_mentioned,
                "brand_mention_count": a.brand_mention_count,
                "brand_first_position": a.brand_first_position,
                "competitors_mentioned": a.competitors_mentioned,
                "snippet": a.snippet,
            }
            status = f"mentioned {a.brand_mention_count}x" if a.brand_mentioned else "NOT mentioned"
            print(f"      -> {status}")
        else:
            print(f"      -> ERROR: {err[:120]}")
        runs.append(entry)
        time.sleep(0.5)

    generated_at = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    body = render_html(cfg, runs, week, generated_at)
    out_path = Path(cfg.report_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(body, encoding="utf-8")
    print(f"\nOK Report written: {out_path} ({len(body):,} bytes)")

    # Also drop a small summary.json so CI steps can post Slack/Discord etc.
    hits = sum(1 for r in runs if r.get("ok") and r.get("analysis", {}).get("brand_mentioned"))
    total = sum(1 for r in runs if r.get("ok"))
    summary = {
        "brand": cfg.brand,
        "week": week,
        "generated_at": generated_at,
        "prompts_total": len(cfg.prompts),
        "prompts_ok": total,
        "brand_hits": hits,
        "model": cfg.model,
        "report_path": str(out_path),
    }
    Path("reports/summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
