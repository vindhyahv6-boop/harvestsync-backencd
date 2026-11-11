"""Client for Member 1's deployed yield model (HarvestSync-AI on Render)."""
from datetime import date, timedelta
import requests

import os

YIELD_URL = os.environ.get("YIELD_URL", "https://harvestsync-ai.onrender.com/predict")

# Rough per-acre fallback so the demo never breaks if the API is asleep/down.
# Values Member 1's model supports (from their update).
SUPPORTED = {
    "crop": ["Tomato", "Potato", "Onion", "Maize", "Rice"],
    "soil": ["Red", "Black", "Alluvial", "Loamy"],
    "irrigation": ["Drip", "Rainfed", "Canal"],
}


def check_inputs(crop, soil, irrigation):
    """Return an error message if a value is not supported by the model, else None."""
    for name, val in (("crop", crop), ("soil", soil), ("irrigation", irrigation)):
        if str(val).strip().title() not in SUPPORTED[name]:
            return f"Unsupported {name} '{val}'. Allowed: {', '.join(SUPPORTED[name])}"
    return None


FALLBACK = {  # crop: (kg per acre, days to harvest)
    "rice": (2000, 120), "wheat": (1800, 130), "maize": (2200, 110),
    "tomato": (9000, 90), "potato": (8000, 100), "onion": (7000, 120),
    "cotton": (600, 160), "sugarcane": (30000, 330), "ragi": (1000, 115),
}


def _flatten(raw):
    # If the API wraps the answer, e.g. {"prediction": {...}}, unwrap it.
    if isinstance(raw, dict) and len(raw) == 1:
        only = next(iter(raw.values()))
        if isinstance(only, dict):
            return only
    return raw


def _pick(raw, *needles):
    for k, v in raw.items():
        kl = str(k).lower()
        if all(n in kl for n in needles):
            return v
    return None


def normalize(raw, sowing_date):
    """Accepts any reasonable key names (expected_yield_kg, yield, harvest_days...)."""
    raw = _flatten(raw)
    y = _pick(raw, "yield")
    days = _pick(raw, "day")
    hdate = _pick(raw, "date")
    if y is None:
        raise ValueError(f"No yield found in response: {raw}")
    y = float(y)
    days = int(round(float(days))) if days is not None else None
    if not hdate and days is not None:
        hdate = (date.fromisoformat(sowing_date) + timedelta(days=days)).isoformat()
    if days is None and hdate:
        days = (date.fromisoformat(str(hdate)[:10]) - date.fromisoformat(sowing_date)).days
    return {"yield_kg": round(y, 1), "harvest_days": days,
            "harvest_date": str(hdate)[:10] if hdate else None}


def fallback_estimate(crop, area, sowing_date):
    kg_acre, days = FALLBACK.get(str(crop).lower(), (2000, 120))
    return {"yield_kg": round(kg_acre * float(area), 1), "harvest_days": days,
            "harvest_date": (date.fromisoformat(sowing_date) + timedelta(days=days)).isoformat()}


def predict_yield(crop, area, soil, rainfall, temperature, irrigation, sowing_date):
    payload = {"crop": str(crop).strip().title(), "area": area, "soil": str(soil).strip().title(),
               "rainfall": rainfall, "temperature": temperature,
               "irrigation": str(irrigation).strip().title(),
               "sowing_date": sowing_date}
    last_err = None
    for _ in range(2):  # Render free tier cold start: first call can be slow
        r = None
        try:
            r = requests.post(YIELD_URL, json=payload, timeout=60)
            r.raise_for_status()
            out = normalize(r.json(), sowing_date)
            out["source"] = "model"
            return out
        except (requests.RequestException, ValueError, KeyError) as e:
            last_err = f"{e} {r.text[:200] if r is not None else ''}".strip()
    out = fallback_estimate(crop, area, sowing_date)
    out["source"] = "fallback"
    out["warning"] = f"Yield API unavailable, used estimate: {last_err}"
    return out
