"""POSANTRA | VERIQ - Streamlit application.

Animated, simple-language results first (images and post links); the full
technical report is one switch away. Presentation only: no analysis logic
lives here. Results are cached per file so reruns are instant.
"""
from __future__ import annotations

import base64
import html
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from io import BytesIO
from typing import Optional

import numpy as np
import streamlit as st
from PIL import Image

import config
from database import database as local_db
from modules import (
    ai_indicator,
    file_kind,
    forensic_analyzer,
    hash_engine,
    image_analyzer,
    image_fetch,
    metadata_analyzer,
    ocr_engine,
    place_clues,
    post_extractor,
    report_generator,
    security,
    simple_post,
    simple_result,
    ui_claims,
    ui_report,
    ui_theme,
    url_validator,
    verdict_engine,
    verification_guide,
)

GOLD = "#e3b04b"
BLUE = "#58a6ff"
MAX_CACHED = 6
BIG_IMAGE_PIXELS = 6_000_000


def is_online() -> bool:
    """True on a shared host (set VERIQ_ONLINE=1/0 to override auto-detection)."""
    flag = os.environ.get("VERIQ_ONLINE")
    if flag is not None:
        return flag.strip().lower() in ("1", "true", "yes")
    return bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("STREAMLIT_RUNTIME_ENV")
                or os.path.exists("/mount/src") or os.path.exists("/home/adminuser"))


ONLINE = is_online()
WHERE = "the host's server" if ONLINE else "this computer"

AWARENESS_TIPS = [
    ("Screenshots", "remove an image's AI label. A missing label proves nothing."),
    ("WhatsApp", "re-saves pictures and strips their details. Ask for the original as a Document."),
    ("Pause", "before you share. Shocking posts spread fastest."),
    ("Search", "the picture on Google Lens or TinEye to find where it began."),
    ("Check", "the date. Old photos are often reposted as new events."),
    ("Look", "at hands, text and shadows. AI still makes small mistakes."),
    ("Trust", "reliable sources, not forwarded messages."),
    ("Remember", "no tool can be 100% sure. VERIQ gives clues, not final proof."),
]


@lru_cache(maxsize=1)
def load_emblem_png() -> Optional[bytes]:
    for name in ("logo.png", "logo.jpg", "logo.jpeg", "logo.webp"):
        path = config.BASE_DIR / "assets" / name
        if not path.is_file():
            continue
        try:
            with Image.open(path) as img:
                img = img.convert("RGB")
                w, h = img.size
                arr = np.asarray(img.crop((int(w * 0.32), int(h * 0.17), int(w * 0.68), int(h * 0.55))),
                                 dtype=np.float32)
            alpha = np.clip((arr.max(axis=2) - 50.0) / 70.0, 0.0, 1.0) * 255.0
            emblem = Image.fromarray(np.dstack([arr, alpha]).astype("uint8"), "RGBA")
            emblem.thumbnail((260, 260))
            out = BytesIO()
            emblem.save(out, format="PNG")
            return out.getvalue()
        except Exception:
            continue
    return None


def page_icon():
    data = load_emblem_png()
    if data:
        try:
            return Image.open(BytesIO(data))
        except Exception:
            pass
    return "🛡️"


def preview_uri(data: bytes) -> Optional[str]:
    try:
        with Image.open(BytesIO(data)) as img:
            rgb = img.convert("RGB")
        rgb.thumbnail((700, 700))
        out = BytesIO()
        rgb.save(out, format="JPEG", quality=80)
        return "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode("ascii")
    except Exception:
        return None


st.set_page_config(page_title=config.PRODUCT_FULL_NAME, page_icon=page_icon(), layout="wide")
ui_theme.apply_theme()

