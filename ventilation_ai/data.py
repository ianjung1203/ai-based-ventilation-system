"""Strict telemetry validation and causal, run-isolated training windows.

window_open at t describes the action during [t, t + sample_seconds).
Targets stop at an action change; the endpoint may report the new action.
"""
from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SAMPLE_SECONDS = 10
HISTORY_SECONDS = 300
HORIZONS = {"closed": [60, 120, 180, 300, 600, 900],
            "open": [10, 30, 60, 90, 120, 180, 300, 450, 600]}


def timestamp(value):
    if isinstance(value, bool):
        raise ValueError("timestamp must be epoch seconds or an ISO timestamp with timezone")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        try:
            result = float(value)
        except (TypeError, ValueError):
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                raise ValueError("timestamp needs a timezone")
            result = dt.timestamp()
    if not np.isfinite(result):
        raise ValueError("non-finite timestamp")
    return result


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Reading:
    timestamp: float
    run_id: str
    co2_ppm: float
    temp_c: float
    humidity_pct: float
    outdoor_co2_ppm: float
    outdoor_temp_c: float
    outdoor_pm25_ugm3: float
    window_open: bool
    window_changed_at: float
    outdoor_observed_at: float
    source: str = "MEASURED"
    outdoor_source: str = "MEASURED"

    @classmethod
    def parse(cls, raw):
        required = set(cls.__dataclass_fields__) - {"source", "outdoor_source"}
        missing = required - raw.keys()
        if missing:
            raise ValueError(f"missing fields: {', '.join(sorted(missing))}")
        d = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        d["timestamp"] = timestamp(d["timestamp"])
        d["window_changed_at"] = timestamp(d["window_changed_at"])
        d["outdoor_observed_at"] = timestamp(d["outdoor_observed_at"])
        if d["window_changed_at"] > d["timestamp"]:
            raise ValueError("window_changed_at is in the future")
        if d["outdoor_observed_at"] > d["timestamp"]:
            raise ValueError("outdoor_observed_at is in the future")
        states = {"true": True, "false": False, "1": True, "0": False}
        value = d["window_open"]
        if str(value).lower() not in states:
            raise ValueError("window_open must be true/false or 1/0")
        d["window_open"] = states[str(value).lower()]
        for name, lo, hi in [("co2_ppm", 250, 10000), ("temp_c", -30, 60),
                             ("humidity_pct", 0, 100), ("outdoor_co2_ppm", 250, 2000),
                             ("outdoor_temp_c", -50, 60), ("outdoor_pm25_ugm3", 0, 2000)]:
            if isinstance(d[name], bool):
                raise ValueError(f"{name} must be numeric")
            d[name] = float(d[name])
            if not np.isfinite(d[name]) or not lo <= d[name] <= hi:
                raise ValueError(f"{name} must be finite and in [{lo}, {hi}]")
        if not isinstance(d["run_id"], str) or not d["run_id"].strip():
            raise ValueError("run_id must be a nonempty string")
        for name in ("source", "outdoor_source"):
            if d.get(name, "MEASURED") not in {"MEASURED", "SYNTHETIC", "SCENARIO"}:
                raise ValueError(f"invalid {name}")
        return cls(**d)

    def to_dict(self):
        return asdict(self)


def load_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as f:
        rows = [Reading.parse(row) for row in csv.DictReader(f)]
    validate_series(rows, grouped=True)
    return rows


