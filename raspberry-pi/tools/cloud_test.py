#!/usr/bin/env python3
"""
AWS IoT Core(대원 서버) 연결 테스트 — SAD 4.2 / cloud/tools/fake_pi.py 형식을 따른다.

하는 일
  1) 시계와 인증서 파일 확인
  2) vent-01 로 접속
  3) vent/vent-01/cmd 구독 (대시보드 수동 버튼 명령 받기)
  4) vent/vent-01/heartbeat 1건 발행 -> 대시보드에 '온라인'으로 표시됨
  5) (--telemetry) 로컬 DB의 최신 센서값 1건을 vent/vent-01/telemetry 로 발행
  6) --wait 초 동안 명령을 기다렸다가, 받으면 actuator 로 결과를 보고

주의
  - 대원 노트북의 fake_pi.py 가 같은 vent-01 로 접속해 있으면 서로 끊어 버린다. 먼저 꺼 달라고 할 것.
  - LED/모터는 움직이지 않는다. 명령을 받고 응답하는 통신만 확인한다.

실행
  source ~/venv/bin/activate
  python3 ~/airtiming/tools/cloud_test.py                 # heartbeat + 명령 대기 120초
  python3 ~/airtiming/tools/cloud_test.py --telemetry     # 센서값 1건도 보내기
  python3 ~/airtiming/tools/cloud_test.py --port 443      # 학교망에서 8883이 막혔을 때
"""

import argparse
import glob
import json
import os
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

DEFAULT_ENDPOINT = "a3kpxm984jauzv-ats.iot.ap-southeast-2.amazonaws.com"
DEFAULT_DEVICE = "vent-01"
CERT_DIR = Path.home() / "airtiming" / "certs"
DB_PATH = Path.home() / "airtiming" / "readings.db"
SEQ_FILE = Path.home() / "airtiming" / ".vent_seq"   # 실제 전송 프로그램도 이 번호를 이어서 쓴다
CMD_TTL_S = 30                                        # SAD: 30초 지난 명령은 무시


# ------------------------------------------------------------ 공통 규약 (SAD 4.2)
def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Seq:
    """기기 메시지 일련번호: 1부터 증가, 껐다 켜도 이어지고 재사용하지 않는다."""

    def __init__(self, path=SEQ_FILE):
        self.path = path
        try:
            self.v = int(path.read_text().strip())
        except Exception:
            self.v = 0

    def next(self):
        self.v += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(str(self.v))
        return self.v


def clock_synced():
    try:
        out = subprocess.run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        return out == "yes"
    except Exception:
        return None


def find_one(cert_dir, *patterns):
    for pat in patterns:
        files = sorted(glob.glob(str(cert_dir / pat)))
        if len(files) == 1:
            return files[0]
        if len(files) > 1:
            sys.exit(f"   [오류] {cert_dir} 에 '{pat}' 파일이 여러 개입니다: {files}")
    sys.exit(f"   [오류] {cert_dir} 에서 {' 또는 '.join(patterns)} 파일을 찾지 못했습니다.\n"
             f"   대원에게 받은 인증서 3개를 이 폴더에 넣으세요.")


def latest_reading(db_path):
    """collector.py가 쌓은 최신 센서값 1건 (없으면 None)."""
    if not db_path.exists():
        return None
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM readings ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None
    finally:
        conn.close()


