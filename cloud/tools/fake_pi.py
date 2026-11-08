"""
가짜 파이 (vent-01)
- 진짜 라즈베리파이 대신 노트북에서 AWS IoT Core로 메시지를 보낸다.
- 메시지 형식은 SAD v0.5 4.2절(MQTT 토픽 설계, 공통 규약)을 따른다.

실행 (cmd, my-project 폴더에서):
    py -3.12 -m pip install paho-mqtt
    py -3.12 cloud\\tools\\fake_pi.py

옵션:
    --interval 10   telemetry 전송 간격(초). 플랩이 열리면 SAD대로 5초로 줄어든다.
    --count 0       telemetry를 몇 번 보내고 끝낼지 (0 = Ctrl+C 할 때까지 계속)
    --dup           각 telemetry를 두 번씩 보낸다 (3단계 '중복 저장' 테스트용)

인증서 파일은 깃 저장소 바깥(C:\\vent-certs)에서 읽는다. 저장소에 넣지 말 것.
"""
import argparse
import glob
import json
import os
import random
import ssl
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

ENDPOINT = os.environ.get("VENT_IOT_ENDPOINT", "a3kpxm984jauzv-ats.iot.ap-southeast-2.amazonaws.com")
DEVICE_ID = os.environ.get("VENT_DEVICE_ID", "vent-01")  # IoT 사물 이름과 같아야 접속된다
CERT_DIR = os.environ.get("VENT_CERT_DIR", r"C:\vent-certs")
SEQ_FILE = os.path.join(os.path.expanduser("~"), ".vent_fake_seq")  # 재실행해도 seq가 이어지게
CMD_TTL_S = 30          # 명령 유효기간 (SAD: 30초 지난 cmd는 무시)
HEARTBEAT_S = 300       # heartbeat 주기 (SAD: 5분)


def find_one(pattern):
    files = glob.glob(os.path.join(CERT_DIR, pattern))
    if len(files) != 1:
        sys.exit(f"[오류] {CERT_DIR} 에서 '{pattern}' 파일을 정확히 1개 찾지 못했습니다: {files}")
    return files[0]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class Seq:
    """Edge outbox 일련번호 흉내: 1부터 증가, 재실행해도 이어지고 재사용하지 않는다."""

    def __init__(self):
        try:
            with open(SEQ_FILE) as f:
                self.v = int(f.read().strip())
        except Exception:
            self.v = 0

    def next(self):
        self.v += 1
        with open(SEQ_FILE, "w") as f:
            f.write(str(self.v))
        return self.v


seq = Seq()
state = {"co2": 650.0, "occupancy": 2, "flap": "CLOSED", "run_id": "NONE", "start": time.time()}
seen_cmd_ids = set()


def topic(name):
    return f"vent/{DEVICE_ID}/{name}"


def base():
    s = seq.next()
    return {
        "schema_version": 1,
        "ts": now_iso(),
        "msg_id": f"{DEVICE_ID}-{s}",
        "seq": s,
        "run_id": state["run_id"],
    }


def publish(client, name, payload, dup=False):
    body = json.dumps(payload, ensure_ascii=False)
    client.publish(topic(name), body, qos=1)
    print(f"→ {topic(name)}  {body}")
    if dup:
        client.publish(topic(name), body, qos=1)
        print("   (같은 메시지를 한 번 더 보냄: 중복 저장 테스트)")


def make_telemetry():
    # 플랩이 닫혀 있으면 사람 수만큼 CO2가 오르고, 열려 있으면 내려간다 (그럴듯한 가짜 값)
    if state["flap"] == "OPEN":
        state["co2"] = max(420.0, state["co2"] - random.uniform(20, 40))
    else:
        state["co2"] = min(4000.0, state["co2"] + state["occupancy"] * random.uniform(3, 8))
    p = base()
    p.update({
        "co2_ppm": round(state["co2"], 1),
        "pm25_ugm3": round(random.uniform(8, 20), 1),
        "temp_c": round(random.uniform(22, 25), 1),
        "humidity_pct": round(random.uniform(40, 55), 1),
        "occupancy": state["occupancy"],
        "outdoor_pm25_ugm3": 15.0,
        "outdoor_temp_c": 12.0,
        "outdoor_source": "SCENARIO",
        "quality": "OK",
    })
    return p


def make_heartbeat():
    p = base()
    p.update({
        "uptime_s": int(time.time() - state["start"]),
        "outbox_size": 0,
        "model_version": "fake-0",
        "time_synced": True,
    })
    return p


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code.is_failure:
        print(f"[접속 실패] {reason_code}")
        return
    print(f"[접속 성공] {ENDPOINT} 에 {DEVICE_ID} 로 연결됨")
    client.subscribe(topic("cmd"), qos=1)
    print(f"[구독] {topic('cmd')} (대시보드 버튼 명령을 기다림)")
    publish(client, "heartbeat", make_heartbeat())


def on_disconnect(client, userdata, flags, reason_code, properties):
    print(f"[연결 끊김] {reason_code} (자동으로 다시 접속을 시도합니다)")


def on_message(client, userdata, msg):
    """cmd를 받으면 SAD 규칙대로 처리하고, 같은 cmd_id로 actuator를 보고한다."""
    print(f"← {msg.topic}  {msg.payload.decode('utf-8', 'replace')}")
    try:
        cmd = json.loads(msg.payload)
        cmd_id = cmd["cmd_id"]
        action = cmd["action"]
        age = (datetime.now(timezone.utc) - parse_iso(cmd["issued_ts"])).total_seconds()
    except Exception as e:
        print(f"   [무시] cmd 형식 오류: {e}")
        return

    if cmd_id in seen_cmd_ids:
        result = "DUPLICATE"
    elif age > CMD_TTL_S:
        result = "EXPIRED"
    elif action not in ("OPEN", "CLOSE"):
        result = "BLOCKED"
    else:
        result = "OK"
        state["flap"] = "OPEN" if action == "OPEN" else "CLOSED"
    seen_cmd_ids.add(cmd_id)

    p = base()
    p.update({
        "state": state["flap"],
        "trigger": "MANUAL",
        "rec_id": None,
        "cmd_id": cmd_id,
        "result": result,
    })
    publish(client, "actuator", p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=10)
    ap.add_argument("--count", type=int, default=0)
    ap.add_argument("--dup", action="store_true")
    args = ap.parse_args()

    ca = find_one("AmazonRootCA1.pem")
    cert = find_one("*-certificate.pem.crt")
    key = find_one("*-private.pem.key")

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=DEVICE_ID, protocol=mqtt.MQTTv311)
    client.tls_set(ca_certs=ca, certfile=cert, keyfile=key, tls_version=ssl.PROTOCOL_TLS_CLIENT)
    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message

    print(f"[시작] {ENDPOINT}:8883 접속 중... (끝내려면 Ctrl+C)")
    client.connect(ENDPOINT, 8883, keepalive=60)
    client.loop_start()
    time.sleep(2)

    sent = 0
    last_hb = time.time()
    try:
        while args.count == 0 or sent < args.count:
            publish(client, "telemetry", make_telemetry(), dup=args.dup)
            sent += 1
            if time.time() - last_hb >= HEARTBEAT_S:
                publish(client, "heartbeat", make_heartbeat())
                last_hb = time.time()
            # SAD: 플랩이 열려 있는 동안은 5초 간격
            time.sleep(5 if state["flap"] == "OPEN" else args.interval)
    except KeyboardInterrupt:
        print("\n[종료] Ctrl+C")
    finally:
        time.sleep(1)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
