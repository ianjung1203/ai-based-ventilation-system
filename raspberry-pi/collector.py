#!/usr/bin/env python3
"""
AirTiming 통합 수집 스크립트 v3

두 가지 리듬이 동시에 돌아간다.
  [빠른 루프 - 메인 스레드]  0.05초마다 VL53L0X 2대로 출입 판정
  [느린 루프 - 별도 스레드]  10초마다 SCD41 / PMS5003 측정 + 창문(LED) 제어

창문 제어 (실제 모터 대신 LED)
  CO2 >= 1500 ppm  -> 창문 열림 (LED 켜짐)
  CO2 <  1000 ppm  -> 창문 닫힘 (LED 꺼짐)
  그 사이 값에서는 직전 상태를 유지한다 (1500 근처에서 깜빡이는 것 방지)

테이블
  readings      : 10초마다 환경값 + 재실 추정 + 창문 상태
  events        : 출입 이벤트 (사람/손이 지나갈 때마다 1행)
  window_events : 창문이 열리거나 닫힐 때마다 1행

배선
  SCD41    I2C bus 1 (0x62)
  VL53L0X  I2C bus 1 (0x29)  -> 바깥쪽 1번
  VL53L0X  I2C bus 3 (0x29)  -> 안쪽 2번  (GPIO23=SDA, GPIO24=SCL)
  PMS5003  UART /dev/serial0 (센서 TXD -> 파이 RXD0)
  LED      GPIO18 -> 저항(220~330옴) -> LED 긴다리 / LED 짧은다리 -> GND

실행:
  source ~/venv/bin/activate
  python3 ~/airtiming/collector.py
"""

import json
import logging
import signal
import sqlite3
import struct
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import serial
import board
import digitalio
import adafruit_scd4x
import adafruit_vl53l0x
from adafruit_extended_bus import ExtendedI2C

# ============================================================ 설정
DEVICE_ID = "pi01"
DB_PATH = Path.home() / "airtiming" / "readings.db"

ENV_INTERVAL_SEC = 10        # 환경값 저장 + 창문 판단 주기
TOF_INTERVAL_SEC = 0.05      # 거리센서 읽는 주기
PMS_PORT = "/dev/serial0"
PMS_WARMUP_SEC = 30          # 이 시간 동안은 PM 값을 기록하지 않음
SEAL_BOX_MODE = True         # 밀폐 상자 실험이면 True -> SCD41 자동보정 끔

# --- 창문(LED) 제어 ---------------------------------------------
LED_PIN = board.D18          # LED가 연결된 GPIO
CO2_OPEN_PPM = 1500          # 이 이상이면 창문 열림 (LED 켜짐)
CO2_CLOSE_PPM = 1000         # 이 미만으로 내려가야 창문 닫힘 (LED 꺼짐)

# --- 출입 판정 --------------------------------------------------
BASELINE_SEC = 5.0           # 시작할 때 빈 상태를 재는 시간
BLOCK_RATIO = 0.70           # 기준 거리의 70% 아래면 "가려짐"
OUT_OF_RANGE_MM = 8000       # 이 이상은 "앞에 아무것도 없음"(측정 실패)
FALLBACK_BLOCK_MM = 150      # 기준을 못 잡았을 때 쓰는 고정 기준
CLEAR_DEBOUNCE_SEC = 0.30    # 둘 다 이만큼 비어 있어야 통과가 끝난 것으로 봄
MIN_EVENT_SEC = 0.05         # 이보다 짧으면 잡음으로 버림
MAX_EVENT_SEC = 5.0          # 이보다 길면 물체가 놓인 것으로 보고 버림
TOF_TIMING_BUDGET = 33000    # 33ms, 빠른 응답 우선

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("collector")

stop = threading.Event()
_occupancy = 0
_occ_lock = threading.Lock()


def _on_signal(signum, frame):
    log.info("종료 신호 수신, 정리 중")
    stop.set()


