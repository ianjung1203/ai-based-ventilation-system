"""
vent-query-api (C1, 대원) - 대시보드가 저장된 데이터를 꺼내 가는 조회 API.
근거: SAD v0.5 부록 A.3

  GET /devices                       기기 목록 + 마지막 heartbeat + 온라인 여부(서버 수신 시각 기준)
  GET /devices/{id}/latest           최신 telemetry·prediction·recommendation·actuator·occupancy + 상태
  GET /devices/{id}/history          기간별 기록
        ?type=readings|predictions|recommendations|actuator|occupancy (기본 readings)
        &from=ISO&to=ISO              (기본: 최근 1시간, 최대 7일)
        &limit=1..1000                (기본 500)
        &next_token=...               (다음 쪽)

시각은 UTC ISO-8601. DynamoDB 정렬키 sk = "ts#seq" 이므로 문자열 비교로 기간 조회한다.
"""
import base64
import json
import os
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

_ddb = boto3.resource("dynamodb")

TABLES = {
    "readings": os.environ.get("READINGS_TABLE", "vent-readings"),
    "predictions": os.environ.get("PREDICTIONS_TABLE", "vent-predictions"),
    "recommendations": os.environ.get("RECOMMENDATIONS_TABLE", "vent-recommendations"),
    "actuator": os.environ.get("ACTUATOR_TABLE", "vent-actuator-events"),
    "occupancy": os.environ.get("OCCUPANCY_TABLE", "vent-occupancy-events"),
}
STATUS_TABLE = os.environ.get("STATUS_TABLE", "vent-device-status")

MAX_RANGE = timedelta(days=7)        # SAD: 최대 7일
MAX_LIMIT = 1000                     # SAD: 최대 1,000건
DEFAULT_LIMIT = 500
DEFAULT_RANGE = timedelta(hours=1)
OFFLINE_AFTER = timedelta(minutes=15)  # SAD: heartbeat 15분 이상 없으면 오프라인


class BadRequest(Exception):
    pass


# ───────── 공통 도우미 ─────────
def _json_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store"},
        "body": json.dumps(body, ensure_ascii=False, default=_json_default),
    }


def _iso(dt):
    """2026-11-08T11:17:45.038Z 형식 (저장된 ts와 같은 모양이어야 문자열 비교가 맞다)"""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(s, name):
    try:
        dt = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
    except Exception:
        raise BadRequest(f"{name} 형식이 잘못됐습니다. 예: 2026-11-08T11:00:00Z")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _encode_token(key):
    return base64.urlsafe_b64encode(json.dumps(key, default=_json_default).encode()).decode()


def _decode_token(tok):
    try:
        return json.loads(base64.urlsafe_b64decode(tok.encode()).decode())
    except Exception:
        raise BadRequest("next_token이 잘못됐습니다.")


def _latest(table_name, device_id):
    r = _ddb.Table(table_name).query(
        KeyConditionExpression=Key("device_id").eq(device_id),
        ScanIndexForward=False,  # 최신 것부터
        Limit=1,
    )
    items = r.get("Items", [])
    return items[0] if items else None


def _received_at(status):
    """서버가 heartbeat를 받은 시각(received_at_ms, IoT Rule의 timestamp()).
    파이 시계가 틀려도 영향이 없도록 온라인 판단은 이 값을 쓴다 (정훈 오프라인 알림과 같은 기준)."""
    ms = (status or {}).get("received_at_ms")
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)


def _online(status, now):
    received = _received_at(status)
    if received is None:
        return False
    return now - received <= OFFLINE_AFTER


# ───────── 경로별 처리 ─────────
def list_devices():
    now = datetime.now(timezone.utc)
    items = _ddb.Table(STATUS_TABLE).scan().get("Items", [])
    devices = [
        {
            "device_id": it["device_id"],
            "last_heartbeat_ts": it.get("last_heartbeat_ts"),
            "last_seen_ts": _iso(_received_at(it)) if _received_at(it) else None,
            "online": _online(it, now),
            "model_version": it.get("model_version"),
        }
        for it in items
    ]
    devices.sort(key=lambda d: d["device_id"])
    return {"devices": devices, "server_ts": _iso(now)}


