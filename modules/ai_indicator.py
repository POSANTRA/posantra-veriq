"""POSANTRA | VERIQ - experimental AI-pixel indicator (ensemble).

Runs one or more local open-source image classifiers. LOW RELIABILITY,
especially on screenshots and messaging-app copies. 'Leans AI' needs ALL
models to agree; any disagreement is 'unsure'. A hint only: it never feeds a
verdict, never says 'real', and shows no percentage.
"""
from __future__ import annotations

import importlib.util
import threading
from dataclasses import dataclass
from io import BytesIO
from typing import Optional

import config

LEANS_AI = "leans_ai"
NO_SIGNS = "no_signs"
UNSURE = "unsure"
HIGH, LOW = 0.90, 0.10
AI_WORDS = ("artificial", "ai", "fake", "synthetic", "generated")
REAL_WORDS = ("human", "real", "natural", "authentic")
MAX_SIDE = 448

_lock = threading.Lock()
_loaded: dict = {}


@dataclass
class AIIndicator:
    status: str                       # Completed / Not available / Failed
    level: str = ""
    model: str = ""
    error: Optional[str] = None
    votes_ai: int = 0
    votes_total: int = 0


def available() -> bool:
    return all(importlib.util.find_spec(m) for m in ("torch", "transformers"))


def model_ids() -> list:
    ids = getattr(config, "AI_MODEL_IDS", None)
    return list(ids) if ids else [config.AI_MODEL_ID]


def ai_probability(predictions: list) -> Optional[float]:
    ai = real = None
    for item in predictions or []:
        label = str(item.get("label", "")).lower()
        score = float(item.get("score", 0.0))
        if any(w in label for w in REAL_WORDS):
            real = max(real or 0.0, score)
        elif any(w in label for w in AI_WORDS):
            ai = max(ai or 0.0, score)
    if ai is not None:
        return ai
    if real is not None:
        return 1.0 - real
    return None


def level_for(score: Optional[float]) -> str:
    if score is None:
        return UNSURE
    if score >= HIGH:
        return LEANS_AI
    if score <= LOW:
        return NO_SIGNS
    return UNSURE


def combine(levels: list) -> str:
    """Say 'leans AI' or 'no signs' only when every model agrees."""
    if levels and all(l == LEANS_AI for l in levels):
        return LEANS_AI
    if levels and all(l == NO_SIGNS for l in levels):
        return NO_SIGNS
    return UNSURE


def _pipeline(model_id: str):
    with _lock:
        if model_id not in _loaded:
            from transformers import pipeline
            _loaded[model_id] = pipeline("image-classification", model=model_id)
        return _loaded[model_id]


def warm() -> None:
    """Load models in the background so the first scan is not delayed. Never raises."""
    if not available():
        return
    for mid in model_ids():
        try:
            _pipeline(mid)
        except Exception:
            pass


def analyze(data: bytes, model_id: Optional[str] = None) -> AIIndicator:
    ids = [model_id] if model_id else model_ids()
    label = ", ".join(ids)
    if not available():
        return AIIndicator(config.STATUS_NOT_AVAILABLE, model=label,
                           error="torch and transformers are not installed.")
    try:
        from PIL import Image
        with Image.open(BytesIO(data)) as img:
            rgb = img.convert("RGB")
        rgb.thumbnail((MAX_SIDE, MAX_SIDE))
    except Exception as exc:
        return AIIndicator(config.STATUS_FAILED, model=label,
                           error=f"The image could not be read ({type(exc).__name__}).")
    levels, used, errors = [], [], []
    for mid in ids:
        try:
            levels.append(level_for(ai_probability(_pipeline(mid)(rgb, top_k=5))))
            used.append(mid)
        except Exception as exc:
            errors.append(f"{mid}: {type(exc).__name__}")
    if not levels:
        return AIIndicator(config.STATUS_FAILED, model=label, error="; ".join(errors) or "No model ran.")
    return AIIndicator(config.STATUS_COMPLETED, combine(levels), ", ".join(used), None,
                       votes_ai=levels.count(LEANS_AI), votes_total=len(levels))