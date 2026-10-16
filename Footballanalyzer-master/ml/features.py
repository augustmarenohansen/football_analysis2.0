import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin
from sklearn.preprocessing import StandardScaler

class FeatureBuilder(BaseEstimator, TransformerMixin):
    """Builds features from raw season totals."""
    def __init__(self):
        self.scaler = StandardScaler()
        self.feature_columns_ = None

    def fit(self, X, y=None):
        feats = self._prepare_features(X)
        self.feature_columns_ = feats.columns
        self.scaler.fit(feats)
        return self

    def transform(self, X):
        feats = self._prepare_features(X)
        feats = feats[self.feature_columns_]
        Z = self.scaler.transform(feats)
        return pd.DataFrame(Z, columns=self.feature_columns_, index=X.index)

    def _prepare_features(self, X: pd.DataFrame) -> pd.DataFrame:
        df = X.copy()
        mp = np.maximum(df["mp"].astype(float), 1.0)
        df["win_ratio"] = df["w"].astype(float) / mp
        df["goals_per_game"] = df["gf"].astype(float) / mp
        df["goals_against_per_game"] = df["ga"].astype(float) / mp
        cols = ["mp", "win_ratio", "goals_per_game", "goals_against_per_game", "gd"]
        return df[cols]