signal.signal(signal.SIGINT, _on_signal)
signal.signal(signal.SIGTERM, _on_signal)


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ============================================================ DB
SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    co2         INTEGER,
    temp        REAL,
    rh          REAL,
    pm1         INTEGER,
    pm25        INTEGER,
    pm10        INTEGER,
    occupancy   INTEGER,
    window_open INTEGER,
    synced      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(device_id, ts)
);
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    direction   TEXT    NOT NULL,
    duration_ms INTEGER,
    occupancy   INTEGER,
    synced      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS window_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id   TEXT    NOT NULL,
    ts          TEXT    NOT NULL,
    action      TEXT    NOT NULL,
    co2         INTEGER,
    synced      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_r_unsynced ON readings(synced) WHERE synced = 0;
CREATE INDEX IF NOT EXISTS idx_e_unsynced ON events(synced) WHERE synced = 0;
CREATE INDEX IF NOT EXISTS idx_w_unsynced ON window_events(synced) WHERE synced = 0;
"""


def open_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def migrate(conn):
    """예전 버전으로 만든 DB에 새 컬럼이 없으면 추가한다."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(readings)")}
    for name, typ in (("occupancy", "INTEGER"), ("window_open", "INTEGER")):
        if name not in cols:
            conn.execute(f"ALTER TABLE readings ADD COLUMN {name} {typ}")
            log.info("readings 테이블에 %s 컬럼 추가", name)
    conn.commit()


# ============================================================ 창문(LED)
class Window:
    """실제 창문 모터 대신 LED로 열림/닫힘을 표시한다."""

    def __init__(self, pin):
        self.led = digitalio.DigitalInOut(pin)
        self.led.switch_to_output(value=False)
        self.is_open = False

    def update(self, co2):
        """CO2 값을 보고 상태가 바뀌면 'open' 또는 'close'를, 그대로면 None을 반환."""
        if co2 is None:
            return None
        if not self.is_open and co2 >= CO2_OPEN_PPM:
            self._set(True)
            return "open"
        if self.is_open and co2 < CO2_CLOSE_PPM:
            self._set(False)
            return "close"
        return None

    def _set(self, state):
        self.is_open = state
        self.led.value = state

    def off(self):
        try:
            self.led.value = False
            self.led.deinit()
        except Exception:
            pass


def save_window_event(conn, action, co2):
    try:
        conn.execute(
            "INSERT INTO window_events (device_id, ts, action, co2) VALUES (?, ?, ?, ?)",
            (DEVICE_ID, now_utc(), action, co2))
        conn.commit()
    except Exception as e:
        log.error("window_events 저장 실패: %s", e)


# ============================================================ PMS5003
def read_pms(ser, timeout_sec=3.0):
    deadline = time.time() + timeout_sec
    ser.reset_input_buffer()
    while time.time() < deadline:
        if ser.read(1) != b"\x42":
            continue
        if ser.read(1) != b"\x4d":
            continue
        frame = ser.read(30)
        if len(frame) != 30:
            return None
        if 0x42 + 0x4D + sum(frame[:28]) != int.from_bytes(frame[28:30], "big"):
            continue
        v = struct.unpack(">13H", frame[2:28])
        # v[0:3] = CF=1 기준, v[3:6] = 대기환경 기준
        return {"pm1": v[3], "pm25": v[4], "pm10": v[5]}
    return None


