"""vent-notify 시험: recommendation -> alert 를 IoT Core 에 게시 (노트북 aws login 권한 사용)

사용:
  py -3.12 cloud\\tools\\test_alert.py          기본: 메일+디스코드 1번 와야 함
  py -3.12 cloud\\tools\\test_alert.py --dup    같은 alert 2번 -> 알림은 1번만
  py -3.12 cloud\\tools\\test_alert.py --late   10분 전 ts 의 alert -> 알림 안 옴(버림)

주의: 시험 메시지도 vent-recommendations 와 S3 raw/ 에 저장된다 (run_id=NONE).
"""
import argparse
import json
import time
import uuid
from datetime import datetime, timedelta, timezone

import boto3

ENDPOINT = "https://a3kpxm984jauzv-ats.iot.ap-southeast-2.amazonaws.com"


def iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


parser = argparse.ArgumentParser()
parser.add_argument("--device", default="vent-01")
parser.add_argument("--dup", action="store_true", help="같은 rec_id 의 alert 를 2번 보냄")
parser.add_argument("--late", action="store_true", help="10분 전 ts 로 alert 를 보냄")
args = parser.parse_args()

iot = boto3.client("iot-data", region_name="ap-southeast-2", endpoint_url=ENDPOINT)
seq = int(time.time())  # 시험용 seq (fake_pi 와 겹치지 않게 큰 수)


def publish(kind, body, ts=None):
    global seq
    seq += 1
    msg = {
        "schema_version": 1,
        "ts": ts or iso(datetime.now(timezone.utc)),
        "msg_id": f"{args.device}-{seq}",
        "seq": seq,
        "run_id": "NONE",
        **body,
    }
    topic = f"vent/{args.device}/{kind}"
    iot.publish(topic=topic, qos=1, payload=json.dumps(msg).encode("utf-8"))
    print("->", topic, json.dumps(msg, ensure_ascii=False))


now = datetime.now(timezone.utc)
rec_id = str(uuid.uuid4())

publish("recommendation", {
    "rec_id": rec_id,
    "need_vent": True,
    "start_ts": iso(now + timedelta(minutes=1)),
    "duration_sec": 300,
    "reason_code": "CO2_HIGH",
})
time.sleep(2)  # 추천이 테이블에 저장될 시간

alert_ts = iso(now - timedelta(minutes=10)) if args.late else None
for _ in range(2 if args.dup else 1):
    publish("alert", {"rec_id": rec_id}, ts=alert_ts)
    time.sleep(1)

print("rec_id:", rec_id)