BRAND_CSS = """
<style>
    :root { --gold: __GOLD__; --blue: __BLUE__; }
    .stApp { background: #060a13; }
    .block-container { position: relative; z-index: 2; }

    .stApp::before { content: ""; position: fixed; inset: 0; pointer-events: none; z-index: 0;
        background-image: linear-gradient(rgba(227,176,75,0.05) 1px, transparent 1px),
            linear-gradient(90deg, rgba(227,176,75,0.05) 1px, transparent 1px);
        background-size: 48px 48px;
        -webkit-mask-image: radial-gradient(ellipse at 50% 0%, #000 0%, transparent 72%);
        mask-image: radial-gradient(ellipse at 50% 0%, #000 0%, transparent 72%);
        animation: gridDrift 40s linear infinite; }
    .orb { position: fixed; border-radius: 50%; filter: blur(70px); opacity: .20; pointer-events: none; z-index: 0;
        animation: drift 20s ease-in-out infinite alternate; }
    .orb.o1 { width: 420px; height: 420px; background: #e3b04b; top: -100px; left: -80px; }
    .orb.o2 { width: 360px; height: 360px; background: #2ea36b; top: 30%; right: -120px; animation-duration: 26s; }
    .orb.o3 { width: 380px; height: 380px; background: #4a6cff; bottom: -140px; left: 30%; animation-duration: 23s; }
    .bq-particles { position: fixed; inset: 0; pointer-events: none; z-index: 1; overflow: hidden; }
    .bq-particles span { position: absolute; bottom: -12px; border-radius: 50%; background: var(--gold);
        opacity: 0; animation: rise linear infinite; box-shadow: 0 0 8px rgba(227,176,75,0.7); }

    @keyframes gridDrift { to { background-position: 48px 48px, 48px 48px; } }
    @keyframes drift { from { transform: translate(0,0) scale(1); } to { transform: translate(60px, 40px) scale(1.15); } }
    @keyframes rise { 0% { transform: translateY(0) translateX(0); opacity: 0; } 10% { opacity: .7; }
        90% { opacity: .25; } 100% { transform: translateY(-105vh) translateX(30px); opacity: 0; } }
    @keyframes sweep { to { background-position: -200% 0; } }
    @keyframes fadeUp { from { opacity: 0; transform: translateY(16px); } to { opacity: 1; transform: none; } }
    @keyframes pop { from { opacity: 0; transform: scale(0.92); } to { opacity: 1; transform: none; } }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes glow { 0%, 100% { filter: drop-shadow(0 0 4px rgba(227,176,75,.25)); }
        50% { filter: drop-shadow(0 0 16px rgba(227,176,75,.7)); } }
    @keyframes floaty { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-4px); } }
    @keyframes pulseBorder { 0%, 100% { box-shadow: 0 0 0 0 rgba(227,176,75,0); }
        50% { box-shadow: 0 0 22px 0 rgba(227,176,75,0.28); } }
    @keyframes blink { 0%, 100% { opacity: .25; } 50% { opacity: 1; } }
    @keyframes marquee { to { transform: translateX(-50%); } }
    @keyframes orbit { from { transform: rotate(0deg) translateX(26px) rotate(0deg); }
        to { transform: rotate(360deg) translateX(26px) rotate(-360deg); } }
    @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(300%); } }
    @keyframes ping { from { transform: scale(.2); opacity: .8; } to { transform: scale(1); opacity: 0; } }
    @keyframes scanY { 0% { top: -6%; } 100% { top: 104%; } }
    @keyframes lampOn { from { transform: scale(.6); opacity: 0; } to { transform: none; opacity: 1; } }
    @keyframes flow { to { background-position: 200% 0; } }
    @keyframes shimmer { to { background-position: -200% 0; } }
    @keyframes ripple { from { transform: scale(1); opacity: .7; } to { transform: scale(1.6); opacity: 0; } }
    @keyframes stamp { from { transform: scale(2.2) rotate(-14deg); opacity: 0; } to { transform: none; opacity: 1; } }
    @keyframes rotw { 0%, 20% { transform: translateY(0); } 25%, 45% { transform: translateY(-1.3em); }
        50%, 70% { transform: translateY(-2.6em); } 75%, 95% { transform: translateY(-3.9em); } 100% { transform: translateY(0); } }
    @keyframes typing { from { width: 0; } to { width: 100%; } }
    @keyframes caret { 50% { border-color: transparent; } }
    @keyframes sparkle { 0% { transform: translate(0,0) scale(.4); opacity: 1; }
        100% { transform: translate(var(--dx), var(--dy)) scale(1); opacity: 0; } }
    @keyframes stageOn { from { background: #10151f; } to { background: rgba(227,176,75,.2); } }

    .bq-header { position: relative; display: flex; align-items: center; gap: 1.2rem;
        padding-bottom: 1.1rem; margin-bottom: 1rem; animation: fadeUp .7s ease both; }
    .bq-header::after { content: ""; position: absolute; left: 0; right: 0; bottom: 0; height: 2px;
        background: linear-gradient(90deg, transparent, var(--gold), #2ea36b, var(--gold), transparent);
        background-size: 200% 100%; animation: sweep 6s linear infinite; }
    .bq-logo { width: 78px; height: 78px; object-fit: contain;
        animation: glow 4s ease-in-out infinite, floaty 6s ease-in-out infinite; }
    .bq-title { font-size: 2rem; font-weight: 800; letter-spacing: .1em; line-height: 1.15; margin: 0; color: #f4f6fa; }
    .bq-title .bar { color: var(--gold); padding: 0 .45rem; font-weight: 300; }
    .bq-title .q { color: var(--gold); }
    .bq-cat { color: #8b949e; font-size: .9rem; margin: .25rem 0 0 0; }
    .bq-tag { margin: .45rem 0 0 0; font-size: .8rem; font-weight: 700; letter-spacing: .22em;
        background: linear-gradient(90deg, var(--gold), #fff2c9, var(--gold)); background-size: 200% 100%;
        -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
        color: transparent; animation: sweep 5s linear infinite; }

    .tick { display: flex; align-items: stretch; border: 1px solid #262c34; border-radius: 999px;
        background: rgba(16,21,31,.85); margin: 0 0 1.2rem 0; overflow: hidden; animation: fadeUp .8s ease both; }
    .tick-label { flex: 0 0 auto; padding: .5rem 1rem; font-size: .7rem; font-weight: 800; letter-spacing: .2em;
        color: #0b101a; background: linear-gradient(90deg, var(--gold), #f5d68a); display: flex; align-items: center; gap: .5rem; }
    .tick-label i { width: 8px; height: 8px; border-radius: 50%; background: #0b101a; animation: blink 1.4s ease-in-out infinite; }
    .tick-view { flex: 1; overflow: hidden; position: relative;
        -webkit-mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent);
        mask-image: linear-gradient(90deg, transparent, #000 4%, #000 96%, transparent); }
    .tick-track { display: inline-flex; white-space: nowrap; padding: .5rem 0; animation: marquee 52s linear infinite; }
    .tick:hover .tick-track { animation-play-state: paused; }
    .tick-item { padding: 0 2.2rem; color: #c9d1d9; font-size: .85rem; }
    .tick-item b { color: var(--gold); }
    .tick-item::before { content: "◈"; color: var(--gold); margin-right: .7rem; }

    .veriq-panel, .src-card { animation: fadeUp .5s ease both; transition: transform .2s, border-color .2s, box-shadow .2s; }
    .verdict-box { animation: pop .55s cubic-bezier(.2,.9,.3,1.2) both; }
    .src-card:hover, .veriq-panel:hover { transform: translateY(-2px); border-color: rgba(227,176,75,.45);
        box-shadow: 0 6px 22px rgba(0,0,0,.35); }
    [data-testid="stAlert"], [data-testid="stExpander"] { animation: fadeUp .45s ease both; }
    .stMarkdown h4::before { content: ""; display: inline-block; width: 4px; height: .95em; margin-right: .6rem;
        background: var(--gold); border-radius: 2px; vertical-align: -.1em; }
    .stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button,
    [data-testid="stLinkButton"] a { border: 1px solid rgba(227,176,75,.5); background: #10151f; color: #f4f6fa;
        border-radius: 8px; transition: all .2s; }
    .stButton > button:hover, .stDownloadButton > button:hover,
    [data-testid="stFormSubmitButton"] > button:hover, [data-testid="stLinkButton"] a:hover {
        border-color: var(--gold); box-shadow: 0 0 14px rgba(227,176,75,.35); transform: translateY(-1px); color: #fff; }

    div[role="radiogroup"] { gap: .6rem; }
    div[role="radiogroup"] label { padding: 8px 20px; border: 1px solid #262c34; border-radius: 999px;
        background: #10151f; transition: all .25s; }
    div[role="radiogroup"] label:hover { border-color: var(--gold); transform: translateY(-2px); }
    div[role="radiogroup"] label:has(input:checked) { border-color: var(--gold);
        background: linear-gradient(90deg, rgba(227,176,75,.18), rgba(227,176,75,.06));
        box-shadow: 0 0 16px rgba(227,176,75,.25); }
    div[role="radiogroup"] label > div:first-child { display: none; }

    [data-testid="stFileUploaderDropzone"] { border: 2px dashed rgba(227,176,75,.55); border-radius: 14px;
        background: linear-gradient(110deg, rgba(16,21,31,.85) 30%, rgba(227,176,75,.07) 50%, rgba(16,21,31,.85) 70%);
        background-size: 250% 100%; animation: pulseBorder 3s ease-in-out infinite, shimmer 6s linear infinite; transition: all .25s; }
    [data-testid="stFileUploaderDropzone"]:hover { border-color: var(--gold); transform: scale(1.006); }
    [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea { border-radius: 10px; }

    .lp { display: flex; align-items: center; gap: 2rem; margin: .6rem 0 1.2rem 0; flex-wrap: wrap; }
    .lp-text { flex: 1 1 340px; animation: fadeUp .7s ease both; }
    .lp-kicker { font-size: .72rem; letter-spacing: .28em; color: var(--gold); font-weight: 700; }
    .lp-h { font-size: 2.3rem; font-weight: 800; line-height: 1.15; margin: .4rem 0 .6rem 0; color: #f4f6fa; }
    .lp-h em { font-style: normal; background: linear-gradient(90deg, var(--gold), #fff2c9, #2ea36b, var(--gold));
        background-size: 250% 100%; -webkit-background-clip: text; background-clip: text;
        -webkit-text-fill-color: transparent; color: transparent; animation: sweep 6s linear infinite; }
    .lp-p { color: #9aa4b2; max-width: 520px; line-height: 1.55; }
    .typed { display: inline-block; overflow: hidden; white-space: nowrap; max-width: 100%; vertical-align: bottom;
        border-right: 3px solid var(--gold); animation: typing 2.2s steps(34, end) both, caret .8s step-end 6; }
    .rotline { margin-top: .9rem; color: #c9d1d9; font-weight: 600; display: flex; gap: .5rem; align-items: baseline; }
    .rot { display: inline-block; height: 1.3em; overflow: hidden; vertical-align: bottom; }
    .rot-in { display: flex; flex-direction: column; animation: rotw 12s ease-in-out infinite; }
    .rot-in b { height: 1.3em; line-height: 1.3em; color: var(--gold); font-weight: 800; }
    .radar { flex: 0 0 auto; position: relative; width: 190px; height: 190px; border-radius: 50%;
        border: 1px solid rgba(227,176,75,.4); background: radial-gradient(circle, rgba(227,176,75,.10), transparent 70%);
        animation: pop .8s ease both; }
    .radar::before, .radar::after { content: ""; position: absolute; border-radius: 50%; border: 1px solid rgba(227,176,75,.25); }
    .radar::before { inset: 28px; } .radar::after { inset: 58px; }
    .radar .sweep { position: absolute; inset: 0; border-radius: 50%;
        background: conic-gradient(from 0deg, rgba(227,176,75,0) 0deg, rgba(227,176,75,.55) 60deg, rgba(227,176,75,0) 61deg);
        animation: spin 3.2s linear infinite; }
    .radar .dot { position: absolute; width: 8px; height: 8px; border-radius: 50%; background: #2ea36b;
        box-shadow: 0 0 10px #2ea36b; animation: blink 2.4s ease-in-out infinite; }
    .radar .dot::after { content: ""; position: absolute; inset: -6px; border-radius: 50%; border: 1px solid #2ea36b;
        animation: ping 2.4s ease-out infinite; }
    .radar .d1 { top: 38px; left: 118px; } .radar .d2 { top: 112px; left: 44px; animation-delay: .8s; }
    .radar .d3 { top: 132px; left: 128px; animation-delay: 1.5s; }
    .radar .core { position: absolute; inset: 82px; border-radius: 50%; background: var(--gold); box-shadow: 0 0 18px var(--gold); }
    .fgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: .8rem; margin-top: .6rem; }
    .fcard { padding: 1rem 1.1rem; border: 1px solid #262c34; border-radius: 12px; background: #0d121c;
        animation: fadeUp .6s ease both; transition: all .25s; position: relative; overflow: hidden; }
    .fcard::after { content: ""; position: absolute; top: 0; left: -80%; width: 50%; height: 100%;
        background: linear-gradient(100deg, transparent, rgba(227,176,75,.10), transparent); transition: left .6s; }
    .fcard:hover { border-color: var(--gold); transform: translateY(-4px) rotate(-.4deg); box-shadow: 0 8px 26px rgba(0,0,0,.4); }
    .fcard:hover::after { left: 130%; }
    .fcard .ic { font-size: 1.5rem; display: inline-block; transition: transform .3s; }
    .fcard:hover .ic { transform: scale(1.25) rotate(-8deg); }
    .fcard .t { font-weight: 700; color: #f4f6fa; margin-top: .3rem; }
    .fcard .d { color: #8b949e; font-size: .82rem; margin-top: .15rem; line-height: 1.4; }

    .how { display: flex; align-items: stretch; margin: 1.4rem 0 .4rem 0; flex-wrap: wrap; }
    .how-step { flex: 1 1 200px; position: relative; padding: 1rem 1.2rem; border: 1px solid #262c34;
        background: #0d121c; animation: fadeUp .7s ease both; }
    .how-step:first-child { border-radius: 12px 0 0 12px; } .how-step:last-child { border-radius: 0 12px 12px 0; }
    .how-n { display: inline-flex; width: 28px; height: 28px; border-radius: 50%; align-items: center;
        justify-content: center; font-weight: 800; color: #0b101a; background: var(--gold); font-size: .85rem;
        box-shadow: 0 0 12px rgba(227,176,75,.5); }
    .how-t { font-weight: 700; color: #f4f6fa; margin: .5rem 0 .15rem 0; }
    .how-d { color: #8b949e; font-size: .82rem; line-height: 1.4; }
    .how-step:not(:last-child)::after { content: "➜"; position: absolute; right: -11px; top: 50%; z-index: 3;
        transform: translateY(-50%); color: var(--gold); background: #060a13; padding: 2px 0; animation: blink 2s ease-in-out infinite; }
    .stats { display: flex; gap: 1.6rem; margin: .8rem 0 0 0; flex-wrap: wrap; }
    .stat b { font-size: 1.5rem; color: var(--gold); display: block; line-height: 1.1; }
    .stat span { color: #8b949e; font-size: .78rem; letter-spacing: .06em; }

    .pipe { display: flex; align-items: center; gap: .4rem; margin: .4rem 0 1rem 0; flex-wrap: wrap; }
    .pipe-n { padding: 5px 12px; border: 1px solid #262c34; border-radius: 999px; background: #10151f;
        color: #c9d1d9; font-size: .78rem; animation: fadeUp .5s ease both, stageOn .5s ease both; }
    .pipe-a { height: 2px; width: 26px; border-radius: 2px;
        background: linear-gradient(90deg, #262c34, var(--gold), #262c34); background-size: 200% 100%; animation: flow 2s linear infinite; }

    .scan-card { position: relative; overflow: hidden; display: flex; align-items: center; gap: 1.4rem;
        border: 1px solid rgba(227,176,75,.35); border-radius: 14px; background: #0b101a;
        padding: 1.3rem 1.6rem; margin: .6rem 0 1rem 0; animation: pulseBorder 2s ease-in-out infinite; }
    .scan-radar { flex: 0 0 auto; width: 96px; height: 96px; border-radius: 50%; position: relative;
        border: 1px solid rgba(227,176,75,.5); background: radial-gradient(circle, rgba(227,176,75,.12), transparent 70%); }
    .scan-radar::before { content: ""; position: absolute; inset: 20px; border-radius: 50%; border: 1px solid rgba(227,176,75,.3); }
    .scan-radar .sw { position: absolute; inset: 0; border-radius: 50%;
        background: conic-gradient(from 0deg, rgba(227,176,75,0) 0deg, rgba(227,176,75,.7) 70deg, rgba(227,176,75,0) 71deg);
        animation: spin 1.1s linear infinite; }
    .scan-radar .lens { position: absolute; top: 34px; left: 34px; width: 28px; height: 28px; font-size: 1.1rem;
        display: flex; align-items: center; justify-content: center; animation: orbit 2.6s linear infinite; }
    .scan-radar .bl { position: absolute; width: 6px; height: 6px; border-radius: 50%; background: #2ea36b;
        box-shadow: 0 0 8px #2ea36b; animation: blink 1.3s ease-in-out infinite; }
    .scan-radar .b1 { top: 16px; left: 62px; } .scan-radar .b2 { top: 66px; left: 22px; animation-delay: .5s; }
    .scan-body { flex: 1; }
    .scan-title { font-weight: 800; letter-spacing: .18em; color: var(--gold); font-size: .85rem; }
    .scan-steps { margin-top: .5rem; color: #9aa4b2; font-size: .88rem; }
    .scan-steps span { display: inline-block; margin-right: 1.1rem; animation: blink 1.2s ease-in-out infinite; }
    .scan-steps span:nth-child(2) { animation-delay: .25s; } .scan-steps span:nth-child(3) { animation-delay: .5s; }
    .scan-steps span:nth-child(4) { animation-delay: .75s; } .scan-steps span:nth-child(5) { animation-delay: 1s; }
    .scan-bar { margin-top: .8rem; height: 4px; border-radius: 4px; background: #1a2130; overflow: hidden; }
    .scan-bar::after { content: ""; display: block; height: 100%; width: 35%; border-radius: 4px;
        background: linear-gradient(90deg, transparent, var(--gold), transparent); animation: slide 1.2s ease-in-out infinite; }

    .kind { display: flex; align-items: center; gap: 1rem; padding: .9rem 1.2rem; border: 1px solid #262c34;
        border-left: 4px solid var(--kc); border-radius: 14px; background: #0d121c; margin: .4rem 0 1rem 0;
        animation: fadeUp .5s ease both; }
    .kind-ic { flex: 0 0 auto; width: 58px; height: 58px; border-radius: 14px; display: flex; align-items: center;
        justify-content: center; font-size: 1.8rem; border: 2px solid var(--kc);
        box-shadow: 0 0 16px -4px var(--kc); animation: stamp .6s cubic-bezier(.2,1.4,.4,1) both; }
    .kind-k { font-size: .68rem; letter-spacing: .2em; color: #8b949e; font-weight: 700; }
    .kind-t { font-size: 1.15rem; font-weight: 800; color: #f4f6fa; }
    .kind-s { color: #9aa4b2; font-size: .85rem; margin-top: .1rem; }
    .kind-ev { display: flex; flex-wrap: wrap; gap: .4rem; margin-top: .5rem; }
    .kind-ev span { padding: 2px 10px; border: 1px solid #262c34; border-radius: 999px; background: #10151f;
        color: #c9d1d9; font-size: .74rem; animation: fadeUp .5s ease both; }

    .pv { position: relative; border-radius: 14px; overflow: hidden; border: 1px solid rgba(227,176,75,.4);
        animation: pop .6s ease both; line-height: 0; }
    .pv img { width: 100%; display: block; }
    .pv-scan { position: absolute; left: 0; right: 0; height: 36px; top: -6%;
        background: linear-gradient(180deg, transparent, rgba(227,176,75,.35), transparent);
        animation: scanY 2.4s ease-in-out 2; opacity: .9; }
    .pv::after { content: ""; position: absolute; inset: 0; pointer-events: none; border-radius: 14px;
        box-shadow: inset 0 0 30px rgba(227,176,75,.15); }

    .sr-wrap { position: relative; border-radius: 16px; padding: 2px; overflow: hidden; background: #1a2130;
        animation: pop .6s cubic-bezier(.2,.9,.3,1.2) both; transition: transform .3s; }
    .sr-wrap:hover { transform: perspective(900px) rotateX(1.5deg) translateY(-3px); }
    .sr-wrap::before { content: ""; position: absolute; inset: -100%;
        background: conic-gradient(from 0deg, transparent 0 62%, var(--c) 100%); animation: spin 4.5s linear infinite; }
    .sr-hero { position: relative; display: flex; align-items: center; gap: 1.4rem; padding: 1.5rem 1.7rem;
        border-radius: 14px; background: #0b101a; box-shadow: inset 0 0 40px -20px var(--c); }
    .sr-ring { flex: 0 0 auto; width: 88px; height: 88px; border-radius: 50%; display: flex; align-items: center;
        justify-content: center; font-size: 2.5rem; border: 2px solid var(--c); position: relative; }
    .sr-ring::after { content: ""; position: absolute; inset: -2px; border-radius: 50%; border: 2px solid var(--c);
        animation: ripple 2.4s ease-out infinite; }
    .sr-kicker { font-size: .7rem; letter-spacing: .22em; color: #8b949e; font-weight: 600; }
    .sr-head { font-size: 2.1rem; font-weight: 800; color: var(--c); line-height: 1.15; margin: .15rem 0 .4rem 0; }
    .sr-sub { color: #d8dde3; font-size: 1.02rem; line-height: 1.5; }
    .sr-badge { display: inline-block; margin-top: .7rem; padding: 3px 12px; border-radius: 999px;
        border: 1px solid var(--c); color: var(--c); font-size: .75rem; font-weight: 700; letter-spacing: .05em; }
    .sr-list { margin: .6rem 0 0 0; }
    .sr-item { display: flex; gap: .8rem; align-items: flex-start; padding: .7rem 1rem; margin-bottom: .5rem;
        border: 1px solid #262c34; border-radius: 10px; background: #10151f; animation: fadeUp .5s ease both; transition: all .2s; }
    .sr-item:hover { border-color: var(--gold); transform: translateX(6px); }
    .sr-item .i { font-size: 1.3rem; }
    .sr-step { padding: .55rem 1rem; margin-bottom: .4rem; border-left: 3px solid var(--gold); background: #10151f;
        border-radius: 0 8px 8px 0; color: #d8dde3; animation: fadeUp .5s ease both; }
    .sr-note { color: #8b949e; font-size: .8rem; margin-top: .8rem; }

    .lamps { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: .7rem; margin: .5rem 0 1rem 0; }
    .lamp { position: relative; text-align: center; padding: .8rem .5rem; border: 1px solid #262c34; border-radius: 12px;
        background: #0d121c; animation: fadeUp .6s ease both; transition: all .25s; }
    .lamp:hover { transform: translateY(-3px); }
    .lamp .bulb { width: 46px; height: 46px; margin: 0 auto .45rem auto; border-radius: 50%; display: flex;
        align-items: center; justify-content: center; font-size: 1.3rem; border: 2px solid var(--lc);
        background: radial-gradient(circle, color-mix(in srgb, var(--lc) 28%, transparent), transparent 70%);
        box-shadow: 0 0 14px -2px var(--lc); animation: lampOn .5s ease both; }
    .lamp.off .bulb, .lamp.skip .bulb { box-shadow: none; opacity: .45; filter: grayscale(1); }
    .lamp.skip .bulb { border-style: dashed; }
    .lamp .ln { font-weight: 700; font-size: .85rem; color: #f4f6fa; }
    .lamp .lt { font-size: .74rem; color: #8b949e; margin-top: .15rem; line-height: 1.3; }
    .lamp.on, .lamp.alert, .lamp.hint { border-color: var(--lc); }
    .lamp.on::before, .lamp.alert::before, .lamp.hint::before { content: ""; position: absolute; top: 30px; left: 50%;
        width: 6px; height: 6px; border-radius: 50%; background: var(--lc); pointer-events: none;
        --dx: -34px; --dy: -22px; animation: sparkle .9s ease-out .35s both; box-shadow: 30px 6px 0 var(--lc), 62px -8px 0 var(--lc); }

    @media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation: none !important; transition: none !important; } }
    @media (max-width: 700px) {
        .sr-hero { flex-direction: column; text-align: center; } .lp-h { font-size: 1.8rem; }
        .scan-card { flex-direction: column; text-align: center; }
        .how-step, .how-step:first-child, .how-step:last-child { border-radius: 12px; margin-bottom: .5rem; }
        .how-step:not(:last-child)::after { display: none; }
    }
</style>
""".replace("__GOLD__", GOLD).replace("__BLUE__", BLUE)
st.markdown(BRAND_CSS, unsafe_allow_html=True)


