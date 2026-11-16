import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from ventilation_ai.data import Reading, features, make_dataset, timestamp, validate_series
from ventilation_ai.models import load_bundle
from ventilation_ai.policy import Controller, physics_duration
from ventilation_ai.predictor import Predictor, crossing_time
from ventilation_ai.server import Application
from ventilation_ai.simulation import generate_runs

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "artifacts" / "demo_model"


def reading(ts=1800, co2=1100, **kw):
    defaults = dict(timestamp=ts, run_id="test", co2_ppm=co2, temp_c=24., humidity_pct=50.,
                    outdoor_co2_ppm=420., outdoor_temp_c=20., outdoor_pm25_ugm3=10.,
                    window_open=False, window_changed_at=0., outdoor_observed_at=ts)
    defaults.update(kw)
    return Reading.parse(defaults)


def forecast(high=True, duration=180, source="MEASURED", eta=30):
    return {"status": "READY", "training_source": source, "threshold_eta_sec": eta,
            "target_eta_sec": duration,
            "curves": {"closed": {"status": "READY", "co2_ppm": [1100 if high else 900]},
                       "open": {"status": "READY", "co2_ppm": [800]}}}


class DataTests(unittest.TestCase):
    def test_time_formats_and_timezone(self):
        self.assertEqual(timestamp("1767225600"), timestamp("2026-01-01T00:00:00Z"))
        with self.assertRaises(ValueError):
            timestamp("2026-01-01T00:00:00")

    def test_reject_invalid_inputs(self):
        for key, value in [("co2_ppm", float("nan")), ("co2_ppm", None),
                           ("humidity_pct", 101), ("window_open", "maybe"),
                           ("window_changed_at", 1900), ("outdoor_observed_at", 2000)]:
            raw = reading().to_dict(); raw[key] = value
            with self.assertRaises((ValueError, TypeError)):
                Reading.parse(raw)

    def test_history_gap_duplicate_run_and_transition_validation(self):
        a = reading(ts=1800)
        for b in [reading(ts=1800), reading(ts=1820), reading(ts=1810, run_id="other"),
                  reading(ts=1810, window_open=True, window_changed_at=0)]:
            with self.assertRaises(ValueError):
                validate_series([a, b], regular=True)

    def test_features_are_causal_and_action_condition_is_separate(self):
        h = [reading(ts=1800+i*10, co2=800+i*2) for i in range(31)]
        alternative = h[:-1] + [replace(h[-1], window_open=True, window_changed_at=h[-1].timestamp)]
        np.testing.assert_array_equal(features(h), features(alternative))
        reversed_trend = [replace(r, co2_ppm=920-i*2) for i, r in enumerate(h)]
        self.assertNotEqual(features(h).tolist(), features(reversed_trend).tolist())

    def test_labels_stop_at_action_changes_not_at_target_limit(self):
        rows = [reading(ts=i*10, co2=700+i, window_open=i>=40,
                        window_changed_at=400 if i>=40 else 0) for i in range(110)]
        closed = make_dataset(rows, "closed", stride=1)
        self.assertTrue(closed.mask[:, 0].any())
        self.assertFalse(closed.mask[:, 1:].any())
        opened = make_dataset(rows, "open", stride=1)
        self.assertTrue(opened.mask[0, -1])  # full 600 s episode at opening origin
        self.assertFalse(opened.mask[-1, -1])

    def test_crossing_interpolation_and_no_reach(self):
        self.assertEqual(crossing_time(900, [60, 120], [960, 1020], 1000, "up"), 100)
        self.assertEqual(crossing_time(1200, [60, 120], [900, 700], 800, "down"), 90)
        self.assertIsNone(crossing_time(1200, [60], [1000], 800, "down"))


