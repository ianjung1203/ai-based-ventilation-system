"""Stateful lab policy. Decisions are requests, never motor acknowledgements.

Approved interpretation: 600-second cap and 300-second closed interval also
apply in protection mode. Protection bypasses outdoor PM/temperature limits.
Scheduled openings get a fresh duration estimate at execution, not at booking.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .data import Reading, iso


@dataclass(frozen=True)
class Policy:
    threshold_ppm: float = 1000
    target_ppm: float = 800
    protection_on_ppm: float = 4500
    protection_off_ppm: float = 3000
    max_open_sec: int = 600
    cooldown_sec: int = 300
    lead_sec: int = 60
    fallback_ach: float = 20
    fallback_source_ppm_sec: float = 0


def physics_duration(co2, outside, target=800, ach=20, source_ppm_sec=0):
    if ach <= 0 or source_ppm_sec < 0:
        raise ValueError("ACH must be positive and source must be nonnegative")
    if co2 <= target:
        return 0.0
    equilibrium = outside + source_ppm_sec * 3600 / ach
    if target <= equilibrium:
        return None
    return math.log((co2 - equilibrium) / (target - equilibrium)) * 3600 / ach


class Controller:
    def __init__(self, policy=None, allow_synthetic_model=False):
        self.policy = policy or Policy()
        self.allow_synthetic_model = allow_synthetic_model
        self.protection = False
        self.streak = 0
        self.last_minute = None
        self.open_deadline = None
        self.open_origin = None
        self.pending_duration = None
        self.pending_at = None
        self.last_ts = None
        self.last_decision = None

    def decide(self, reading: Reading, prediction, now=None):
        r, p = reading, self.policy
        try:
            r = Reading.parse(reading.to_dict())
        except (ValueError, TypeError, OverflowError):
            return self._result("CLOSE" if reading.window_open else "HOLD", "INVALID_SENSOR_INPUT", reading)
        now = r.timestamp if now is None else now
        if self.last_ts is not None and r.timestamp < self.last_ts:
            return self._result("CLOSE" if r.window_open else "HOLD", "OUT_OF_ORDER_READING", r)
        # Stale checks run even for an otherwise duplicate observation.
        if now - r.timestamp > 30 or now < r.timestamp - 2:
            return self._result("CLOSE" if r.window_open else "HOLD", "STALE_OR_FUTURE_READING", r)
        if self.last_ts == r.timestamp:
            return self.last_decision
        self.last_ts = r.timestamp
        result = self._decide(r, prediction)
        self.last_decision = result
        return result

    def _result(self, action, reason, r, **extra):
        return {"action": action, "reason_codes": [reason], "start_at": None,
                "duration_sec": None, "target_ppm": self.policy.target_ppm,
                "protection_active": self.protection, "confirmation_count": self.streak,
                "policy_version": "ventilation-v1-conservative-intervals", **extra}

    def _decide(self, r, forecast):
        p = self.policy
        elapsed = r.timestamp - r.window_changed_at
        if r.co2_ppm >= p.protection_on_ppm:
            self.protection = True
        elif r.co2_ppm <= p.protection_off_ppm:
            self.protection = False
        if not r.window_open:
            self.open_deadline = None
            self.open_origin = None
        if r.window_open and elapsed >= p.max_open_sec:
            return self._result("CLOSE", "MAXIMUM_OPEN_TIME", r)
        curves = forecast.get("curves", {})
        source_ok = forecast.get("training_source") == "MEASURED" or self.allow_synthetic_model
        ready = forecast.get("status") == "READY" and source_ok
        closed_ready = ready and curves.get("closed", {}).get("status") == "READY"
        opened_ready = ready and curves.get("open", {}).get("status") == "READY"
        high_prediction = closed_ready and curves["closed"]["co2_ppm"][-1] >= p.threshold_ppm
        minute = int(r.timestamp // 60)
        if minute != self.last_minute:
            adjacent = self.last_minute is not None and minute == self.last_minute + 1
            self.streak = ((self.streak + 1) if adjacent else 1) if high_prediction else 0
            self.last_minute = minute
        elif not high_prediction:
            self.streak = 0
        if r.window_open and r.co2_ppm <= p.target_ppm:
            return self._result("CLOSE", "TARGET_REACHED", r)
        # The actuator-reported transition time anchors cooldown across restarts.
        if not r.window_open and elapsed < p.cooldown_sec:
            return self._result("HOLD", "REOPEN_COOLDOWN", r,
                                retry_after_sec=math.ceil(p.cooldown_sec - elapsed))
        if self.protection:
            if r.window_open:
                self.open_deadline = r.window_changed_at + p.max_open_sec
                self.open_origin = r.window_changed_at
                return self._result("KEEP_OPEN", "PROTECTION_CO2", r,
                                    remaining_sec=math.ceil(self.open_deadline - r.timestamp),
                                    target_ppm=p.protection_off_ppm)
            self.pending_duration, self.pending_at = p.max_open_sec, r.timestamp
            return self._result("OPEN", "PROTECTION_CO2", r, duration_sec=p.max_open_sec,
                                start_at=iso(r.timestamp), target_ppm=p.protection_off_ppm)
        need = r.window_open or r.co2_ppm >= p.threshold_ppm or self.streak >= 2
        if not need:
            return self._result("HOLD", "CO2_BELOW_THRESHOLD" if closed_ready else "MEASURED_RULE_FALLBACK", r)
        if r.timestamp - r.outdoor_observed_at > 7200:
            return self._result("CLOSE" if r.window_open else "HOLD", "OUTDOOR_DATA_STALE", r)
        pm = r.outdoor_pm25_ugm3
        if pm > 75 and r.co2_ppm < 2000:
            return self._result("CLOSE" if r.window_open else "HOLD", "OUTDOOR_PM_VERY_HIGH", r, warning=True)
        # Scheduled duration is intentionally null until opening is actually due.
        if not r.window_open and r.co2_ppm < p.threshold_ppm and self.streak >= 2:
            eta = forecast.get("threshold_eta_sec")
            if eta is None:
                return self._result("HOLD", "NO_THRESHOLD_CROSSING", r)
            if eta > p.lead_sec:
                return self._result("SCHEDULED", "PREDICTED_THRESHOLD_CROSSING", r,
                                    start_at=iso(r.timestamp + eta - p.lead_sec),
                                    duration_status="RECALCULATE_AT_OPEN")
        estimate = forecast.get("target_eta_sec") if opened_ready else None
        method = "LEARNED_OPEN_CURVE" if opened_ready else "PHYSICS_FALLBACK"
        if not opened_ready:
            estimate = physics_duration(r.co2_ppm, r.outdoor_co2_ppm, p.target_ppm,
                                        p.fallback_ach, p.fallback_source_ppm_sec)
        warning = estimate is None or estimate > p.max_open_sec
        duration = p.max_open_sec if estimate is None else min(p.max_open_sec, max(10, math.ceil(estimate)))
        if pm > 75:
            duration = min(duration, 60)
            reason = "CO2_2000_PM_EXCEPTION"
        elif pm > 35:
            duration = min(duration, 120)
            reason = "SPLIT_VENTILATION"
        else:
            reason = "VENTILATION_REQUIRED"
        if r.outdoor_temp_c <= 0 or r.outdoor_temp_c >= 33:
            duration = max(10, duration // 2)
        if r.window_open:
            if self.open_origin != r.window_changed_at:
                # Prefer the pre-opening approved budget, expiring after 30 s.
                budget = (self.pending_duration if self.pending_at is not None and
                          0 <= r.window_changed_at - self.pending_at <= 30 else duration)
                self.open_deadline = r.window_changed_at + budget
                self.open_origin = r.window_changed_at
                self.pending_duration = self.pending_at = None
            # Replanning may shorten a deadline; it cannot extend the initial budget.
            self.open_deadline = min(self.open_deadline, r.timestamp + duration,
                                     r.window_changed_at + p.max_open_sec)
            # New PM/temperature restrictions limit the whole opening episode.
            environmental_cap = 60 if pm > 75 else 120 if pm > 35 else p.max_open_sec
            if r.outdoor_temp_c <= 0 or r.outdoor_temp_c >= 33:
                environmental_cap = max(10, environmental_cap // 2)
            self.open_deadline = min(self.open_deadline, r.window_changed_at + environmental_cap)
            if r.timestamp >= self.open_deadline:
                return self._result("CLOSE", "OPEN_BUDGET_FINISHED", r, warning=warning)
            return self._result("KEEP_OPEN", reason, r, remaining_sec=math.ceil(self.open_deadline - r.timestamp),
                                duration_method=method, target_may_not_be_reached=warning)
        self.pending_duration, self.pending_at = duration, r.timestamp
        return self._result("OPEN", reason, r, start_at=iso(r.timestamp), duration_sec=duration,
                            duration_method=method, target_may_not_be_reached=warning)
