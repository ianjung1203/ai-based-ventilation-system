"""NumPy ridge and a learned temporal-feature MLP; no pickle or heavy runtime."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np

from .data import HORIZONS, Dataset


def mae_by_horizon(pred, y, mask):
    return np.array([np.mean(np.abs(pred[mask[:, j], j] - y[mask[:, j], j]))
                     if mask[:, j].any() else np.nan for j in range(y.shape[1])]) * 1000


class Regressor:
    def __init__(self, kind="ridge", alpha=10, hidden=48, seed=42):
        self.kind, self.alpha, self.hidden, self.seed = kind, alpha, hidden, seed
        self.params = {}

    def fit(self, data: Dataset, validation: Dataset, epochs=220):
        x, y, mask = data.x, data.y, data.mask
        if np.min(mask.sum(axis=0)) < 5:
            raise ValueError("each horizon needs at least 5 observed targets; collect longer/more runs")
        self.xmean = x.mean(axis=0)
        self.xscale = np.maximum(x.std(axis=0), .02)
        self.ymean = np.array([y[mask[:, j], j].mean() for j in range(y.shape[1])])
        self.yscale = np.maximum(np.array([y[mask[:, j], j].std() for j in range(y.shape[1])]), .05)
        self.xmin, self.xmax = x.min(axis=0), x.max(axis=0)
        z = (x - self.xmean) / self.xscale
        target = (y - self.ymean) / self.yscale
        if self.kind == "ridge":
            z = np.c_[z, np.ones(len(z))]
            w = []
            for j in range(y.shape[1]):
                m = mask[:, j]
                reg = np.eye(z.shape[1]) * self.alpha
                reg[-1, -1] = 0
                w.append(np.linalg.solve(z[m].T @ z[m] + reg, z[m].T @ target[m, j]))
            self.params = {"w": np.array(w).T}
            self.epochs_used = 0
            return self
        if self.kind != "mlp":
            raise ValueError("unknown regressor kind")
        rng = np.random.default_rng(self.seed)
        self.params = {"w1": rng.normal(0, 1 / np.sqrt(z.shape[1]), (z.shape[1], self.hidden)),
                       "b1": np.zeros(self.hidden),
                       "w2": rng.normal(0, .05, (self.hidden, y.shape[1])),
                       "b2": np.zeros(y.shape[1])}
        mom = {k: np.zeros_like(v) for k, v in self.params.items()}
        vel = {k: np.zeros_like(v) for k, v in self.params.items()}
        # Each horizon has equal total weight despite censored long horizons.
        horizon_weight = 1 / np.maximum(mask.mean(axis=0), .01)
        best, best_params, wait, step = float("inf"), None, 0, 0
        for epoch in range(epochs):
            for ix in np.array_split(rng.permutation(len(z)), max(1, int(np.ceil(len(z) / 128)))):
                step += 1
                p = self.params
                a = np.tanh(z[ix] @ p["w1"] + p["b1"])
                output = a @ p["w2"] + p["b2"]
                err = (output - target[ix]) * mask[ix] * horizon_weight
                grad_out = 2 * err / (len(ix) * y.shape[1])
                grad_a = (grad_out @ p["w2"].T) * (1 - a * a)
                grads = {"w2": a.T @ grad_out + .0002 * p["w2"],
                         "b2": grad_out.sum(axis=0),
                         "w1": z[ix].T @ grad_a + .0002 * p["w1"],
                         "b1": grad_a.sum(axis=0)}
                for k, g in grads.items():
                    g = np.clip(g, -5, 5)
                    mom[k] = .9 * mom[k] + .1 * g
                    vel[k] = .999 * vel[k] + .001 * g * g
                    p[k] -= .002 * (mom[k] / (1 - .9 ** step)) / (np.sqrt(vel[k] / (1 - .999 ** step)) + 1e-8)
            score = float(np.nanmean(mae_by_horizon(self.predict(validation.x), validation.y, validation.mask)))
            if score < best - .02:
                best, wait = score, 0
                best_params = {k: v.copy() for k, v in self.params.items()}
                self.epochs_used = epoch + 1
            else:
                wait += 1
            if wait >= 30:
                break
        self.params = best_params
        return self

    def predict(self, x):
        z = (np.atleast_2d(x) - self.xmean) / self.xscale
        if self.kind == "ridge":
            y = np.c_[z, np.ones(len(z))] @ self.params["w"]
        else:
            p = self.params
            y = np.tanh(z @ p["w1"] + p["b1"]) @ p["w2"] + p["b2"]
        return y * self.yscale + self.ymean

    def out_of_range(self, x):
        # A screening heuristic, not a statistical guarantee of model validity.
        margin = np.maximum((self.xmax - self.xmin) * .25, .05)
        return bool(np.any((x < self.xmin - margin) | (x > self.xmax + margin)))

    def arrays(self):
        return {**self.params, **{k: getattr(self, k) for k in
                ["xmean", "xscale", "ymean", "yscale", "xmin", "xmax"]}}


def save_bundle(path, models, metadata):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    arrays = {f"{mode}__{k}": v for mode, model in models.items() for k, v in model.arrays().items()}
    np.savez_compressed(path / "weights.npz", **arrays)
    metadata = {**metadata, "format_version": 1, "horizons_seconds": HORIZONS,
                "models": {mode: {"kind": m.kind, "epochs_used": m.epochs_used} for mode, m in models.items()},
                "weights_sha256": hashlib.sha256((path / "weights.npz").read_bytes()).hexdigest()}
    (path / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def load_bundle(path):
    path = Path(path)
    meta = json.loads((path / "metadata.json").read_text(encoding="utf-8"))
    if meta.get("format_version") != 1 or meta.get("horizons_seconds") != HORIZONS:
        raise ValueError("unsupported model schema")
    if hashlib.sha256((path / "weights.npz").read_bytes()).hexdigest() != meta["weights_sha256"]:
        raise ValueError("model checksum mismatch")
    models = {}
    with np.load(path / "weights.npz", allow_pickle=False) as weights:
        for mode, spec in meta["models"].items():
            model = Regressor(spec["kind"])
            for key in ["xmean", "xscale", "ymean", "yscale", "xmin", "xmax"]:
                setattr(model, key, weights[f"{mode}__{key}"])
            keys = ["w"] if model.kind == "ridge" else ["w1", "b1", "w2", "b2"]
            model.params = {k: weights[f"{mode}__{k}"] for k in keys}
            if not all(np.isfinite(v).all() for v in model.arrays().values()):
                raise ValueError("non-finite model weights")
            models[mode] = model
    return models, meta