def background_html(count: int = 14) -> str:
    spans = [f'<span style="left:{(i * 37) % 100}%;width:{2 + (i * 5) % 4}px;height:{2 + (i * 5) % 4}px;'
             f'animation-duration:{14 + (i * 7) % 16}s;animation-delay:{-((i * 3) % 20)}s"></span>'
             for i in range(count)]
    return ('<div class="orb o1"></div><div class="orb o2"></div><div class="orb o3"></div>'
            '<div class="bq-particles">' + "".join(spans) + "</div>")


st.markdown(background_html(), unsafe_allow_html=True)

LAMP_COLOURS = {simple_result.ON: GOLD, simple_result.ALERT: "#e5534b", simple_result.HINT: "#d29922",
                simple_result.OFF: "#8b949e", simple_result.SKIP: "#8b949e"}


# ------------------------------------------------------------------ chrome
def render_header() -> None:
    data = load_emblem_png()
    if data:
        b64 = base64.b64encode(data).decode("ascii")
        logo = f'<img class="bq-logo" src="data:image/png;base64,{b64}" alt="POSANTRA logo">'
    else:
        logo = '<div style="font-size:2.6rem">🛡️</div>'
    st.markdown(
        f"""<div class="bq-header">{logo}<div>
        <p class="bq-title">POSANTRA<span class="bar">|</span><span class="q">VERIQ</span></p>
        <p class="bq-cat">{html.escape(config.PRODUCT_CATEGORY)}</p>
        <p class="bq-tag">{html.escape(config.PRODUCT_TAGLINE.upper())}</p></div></div>""",
        unsafe_allow_html=True)


