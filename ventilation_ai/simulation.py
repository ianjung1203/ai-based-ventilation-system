"""Synthetic lab-only data with CO2 generation and finite ventilation rates."""
from __future__ import annotations

import math

import numpy as np

from .data import Reading, SAMPLE_SECONDS


def evolve(co2, outdoor_co2, source_ppm_sec, ach, seconds):
    k = ach / 3600
    equilibrium = outdoor_co2 + source_ppm_sec / k
    return equilibrium + (co2 - equilibrium) * math.exp(-k * seconds)


def generate_runs(count=48, seed=2026):
    """Independent randomised experiments, including non-reaching open episodes.

    The open command lasts 600 s. Long targets exist only at the opening origin;
    shorter observed targets remain usable later in the same episode.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for run in range(count):
        start = 1767225600 + run * 86400
        out_co2 = rng.uniform(390, 460)
        out_temp = rng.uniform(-4, 36)
        temp = rng.uniform(19, 28)
        humidity = rng.uniform(30, 70)
        co2 = rng.uniform(450, 950)
        source = rng.uniform(.12, 1.05)
        # The same box geometry; changing thermal gradient changes exchange.
        ach_open = 11 + .7 * abs(temp - out_temp)
        ach_closed = .4
        changed_at, was_open = start, False
        pm = float(rng.choice([10, 25, 50, 90]))
        phase_offset = rng.uniform(0, 6)
        for index in range(720):
            ts = start + index * SAMPLE_SECONDS
            phase = index % 240
            is_open = phase >= 180  # 30 min closed + 10 min open, three repeats
            if is_open != was_open:
                changed_at = ts
            rows.append(Reading(ts, f"synthetic-{run:03d}", round(co2 + rng.normal(0, 3), 3),
                                round(temp, 3), round(humidity, 3), round(out_co2, 3), round(out_temp, 3),
                                pm, is_open, changed_at, ts, "SYNTHETIC", "SCENARIO"))
            emission = source * (1 + .12 * math.sin(index / 100 + phase_offset))
            co2 = evolve(co2, out_co2, emission, ach_open if is_open else ach_closed, SAMPLE_SECONDS)
            was_open = is_open
    return rows
