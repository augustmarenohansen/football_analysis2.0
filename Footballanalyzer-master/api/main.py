# api/main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from ml.features import FeatureBuilder
from pydantic import BaseModel
import pandas as pd
import numpy as np
import os
import unicodedata
import joblib
import math
from typing import List, Dict, Any

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "http://127.0.0.1:8000",   
        "http://localhost:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

#  helpers 
def _norm(s: str) -> str:
    if s is None:
        return ""
    s = str(s).replace("\u00a0", " ")
    s = unicodedata.normalize("NFKC", s)
    return s.strip().casefold()

def s_int(x: Any, default: int = 0) -> int:
    try:
        if x is None or (isinstance(x, float) and math.isnan(x)):
            return default
        return int(float(x))
    except Exception:
        return default

def s_float(x: Any, default: float = 0.0) -> float:
    try:
        f = float(x)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default

def s_str(x: Any, default: str = "-") -> str:
    if x is None:
        return default
    if isinstance(x, float) and math.isnan(x):
        return default
    s = str(x).strip()
    return s if s else default

#  load data 
try:
    base_dir = os.path.dirname(os.path.dirname(__file__))  # project root
    data_path = os.path.join(base_dir, "data", "serie_a_full_data.csv")
    df = pd.read_csv(data_path)
    df.columns = df.columns.str.lower()
    df["sesonger"] = pd.to_numeric(df["sesonger"], errors="coerce")
    df["squad"] = df["squad"].astype(str)
    df["squad_norm"] = df["squad"].apply(_norm)

    latest = int(df["sesonger"].max())
    print("✅ Data loaded. Latest season:", latest)
except Exception as e:
    print("❌ Error loading data:", e)
    df = None


import sys

def _install_featurebuilder_pickle_shim():
    """
    Some old pickles reference __main__.FeatureBuilder.
    This shim maps that to ml.features.FeatureBuilder so joblib can unpickle.
    Safe to call multiple times.
    """
    try:
        from ml.features import FeatureBuilder as _RealFeatureBuilder
        globals()["FeatureBuilder"] = _RealFeatureBuilder
        _RealFeatureBuilder.__module__ = "__main__"
        sys.modules["__main__"] = sys.modules[__name__]
        print("▶ Installed FeatureBuilder pickle-compat shim.")
    except Exception as e:
        print(f"⚠️  Failed to install pickle shim: {e}")

model = None
try:
    model_path = os.path.join(base_dir, "models", "model.joblib")
    abs_model_path = os.path.abspath(model_path)
    if not os.path.exists(model_path):
        print(f"❌ Model file not found at: {abs_model_path}")
        raise FileNotFoundError(abs_model_path)


    try:
        from ml.features import FeatureBuilder  
        model = joblib.load(model_path)
        print(f"✅ ML model loaded (normal): {abs_model_path}")
    except Exception as first_err:
        print(f"ℹ️  Normal load failed: {first_err}")
        _install_featurebuilder_pickle_shim()
        model = joblib.load(model_path)
        print(f"✅ ML model loaded (shim): {abs_model_path}")

except Exception as e:
    model = None
    print(f"⚠️  No ML model loaded ({e}). /api/compare will fall back to heuristic.")

class MatchPrediction(BaseModel):
    home_team: str
    away_team: str

# endpoints 
@app.get("/api/teams")
async def get_teams() -> Dict[str, List[str]]:
    if df is None:
        raise HTTPException(status_code=500, detail="Data not loaded")
    latest = int(df["sesonger"].max())
    teams = sorted(df[df["sesonger"] == latest]["squad"].dropna().unique().tolist())
    return {"teams": teams}

@app.get("/api/team/{team}")
async def get_team_stats(team: str):
    if df is None:
        raise HTTPException(status_code=500, detail="Data not loaded")
    tnorm = _norm(team)
    block = df[df["squad_norm"] == tnorm]
    if block.empty:
        raise HTTPException(status_code=404, detail=f"Team {team} not found")

    latest = int(block["sesonger"].max())
    row = block[block["sesonger"] == latest].iloc[0]

    return {
        "mp":  s_int(row.get("mp")),
        "w":   s_int(row.get("w")),
        "d":   s_int(row.get("d")),
        "l":   s_int(row.get("l")),
        "gf":  s_int(row.get("gf")),
        "ga":  s_int(row.get("ga")),
        "gd":  s_int(row.get("gd")),
        "pts": s_int(row.get("pts")),
        "last_5":     s_str(row.get("last_5")),
        "top_scorer": s_str(row.get("top_team_scorer")),
        "goalkeeper": s_str(row.get("goalkeeper")),
    }

