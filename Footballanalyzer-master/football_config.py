from pathlib import Path

ROOT = Path(__file__).resolve().parent
LEAGUES = {39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1"}
CACHE = ROOT / "data" / "api_football"
BUNDLE = ROOT / "models" / "match_bundle.joblib"