def render_ticker() -> None:
    one = "".join(f'<span class="tick-item"><b>{html.escape(a)}</b> {html.escape(b)}</span>'
                  for a, b in AWARENESS_TIPS)
    st.markdown('<div class="tick"><div class="tick-label"><i></i>AWARENESS</div>'
                f'<div class="tick-view"><div class="tick-track">{one}{one}</div></div></div>',
                unsafe_allow_html=True)


def pipeline_html(steps: list) -> str:
    parts = []
    for i, s in enumerate(steps):
        if i:
            parts.append('<span class="pipe-a"></span>')
        parts.append(f'<span class="pipe-n" style="animation-delay:{i * .12:.2f}s">{html.escape(s)}</span>')
    return '<div class="pipe">' + "".join(parts) + "</div>"


def render_landing(kind: str) -> None:
    rot = ""
    if kind == "image":
        kicker, headline = "IMAGE CHECK", "Is this picture <em>what it claims</em> to be?"
        text = ("Drop in a picture. VERIQ looks for hidden creation labels, camera details, "
                "text and earlier sightings, then explains what it found in plain words.")
        rot = ('<div class="rotline">Spots: <span class="rot"><span class="rot-in"><b>AI labels</b>'
               "<b>Camera photos</b><b>Screenshots</b><b>WhatsApp copies</b></span></span></div>")
        cards = [("🤖", "AI labels", "Reads a file's own hidden AI-creation label."),
                 ("📷", "Camera clues", "Finds camera and editing-app details."),
                 ("💬", "File kind", "Spots WhatsApp copies and screenshots."),
                 ("🧬", "Copy spotting", "Recognises copies of images you checked."),
                 ("🔤", "Text reading", "Reads words inside the picture.")]
        steps = [("Drop", "Upload a JPG, PNG or WebP picture."),
                 ("Scan", "VERIQ checks labels, camera info, file kind, text and look-alikes."),
                 ("Understand", "You get a plain answer, clue lamps and next steps.")]
    else:
        kicker, headline = "POST CHECK", "Is this post <em>worth believing</em>?"
        text = ("Paste a public post link. VERIQ reads what the site publicly shows, checks the post's "
                "picture, finds statements that can be fact-checked and helps you compare them with sources.")
        cards = [("🔗", "Safe link check", "Blocks unsafe and private addresses."),
                 ("📄", "Public text", "Reads only what the site shows openly."),
                 ("🖼️", "Post picture", "Checks the preview picture, or one you upload."),
                 ("🔎", "Claim finder", "Spots statements that can be checked."),
                 ("📚", "Evidence", "Searches Wikipedia and news indexes.")]
        steps = [("Paste", "Copy the post's link here."),
                 ("Read", "VERIQ fetches only the public text and picture, never logging in."),
                 ("Compare", "Check its claims and picture against clues and sources.")]
    items = "".join(
        f'<div class="fcard" style="animation-delay:{i * 0.1:.1f}s"><div class="ic">{icon}</div>'
        f'<div class="t">{html.escape(t)}</div><div class="d">{html.escape(d)}</div></div>'
        for i, (icon, t, d) in enumerate(cards))
    how = "".join(
        f'<div class="how-step" style="animation-delay:{i * 0.15:.2f}s"><span class="how-n">{i + 1}</span>'
        f'<div class="how-t">{html.escape(t)}</div><div class="how-d">{html.escape(d)}</div></div>'
        for i, (t, d) in enumerate(steps))
    stats = ""
    if not ONLINE:
        try:
            stats = (f'<div class="stats"><div class="stat"><b>{local_db.count_fingerprints()}</b>'
                     "<span>IMAGES REMEMBERED ON THIS COMPUTER</span></div></div>")
        except sqlite3.Error:
            stats = ""
    st.markdown(
        f'<div class="lp"><div class="lp-text"><div class="lp-kicker">◈ {kicker}</div>'
        f'<div class="lp-h"><span class="typed">{headline}</span></div>'
        f'<div class="lp-p">{html.escape(text)}</div>{rot}{stats}</div>'
        '<div class="radar"><div class="sweep"></div><div class="dot d1"></div>'
        '<div class="dot d2"></div><div class="dot d3"></div><div class="core"></div></div></div>'
        f'<div class="fgrid">{items}</div><div class="how">{how}</div>', unsafe_allow_html=True)