def _features_from_stats(stats: dict) -> pd.DataFrame:
   
    row = {
        "mp":  s_int(stats.get("mp")),
        "w":   s_int(stats.get("w")),
        "d":   s_int(stats.get("d")),
        "l":   s_int(stats.get("l")),
        "gf":  s_int(stats.get("gf")),
        "ga":  s_int(stats.get("ga")),
        "gd":  s_int(stats.get("gd")),
        "pts": s_int(stats.get("pts")),
        "sesonger": 0,  
    }
    return pd.DataFrame([row])

@app.post("/api/compare")
async def compare_teams(match: MatchPrediction):
    home = await get_team_stats(match.home_team)
    away = await get_team_stats(match.away_team)

    ml_home_prob = ml_away_prob = None
    if model is not None:
        Xh = _features_from_stats(home).drop(columns=["sesonger"], errors="ignore")
        Xa = _features_from_stats(away).drop(columns=["sesonger"], errors="ignore")
        try:
            ml_home_prob = float(model.predict_proba(Xh)[0][1])  # P(above-average)
            ml_away_prob = float(model.predict_proba(Xa)[0][1])
        except Exception as e:
            print("ML scoring failed:", e)
            ml_home_prob = ml_away_prob = None

    # 3) Heuristic as safety net
    mp_h = max(s_int(home["mp"]), 1)
    mp_a = max(s_int(away["mp"]), 1)

    win_h = s_int(home["w"]) / mp_h
    win_a = s_int(away["w"]) / mp_a
    gpg_h = s_int(home["gf"]) / mp_h
    gpg_a = s_int(away["gf"]) / mp_a
    def_h = s_int(home["ga"]) / mp_h
    def_a = s_int(away["ga"]) / mp_a

    st_h = (win_h * 1.2 + gpg_h) / (def_a + 1.0)
    st_a = (win_a + gpg_a) / (def_h + 1.0)

    tot = st_h + st_a + 1.0
    h_prob_h = st_h / tot
    a_prob_h = st_a / tot
    d_prob_h = max(0.0, 1.0 - (h_prob_h + a_prob_h))

    
    if ml_home_prob is not None and ml_away_prob is not None:
        draw_prior = 0.22  
        s = ml_home_prob + ml_away_prob + 1e-9
        h_prob_ml = (1 - draw_prior) * (ml_home_prob / s)
        a_prob_ml = (1 - draw_prior) * (ml_away_prob / s)
        d_prob_ml = draw_prior

        w_ml, w_h = 0.65, 0.35  
        home_p = w_ml * h_prob_ml + w_h * h_prob_h
        away_p = w_ml * a_prob_ml + w_h * a_prob_h
        draw_p = w_ml * d_prob_ml + w_h * d_prob_h
        model_name = "logreg-season-strength (ML) + heuristic blend"
        ml_raw = {"home_strength_prob": round(ml_home_prob, 3),
                  "away_strength_prob": round(ml_away_prob, 3)}
    else:
        home_p, draw_p, away_p = h_prob_h, d_prob_h, a_prob_h
        model_name = "heuristic-only (no model loaded)"
        ml_raw = None

    ssum = home_p + draw_p + away_p
    if ssum > 0:
        home_p, draw_p, away_p = home_p/ssum, draw_p/ssum, away_p/ssum

    outcomes = ["Home Win", "Draw", "Away Win"]
    pred = outcomes[int(np.argmax([home_p, draw_p, away_p]))]

    return {
        "home_win": round(float(home_p), 3),
        "draw":     round(float(draw_p), 3),
        "away_win": round(float(away_p), 3),
        "prediction": pred,
        "details": {
            "model": model_name,
            "ml_raw": ml_raw,
            "home_team": {
                "form": {
                    "win_ratio": round(win_h * 100, 1),
                    "goals_per_game": round(gpg_h, 2),
                    "defense_rating": round(1.0 / (def_h + 1.0), 2),
                },
                "recent": {
                    "last_5": home.get("last_5", "-"),
                    "top_scorer": home.get("top_scorer", "-"),
                    "goalkeeper": home.get("goalkeeper", "-"),
                },
            },
            "away_team": {
                "form": {
                    "win_ratio": round(win_a * 100, 1),
                    "goals_per_game": round(gpg_a, 2),
                  "defense_rating": round(1.0 / (def_a + 1.0), 2),
                },
                "recent": {
                    "last_5": away.get("last_5", "-"),
                    "top_scorer": away.get("top_scorer", "-"),
                    "goalkeeper": away.get("goalkeeper", "-"),
                },
            },
        },
    }


from api.matches import router as matches_router
app.include_router(matches_router)

# Register after the API routes so the same server can serve the website.
app.mount("/", StaticFiles(directory=os.path.join(base_dir, "frontend"), html=True), name="frontend")