def latest(device_id):
    now = datetime.now(timezone.utc)
    status = _ddb.Table(STATUS_TABLE).get_item(Key={"device_id": device_id}).get("Item")
    body = {
        "device_id": device_id,
        "telemetry": _latest(TABLES["readings"], device_id),
        "prediction": _latest(TABLES["predictions"], device_id),
        "recommendation": _latest(TABLES["recommendations"], device_id),
        "actuator": _latest(TABLES["actuator"], device_id),
        "occupancy": _latest(TABLES["occupancy"], device_id),
        "status": {
            "last_heartbeat_ts": (status or {}).get("last_heartbeat_ts"),
            "last_seen_ts": _iso(_received_at(status)) if _received_at(status) else None,
            "online": _online(status, now),
            "model_version": (status or {}).get("model_version"),
            "time_synced": (status or {}).get("time_synced"),
        },
        "server_ts": _iso(now),
    }
    return body


def history(device_id, q):
    kind = q.get("type", "readings")
    if kind not in TABLES:
        raise BadRequest(f"type은 {', '.join(TABLES)} 중 하나여야 합니다.")

    now = datetime.now(timezone.utc)
    to_dt = _parse_iso(q["to"], "to") if q.get("to") else now
    from_dt = _parse_iso(q["from"], "from") if q.get("from") else to_dt - DEFAULT_RANGE
    if from_dt >= to_dt:
        raise BadRequest("from은 to보다 앞이어야 합니다.")
    if to_dt - from_dt > MAX_RANGE:
        raise BadRequest("한 번에 최대 7일까지만 조회할 수 있습니다.")

    try:
        limit = int(q.get("limit", DEFAULT_LIMIT))
    except ValueError:
        raise BadRequest("limit은 숫자여야 합니다.")
    if not 1 <= limit <= MAX_LIMIT:
        raise BadRequest(f"limit은 1~{MAX_LIMIT} 사이여야 합니다.")

    # sk = "ts#seq" → 'from' 이상, 'to#~' 이하 ('~'는 숫자보다 뒤라 to 시각의 모든 seq 포함)
    kwargs = {
        "KeyConditionExpression": Key("device_id").eq(device_id)
        & Key("sk").between(_iso(from_dt), _iso(to_dt) + "#~"),
        "ScanIndexForward": True,  # 그래프용: 오래된 것부터
        "Limit": limit,
    }
    if q.get("next_token"):
        kwargs["ExclusiveStartKey"] = _decode_token(q["next_token"])

    r = _ddb.Table(TABLES[kind]).query(**kwargs)
    items = r.get("Items", [])
    lek = r.get("LastEvaluatedKey")
    return {
        "device_id": device_id,
        "type": kind,
        "from": _iso(from_dt),
        "to": _iso(to_dt),
        "count": len(items),
        "items": items,
        "next_token": _encode_token(lek) if lek else None,
    }


# ───────── Lambda 진입점 (API Gateway HTTP API, payload v2) ─────────
def handler(event, context):
    t0 = time.time()
    route = event.get("routeKey", "")
    params = event.get("pathParameters") or {}
    q = event.get("queryStringParameters") or {}
    try:
        if route == "GET /devices":
            body = list_devices()
        elif route == "GET /devices/{id}/latest":
            body = latest(params["id"])
        elif route == "GET /devices/{id}/history":
            body = history(params["id"], q)
        else:
            return _resp(404, {"error": "NOT_FOUND", "message": f"없는 경로입니다: {route}"})
        print(json.dumps({"route": route, "ms": round((time.time() - t0) * 1000)}))
        return _resp(200, body)
    except BadRequest as e:
        return _resp(400, {"error": "BAD_REQUEST", "message": str(e)})
    except Exception as e:  # 예상 못 한 오류는 로그에 남기고 500
        print(f"[ERROR] {route} {type(e).__name__}: {e}")
        return _resp(500, {"error": "INTERNAL", "message": "서버 오류"})
