"""vent-notify: alert(rec_id, ts) -> 추천 내용 찾기 -> SNS 이메일 + 디스코드 전송"""
import json
import os
import urllib.request

import boto3

SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

sns = boto3.client("sns", region_name="ap-southeast-2")

# 같은 rec_id는 한 번만 보내기 (임시: Lambda 메모리에만 기억 -> 나중에 DynamoDB로 교체)
_sent_rec_ids = set()


def get_recommendation(rec_id):
    """[가짜] 나중에 vent-recommendations 테이블에서 rec_id로 찾도록 교체"""
    return {
        "rec_id": rec_id,
        "device_id": "vent-01",
        "co2_ppm": 1180,
        "pred_co2_10min_ppm": 1350,
        "action": "VENTILATE",
        "reason": "10분 뒤 CO2가 1,000ppm을 넘을 것으로 예측됨",
    }


def build_message(rec, ts):
    # SNS 제목은 영어(ASCII)만 안전 -> 한글은 본문에
    subject = f"[vent] {rec['device_id']} ventilation alert"
    body = (
        f"기기: {rec['device_id']}\n"
        f"시각(UTC): {ts}\n"
        f"현재 CO2: {rec['co2_ppm']} ppm\n"
        f"10분 뒤 예측: {rec['pred_co2_10min_ppm']} ppm\n"
        f"추천: {rec['action']}\n"
        f"이유: {rec['reason']}\n"
        f"rec_id: {rec['rec_id']}"
    )
    return subject, body


def send_sns(subject, body):
    sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject, Message=body)


def send_discord(subject, body):
    data = json.dumps({"content": f"**{subject}**\n{body}"}).encode("utf-8")
    req = urllib.request.Request(
        DISCORD_WEBHOOK_URL,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "vent-notify/1.0"},
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status


def lambda_handler(event, context):
    rec_id = event.get("rec_id")
    ts = event.get("ts")
    if not rec_id:
        return {"status": "error", "reason": "rec_id 없음"}

    if rec_id in _sent_rec_ids:
        return {"status": "skipped", "rec_id": rec_id}

    rec = get_recommendation(rec_id)
    subject, body = build_message(rec, ts)

    result = {"status": "sent", "rec_id": rec_id, "sns": False, "discord": False}
    try:
        send_sns(subject, body)
        result["sns"] = True
    except Exception as e:
        print("SNS 실패:", e)
    try:
        send_discord(subject, body)
        result["discord"] = True
    except Exception as e:
        print("디스코드 실패:", e)

    # 하나라도 성공했으면 '보냄'으로 기억 (둘 다 실패하면 다음에 다시 시도)
    if result["sns"] or result["discord"]:
        _sent_rec_ids.add(rec_id)
    else:
        result["status"] = "failed"
    return result