class PolicyTests(unittest.TestCase):
    def test_current_threshold_immediate_without_ai(self):
        self.assertEqual(Controller().decide(reading(co2=999), {})["action"], "HOLD")
        self.assertEqual(Controller().decide(reading(co2=1000), {})["action"], "OPEN")

    def test_confirmation_is_two_distinct_consecutive_minutes(self):
        c = Controller()
        self.assertEqual(c.decide(reading(1800, 900), forecast())["action"], "HOLD")
        for t in (1800, 1810, 1820, 1850):
            self.assertEqual(c.decide(reading(t, 900), forecast())["confirmation_count"], 1)
        self.assertEqual(c.decide(reading(1860, 900), forecast())["action"], "OPEN")

    def test_confirmation_resets_on_gap_or_low_prediction(self):
        c = Controller()
        c.decide(reading(1800, 900), forecast())
        self.assertEqual(c.decide(reading(1920, 900), forecast())["confirmation_count"], 1)
        c.decide(reading(1930, 900), forecast(False))
        self.assertEqual(c.decide(reading(1980, 900), forecast())["confirmation_count"], 1)

    def test_schedule_recalculates_duration_at_open(self):
        c = Controller()
        c.decide(reading(1800, 900), forecast(eta=360))
        result = c.decide(reading(1860, 900), forecast(eta=300))
        self.assertEqual(result["action"], "SCHEDULED")
        self.assertIsNone(result["duration_sec"])

    def test_pm_boundaries(self):
        for pm, seconds in [(35, 180), (35.1, 120), (75, 120)]:
            d = Controller().decide(reading(outdoor_pm25_ugm3=pm), forecast())
            self.assertEqual(d["duration_sec"], seconds)
        self.assertEqual(Controller().decide(reading(outdoor_pm25_ugm3=75.1), forecast())["action"], "HOLD")
        d = Controller().decide(reading(co2=2000, outdoor_pm25_ugm3=76), forecast())
        self.assertEqual(d["duration_sec"], 60)

    def test_temperature_applies_once_and_minimum_is_10(self):
        for temp in (0, -2, 33, 35):
            result = Controller().decide(reading(outdoor_temp_c=temp), forecast(duration=120))
            self.assertEqual(result["duration_sec"], 60)
        self.assertEqual(Controller().decide(reading(outdoor_temp_c=0), forecast(duration=10))["duration_sec"], 10)

    def test_protection_hysteresis_outdoor_bypass_and_cooldown(self):
        c = Controller()
        r = reading(co2=4500, outdoor_pm25_ugm3=90, outdoor_temp_c=-2)
        self.assertEqual(c.decide(r, {})["duration_sec"], 600)
        d = c.decide(replace(r, timestamp=1810, co2_ppm=3500, window_open=True, window_changed_at=1800), {})
        self.assertTrue(d["protection_active"])
        self.assertFalse(c.decide(replace(r, timestamp=1820, co2_ppm=3000), {})["protection_active"])
        d = Controller().decide(reading(co2=4500, window_changed_at=1700), {})
        self.assertEqual(d["reason_codes"], ["REOPEN_COOLDOWN"])

    def test_600_cap_and_target_closure(self):
        d = Controller().decide(reading(co2=4600, window_open=True, window_changed_at=1200), {})
        self.assertEqual(d["reason_codes"], ["MAXIMUM_OPEN_TIME"])
        d = Controller().decide(reading(co2=800, window_open=True, window_changed_at=1790), forecast())
        self.assertEqual(d["reason_codes"], ["TARGET_REACHED"])

    def test_budget_is_not_renewed_by_repeated_predictions(self):
        c = Controller()
        c.decide(reading(), forecast(duration=60))
        for t in (1810, 1840):
            d = c.decide(reading(t, window_open=True, window_changed_at=1800), forecast(duration=600))
            self.assertEqual(d["remaining_sec"], 1860-t)
        self.assertEqual(c.decide(reading(1860, window_open=True, window_changed_at=1800), forecast(duration=600))["action"], "CLOSE")

    def test_synthetic_model_is_not_automatically_used_for_live_control(self):
        c = Controller()
        c.decide(reading(1800, 900), forecast(source="SYNTHETIC_OR_MIXED"))
        self.assertEqual(c.decide(reading(1860, 900), forecast(source="SYNTHETIC_OR_MIXED"))["action"], "HOLD")

    def test_missing_target_not_fabricated(self):
        d = Controller().decide(reading(), forecast(duration=None))
        self.assertTrue(d["target_may_not_be_reached"])
        self.assertEqual(d["duration_sec"], 600)
        self.assertIsNone(physics_duration(2000, 420, source_ppm_sec=4, ach=20))

    def test_stale_and_outdoor_errors(self):
        r = reading(window_open=True, window_changed_at=1790)
        self.assertEqual(Controller().decide(r, forecast(), now=1900)["action"], "CLOSE")
        r = reading(ts=9000, outdoor_observed_at=0)
        self.assertEqual(Controller().decide(r, forecast())["reason_codes"], ["OUTDOOR_DATA_STALE"])

    def test_invalid_sensor_cannot_keep_window_open(self):
        r = replace(reading(window_open=True, window_changed_at=1790), co2_ppm=float("nan"))
        self.assertEqual(Controller().decide(r, forecast())["action"], "CLOSE")