def scanner_html(title: str, steps: list) -> str:
    spans = "".join(f"<span>◈ {html.escape(s)}</span>" for s in steps)
    return ('<div class="scan-card"><div class="scan-radar"><div class="sw"></div>'
            '<div class="bl b1"></div><div class="bl b2"></div><div class="lens">🔍</div></div>'
            f'<div class="scan-body"><div class="scan-title">{html.escape(title)}</div>'
            f'<div class="scan-steps">{spans}</div><div class="scan-bar"></div></div></div>')


# ------------------------------------------------------- simple result view
def render_kind(kind) -> None:
    if kind is None:
        return
    chips = "".join(f'<span style="animation-delay:{i * .12:.2f}s">{html.escape(e)}</span>'
                    for i, e in enumerate(kind.evidence))
    st.markdown(
        f'<div class="kind" style="--kc:{BLUE}"><div class="kind-ic">{html.escape(kind.icon)}</div><div>'
        '<div class="kind-k">FILE KIND</div>'
        f'<div class="kind-t">{html.escape(kind.label)}</div>'
        f'<div class="kind-s">{html.escape(kind.sentence)}</div>'
        f'<div class="kind-ev">{chips}</div></div></div>', unsafe_allow_html=True)


def render_clues(clues: list) -> None:
    if not clues:
        return
    st.markdown("#### Clue Lamps")
    lamps = "".join(
        f'<div class="lamp {html.escape(state)}" style="--lc:{LAMP_COLOURS.get(state, "#8b949e")};'
        f'animation-delay:{i * 0.1:.1f}s"><div class="bulb">{html.escape(icon)}</div>'
        f'<div class="ln">{html.escape(name)}</div><div class="lt">{html.escape(note)}</div></div>'
        for i, (icon, name, state, note) in enumerate(clues))
    st.markdown(f'<div class="lamps">{lamps}</div>', unsafe_allow_html=True)
    st.caption("Lit lamps are clues that were found. Dim lamps mean nothing was found or the "
               "check was not run. A dim lamp never means the picture is real.")


def render_simple(result, preview: Optional[bytes] = None, heading: str = "Result",
                  show_search: bool = True) -> None:
    st.markdown(f"#### {heading}")
    hero = (f'<div class="sr-wrap" style="--c:{result.colour}"><div class="sr-hero">'
            f'<div class="sr-ring">{result.icon}</div><div>'
            '<div class="sr-kicker">VERIQ SAYS</div>'
            f'<div class="sr-head">{html.escape(result.headline)}</div>'
            f'<div class="sr-sub">{html.escape(result.sentence)}</div>'
            f'<span class="sr-badge">{html.escape(result.certainty)}</span></div></div></div>')
    if preview is not None:
        left, right = st.columns([1, 2], gap="large")
        with left:
            uri = preview_uri(preview)
            if uri:
                st.markdown(f'<div class="pv"><img src="{uri}" alt="Uploaded image preview">'
                            '<div class="pv-scan"></div></div>', unsafe_allow_html=True)
            else:
                st.image(preview)
        with right:
            st.markdown(hero, unsafe_allow_html=True)
    else:
        st.markdown(hero, unsafe_allow_html=True)

    render_clues(getattr(result, "clues", []))

    if result.bullets:
        st.markdown("#### What we found")
        st.markdown('<div class="sr-list">' + "".join(
            f'<div class="sr-item" style="animation-delay:{i * 0.12:.2f}s">'
            f'<span class="i">{html.escape(icon)}</span><span>{html.escape(text)}</span></div>'
            for i, (icon, text) in enumerate(result.bullets)) + "</div>", unsafe_allow_html=True)
    if result.next_steps:
        st.markdown("#### What you can do next")
        st.markdown("".join(f'<div class="sr-step" style="animation-delay:{i * 0.12:.2f}s">'
                            f"{html.escape(s)}</div>" for i, s in enumerate(result.next_steps)),
                    unsafe_allow_html=True)
        if preview is not None and show_search:
            cols = st.columns(len(verification_guide.REVERSE_SEARCH))
            for col, (name, url) in zip(cols, verification_guide.REVERSE_SEARCH):
                col.link_button(name, url)
    if hasattr(result, "clues"):
        with st.expander("Copy a short summary to share"):
            st.code(simple_result.summary_text(result), language=None)
    st.markdown('<div class="sr-note">VERIQ gives clues, not final proof. It never says a picture is '
                f"'real' or a post is 'true'. Image checks run on {WHERE}.</div>",
                unsafe_allow_html=True)


def render_place(meta) -> None:
    st.markdown("#### Place Clues")
    clues = place_clues.collect(meta)
    if not clues["gps"] and not clues["offsets"]:
        st.info("No location information is stored in this file, so VERIQ cannot name a region. "
                "Screenshots, WhatsApp copies and AI images usually carry none. VERIQ never guesses a place.")
        return
    if clues["gps"]:
        lat, lon = clues["gps"]
        st.markdown(f"📍 **Embedded GPS:** {lat:.4f}, {lon:.4f}")
        key = f"veriq_region_{lat:.2f}_{lon:.2f}"
        if st.button("Look up region name (sends rounded coordinates to OpenStreetMap)", key=key + "_b"):
            with st.spinner("Looking up..."):
                st.session_state[key] = place_clues.region_lookup(lat, lon)
        if key in st.session_state:
            region, error = st.session_state[key]
            if region:
                st.success(f"Approximate region named by OpenStreetMap: {region}")
            else:
                st.warning(error or "No region found.")
    if clues["offsets"]:
        st.markdown("🕒 **Time-zone offset recorded:** " + ", ".join(clues["offsets"]))
    st.caption("This is information stored inside the file. It can be edited or copied from another "
               "file. It may show where the picture was taken, but not where the person who "
               "uploaded or shared it is.")


# ----------------------------------------------- cached image analysis
def get_local_comparison(hashes, validation, info, remember: bool, origin: str = "") -> Optional[dict]:
    """Compare once per image per session BEFORE saving, so reruns never self-match.

    Online, the shared database is never read or written (visitors must not see each other's images).
    """
    if ONLINE:
        return None
    cache = st.session_state.setdefault("veriq_cmp", {})
    saved = st.session_state.setdefault("veriq_saved", set())
    sha = hashes.sha256
    if sha not in cache:
        try:
            exact = local_db.get_by_sha(sha)
            records = local_db.all_fingerprints()
            cache[sha] = {"ok": True, "exact": exact,
                          "matches": hash_engine.compare_to_records(hashes, records),
                          "total": len(records)}
        except sqlite3.Error:
            cache[sha] = {"ok": False}
    result = cache[sha]
    result["saved"] = sha in saved
    if remember and result["ok"] and sha not in saved:
        try:
            local_db.save_fingerprint(sha, hashes.ahash, hashes.phash, hashes.dhash,
                                      validation.safe_name, info.width, info.height, origin)
            saved.add(sha)
            result["saved"] = True
        except sqlite3.Error:
            result["save_failed"] = True
    return result


def _trim(cache: dict) -> None:
    while len(cache) > MAX_CACHED:
        cache.pop(next(iter(cache)))


def _small_copy(data: bytes) -> bytes:
    """Downscale very large images so OCR and hashing stay fast (metadata uses the original)."""
    try:
        with Image.open(BytesIO(data)) as img:
            if img.width * img.height <= BIG_IMAGE_PIXELS:
                return data
            rgb = img.convert("RGB")
        rgb.thumbnail((2400, 2400))
        out = BytesIO()
        rgb.save(out, format="PNG")
        return out.getvalue()
    except Exception:
        return data


