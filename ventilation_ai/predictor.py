from __future__ import annotations

import time

import numpy as np

from .data import HORIZONS, Reading, features, iso, validate_series
from .models import load_bundle


def crossing_time(initial, horizons, values, target, direction):
    """First crossing, linearly interpolated between forecast grid points."""
    reached = (lambda value: value >= target) if direction == "up" else (lambda value: value <= target)
    if reached(initial):
        return 0.0
    previous_t, previous = 0, initial
    for t, value in zip(horizons, values):
        if reached(value):
            return float(previous_t + (target - previous) * (t - previous_t) / (value - previous))
        previous_t, previous = t, value
    return None


class Predictor:
    def __init__(self, model_dir):
        self.models, self.metadata = load_bundle(model_dir)

    def forecast(self, history, now=None):
        started = time.perf_counter()
        base = {"model_version": self.metadata["model_version"],
                "training_source": self.metadata["training_source"],
                "status": "UNAVAILABLE", "reason_codes": [], "curves": {}}
        if not history:
            base["reason_codes"] = ["EMPTY_HISTORY"]
            return base
        try:
            rows = [Reading.parse(r.to_dict() if isinstance(r, Reading) else r) for r in history]
            # Deliberately validate all supplied records, not silently sort duplicates.
            validate_series(rows, regular=True)
            last = rows[-1]
            age = (time.time() if now is None else now) - last.timestamp
            if age > 30 or age < -2:
                raise ValueError("STALE_OR_FUTURE_READING")
            x = features(rows)
        except (ValueError, TypeError, KeyError, OverflowError) as e:
            base["reason_codes"] = [str(e)]
            return base
        base.update(base_ts=iso(last.timestamp), observed_co2_ppm=last.co2_ppm,
                    history_count=len(rows), status="READY")
        available_open = max(0, 600 - (last.timestamp - last.window_changed_at)) if last.window_open else 600
        base["available_open_seconds"] = available_open
        for mode, model in self.models.items():
            raw = last.co2_ppm + model.predict(x)[0] * 1000
            seconds = np.array(HORIZONS[mode])
            # Long open targets were observed only before the 600 s cap. Never
            # extrapolate those heads beyond the remaining permitted episode.
            eligible = seconds <= available_open if mode == "open" else np.ones(len(seconds), dtype=bool)
            raw, seconds = raw[eligible], seconds[eligible]
            valid = np.isfinite(raw).all() and np.all(raw <= 10000)
            ood = model.out_of_range(x)
            means = np.clip(raw, last.outdoor_co2_ppm, 10000)
            errors = np.array(self.metadata["validation_abs_error_p90_ppm"][mode])[eligible]
            base["curves"][mode] = {
                "status": "READY" if valid and not ood else "OUT_OF_TRAINING_RANGE",
                "assumed_window_state": mode.upper(), "seconds": seconds.tolist(),
                "co2_ppm": np.round(means, 1).tolist(),
                "lower_ppm": np.round(np.maximum(last.outdoor_co2_ppm, means - errors), 1).tolist(),
                "upper_ppm": np.round(means + errors, 1).tolist(),
                "band_type": "VALIDATION_ABSOLUTE_ERROR_P90_NOT_GUARANTEED",
            }
        closed, opened = base["curves"]["closed"], base["curves"]["open"]
        base["threshold_eta_sec"] = crossing_time(last.co2_ppm, closed["seconds"], closed["co2_ppm"], 1000, "up") if closed["status"] == "READY" else None
        base["target_eta_sec"] = crossing_time(last.co2_ppm, opened["seconds"], opened["co2_ppm"], 800, "down") if opened["status"] == "READY" else None
        base["target_status"] = ("ALREADY_AT_TARGET" if last.co2_ppm <= 800
                                  else "PREDICTED_WITHIN_AVAILABLE_HORIZON" if base["target_eta_sec"] is not None
                                  else "NOT_REACHED_WITHIN_HORIZON" if opened["status"] == "READY" else "UNAVAILABLE")
        base["inference_ms"] = round((time.perf_counter() - started) * 1000, 3)
        base["assumption"] = self.metadata["assumption"]
        return base