# ============================================================ 환경값 + 창문 스레드
def env_worker(window):
    conn = open_db()

    scd = None
    try:
        scd = adafruit_scd4x.SCD4X(board.I2C())
        scd.stop_periodic_measurement()
        time.sleep(0.5)
        if SEAL_BOX_MODE and scd.self_calibration_enabled:
            # 밀폐 상자는 외기(400ppm)에 노출되지 않아 자동보정이 값을 망가뜨린다
            scd.self_calibration_enabled = False
            scd.persist_settings()
            log.info("SCD41 자동보정(ASC) 비활성화")
        scd.start_periodic_measurement()
        log.info("SCD41 준비 완료")
    except Exception as e:
        scd = None
        log.error("SCD41 초기화 실패: %s", e)

    ser = None
    try:
        ser = serial.Serial(PMS_PORT, baudrate=9600, timeout=2)
        log.info("PMS5003 연결 완료, %d초 워밍업 뒤부터 기록", PMS_WARMUP_SEC)
    except Exception as e:
        log.error("PMS5003 열기 실패: %s", e)
    pms_ready_at = time.monotonic() + PMS_WARMUP_SEC

    while not stop.is_set():
        start = time.monotonic()
        row = {
            "device_id": DEVICE_ID, "ts": now_utc(),
            "co2": None, "temp": None, "rh": None,
            "pm1": None, "pm25": None, "pm10": None,
            "occupancy": None, "window_open": None,
        }

        # SCD41 -- 측정 주기가 5초라 data_ready 확인이 필요하다
        if scd is not None:
            try:
                if scd.data_ready:
                    row["co2"] = scd.CO2
                    row["temp"] = round(scd.temperature, 2)
                    row["rh"] = round(scd.relative_humidity, 2)
            except Exception as e:
                log.error("SCD41 읽기 실패: %s", e)

        # PMS5003 -- 워밍업이 끝난 뒤부터만 기록
        if ser is not None and time.monotonic() >= pms_ready_at:
            try:
                pm = read_pms(ser)
                if pm:
                    row.update(pm)
            except Exception as e:
                log.error("PMS5003 읽기 실패: %s", e)

        # 창문(LED) 제어
        if window is not None:
            action = window.update(row["co2"])
            if action == "open":
                log.info("창문 열림 (CO2 %d ppm >= %d) -> LED 켜짐",
                         row["co2"], CO2_OPEN_PPM)
                save_window_event(conn, "open", row["co2"])
            elif action == "close":
                log.info("창문 닫힘 (CO2 %d ppm < %d) -> LED 꺼짐",
                         row["co2"], CO2_CLOSE_PPM)
                save_window_event(conn, "close", row["co2"])
            row["window_open"] = int(window.is_open)

        with _occ_lock:
            row["occupancy"] = _occupancy

        try:
            conn.execute(
                """INSERT OR IGNORE INTO readings
                   (device_id, ts, co2, temp, rh, pm1, pm25, pm10, occupancy, window_open)
                   VALUES (:device_id, :ts, :co2, :temp, :rh,
                           :pm1, :pm25, :pm10, :occupancy, :window_open)""", row)
            conn.commit()
            log.info("ENV %s", json.dumps(row, ensure_ascii=False))
        except Exception as e:
            log.error("readings 저장 실패: %s", e)

        stop.wait(max(0, ENV_INTERVAL_SEC - (time.monotonic() - start)))

    conn.close()
    if ser:
        ser.close()


