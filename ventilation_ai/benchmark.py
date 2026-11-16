"""Paired closed-loop simulation. These results never certify real hardware."""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from .data import Reading, SAMPLE_SECONDS
from .policy import Controller
from .simulation import evolve


def compare_controllers(predictor, scenarios=8, seed=709):
    rng = np.random.default_rng(seed)
    conditions = [(float(rng.uniform(.2, .8)), float(rng.uniform(10, 28)), float(pm))
                  for pm in np.resize([10, 50, 90, 10], scenarios)]
    results = []
    for scenario, (emission, out_temp, pm) in enumerate(conditions):
        # Identical physical parameters and sensor noise for the three policies.
        noise = np.random.default_rng(seed + scenario).normal(0, 2, 720)
        for strategy in ("current_rules", "ai_start_physics_duration", "ai_start_ai_duration"):
            controller = Controller(allow_synthetic_model=True)
            history = []
            co2, opened, changed = 650., False, 1767225600.
            metrics = {"scenario": scenario, "strategy": strategy, "source": "SYNTHETIC",
                       "seconds_above_1000": 0, "max_co2_ppm": 0., "open_seconds": 0,
                       "opening_count": 0, "closing_count": 0, "closures_at_target": 0}
            for i in range(720):
                ts = 1767225600 + i * SAMPLE_SECONDS
                row = Reading(ts, f"benchmark-{scenario}", co2 + noise[i], 24., 50., 420.,
                              out_temp, pm, opened, changed, ts, "SYNTHETIC", "SCENARIO")
                history.append(row)
                if i >= 30:
                    if strategy == "current_rules":
                        forecast = {"status": "UNAVAILABLE"}
                    else:
                        forecast = predictor.forecast(history[-31:], now=ts)
                        if strategy == "ai_start_physics_duration":
                            forecast["curves"].get("open", {})["status"] = "DISABLED_FOR_COMPARISON"
                    decision = controller.decide(row, forecast, now=ts)
                    if decision["action"] == "OPEN" and not opened:
                        opened, changed = True, ts
                        metrics["opening_count"] += 1
                    elif decision["action"] == "CLOSE" and opened:
                        opened, changed = False, ts
                        metrics["closing_count"] += 1
                        metrics["closures_at_target"] += int(co2 <= 800)
                    history[-1] = replace(row, window_open=opened, window_changed_at=changed)
                    metrics["seconds_above_1000"] += SAMPLE_SECONDS * int(co2 > 1000)
                    metrics["max_co2_ppm"] = max(metrics["max_co2_ppm"], co2)
                    metrics["open_seconds"] += SAMPLE_SECONDS * int(opened)
                source = emission * (1 + .12 * math.sin(i / 100 + scenario))
                ach = 11 + .7 * abs(24 - out_temp) if opened else .4
                co2 = evolve(co2, 420, source, ach, SAMPLE_SECONDS)
            metrics["max_co2_ppm"] = round(metrics["max_co2_ppm"], 1)
            results.append(metrics)
    summary = {}
    for strategy in ("current_rules", "ai_start_physics_duration", "ai_start_ai_duration"):
        subset = [r for r in results if r["strategy"] == strategy]
        summary[strategy] = {key: round(float(np.mean([r[key] for r in subset])), 2) for key in
                             ["seconds_above_1000", "max_co2_ppm", "open_seconds", "opening_count"]}
    return {"scope": "SYNTHETIC_ONLY", "evaluation_seconds_per_scenario": 6900,
            "note": "Same simulated box/noise per strategy; includes PM restrictions. Not field performance or an energy metric.",
            "mean_metrics": summary, "runs": results}