def save_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(Reading.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(r.to_dict() for r in rows)


def group_runs(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r.run_id, []).append(r)
    return groups


def validate_series(rows, grouped=False, regular=False):
    if not rows:
        raise ValueError("empty telemetry")
    groups = group_runs(rows) if grouped else {rows[0].run_id: rows}
    for run, values in groups.items():
        if any(r.run_id != run for r in values):
            raise ValueError("history crosses run_id boundaries")
        for a, b in zip(values, values[1:]):
            dt = b.timestamp - a.timestamp
            if dt <= 0:
                raise ValueError("timestamps must be strictly increasing within each run")
            if regular and abs(dt - SAMPLE_SECONDS) > 0.01:
                raise ValueError("history requires uninterrupted 10-second samples")
            if a.window_open == b.window_open and a.window_changed_at != b.window_changed_at:
                raise ValueError("window_changed_at changed without a state change")
            if a.window_open != b.window_open and not a.timestamp < b.window_changed_at <= b.timestamp:
                raise ValueError("inconsistent actuator transition timestamp")


def features(history):
    """Five-minute lag vector. Only observations available at the origin are used.

    Exclude the current action from features: it is the future action hypothesis
    selected by the open/closed model. Past actions remain observed inputs.
    """
    n = HISTORY_SECONDS // SAMPLE_SECONDS + 1
    if len(history) < n:
        raise ValueError(f"need {n} readings (5 minutes at 10-second intervals)")
    h = history[-n:]
    c = np.array([r.co2_ppm for r in h])
    last = h[-1]
    lag = (c[::3] - c[-1]) / 1000
    past_actions = np.array([r.window_open for r in h[:-1]], dtype=float)
    x = [last.co2_ppm / 1000, last.outdoor_co2_ppm / 1000,
         last.temp_c / 30, last.humidity_pct / 100, last.outdoor_temp_c / 30,
         (last.temp_c - last.outdoor_temp_c) / 30,
         np.mean(c[-6:]) / 1000, np.std(c) / 1000,
         (c[-1] - c[-7]) / 1000, (c[-1] - c[0]) / 1000,
         float(np.mean(past_actions)), float(past_actions[-1])]
    # Physical starting excess helps a small regressor learn nonlinear decay.
    excess = (last.co2_ppm - last.outdoor_co2_ppm) / 1000
    x += [excess, excess ** 2, excess * abs(last.temp_c - last.outdoor_temp_c) / 30]
    return np.array(x + lag.tolist() + past_actions[::3].tolist(), dtype=float)


@dataclass
class Dataset:
    x: np.ndarray
    y: np.ndarray
    mask: np.ndarray
    initial: np.ndarray
    trend: np.ndarray
    runs: np.ndarray


def make_dataset(rows, mode, stride=3):
    xs, ys, masks, initial, trends, ids = [], [], [], [], [], []
    horizons = HORIZONS[mode]
    n = HISTORY_SECONDS // SAMPLE_SECONDS
    for run, values in group_runs(rows).items():
        # Gaps invalidate windows, never bridge them with made-up samples.
        times = np.array([r.timestamp for r in values])
        gaps = np.r_[0, np.cumsum(np.abs(np.diff(times) - SAMPLE_SECONDS) > .01)]
        for i in range(n, len(values) - 1):
            if i % stride and values[i].window_open == values[i - 1].window_open:
                continue
            if values[i].window_open != (mode == "open") or gaps[i] != gaps[i - n]:
                continue
            x = features(values[i - n:i + 1])
            y, mask = [], []
            for seconds in horizons:
                j = i + seconds // SAMPLE_SECONDS
                valid = (j < len(values) and gaps[j] == gaps[i] and
                         all(r.window_open == (mode == "open") for r in values[i:j]))
                mask.append(valid)
                y.append((values[j].co2_ppm - values[i].co2_ppm) / 1000 if valid else 0)
            if not any(mask):
                continue
            xs.append(x); ys.append(y); masks.append(mask)
            initial.append(values[i].co2_ppm)
            trends.append((values[i].co2_ppm - values[i - 6].co2_ppm) / 60)
            ids.append(run)
    if not xs:
        raise ValueError(f"no valid {mode} training windows")
    return Dataset(np.array(xs), np.array(ys), np.array(masks, dtype=bool),
                   np.array(initial), np.array(trends), np.array(ids))