def analyze_image(data: bytes, filename: str, remember: bool, use_ai: bool) -> dict:
    validation = security.validate_upload(filename, data)
    if not validation.ok:
        return {"error": validation.errors}
    info = image_analyzer.analyze_basic(data, validation.detected_mime)
    if info.status != config.STATUS_COMPLETED:
        return {"error": [f"The image could not be analysed: {info.error}"]}

    sha = validation.sha256
    base_cache = st.session_state.setdefault("veriq_base", {})
    if sha not in base_cache:
        small = _small_copy(data)
        with ThreadPoolExecutor(max_workers=3) as pool:
            f_meta = pool.submit(metadata_analyzer.analyze_metadata, data, validation.extension)
            f_ocr = pool.submit(ocr_engine.extract_text, small)
            f_hash = pool.submit(hash_engine.compute_hashes, small)
            meta, ocr, hashes = f_meta.result(), f_ocr.result(), f_hash.result()
        if hashes.sha256 != sha:       # keep the SHA of the real file, not of the downscaled copy
            hashes.sha256 = sha
        base_cache[sha] = {"meta": meta, "ocr": ocr, "hashes": hashes}
        _trim(base_cache)
    base = base_cache[sha]
    meta, ocr, hashes = base["meta"], base["ocr"], base["hashes"]

    kind = file_kind.detect(validation.safe_name, info, meta)
    origin = simple_result.origin_of(meta)
    comparison = None
    if hashes.status == config.STATUS_COMPLETED:
        comparison = get_local_comparison(hashes, validation, info, remember, origin)

    ai_hint = None
    if use_ai and not origin and ai_indicator.available():
        ai_cache = st.session_state.setdefault("veriq_ai", {})
        if sha not in ai_cache:
            ai_cache[sha] = ai_indicator.analyze(data)
            _trim(ai_cache)
        ai_hint = ai_cache[sha]

    return {"error": None, "data": data, "validation": validation, "info": info, "meta": meta,
            "ocr": ocr, "hashes": hashes, "comparison": comparison, "ai_hint": ai_hint, "kind": kind}


def scanning_steps(use_ai: bool) -> list:
    steps = ["Hidden labels", "Camera info", "File kind", "Text", "Similar images"]
    return steps + (["Pixel check"] if use_ai else [])


# ------------------------------------------------ technical report sections
def render_summary(verdict) -> None:
    st.markdown("#### Investigation Summary")
    ui_theme.render_verdict_card(verdict.assessment, verdict.strength)
    st.markdown("**Reason**")
    st.write(verdict.reason)
    if verdict.findings:
        st.markdown("**Findings behind this assessment**")
        st.table([{"Area": f.area, "Finding": f.text, "Weight": f.weight} for f in verdict.findings])
    else:
        st.caption("No findings were recorded.")
    with st.expander("Limitations of this assessment"):
        for text in verdict.limitations:
            st.markdown(f"- {text}")
    with st.expander("Suggested manual checks"):
        for text in verdict.suggested_checks:
            st.markdown(f"- {text}")
    if not verdict.context_checked:
        st.caption("Claim and context research: not performed in this investigation.")


def render_media_information(validation, info) -> None:
    st.markdown("#### Media Information")
    rows = [("File name", validation.safe_name), ("Detected type", validation.detected_mime),
            ("Format (decoder)", info.format), ("File size", f"{validation.size_bytes:,} bytes"),
            ("Dimensions", f"{info.width} x {info.height} px"), ("Megapixels", str(info.megapixels)),
            ("Colour mode", f"{info.mode} ({info.channels} channels)"),
            ("Transparency", "Yes" if info.has_alpha else "No"),
            ("Animated", f"Yes ({info.frames} frames)" if info.animated else "No"),
            ("Average colour (RGB)", str(info.mean_rgb) if info.mean_rgb else "Not available")]
    st.table([{"Field": k, "Value": v} for k, v in rows])
    st.markdown("**SHA-256**")
    st.code(validation.sha256, language=None)
    st.caption("Validation passed. This image was decoded and is not stored.")


def render_metadata(meta) -> None:
    st.markdown("#### Metadata")
    if meta.status != config.STATUS_COMPLETED:
        st.warning(f"Metadata analysis: {meta.status}. {meta.error or ''}")
        return
    st.caption(f"Status: {meta.status}  |  Source: {meta.source}")
    cc = meta.content_credentials
    if cc:
        st.markdown("**Content Credentials (C2PA) found**")
        ai_declared = any("AI" in s for s in cc["digital_source_types"])
        message = ("The file carries an embedded provenance manifest"
                   + (" that declares AI-generated content" if ai_declared else "")
                   + ". VERIQ reads these claims but has not validated the signature.")
        (st.warning if ai_declared else st.info)(message)
        rows = [("Declared source type", ", ".join(cc["digital_source_types"]) or "Not stated"),
                ("Software agent", cc["software_agent"] or "Not stated"),
                ("Manifest generator", cc["generator"] or "Not stated"),
                ("Recorded actions", ", ".join(cc["actions"]) or "Not stated"),
                ("Action timestamps", ", ".join(cc["when"]) or "Not stated")]
        st.table([{"Field": k, "Value": v} for k, v in rows])
    st.markdown("**Metadata found**")
    if meta.found:
        st.table([{"Field": k, "Value": v} for k, v in meta.found.items()])
    else:
        st.write("None of the key fields below were found.")
    st.markdown("**Metadata absent**")
    st.write(", ".join(meta.absent) if meta.absent else "All key fields were present.")
    st.markdown("**GPS location (embedded metadata)**")
    if meta.gps:
        st.warning(f"Embedded coordinates: {meta.gps['latitude']:.6f}, {meta.gps['longitude']:.6f}. "
                   "This is metadata stored inside the file. It may be modified, copied from "
                   "another file or unreliable, and it does not show where the uploader is.")
        if meta.gps["warning"]:
            st.error(meta.gps["warning"])
    else:
        st.write("No GPS metadata was found.")
    for note in meta.notes:
        st.caption(note)
    if meta.all_tags:
        with st.expander(f"All embedded tags ({len(meta.all_tags)})"):
            st.dataframe(meta.all_tags, hide_index=True)


def render_ocr(ocr) -> None:
    st.markdown("#### OCR")
    st.caption(f"Status: {ocr.status}")
    if ocr.status == config.STATUS_NOT_AVAILABLE:
        st.warning(ocr.error or "OCR is not available.")
        return
    if ocr.status == config.STATUS_FAILED:
        st.error(f"OCR failed: {ocr.error}")
        return
    if ocr.text:
        st.markdown("**Extracted text**")
        st.code(ocr.text, language=None)
        c1, c2, c3 = st.columns(3)
        c1.metric("Words read", ocr.word_count)
        c2.metric("Mean confidence", f"{ocr.mean_confidence}%" if ocr.mean_confidence is not None else "n/a")
        c3.metric("Language model", ocr.language)
    else:
        st.write("No text was detected.")
    for note in ocr.notes:
        st.caption(note)


def render_forensics(result) -> None:
    st.markdown("#### Forensic Indicators")
    if result.status != config.STATUS_COMPLETED:
        st.error(f"Forensic analysis: {result.status}. {result.error or ''}")
        return
    st.caption("Forensic indicators are technical observations, not proof of manipulation.")
    st.table([{"Indicator": i.name, "Status": i.status, "Finding": i.summary,
               "Worth a closer look": "Yes" if i.significance == "observation" else "No"}
              for i in result.indicators])
    with st.expander("What each indicator means"):
        for ind in result.indicators:
            if ind.detail:
                st.markdown(f"**{ind.name}.** {ind.detail}")
    if result.ela_png:
        with st.expander("ELA heatmap (brighter = larger change when re-saved)"):
            st.image(result.ela_png, width="stretch")
    st.markdown("**Limitations**")
    for text in result.limitations:
        st.caption(text)