# ------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--endpoint", default=os.environ.get("VENT_IOT_ENDPOINT", DEFAULT_ENDPOINT))
    ap.add_argument("--device", default=os.environ.get("VENT_DEVICE_ID", DEFAULT_DEVICE))
    ap.add_argument("--port", type=int, default=8883, choices=[8883, 443])
    ap.add_argument("--certs", default=str(CERT_DIR))
    ap.add_argument("--telemetry", action="store_true", help="최신 센서값 1건도 보내기")
    ap.add_argument("--wait", type=int, default=120, help="명령을 기다릴 시간(초)")
    args = ap.parse_args()

    dev = args.device
    topic = lambda name: f"vent/{dev}/{name}"
    seq = Seq()
    started = time.time()

    def base():
        s = seq.next()
        return {"schema_version": 1, "ts": now_iso(), "msg_id": f"{dev}-{s}",
                "seq": s, "run_id": "NONE"}

    # 1) 시계
    synced = clock_synced()
    print(f"1) 시계: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} "
          f"(인터넷 시간 동기화: {'예' if synced else '아니오' if synced is False else '확인 불가'})")
    if synced is False:
        print("   [주의] 시계가 틀리면 TLS 접속이 실패합니다. 인터넷 연결 후 1~2분 기다렸다 다시 해 보세요.")

    # 2) 인증서
    cert_dir = Path(args.certs).expanduser()
    ca = find_one(cert_dir, "AmazonRootCA1.pem")
    cert = find_one(cert_dir, "*-certificate.pem.crt", "device.pem.crt")
    key = find_one(cert_dir, "*-private.pem.key", "private.pem.key")
    print(f"2) 인증서: {Path(cert).name}, {Path(key).name}, {Path(ca).name}")

    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=ca)
    try:
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    except ssl.SSLError as e:
        sys.exit(f"   [오류] 인증서와 개인 키가 짝이 맞지 않거나 파일이 깨졌습니다: {e}")
    if args.port == 443:
        # AWS IoT Core는 443 포트에서 ALPN 이름으로 MQTT를 구분한다
        ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])

    connected = threading.Event()
    dropped = threading.Event()
    refused = []
    seen_cmd = set()
    got_cmd = []
    flap = {"state": "CLOSED"}   # 테스트용 가상 창문 상태 (실제 LED/모터는 움직이지 않음)

    def publish(name, payload):
        body = json.dumps(payload, ensure_ascii=False)
        info = client.publish(topic(name), body, qos=1)
        try:
            info.wait_for_publish(timeout=10)
        except RuntimeError:
            pass
        ok = info.is_published()
        print(f"   {'→' if ok else '✗'} {topic(name)}  {body}")
        return ok

    def on_connect(c, u, flags, rc, props):
        if rc.is_failure:
            refused.append(str(rc))
        else:
            c.subscribe(topic("cmd"), qos=1)
        connected.set()

    def on_disconnect(c, u, flags, rc, props):
        dropped.set()

    def on_message(c, u, msg):
        print(f"\n   ← {msg.topic}  {msg.payload.decode('utf-8', 'replace')}")
        try:
            cmd = json.loads(msg.payload)
            cmd_id, action = cmd["cmd_id"], str(cmd["action"]).upper()
            age = (datetime.now(timezone.utc) - parse_iso(cmd["issued_ts"])).total_seconds()
        except Exception as e:
            print(f"     [무시] 명령 형식 오류: {e}")
            return
        if cmd_id in seen_cmd:
            result = "DUPLICATE"
        elif age > CMD_TTL_S:
            result = "EXPIRED"
        elif action not in ("OPEN", "CLOSE"):
            result = "BLOCKED"
        else:
            result = "OK"
            flap["state"] = "OPEN" if action == "OPEN" else "CLOSED"
        seen_cmd.add(cmd_id)
        print(f"     명령 {action}, 발행 후 {age:.1f}초 경과 -> {result} (창문 {flap['state']})")
        p = base()
        p.update({"state": flap["state"],
                  "trigger": "MANUAL", "rec_id": None, "cmd_id": cmd_id, "result": result})
        # 콜백 안에서는 PUBACK을 기다리면 안 되므로 그냥 발행한다
        c.publish(topic("actuator"), json.dumps(p, ensure_ascii=False), qos=1)
        print(f"     → {topic('actuator')}  {json.dumps(p, ensure_ascii=False)}")
        got_cmd.append(result)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=dev, protocol=mqtt.MQTTv311)
    client.tls_set_context(ctx)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    # 3) 접속
    print(f"3) 접속: {args.endpoint}:{args.port} (client_id={dev})")
    try:
        client.connect(args.endpoint, args.port, keepalive=60)
    except socket.gaierror:
        sys.exit("   [실패] 주소를 찾을 수 없습니다. 파이가 인터넷에 연결돼 있는지 확인하세요 (ping google.com).")
    except ssl.SSLError as e:
        sys.exit(f"   [실패] TLS 오류: {e}\n   시계(timedatectl)와 인증서 파일을 확인하세요.")
    except (ConnectionRefusedError, TimeoutError, OSError) as e:
        hint = "" if args.port == 443 else "\n   학교망에서 8883 포트가 막혔을 수 있습니다. --port 443 으로 다시 해 보세요."
        sys.exit(f"   [실패] {e}{hint}")

    client.loop_start()
    if not connected.wait(10) or refused:
        client.loop_stop()
        sys.exit(f"   [실패] 서버가 응답하지 않거나 거부했습니다 {refused}\n"
                 "   대원에게 인증서가 '활성' 상태이고 vent-01 사물·정책에 붙어 있는지 확인해 달라고 하세요.")
    if dropped.wait(1.5):
        client.loop_stop()
        sys.exit("   [실패] 접속 직후 끊겼습니다. 같은 vent-01 로 다른 프로그램(대원의 fake_pi.py 등)이\n"
                 "   접속해 있거나, 정책이 이 client_id를 허용하지 않습니다.")
    print(f"   성공, {topic('cmd')} 구독")

    # 4) heartbeat
    print("4) heartbeat 발행")
    hb = base()
    hb.update({"uptime_s": int(time.time() - started), "outbox_size": 0,
               "model_version": "none", "time_synced": bool(synced)})
    if not publish("heartbeat", hb) or dropped.is_set():
        client.loop_stop()
        sys.exit("   [실패] 발행 후 끊겼습니다. 정책이 vent/vent-01/* 발행을 허용하는지 대원에게 확인하세요.")

    # 5) telemetry
    if args.telemetry:
        print("5) 최신 센서값 1건 발행")
        r = latest_reading(DB_PATH)
        if r is None:
            print("   [건너뜀] 로컬 DB에 센서값이 없습니다. collector.py를 먼저 돌려 두세요.")
        else:
            t = base()
            t.update({
                "co2_ppm": r.get("co2"), "pm25_ugm3": r.get("pm25"),
                "temp_c": r.get("temp"), "humidity_pct": r.get("rh"),
                "occupancy": r.get("occupancy"),
                "outdoor_pm25_ugm3": None, "outdoor_temp_c": None, "outdoor_source": "NONE",
                "quality": "OK",
            })
            publish("telemetry", t)
            print(f"   (측정 시각 {r.get('ts')} 의 값을 지금 시각으로 보냄)")

    # 6) 명령 대기
    print(f"\n6) {args.wait}초 동안 대시보드 수동 버튼 명령을 기다립니다. (끝내려면 Ctrl+C)")
    try:
        end = time.time() + args.wait
        while time.time() < end and not dropped.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n   중단")

    client.disconnect()
    client.loop_stop()

    print("\n== 결과 ==")
    print("접속·heartbeat: 성공")
    print(f"명령 수신: {len(got_cmd)}건 {got_cmd}" if got_cmd else
          "명령 수신: 없음 (대시보드에서 수동 열기/닫기를 눌러 보면 여기서 받습니다)")


if __name__ == "__main__":
    main()
