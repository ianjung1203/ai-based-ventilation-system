from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .data import HORIZONS, HISTORY_SECONDS, SAMPLE_SECONDS, features, group_runs, make_dataset, validate_series
from .models import Regressor, mae_by_horizon, save_bundle
from .predictor import crossing_time


def event_metrics(model, rows, mode):
    """Crossing times against the dense 10-second trace, on complete episodes only."""
    horizon = HORIZONS[mode][-1]
    count = horizon // SAMPLE_SECONDS
    target, direction = (1000, "up") if mode == "closed" else (800, "down")
    truth_events = predicted_events = hits = complete = 0
    errors = []
    for values in group_runs(rows).values():
        for i in range(30, len(values) - count):
            if i % 6 and values[i].window_open == values[i-1].window_open:
                continue
            future = values[i:i+count+1]
            if any(r.window_open != (mode == "open") for r in future[:-1]):
                continue
            if any(abs(b.timestamp-a.timestamp-SAMPLE_SECONDS) > .01 for a,b in zip(values[i-30:i+count], values[i-29:i+count+1])):
                continue
            initial = values[i].co2_ppm
            if (mode == "closed" and initial >= target) or (mode == "open" and initial <= target):
                continue
            actual = crossing_time(initial, list(range(10, horizon+1, 10)),
                                   [r.co2_ppm for r in future[1:]], target, direction)
            means = np.maximum(values[i].outdoor_co2_ppm, initial + model.predict(features(values[i-30:i+1]))[0] * 1000)
            predicted = crossing_time(initial, HORIZONS[mode], means, target, direction)
            complete += 1
            truth_events += actual is not None
            predicted_events += predicted is not None
            if actual is not None and predicted is not None:
                hits += 1
                errors.append(abs(actual-predicted))
    return {"complete_observation_windows": complete, "actual_crossings": truth_events,
            "predicted_crossings": predicted_events, "matched_crossings": hits,
            "missed_crossings": truth_events-hits, "false_crossings": predicted_events-hits,
            "crossing_time_mae_sec_on_matched_events": float(np.mean(errors)) if errors else None,
            "note": "Only uninterrupted full-horizon windows; incomplete/censored windows excluded. Timing MAE alone excludes missed events; inspect counts too."}


def score(model, data, mode):
    if model == "persistence":
        prediction = np.zeros_like(data.y)
    elif model == "trend":
        prediction = data.trend[:, None] * np.array(HORIZONS[mode])[None, :] / 1000
    else:
        prediction = model.predict(data.x)
    errors = mae_by_horizon(prediction, data.y, data.mask)
    return {"mean_horizon_mae_ppm": float(np.nanmean(errors)),
            "mae_ppm": {str(h): float(v) if np.isfinite(v) else None for h, v in zip(HORIZONS[mode], errors)},
            "observed_target_counts": {str(h): int(v) for h, v in zip(HORIZONS[mode], data.mask.sum(axis=0))}}


def train(rows, output, epochs=220, include_mlp=True):
    validate_series(rows, grouped=True)
    grouped = group_runs(rows)
    runs = sorted(grouped, key=lambda run: grouped[run][0].timestamp)
    if len(runs) < 9:
        raise ValueError("need at least 9 independent experiment runs; split is chronological by run")
    a, b = int(len(runs) * .6), int(len(runs) * .8)
    split_ids = {"train": runs[:a], "validation": runs[a:b], "test": runs[b:]}
    subsets = {name: [row for run in ids for row in grouped[run]] for name, ids in split_ids.items()}
    sources = sorted({r.source for r in rows})
    source = "MEASURED" if sources == ["MEASURED"] else "SYNTHETIC_OR_MIXED"
    report = {"evaluation_scope": source, "row_count": len(rows), "split_runs": split_ids,
              "selection": "validation mean of per-horizon MAE; test never selects the model",
              "limitations": ["Synthetic scores are not measured-world accuracy.",
                              "No automatic motor or cloud deployment.",
                              "Missing future targets after action changes are censored, not labelled as 600 seconds."],
              "models": {}}
    models, bands = {}, {}
    start = time.perf_counter()
    for mode in HORIZONS:
        sets = {name: make_dataset(values, mode) for name, values in subsets.items()}
        for name, d in sets.items():
            if np.min(d.mask.sum(axis=0)) < 3:
                raise ValueError(f"{name}/{mode}: insufficient observed targets at some horizons")
        candidates = {f"ridge_alpha_{alpha}": Regressor("ridge", alpha=alpha) for alpha in (1, 10, 100)}
        if include_mlp:
            candidates["temporal_mlp_48"] = Regressor("mlp")
        validation_scores = {}
        for name, candidate in candidates.items():
            candidate.fit(sets["train"], sets["validation"], epochs=epochs)
            validation_scores[name] = score(candidate, sets["validation"], mode)
            print(f"{mode}/{name}: validation MAE {validation_scores[name]['mean_horizon_mae_ppm']:.1f} ppm", flush=True)
        selected = min(validation_scores, key=lambda key: validation_scores[key]["mean_horizon_mae_ppm"])
        models[mode] = candidates[selected]
        v = sets["validation"]
        residual = np.abs(models[mode].predict(v.x) - v.y) * 1000
        bands[mode] = [float(np.quantile(residual[v.mask[:, j], j], .9)) for j in range(v.y.shape[1])]
        test = sets["test"]
        test_results = {name: score(model, test, mode) for name, model in
                        {"persistence": "persistence", "linear_trend": "trend", **candidates}.items()}
        report["models"][mode] = {"selected": selected, "validation": validation_scores, "test": test_results,
                                  "selected_test_event_metrics": event_metrics(models[mode], subsets["test"], mode),
                                  "validation_abs_error_p90_ppm": bands[mode],
                                  "error_band_note": "Empirical validation residual band; not a guaranteed confidence interval.",
                                  "windows": {name: len(d.x) for name, d in sets.items()}}
    report["training_seconds"] = round(time.perf_counter() - start, 3)
    version = datetime.now(timezone.utc).strftime("yeoreojo-%Y%m%dT%H%M%SZ")
    metadata = {"model_version": version, "training_source": source, "sources": sources,
                "sample_seconds": SAMPLE_SECONDS, "history_seconds": HISTORY_SECONDS,
                "feature_schema": "causal-lags-v1", "validation_abs_error_p90_ppm": bands,
                "split_runs": split_ids, "assumption": "The chosen future window state and outdoor conditions remain constant.",
                "deployment_status": "EXPERIMENTAL"}
    save_bundle(output, models, metadata)
    Path(output, "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return report