def render_hashes(hashes, comparison) -> None:
    st.markdown("#### Image Fingerprints and Local Comparison")
    if hashes.status != config.STATUS_COMPLETED:
        st.error(f"Fingerprinting: {hashes.status}. {hashes.error or ''}")
        return
    st.caption(f"Status: {hashes.status}")
    st.table([{"Hash": "SHA-256 (exact file)", "Value": hashes.sha256},
              {"Hash": "aHash (average)", "Value": hashes.ahash},
              {"Hash": "pHash (perceptual)", "Value": hashes.phash},
              {"Hash": "dHash (difference)", "Value": hashes.dhash}])
    for note in hashes.notes:
        st.caption(note)
    st.markdown("**Local comparison**")
    if comparison is None:
        st.caption("Comparison with earlier images is turned off on the hosted version, so visitors "
                   "never see each other's images. Run VERIQ on your own computer to use it.")
        return
    if not comparison["ok"]:
        st.warning("The local fingerprint history could not be read, so no comparison was made.")
        return
    exact = comparison["exact"]
    if exact:
        st.info(f"A byte-identical file (same SHA-256) was analysed before by this VERIQ installation. "
                f"First recorded: {exact['first_seen']} UTC, as '{exact['filename']}', "
                f"{exact['times_seen']} time(s). This shows only that VERIQ has seen this file before. "
                "It says nothing about where the file came from.")
    matches = comparison["matches"]
    if matches:
        st.warning("Visually similar images were found in this installation's history. Similar images "
                   "may be copies, resized versions or unrelated look-alikes, so compare them yourself.")
        st.table([{"Similarity": m.level, "pHash distance": m.phash_distance,
                   "dHash distance": m.dhash_distance, "aHash distance": m.ahash_distance,
                   "Earlier file had": simple_result.ORIGIN_LABELS.get(m.origin, "Nothing recorded"),
                   "Recorded name": m.filename, "First recorded (UTC)": m.first_seen} for m in matches])
        st.caption("Distances count differing bits out of 64. Smaller means more similar.")
    elif not exact:
        st.write(f"No visually similar image was found among {comparison['total']} locally stored fingerprint(s).")
    if comparison.get("save_failed"):
        st.caption("The fingerprint could not be saved locally.")
    elif comparison["saved"]:
        st.caption("This image's fingerprint (hashes only, not the image) is saved locally.")
    else:
        st.caption("This image's fingerprint was not saved.")
    st.caption("Comparison covers only images analysed by this installation. It is not a reverse image "
               "search of the internet, so \"no match\" does not mean the image is original.")


def render_image_technical(bundle: dict, with_report: bool) -> None:
    data, validation = bundle["data"], bundle["validation"]
    forensic_cache = st.session_state.setdefault("veriq_forensic", {})
    sha = validation.sha256
    if sha not in forensic_cache:
        with st.spinner("Computing forensic indicators..."):
            forensic_cache[sha] = forensic_analyzer.analyze_forensics(data)
        _trim(forensic_cache)
    forensics = forensic_cache[sha]
    verdict = verdict_engine.evaluate(bundle["meta"], bundle["ocr"], forensics,
                                      bundle["hashes"], bundle["comparison"])
    render_summary(verdict)
    render_media_information(validation, bundle["info"])
    render_metadata(bundle["meta"])
    render_ocr(bundle["ocr"])
    render_forensics(forensics)
    render_hashes(bundle["hashes"], bundle["comparison"])
    verification_guide.render_guide(bundle["meta"])
    if with_report:
        ocr = bundle["ocr"]
        claim_result = None
        if ocr.status == config.STATUS_COMPLETED and ocr.text:
            claim_result = ui_claims.render_claim_investigation(
                [("Text extracted from the image (OCR)", ocr.text)], key_prefix="img",
                has_media=True, heading="Context Investigation: Claims in the Image Text")
        ui_report.render_report_panel(
            lambda rid: report_generator.build_image_report(
                rid, validation, bundle["info"], bundle["meta"], bundle["ocr"], forensics,
                bundle["hashes"], bundle["comparison"], verdict, claim_result),
            report_key=f"img_{sha[:16]}")


def show_image_result(bundle: dict, heading: str = "Result") -> None:
    render_kind(bundle["kind"])
    result = simple_result.simplify(bundle["meta"], bundle["ocr"], bundle["comparison"],
                                    bundle["ai_hint"], bundle["kind"])
    render_simple(result, bundle["data"], heading=heading)
    hint = bundle["ai_hint"]
    if hint is not None and hint.status != config.STATUS_COMPLETED:
        st.caption(f"AI-pixel check: {hint.status}. {hint.error or ''}")
    render_place(bundle["meta"])


# ------------------------------------------------------------ Mode: image
def render_image_mode(remember: bool, use_ai: bool) -> None:
    st.subheader("Check an Image")
    uploaded = st.file_uploader("Image", type=[e.lstrip(".") for e in sorted(config.ALLOWED_EXTENSIONS)],
                                label_visibility="collapsed")
    if uploaded is None:
        render_landing("image")
        st.caption(f"JPG, PNG or WebP, up to {config.MAX_UPLOAD_MB} MB.")
        return

    data = uploaded.getvalue()
    scanner = st.empty()
    scanner.markdown(scanner_html("SCANNING IMAGE…", scanning_steps(use_ai)), unsafe_allow_html=True)
    bundle = analyze_image(data, uploaded.name, remember, use_ai)
    scanner.empty()
    if bundle["error"]:
        st.error("This file could not be used.")
        for message in bundle["error"]:
            st.markdown(f"- {message}")
        return

    st.markdown(pipeline_html(["Upload", "Labels", "Camera", "File kind", "Text"] +
                              (["Look-alikes"] if bundle["comparison"] is not None else []) +
                              (["Pixels"] if bundle["ai_hint"] is not None else []) + ["Answer"]),
                unsafe_allow_html=True)
    show_image_result(bundle)

    st.divider()
    if st.toggle("Show full technical report", key="veriq_detail",
                 help="For analysts: metadata, forensic indicators, claims, evidence and report export."):
        render_image_technical(bundle, with_report=True)


# -------------------------------------------------------------- Mode: URL
def run_url_retrieval(raw: str) -> dict:
    info = url_validator.parse_url(raw)
    extraction = post_extractor.extract(info) if info.ok else None
    image = (None, None, None)
    if extraction is not None and extraction.status == config.STATUS_COMPLETED and extraction.media_urls:
        image = image_fetch.fetch_post_image(extraction.media_urls)
    return {"info": info, "extraction": extraction,
            "image": image[0], "image_name": image[1], "image_error": image[2]}


