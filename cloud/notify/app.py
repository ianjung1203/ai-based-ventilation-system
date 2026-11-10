"""vent-notify (C2 정훈)

1) IoT Rule vent_alert_to_notify (vent/+/alert)
   -> rec_id-index 로 추천 내용 찾기 -> SNS 이메일 + 디스코드
   - 5분 넘게 늦은 alert 는 버린다 (SAD 4.2)
2) EventBridge 5분 스케줄 (vent-offline-check)
   -> vent-device-status 에서 heartbeat 가 15분 넘게 없으면 오프라인 알림

같은 알림은 vent-notify-log 테이블에 먼저 기록(조건부 저장)해서 한 번만 보낸다.
  추천 알림:   rec#{rec_id}
  오프라인:    offline#{device_id}#{마지막 heartbeat 수신 시각}
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

KST = timezone(timedelta(hours=9))
LATE_ALERT_SEC = int(os.environ.get("LATE_ALERT_SEC", "300"))
OFFLINE_SEC = int(os.environ.get("OFFLINE_MINUTES", "15")) * 60
LOG_TTL_SEC = 7 * 24 * 3600  # 중복 방지 기록은 7일 뒤 자동 삭제

ddb = boto3.resource("dynamodb")
sns = boto3.client("sns")
ssm = boto3.client("ssm")

rec_table = ddb.Table(os.environ["RECOMMENDATIONS_TABLE"])
status_table = ddb.Table(os.environ["STATUS_TABLE"])
log_table = ddb.Table(os.environ["NOTIFY_LOG_TABLE"])
TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
DISCORD_PARAM = os.environ.get("DISCORD_PARAM", "")

# SAD 4.2 reason_code -> 화면/알림 문구
REASON_TEXT = {
    "CO2_HIGH": "CO2 농도가 높아요",
    "PM_BAD_SPLIT": "바깥 미세먼지가 나빠서 짧게 나눠 환기해요",
    "PM_VERY_BAD_HOLD": "바깥 미세먼지가 매우 나빠서 환기를 미뤄요",
    "CO2_OVERRIDE": "CO2가 매우 높아서 미세먼지와 상관없이 환기해요",
    "UNREACHABLE": "목표 농도까지 낮추기 어려워요",
    "PROTECT_OPEN": "보호 동작으로 열어요",
}

_discord_url = None  # SSM 값을 Lambda 가 살아 있는 동안 재사용


# ───────── 진입점 ─────────
def handler(event, context):
    if event.get("source") == "aws.events":  # EventBridge 스케줄
        return check_offline()
    return handle_alert(event)  # IoT Rule


# ───────── 1) 추천 알림 ─────────
def handle_alert(event):
    rec_id = event.get("rec_id")
    ts = event.get("ts")
    device_id = event.get("device_id", "unknown")
    if not rec_id or not ts:
        log("bad_input", event=event)
        return {"status": "bad_input"}

    try:
        age = (now_utc() - parse_ts(ts)).total_seconds()
    except (TypeError, ValueError):
        log("bad_ts", rec_id=rec_id, ts=ts)
        return {"status": "bad_ts"}
    if age > LATE_ALERT_SEC:
        log("late_alert_dropped", rec_id=rec_id, ts=ts, age_sec=int(age))
        return {"status": "late", "age_sec": int(age)}

    key = f"rec#{rec_id}"
    if not claim(key, device_id=device_id, alert_ts=ts):
        log("duplicate_skipped", rec_id=rec_id)
        return {"status": "skipped", "rec_id": rec_id}

    rec = find_recommendation(rec_id)
    subject, body = build_rec_message(device_id, rec_id, rec)
    sent = send_all(subject, body)
    if not any(sent.values()):
        release(key)  # 둘 다 실패 -> 기록을 지우고 오류를 내서 Lambda 가 다시 시도하게
        raise RuntimeError(f"SNS와 디스코드 모두 실패: rec_id={rec_id}")

    log("alert_sent", rec_id=rec_id, found=rec is not None, **sent)
    return {"status": "sent", "rec_id": rec_id, **sent}


def find_recommendation(rec_id):
    # recommendation 직후 alert 가 오면 GSI 반영이 늦을 수 있어 1초 간격 3번 시도
    for _ in range(3):
        resp = rec_table.query(
            IndexName="rec_id-index",
            KeyConditionExpression=Key("rec_id").eq(rec_id),
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            return items[0]
        time.sleep(1)
    return None


def build_rec_message(device_id, rec_id, rec):
    subject = f"[vent] {device_id} ventilation alert"  # SNS 제목은 영어(ASCII)
    if rec is None:
        body = (
            "환기 알림이 왔지만 추천 내용을 찾지 못했어요.\n"
            f"기기: {device_id}\n"
            f"rec_id: {rec_id}"
        )
        return subject, body

    code = rec.get("reason_code", "")
    body = "\n".join([
        f"기기: {device_id}",
        f"환기 시작: {to_kst(rec.get('start_ts'))}",
        f"권장 시간: {fmt_duration(rec.get('duration_sec'))}",
        f"사유: {REASON_TEXT.get(code, code)} ({code})",
        f"rec_id: {rec_id}",
    ])
    return subject, body


# ───────── 2) 오프라인 알림 ─────────
def check_offline():
    now = now_utc()
    items = status_table.scan().get("Items", [])  # 기기 수가 적어서 scan 으로 충분
    alerted = []
    for it in items:
        device_id = it.get("device_id", "unknown")
        last_ts = it.get("last_heartbeat_ts")
        # 파이 시계가 틀려도 되도록 서버가 받은 시각(received_at_ms)을 우선 사용
        if it.get("received_at_ms") is not None:
            last_dt = datetime.fromtimestamp(int(it["received_at_ms"]) / 1000, tz=timezone.utc)
            mark = str(int(it["received_at_ms"]))
        else:
            try:
                last_dt = parse_ts(last_ts)
            except (TypeError, ValueError):
                continue
            mark = str(last_ts)

        age = (now - last_dt).total_seconds()
        if age <= OFFLINE_SEC:
            continue

        key = f"offline#{device_id}#{mark}"  # 같은 끊김은 한 번만, 새 끊김은 다시 알림
        if not claim(key, device_id=device_id, last_heartbeat_ts=str(last_ts)):
            continue

        subject = f"[vent] {device_id} OFFLINE"
        body = "\n".join([
            f"기기 {device_id}의 heartbeat가 {int(age // 60)}분 동안 오지 않았어요.",
            f"마지막 heartbeat: {to_kst(last_dt.isoformat())}",
            "전원, 와이파이, 파이 프로그램을 확인해 주세요.",
        ])
        sent = send_all(subject, body)
        if not any(sent.values()):
            release(key)  # 다음 5분 스케줄에서 다시 시도
        alerted.append({"device_id": device_id, **sent})

    log("offline_checked", devices=len(items), alerted=alerted)
    return {"status": "checked", "devices": len(items), "alerted": alerted}


# ───────── 중복 방지 기록 ─────────
def claim(key, **info):
    """처음 보는 key 면 기록하고 True, 이미 있으면 False"""
    now = int(time.time())
    try:
        log_table.put_item(
            Item={"notify_key": key, "created_at": now, "expires_at": now + LOG_TTL_SEC, **info},
            ConditionExpression="attribute_not_exists(notify_key)",
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def release(key):
    log_table.delete_item(Key={"notify_key": key})


# ───────── 보내기 ─────────
def send_all(subject, body):
    result = {"sns": False, "discord": False}
    try:
        sns.publish(TopicArn=TOPIC_ARN, Subject=subject, Message=body)
        result["sns"] = True
    except Exception as e:
        log("sns_failed", error=str(e))
    try:
        send_discord(f"**{subject}**\n{body}")
        result["discord"] = True
    except Exception as e:
        log("discord_failed", error=str(e))
    return result


def get_discord_url():
    global _discord_url
    if _discord_url is None:
        resp = ssm.get_parameter(Name=DISCORD_PARAM, WithDecryption=True)
        _discord_url = resp["Parameter"]["Value"]
    return _discord_url


def send_discord(text):
    data = json.dumps({"content": text}).encode("utf-8")
    req = urllib.request.Request(
        get_discord_url(),
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "vent-notify/1.0"},
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status


# ───────── 작은 도구들 ─────────
def now_utc():
    return datetime.now(timezone.utc)


def parse_ts(s):
    # "2026-11-08T11:32:57.180Z" -> datetime(UTC)
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


def to_kst(s):
    try:
        return parse_ts(s).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S (KST)")
    except (TypeError, ValueError):
        return str(s)


def fmt_duration(sec):
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return str(sec)
    m, s = divmod(sec, 60)
    return f"{m}분 {s}초" if s else f"{m}분"


def log(msg, **kw):
    print(json.dumps({"msg": msg, **kw}, ensure_ascii=False, default=str))