@unittest.skipUnless(MODEL.exists(), "train the bundled demonstration model first")
class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.predictor = Predictor(MODEL)
        cls.rows = generate_runs(1, 111)

    def test_predictions_saved_model_and_replay(self):
        h = self.rows[100:131]
        result = self.predictor.forecast(h, now=h[-1].timestamp)
        self.assertEqual(result["status"], "READY")
        self.assertEqual(len(result["curves"]["closed"]["co2_ppm"]), 6)
        self.assertEqual(len(result["curves"]["open"]["co2_ppm"]), 9)
        json.dumps(result, allow_nan=False)
        again = Predictor(MODEL).forecast(h, now=h[-1].timestamp)
        self.assertEqual(result["curves"], again["curves"])

    def test_warmup_stale_and_gap(self):
        h = self.rows[:31]
        self.assertEqual(self.predictor.forecast(h[:10], now=h[9].timestamp)["status"], "UNAVAILABLE")
        self.assertEqual(self.predictor.forecast(h, now=h[-1].timestamp+31)["status"], "UNAVAILABLE")
        self.assertEqual(self.predictor.forecast(h[:5]+h[6:], now=h[-1].timestamp)["status"], "UNAVAILABLE")

    def test_same_current_value_different_history_changes_prediction(self):
        rising = [reading(ts=1800+i*10, co2=600+i*10) for i in range(31)]
        stable = [replace(r, co2_ppm=900) for r in rising]
        a = self.predictor.forecast(rising, now=2100)["curves"]["closed"]["co2_ppm"][3]
        b = self.predictor.forecast(stable, now=2100)["curves"]["closed"]["co2_ppm"][3]
        self.assertGreater(a, b+50)

    def test_open_prediction_does_not_exceed_remaining_600_second_budget(self):
        h = self.rows[200:231]
        result = self.predictor.forecast(h, now=h[-1].timestamp)
        self.assertEqual(result["available_open_seconds"], 100)
        self.assertTrue(all(t <= 100 for t in result["curves"]["open"]["seconds"]))

    def test_model_integrity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            path.joinpath("metadata.json").write_bytes(MODEL.joinpath("metadata.json").read_bytes())
            path.joinpath("weights.npz").write_bytes(b"bad weights")
            with self.assertRaisesRegex(ValueError, "checksum"):
                load_bundle(path)

    def test_training_split_and_test_report(self):
        report = json.loads((MODEL / "evaluation.json").read_text(encoding="utf-8"))
        splits = [set(v) for v in report["split_runs"].values()]
        self.assertFalse(splits[0] & splits[1] or splits[1] & splits[2] or splits[0] & splits[2])
        self.assertEqual(report["evaluation_scope"], "SYNTHETIC_OR_MIXED")
        for value in report["models"].values():
            self.assertIn("linear_trend", value["test"])
            self.assertTrue(np.isfinite(value["test"][value["selected"]]["mean_horizon_mae_ppm"]))

    def test_sqlite_idempotency_and_restart_state(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "test.sqlite3"
            app = Application(MODEL, db)
            now = 1800.
            with patch("ventilation_ai.server.time.time", return_value=now):
                raw = reading(now).to_dict()
                first = app.accept("test-device", raw)
                self.assertEqual(first, app.accept("test-device", raw))
                self.assertEqual(app.db.execute("SELECT count(*) FROM telemetry").fetchone()[0], 1)
                with self.assertRaises(ValueError):
                    app.accept("test-device", {**raw, "co2_ppm": 1200})
                self.assertFalse(first["actuator_connected"])
            app.db.close()
            app = Application(MODEL, db)
            self.assertIsNotNone(app.db.execute("SELECT state FROM controller_state").fetchone())
            with patch("ventilation_ai.server.time.time", return_value=2000):
                self.assertTrue(app.latest("test-device")["stale"])
                self.assertEqual(app.latest("test-device")["recommendation"]["action"], "UNAVAILABLE")
            app.db.close()

    def test_all_demo_scenarios_are_labelled(self):
        app = Application(MODEL, ":memory:")
        for scenario in ["rising", "open", "dust", "cold", "protection", "good"]:
            value = app.demo(scenario)
            self.assertEqual(value["mode"], "SIMULATION")
            self.assertFalse(value["actuator_connected"])
            json.dumps(value, allow_nan=False)
        app.db.close()


if __name__ == "__main__":
    unittest.main()
