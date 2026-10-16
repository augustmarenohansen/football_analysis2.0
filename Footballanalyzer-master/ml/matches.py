"""Match features built only from games finished before the prediction time."""
from collections import defaultdict
from datetime import datetime, timezone
from itertools import groupby
import numpy as np
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


def empty_stats(name):
    return dict(name=name, mp=0, w=0, d=0, l=0, gf=0, ga=0, gd=0, pts=0, form=[])


def features(home, away, league):
    result = {"league": str(league)}
    for prefix, stats in (("home", home), ("away", away)):
        n = max(stats["mp"], 1)
        result.update({f"{prefix}_{k}": stats[k] / n for k in ("w", "d", "gf", "ga", "gd", "pts")})
        form = stats["form"][-5:]
        result[f"{prefix}_form"] = sum({"W": 3, "D": 1, "L": 0}[x] for x in form) / max(len(form), 1)
        result[f"{prefix}_played"] = stats["mp"]
    return result


def apply_result(stats, scored, conceded):
    outcome = "W" if scored > conceded else "D" if scored == conceded else "L"
    stats["mp"] += 1
    stats[outcome.lower()] += 1
    stats["gf"] += scored
    stats["ga"] += conceded
    stats["gd"] = stats["gf"] - stats["ga"]
    stats["pts"] += {"W": 3, "D": 1, "L": 0}[outcome]
    stats["form"].append(outcome)


def build_examples(fixtures):
    states = {}
    examples = []
    seen = set()
    completed = []
    now = datetime.now(timezone.utc).timestamp()
    for f in fixtures:
        # These five leagues include relegation play-offs in the same API league ID.
        # Exclude them before collecting teams or accumulating season statistics.
        if not f["league"].get("round", "").startswith("Regular Season -"):
            continue
        fid = f["fixture"]["id"]
        if fid in seen:
            raise ValueError(f"Duplicate fixture ID: {fid}")
        seen.add(fid)
        league, season = f["league"]["id"], f["league"]["season"]
        for side in ("home", "away"):
            team = f["teams"][side]
            states.setdefault((league, season, team["id"]), empty_stats(team["name"]))
        # League model predicts regulation-time results; exclude abandoned/awarded games.
        if f["fixture"]["status"]["short"] != "FT" or f["fixture"]["timestamp"] > now:
            continue
        if any(type(f["goals"][side]) is not int or f["goals"][side] < 0 for side in ("home", "away")):
            raise ValueError(f"Missing/invalid final score: {fid}")
        completed.append(f)
    completed.sort(key=lambda f: (f["fixture"]["timestamp"], f["fixture"]["id"]))
    # No game at the same kickoff time can influence another game's features.
    pending = []
    for timestamp, group in groupby(completed, key=lambda f: f["fixture"]["timestamp"]):
        # API fixture timestamps are kickoff times, not final-whistle times.
        # Allow a conservative four-hour delay before a result becomes a feature.
        ready = [item for item in pending if item[0] <= timestamp]
        pending = [item for item in pending if item[0] > timestamp]
        for _, home, away, hg, ag in ready:
            apply_result(home, hg, ag)
            apply_result(away, ag, hg)
        group = list(group)
        for f in group:
            league, season = f["league"]["id"], f["league"]["season"]
            home = states[(league, season, f["teams"]["home"]["id"])]
            away = states[(league, season, f["teams"]["away"]["id"])]
            hg, ag = f["goals"]["home"], f["goals"]["away"]
            if min(home["mp"], away["mp"]) >= 5:
                label = "home" if hg > ag else "away" if ag > hg else "draw"
                examples.append((timestamp, features(home, away, league), label))
            pending.append((timestamp + 4 * 3600, home, away, hg, ag))
    for _, home, away, hg, ag in pending:
        apply_result(home, hg, ag)
        apply_result(away, ag, hg)
    return examples, states


def fit_bundle(fixtures, sources):
    examples, states = build_examples(fixtures)
    if len(examples) < 200:
        raise ValueError(f"Only {len(examples)} usable matches; at least 200 required. Fetch more seasons.")
    cutoff = examples[int(len(examples) * 0.8)][0]
    train = [x for x in examples if x[0] + 4 * 3600 < cutoff]
    test = [x for x in examples if x[0] >= cutoff]
    classes = ["away", "draw", "home"]
    if len(train) < 100 or len(test) < 30 or set(x[2] for x in train) != set(classes):
        raise ValueError("Not enough chronological training/validation data for all three outcomes.")
    def pipeline():
        return make_pipeline(DictVectorizer(sparse=False), StandardScaler(), LogisticRegression(max_iter=2000, C=0.1))
    model = pipeline()
    model.fit([x[1] for x in train], [x[2] for x in train])
    probabilities = model.predict_proba([x[1] for x in test])
    truth = [x[2] for x in test]
    prior = np.array([sum(x[2] == c for x in train) / len(train) for c in model.classes_])
    baseline = np.tile(prior, (len(test), 1))
    metrics = {
        "training_matches": len(train), "validation_matches": len(test),
        "validation_from": datetime.fromtimestamp(cutoff, timezone.utc).isoformat(),
        "accuracy": float(accuracy_score(truth, model.classes_[probabilities.argmax(axis=1)])),
        "log_loss": float(log_loss(truth, probabilities, labels=model.classes_)),
        "baseline_accuracy": float(accuracy_score(truth, [model.classes_[prior.argmax()]] * len(test))),
        "baseline_log_loss": float(log_loss(truth, baseline, labels=model.classes_)),
    }
    # Evaluate on later games first, then refit the deployed candidate on all known games.
    model.fit([x[1] for x in examples], [x[2] for x in examples])
    latest = defaultdict(int)
    for league, season, _ in states:
        latest[league] = max(latest[league], season)
    teams = {league: {str(tid): stats for (lid, year, tid), stats in states.items()
                      if lid == league and year == season} for league, season in latest.items()}
    return {"version": 1, "model": model, "teams": teams, "seasons": dict(latest),
            "metrics": metrics, "sources": sources, "trained_at": datetime.now(timezone.utc).isoformat(),
            "last_match": datetime.fromtimestamp(examples[-1][0], timezone.utc).isoformat()}
