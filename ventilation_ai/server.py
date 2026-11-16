"""Loopback-only model API, SQLite experiment log and demonstration viewer.

No physical actuator, MQTT, AWS credentials or external data are simulated as real.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .data import Reading, validate_series
from .policy import Controller
from .predictor import Predictor
from .simulation import generate_runs


class Application:
    def __init__(self, model_dir, db_path):
        self.predictor = Predictor(model_dir)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS telemetry (
                device TEXT, ts REAL, run_id TEXT, reading TEXT, response TEXT,
                PRIMARY KEY(device,ts));
            CREATE TABLE IF NOT EXISTS controller_state (device TEXT PRIMARY KEY, state TEXT);
        """)
        report_path = Path(model_dir) / "evaluation.json"
        self.evaluation = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else {}
        self.demo_rows = generate_runs(2, seed=2070)

    def accept(self, device, raw):
        if not isinstance(device, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", device):
            raise ValueError("invalid device_id")
        row = Reading.parse(raw)
        now = time.time()
        if abs(now - row.timestamp) > 30:
            raise ValueError("live telemetry must be within 30 seconds of server time")
        with self.lock:
            old = self.db.execute("SELECT reading,response FROM telemetry WHERE device=? AND ts=?", (device, row.timestamp)).fetchone()
            if old:
                if json.loads(old[0]) != row.to_dict():
                    raise ValueError("conflicting telemetry for the same device and timestamp")
                return json.loads(old[1])
            latest = self.db.execute("SELECT ts FROM telemetry WHERE device=? ORDER BY ts DESC LIMIT 1", (device,)).fetchone()
            if latest and latest[0] > row.timestamp:
                raise ValueError("out-of-order telemetry")
            previous = self.db.execute("SELECT reading FROM telemetry WHERE device=? AND run_id=? ORDER BY ts DESC LIMIT 30", (device, row.run_id)).fetchall()
            history = [Reading.parse(json.loads(r[0])) for r in reversed(previous)] + [row]
            validate_series(history)
            forecast = self.predictor.forecast(history, now=now)
            controller = Controller()  # synthetic-trained models cannot drive live recommendations
            state = self.db.execute("SELECT state FROM controller_state WHERE device=?", (device,)).fetchone()
            if state:
                controller.__dict__.update(json.loads(state[0]))
            recommendation = controller.decide(row, forecast, now=now)
            response = {"device_id": device, "telemetry": row.to_dict(), "prediction": forecast,
                        "recommendation": recommendation, "actuator_connected": False,
                        "note": "Recommendation only. No motor command was sent."}
            stored_state = {k: v for k, v in controller.__dict__.items() if k not in {"policy", "allow_synthetic_model"}}
            self.db.execute("INSERT INTO telemetry VALUES(?,?,?,?,?)",
                            (device, row.timestamp, row.run_id, json.dumps(row.to_dict()), json.dumps(response)))
            self.db.execute("INSERT OR REPLACE INTO controller_state VALUES(?,?)", (device, json.dumps(stored_state)))
            self.db.commit()
            return response

    def latest(self, device):
        with self.lock:
            value = self.db.execute("SELECT response FROM telemetry WHERE device=? ORDER BY ts DESC LIMIT 1", (device,)).fetchone()
        if not value:
            return None
        response = json.loads(value[0])
        age = time.time() - response["telemetry"]["timestamp"]
        response["stale"] = age > 30
        if response["stale"]:
            response["recommendation"] = {"action": "UNAVAILABLE", "reason_codes": ["STALE_SNAPSHOT"]}
        return response

    def demo(self, scenario):
        if scenario not in {"rising", "open", "dust", "cold", "protection", "good"}:
            raise ValueError("unknown scenario")
        end = 200 if scenario == "open" else 130
        rows = self.demo_rows[end - 60:end + 1]
        shift = time.time() - rows[-1].timestamp
        history = []
        for r in rows:
            fields = dict(timestamp=r.timestamp + shift, window_changed_at=r.window_changed_at + shift,
                          outdoor_observed_at=r.outdoor_observed_at + shift)
            if scenario == "dust":
                fields["outdoor_pm25_ugm3"] = 90.
            elif scenario == "cold":
                fields["outdoor_temp_c"] = -2.
                fields["outdoor_pm25_ugm3"] = 10.
            elif scenario == "protection":
                fields["co2_ppm"] = r.co2_ppm + 4500 - rows[-1].co2_ppm
                fields["outdoor_pm25_ugm3"] = 90.
            elif scenario == "good":
                fields["co2_ppm"] = 550 + .02 * (r.timestamp - rows[0].timestamp)
                fields["outdoor_pm25_ugm3"] = 10.
            else:
                fields["outdoor_pm25_ugm3"] = 10.
            history.append(replace(r, **fields))
        controller = Controller(allow_synthetic_model=True)
        for i in range(30, len(history)):
            forecast = self.predictor.forecast(history[max(0, i - 30):i + 1], now=history[i].timestamp)
            recommendation = controller.decide(history[i], forecast)
        return {"mode": "SIMULATION", "history": [r.to_dict() for r in history[-31:]],
                "prediction": forecast, "recommendation": recommendation, "actuator_connected": False}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def send(self, code, value, html=False):
            data = value.encode("utf-8") if html else json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            try:
                if url.path == "/":
                    self.send(200, Path(__file__).with_name("dashboard.html").read_text(encoding="utf-8"), True)
                elif url.path == "/api/model":
                    self.send(200, {"metadata": app.predictor.metadata, "evaluation": app.evaluation,
                                    "cloud_connected": False, "actuator_connected": False})
                elif url.path == "/api/demo":
                    self.send(200, app.demo(parse_qs(url.query).get("scenario", ["rising"])[0]))
                elif url.path.startswith("/api/devices/") and url.path.endswith("/latest"):
                    value = app.latest(url.path.split("/")[3])
                    self.send(200 if value else 404, value or {"error": "device not found"})
                else:
                    self.send(404, {"error": "not found"})
            except (ValueError, TypeError, KeyError) as error:
                self.send(400, {"error": str(error)})

        def do_POST(self):
            origin = self.headers.get("Origin")
            allowed = {f"http://127.0.0.1:{self.server.server_port}", f"http://localhost:{self.server.server_port}"}
            if origin and origin not in allowed:
                self.send(403, {"error": "cross-origin requests are disabled"})
                return
            if self.headers.get_content_type() != "application/json":
                self.send(415, {"error": "application/json required"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
                if not 0 < length <= 1000000:
                    raise ValueError("request must be between 1 and 1000000 bytes")
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                if self.path == "/api/forecast":
                    history = body.get("history")
                    if not isinstance(history, list) or len(history) > 2000:
                        raise ValueError("history must be a list with at most 2000 readings")
                    self.send(200, app.predictor.forecast(history))
                elif self.path == "/api/telemetry":
                    self.send(200, app.accept(body["device_id"], body["reading"]))
                else:
                    self.send(404, {"error": "not found"})
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                self.send(400, {"error": str(error)})
    return Handler


def serve(model_dir, port, db_path):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    app = Application(model_dir, db_path)
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"열어조 AI viewer: http://127.0.0.1:{server.server_port} (local only; no motor/cloud connection)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        app.db.close()
