import argparse
from sklearn.base import BaseEstimator, TransformerMixin
from ml.features import FeatureBuilder
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
import pandas as pd
import numpy as np
import os
import joblib


def prepare_target(df: pd.DataFrame) -> np.ndarray:
    """Binary label: 1 if pts > league mean that season, else 0."""
    return (df["pts"] > df.groupby("sesonger")["pts"].transform("mean")).astype(int).to_numpy()


def build_pipeline() -> Pipeline:
    return Pipeline([
        ("features", FeatureBuilder()),
        ("clf", LogisticRegression(max_iter=2000))
    ])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", required=True, help="Path to serie_a_full_data.csv")
    p.add_argument("--out", default="models/model.joblib", help="Where to save model")
    args = p.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)

    df = pd.read_csv(args.data)
    df.columns = df.columns.str.lower()

    required = {"mp","w","d","l","gf","ga","gd","pts","sesonger"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        raise SystemExit(f"Missing columns: {missing}")

    X = df[list(required)]
    y = prepare_target(df)

    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)

    pipe = build_pipeline()
    pipe.fit(Xtr, ytr)

    joblib.dump(pipe, args.out)
    print(f"✅ Model saved to {args.out}")

    pred = pipe.predict(Xte)
    acc = accuracy_score(yte, pred)
    print(f"Validation accuracy: {acc:.3f}")


if __name__ == "__main__":
    main()