# ============================================================ 출입 감지
def _pick_threshold(samples, label):
    """빈 상태 측정값에서 '가려짐' 기준 거리를 정한다.
    측정 범위 밖(8190 등) 값은 빼고 계산한다. 그런 값이 기준이 되면
    손을 아무리 가까이 대도 판정이 안 되기 때문이다."""
    valid = [v for v in samples if 0 < v < OUT_OF_RANGE_MM]
    if not valid or len(valid) < len(samples) * 0.5:
        log.warning("%s 센서가 맞은편을 잘 못 봅니다 (유효 %d/%d회). "
                    "기준을 %dmm로 고정합니다. 맞은편에 흰 종이를 붙이면 정확해집니다.",
                    label, len(valid), len(samples), FALLBACK_BLOCK_MM)
        return FALLBACK_BLOCK_MM
    base = sorted(valid)[len(valid) // 2]
    th = int(base * BLOCK_RATIO)
    log.info("%s 기준 거리 %dmm (%d~%d) -> %dmm 미만이면 가려짐",
             label, base, min(valid), max(valid), th)
    return th


def measure_baseline(s1, s2):
    log.info("기준 거리 측정 중 (%.0f초). 센서 앞을 비워 두세요.", BASELINE_SEC)
    a, b = [], []
    t0 = time.monotonic()
    while time.monotonic() - t0 < BASELINE_SEC and not stop.is_set():
        try:
            a.append(s1.range)
            b.append(s2.range)
        except Exception:
            pass
        time.sleep(TOF_INTERVAL_SEC)
    return _pick_threshold(a, "1번"), _pick_threshold(b, "2번")


def save_event(conn, direction, duration_ms, occ):
    try:
        conn.execute(
            """INSERT INTO events (device_id, ts, direction, duration_ms, occupancy)
               VALUES (?, ?, ?, ?, ?)""",
            (DEVICE_ID, now_utc(), direction, duration_ms, occ))
        conn.commit()
    except Exception as e:
        log.error("events 저장 실패: %s", e)


def tof_loop(conn, s1, s2, th1, th2):
    """
    idle   -> 둘 중 하나가 가려지면 active, 어느 쪽이 먼저인지 기록
    active -> 둘 다 CLEAR_DEBOUNCE_SEC 동안 비면 종료하고 방향 판정
    먼저 가려진 쪽이 1번(바깥)이면 들어옴, 2번(안쪽)이면 나감.
    """
    global _occupancy
    active = False
    first = None
    seen1 = seen2 = False
    t_start = 0.0
    t_clear = None

    log.info("출입 감지 시작")
    while not stop.is_set():
        try:
            d1 = s1.range
            d2 = s2.range
        except Exception as e:
            log.error("거리 읽기 실패: %s", e)
            stop.wait(0.5)
            continue

        b1 = 0 < d1 < th1
        b2 = 0 < d2 < th2

        if not active:
            if b1 or b2:
                active = True
                if b1 and not b2:
                    first = 1
                elif b2 and not b1:
                    first = 2
                else:
                    first = None    # 동시에 가려짐 -> 빠져나가는 순서로 판정
                seen1, seen2 = b1, b2
                t_start = time.monotonic()
                t_clear = None
        else:
            seen1 = seen1 or b1
            seen2 = seen2 or b2
            # 동시에 가려졌던 경우: 먼저 비워진 쪽이 들어온 쪽
            if first is None and b1 != b2:
                first = 2 if b1 else 1

            if b1 or b2:
                t_clear = None
            elif t_clear is None:
                t_clear = time.monotonic()
            elif time.monotonic() - t_clear >= CLEAR_DEBOUNCE_SEC:
                dur = t_clear - t_start
                active = False
                if dur < MIN_EVENT_SEC or dur > MAX_EVENT_SEC:
                    log.debug("이벤트 무시 (%.2fs)", dur)
                elif not (seen1 and seen2):
                    log.info("한쪽만 반응 -> 통과 아님 (%s번만, %.2fs)",
                             1 if seen1 else 2, dur)
                elif first is None:
                    log.info("방향 불명 -> 기록만 (%.2fs)", dur)
                    save_event(conn, "unknown", int(dur * 1000), _occupancy)
                else:
                    direction = "in" if first == 1 else "out"
                    with _occ_lock:
                        _occupancy += 1 if direction == "in" else -1
                        _occupancy = max(_occupancy, 0)
                        occ = _occupancy
                    save_event(conn, direction, int(dur * 1000), occ)
                    log.info("출입: %s (%.2fs) -> 현재 %d명",
                             "들어옴" if direction == "in" else "나감", dur, occ)
                first = None
                seen1 = seen2 = False

        stop.wait(TOF_INTERVAL_SEC)


# ============================================================ main
def main():
    conn = open_db()
    conn.executescript(SCHEMA)
    migrate(conn)

    window = None
    try:
        window = Window(LED_PIN)
        log.info("창문(LED) 준비 완료: CO2 %d ppm 이상 열림 / %d ppm 미만 닫힘",
                 CO2_OPEN_PPM, CO2_CLOSE_PPM)
    except Exception as e:
        log.error("LED 초기화 실패, 창문 제어 없이 진행: %s", e)

    s1 = s2 = None
    try:
        s1 = adafruit_vl53l0x.VL53L0X(board.I2C())
        s2 = adafruit_vl53l0x.VL53L0X(ExtendedI2C(3))
        for s in (s1, s2):
            s.measurement_timing_budget = TOF_TIMING_BUDGET
        log.info("VL53L0X 2대 준비 완료")
    except Exception as e:
        s1 = s2 = None
        log.error("VL53L0X 초기화 실패, 출입 감지 없이 진행: %s", e)

    t = threading.Thread(target=env_worker, args=(window,), daemon=True)
    t.start()

    if s1 and s2:
        try:
            th1, th2 = measure_baseline(s1, s2)
            tof_loop(conn, s1, s2, th1, th2)
        except Exception as e:
            log.error("출입 감지 중단, 환경 수집은 계속: %s", e)
            stop.wait()
    else:
        stop.wait()

    t.join(timeout=15)
    if window is not None:
        window.off()
    conn.close()
    log.info("정상 종료")


if __name__ == "__main__":
    main()