def render_url_mode(remember: bool, use_ai: bool) -> None:
    st.subheader("Check a Post Link")
    st.write("Paste the link of a public social-media post.")

    with st.form("veriq_url_form"):
        raw = st.text_input("Public post URL", placeholder="https://...", max_chars=url_validator.MAX_URL_LENGTH)
        submitted = st.form_submit_button("Check this post")
    st.caption(f"VERIQ requests the address from {WHERE}, so the site (and, for X, YouTube and TikTok, "
               "that platform's public oEmbed service) can see the request. It never logs in, imitates a "
               "browser session or bypasses access restrictions.")
    if submitted:
        scanner = st.empty()
        scanner.markdown(scanner_html("READING THE POST…", ["Link check", "Public text", "Picture", "Claims"]),
                         unsafe_allow_html=True)
        st.session_state["veriq_post"] = run_url_retrieval(raw)
        scanner.empty()

    state = st.session_state.get("veriq_post")
    manual = st.session_state.get("veriq_manual")
    url_info = state["info"] if state else None
    url_extraction = state["extraction"] if state else None

    needs_fallback = bool(state) and (url_extraction is None or url_extraction.status != config.STATUS_COMPLETED)
    render_manual_fallback(expanded=needs_fallback)

    if not state and manual is None:
        render_landing("url")
        return

    st.markdown("#### The Post's Picture")
    fetched = state["image"] if state else None
    if fetched is not None:
        st.caption("VERIQ found the post's public preview picture. It is usually a small, recompressed "
                   "copy, so it carries no hidden labels. For a better check, upload the original below.")
    elif state and state.get("image_error"):
        st.caption(f"The post's picture could not be fetched automatically: {state['image_error']} "
                   "Many platforms hide pictures behind a login, and VERIQ does not work around that.")
    elif state:
        st.caption("No public picture was offered by this post.")
    extra = st.file_uploader("Upload the post's picture (save it or take a screenshot)",
                             type=[e.lstrip(".") for e in sorted(config.ALLOWED_EXTENSIONS)],
                             key="veriq_post_img")
    image_data, image_name, image_source = None, None, ""
    if extra is not None:
        image_data, image_name, image_source = extra.getvalue(), extra.name, "Your upload"
    elif fetched is not None:
        image_data, image_name, image_source = fetched, state["image_name"], "Public preview picture"

    bundle = None
    if image_data is not None:
        scanner = st.empty()
        scanner.markdown(scanner_html("SCANNING PICTURE…", scanning_steps(use_ai)), unsafe_allow_html=True)
        bundle = analyze_image(image_data, image_name, remember, use_ai)
        scanner.empty()
        if bundle["error"]:
            st.warning("The picture could not be used: " + " ".join(bundle["error"]))
            bundle = None

    sources, published, has_media, user_provided = [], "", False, False
    if url_extraction is not None and url_extraction.status == config.STATUS_COMPLETED:
        parts = [p for p in (url_extraction.title, url_extraction.text) if p]
        if len(parts) == 2 and parts[0] == parts[1]:
            parts = parts[:1]
        if parts:
            sources.append(("Retrieved post", "\n".join(parts)))
        published, has_media = url_extraction.published, bool(url_extraction.media_urls)
    if manual is not None and manual.status == config.STATUS_COMPLETED:
        sources.append(("Text provided by you", manual.text))
        published = published or manual.published
        user_provided = True

    claim_result = st.session_state.get("veriq_url_claims") if sources else None
    render_simple(simple_post.simplify_post(url_info, url_extraction, manual, claim_result,
                                            image_checked=bundle is not None),
                  heading="Result: The Post's Text")

    if bundle is not None:
        st.caption(f"Picture source: {image_source}.")
        show_image_result(bundle, heading="Result: The Post's Picture")

    st.divider()
    if not st.toggle("Show full technical report", key="veriq_url_detail",
                     help="For analysts: URL details, claims, evidence search, timeline, report export."):
        return

    if state:
        render_post_result(state)
    if manual is not None:
        if manual.status == config.STATUS_COMPLETED:
            render_extracted_content(manual, "Text Provided by You")
        else:
            st.warning(manual.error or "No text was provided.")
    if bundle is not None:
        st.markdown("### Picture details")
        render_image_technical(bundle, with_report=False)

    claim_result = None
    if sources:
        claim_result = ui_claims.render_claim_investigation(
            sources, key_prefix="url", published=published, has_media=has_media, user_provided=user_provided)
        st.session_state["veriq_url_claims"] = claim_result
        st.caption("The simple result above updates the next time the page refreshes (press R).")
    else:
        st.info("No post text is available to investigate. Use the manual text box above.")

    key = (report_generator.url_input_hash(url_info, manual) or "none")[:16]
    ui_report.render_report_panel(
        lambda rid: report_generator.build_url_report(rid, url_info, url_extraction, manual, claim_result),
        report_key=f"url_{key}")


def render_post_result(state: dict) -> None:
    info, extraction = state["info"], state["extraction"]
    st.markdown("#### URL Information")
    if not info.ok:
        st.error("This URL was not accepted.")
        for message in info.errors:
            st.markdown(f"- {message}")
        return
    st.table([{"Field": "Submitted URL (normalised)", "Value": info.normalized},
              {"Field": "Detected platform", "Value": info.platform_name},
              {"Field": "Retrieval status", "Value": extraction.status},
              {"Field": "Retrieval method", "Value": extraction.method or "None"}])
    for note in info.notes:
        st.caption(note)
    if extraction.attempts:
        with st.expander("Retrieval attempts"):
            for attempt in extraction.attempts:
                st.text(attempt)
    if extraction.status == config.STATUS_COMPLETED:
        render_extracted_content(extraction, "Extracted Content")
    else:
        if extraction.error:
            st.warning(extraction.error)
        if extraction.fallback_message:
            st.info(extraction.fallback_message)
        for note in extraction.notes:
            st.caption(note)


def render_extracted_content(extraction, heading: str) -> None:
    st.markdown(f"#### {heading}")
    if extraction.text:
        st.markdown("**Post text**")
        st.text(extraction.text)
    else:
        st.write("No post text was retrieved.")
    rows = [("Title", extraction.title), ("Author / account", extraction.author),
            ("Author link", extraction.author_url), ("Site", extraction.site_name),
            ("Date as reported by the source", extraction.published)]
    rows = [{"Field": k, "Value": v} for k, v in rows if v]
    if rows:
        st.table(rows)
    if extraction.media_urls:
        st.markdown("**Media references**")
        st.table([{"Reference": url} for url in extraction.media_urls])
    elif not extraction.user_provided:
        st.caption("No media references were found.")
    for note in extraction.notes:
        st.caption(note)


def render_manual_fallback(expanded: bool) -> None:
    with st.expander("Provide the post text manually", expanded=expanded):
        with st.form("veriq_manual_form"):
            text = st.text_area("Post text", max_chars=post_extractor.MAX_TEXT_CHARS, height=160)
            author = st.text_input("Author / account (optional)", max_chars=200)
            posted = st.text_input("Date or time shown on the post (optional)", max_chars=100)
            use_text = st.form_submit_button("Use this text")
        if use_text:
            st.session_state["veriq_manual"] = post_extractor.from_manual(text, author, posted)


# ------------------------------------------------------ Privacy / disclaimer
def clear_local_history() -> None:
    try:
        removed = local_db.clear_fingerprints()
    except sqlite3.Error:
        st.error("The local history could not be cleared.")
        return
    for key in ("veriq_cmp", "veriq_saved", "veriq_base", "veriq_ai", "veriq_forensic"):
        st.session_state.pop(key, None)
    st.success(f"Cleared {removed} stored fingerprint(s). Re-upload an image to refresh results.")


def render_privacy_panel() -> None:
    fingerprint_line = (
        "not stored or compared on the hosted version." if ONLINE else
        'only if "Remember" is ticked: hashes, the sanitised file name, dimensions, timestamps and a '
        "short note of what the file said about itself, in a local SQLite file. Never the image."
    )
    with st.expander("Privacy and data handling"):
        if ONLINE:
            st.warning("This is the hosted version. Images you upload are processed on the host's "
                       "server (not on your device). Avoid uploading private or sensitive pictures.")
        st.markdown(f"""
- **What is processed:** images you upload, analysed on {WHERE}.
- **Stored images:** never. Files are analysed in memory and temporary files are deleted straight away.
- **Post URL mode:** the URL you submit is requested from {WHERE}, and so is the post's public
  preview picture if the site offers one. The site, and for X, YouTube and TikTok that platform's public
  oEmbed service, can see those requests. Text you paste manually is processed on {WHERE}.
- **Evidence search:** only when you click Search, the query text you can see is sent to Wikipedia and
  the GDELT news index. **Region lookup:** only when you click it, rounded coordinates go to OpenStreetMap.
- **Fingerprints:** {fingerprint_line}
- **Reports and saved records:** only when you ask. Reports never contain the image.
- **Session data:** analysis results, post content, claims and evidence live in this browser session only.
- **Limit:** files up to {config.MAX_UPLOAD_MB} MB.
""")
        if not ONLINE:
            try:
                st.caption(f"Fingerprints currently stored locally: {local_db.count_fingerprints()}")
            except sqlite3.Error:
                st.caption("The local history could not be read.")
            if st.button("Clear local fingerprint history"):
                clear_local_history()


def render_disclaimer() -> None:
    st.markdown(f'<p class="muted">{html.escape(config.DISCLAIMER)}</p>', unsafe_allow_html=True)


# --------------------------------------------------------------------- Main
def main() -> None:
    render_header()
    render_ticker()
    ui_theme.render_tool_status()

    mode = st.radio("Investigation mode", ["IMAGE INVESTIGATION", "POST URL INVESTIGATION"],
                    horizontal=True, label_visibility="collapsed")

    c1, c2 = st.columns(2)
    remember = False
    if not ONLINE:
        remember = c1.checkbox("Remember fingerprints on this computer (spots copies and screenshots later)",
                               value=True, help="Stores only a short fingerprint and a note of what the file "
                               "said about itself, never the image.")
    use_ai = False
    if ai_indicator.available():
        use_ai = c2.checkbox("Also run the experimental AI-pixel check (models must agree)", value=False,
                             help="Weak and often wrong on screenshots. Runs locally; first use downloads models.")
        if use_ai and not st.session_state.get("veriq_warm"):
            st.session_state["veriq_warm"] = True
            threading.Thread(target=ai_indicator.warm, daemon=True).start()
    st.divider()

    if mode == "IMAGE INVESTIGATION":
        render_image_mode(remember, use_ai)
    else:
        render_url_mode(remember, use_ai)

    st.divider()
    render_privacy_panel()
    if not ONLINE:
        ui_report.render_saved_records()
    render_disclaimer()


main()