"""vent-command-api (C2 정훈) - 원격 명령·설정 API

POST /devices/{id}/actuator   {action: OPEN|CLOSE, duration_sec}  -> vent/{id}/cmd 게시, cmd_id 반환
GET  /commands/{cmd_id}                                           -> 파이 응답(actuator) 확인
PUT  /devices/{id}/settings   {co2_threshold_ppm, target_ppm, ...} (보낸 항목만 변경)
PUT  /devices/{id}/scenario   {pm25, temp, occupancy}  ({} 또는 null 이면 해제)
PUT  /devices/{id}/occupancy  {occupancy_set: 숫자 | null}
PUT  /devices/{id}/run        {action: START|STOP, note}

설정류는 모두 Shadow(클래식) desired 를 바꾼다.
안전 한도(600초, 4,500ppm, 명령 30초)는 파이에 고정이라 여기서 바꿀 수 없다.
"""
import base64
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

CMD_VALID_SEC = 30
DEVICE_RE = re.compile(r"^vent-[A-Za-z0-9_-]{1,40}$")  # 토픽에 / + # 가 끼지 않게
UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")

iot = boto3.client("iot-data", endpoint_url=os.environ["IOT_DATA_ENDPOINT"])
ddb = boto3.resource("dynamodb")
actuator_table = ddb.Table(os.environ["ACTUATOR_TABLE"])
runs_table = ddb.Table(os.environ["RUNS_TABLE"])

# Shadow 설정값 기본값(SAD 4.2)과 허용 범위
DEFAULTS = {
    "co2_threshold_ppm": 1000,
    "target_ppm": 800,
    "co2_override_ppm": 2000,
    "auto_actuate": True,
    "ach_per_h": 30,
    "g_ppm_per_min": 0,
}
RULES = {  # 이름: (종류, 최소, 최대)
    "co2_threshold_ppm": ("int", 400, 4000),
    "target_ppm": ("int", 400, 4000),
    "co2_override_ppm": ("int", 400, 4000),
    "ach_per_h": ("num", 0.1, 200),
    "g_ppm_per_min": ("num", 0, 1000),
    "auto_actuate": ("bool", None, None),
}


class BadRequest(Exception):
    pass


class Conflict(Exception):
    pass


# ───────── 진입점 ─────────
def handler(event, context):
    route = event.get("routeKey", "")
    params = event.get("pathParameters") or {}
    try:
        if route == "GET /commands/{cmd_id}":
            return get_command(params.get("cmd_id", ""))

        device_id = params.get("id", "")
        if not DEVICE_RE.match(device_id):
            raise BadRequest("device id 형식이 잘못됐어요 (예: vent-01)")
        body = read_body(event)
        if route == "GET /devices/{id}/settings":
            return get_settings(device_id)

        if route == "POST /devices/{id}/actuator":
            return post_actuator(device_id, body)
        if route == "PUT /devices/{id}/settings":
            return put_settings(device_id, body)
        if route == "PUT /devices/{id}/scenario":
            return put_scenario(device_id, body)
        if route == "PUT /devices/{id}/occupancy":
            return put_occupancy(device_id, body)
        if route == "PUT /devices/{id}/run":
            return put_run(device_id, body)
        return resp(404, {"error": "not_found", "route": route})
    except BadRequest as e:
        return resp(400, {"error": "bad_request", "message": str(e)})
    except Conflict as e:
        return resp(409, {"error": "conflict", "message": str(e)})
    except Exception as e:  # 예상 못 한 오류는 로그에 남기고 500
        log("error", route=route, error=repr(e))
        return resp(500, {"error": "internal_error"})


# ───────── 수동 명령 ─────────
def post_actuator(device_id, body):
    body = body or {}
    action = str(body.get("action", "")).upper()
    if action not in ("OPEN", "CLOSE"):
        raise BadRequest("action 은 OPEN 또는 CLOSE")
    if action == "OPEN":
        dur = body.get("duration_sec")
        if not is_int(dur) or not 10 <= dur <= 600:
            raise BadRequest("OPEN 은 duration_sec 10~600 정수가 필요해요")
    else:
        dur = 0

    now = now_utc()
    issued = iso(now)
    cmd = {
        "schema_version": 1,
        "ts": issued,
        "cmd_id": str(uuid.uuid4()),
        "action": action,
        "duration_sec": dur,
        "issued_ts": issued,
    }
    iot.publish(topic=f"vent/{device_id}/cmd", qos=1, payload=json.dumps(cmd).encode("utf-8"))
    log("cmd_published", device_id=device_id, **cmd)
    return resp(202, {
        "cmd_id": cmd["cmd_id"],
        "issued_ts": issued,
        "expires_ts": iso(now + timedelta(seconds=CMD_VALID_SEC)),
    })


def get_command(cmd_id):
    if not UUID_RE.match(cmd_id):
        raise BadRequest("cmd_id 형식이 잘못됐어요")
    items = actuator_table.query(
        IndexName="cmd_id-index",
        KeyConditionExpression=Key("cmd_id").eq(cmd_id),
        Limit=1,
    ).get("Items", [])
    if not items:
        # 30초가 지나도 PENDING 이면 화면에서 "응답 없음" 으로 표시
        return resp(200, {"cmd_id": cmd_id, "status": "PENDING", "server_ts": iso(now_utc())})
    it = items[0]
    return resp(200, {
        "cmd_id": cmd_id,
        "status": "DONE",
        "device_id": it.get("device_id"),
        "result": it.get("result"),
        "state": it.get("state"),
        "trigger": it.get("trigger"),
        "ts": it.get("ts"),
        "server_ts": iso(now_utc()),
    })


# ───────── 설정 (Shadow desired) ─────────
def put_settings(device_id, body):
    if not isinstance(body, dict) or not body:
        raise BadRequest("바꿀 설정을 JSON 으로 보내 주세요")
    unknown = sorted(set(body) - set(RULES))
    if unknown:
        raise BadRequest(f"바꿀 수 없는 항목: {unknown} (가능: {sorted(RULES)}; 안전 한도는 파이에 고정)")
    for name, value in body.items():
        check_value(name, value)

    merged = {**DEFAULTS, **current_settings(device_id), **body}
    if not merged["target_ppm"] < merged["co2_threshold_ppm"] < merged["co2_override_ppm"]:
        raise BadRequest(
            "target_ppm < co2_threshold_ppm < co2_override_ppm 이어야 해요 "
            f"(적용하면 {merged['target_ppm']} / {merged['co2_threshold_ppm']} / {merged['co2_override_ppm']})"
        )
    version = update_desired(device_id, body)
    return resp(200, {"device_id": device_id, "desired": body, "shadow_version": version})


def put_scenario(device_id, body):
    if not body:  # null 또는 {} -> 시나리오 해제
        version = update_desired(device_id, {"scenario": None})
        return resp(200, {"device_id": device_id, "scenario": None, "shadow_version": version})
    if not isinstance(body, dict) or set(body) != {"pm25", "temp", "occupancy"}:
        raise BadRequest("scenario 는 {pm25, temp, occupancy} 세 값을 모두 보내 주세요 (해제는 {})")
    if not is_num(body["pm25"]) or not 0 <= body["pm25"] <= 1000:
        raise BadRequest("pm25 는 0~1000")
    if not is_num(body["temp"]) or not -20 <= body["temp"] <= 60:
        raise BadRequest("temp 는 -20~60")
    if not is_int(body["occupancy"]) or not 0 <= body["occupancy"] <= 50:
        raise BadRequest("occupancy 는 0~50 정수")
    version = update_desired(device_id, {"scenario": body})
    return resp(200, {"device_id": device_id, "scenario": body, "shadow_version": version})


def put_occupancy(device_id, body):
    if not isinstance(body, dict) or "occupancy_set" not in body:
        raise BadRequest("{\"occupancy_set\": 숫자 또는 null} 형식으로 보내 주세요")
    value = body["occupancy_set"]
    if value is not None and (not is_int(value) or not 0 <= value <= 50):
        raise BadRequest("occupancy_set 은 0~50 정수 또는 null")
    version = update_desired(device_id, {"occupancy_set": value})
    return resp(200, {"device_id": device_id, "occupancy_set": value, "shadow_version": version})


def put_run(device_id, body):
    body = body or {}
    action = str(body.get("action", "")).upper()
    note = str(body.get("note", ""))[:200]
    shadow_state = get_shadow_state(device_id)
    current = shadow_state.get("run_id") or "NONE"
    now = iso(now_utc())

    if action == "START":
        if current != "NONE":
            raise Conflict(f"이미 진행 중인 실험이 있어요: {current}")
        run_id = "run-" + now_utc().strftime("%Y%m%dT%H%M%SZ")
        runs_table.put_item(Item={
            "device_id": device_id,
            "run_id": run_id,
            "status": "RUNNING",
            "started_ts": now,
            "note": note,
            "scenario_json": json.dumps(shadow_state.get("scenario"), ensure_ascii=False),
        })
        version = update_desired(device_id, {"run_id": run_id})
        return resp(200, {"device_id": device_id, "run_id": run_id, "status": "RUNNING", "shadow_version": version})

    if action == "STOP":
        if current == "NONE":
            raise Conflict("진행 중인 실험이 없어요")
        version = update_desired(device_id, {"run_id": "NONE"})
        runs_table.update_item(
            Key={"device_id": device_id, "run_id": current},
            UpdateExpression="SET #s = :done, ended_ts = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":done": "DONE", ":e": now},
        )
        return resp(200, {"device_id": device_id, "run_id": current, "status": "DONE", "shadow_version": version})

    raise BadRequest("action 은 START 또는 STOP")

def get_settings(device_id):
    """대시보드 설정 화면용: desired(요청), reported(파이 보고), effective(앞으로 적용될 값)"""
    try:
        doc = json.loads(iot.get_thing_shadow(thingName=device_id)["payload"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        doc = {}
    state = doc.get("state", {})
    desired = state.get("desired") or {}
    reported = state.get("reported") or {}
    effective = {**DEFAULTS, "run_id": "NONE", "scenario": None, "occupancy_set": None, **reported, **desired}
    for d in (desired, reported, effective):
        d.pop("welcome", None)  # 콘솔이 넣은 기본값 제외
    return resp(200, {
        "device_id": device_id,
        "desired": desired,
        "reported": reported,
        "effective": effective,
        "shadow_version": doc.get("version"),
    })

# ───────── Shadow 도구 ─────────
def get_shadow_state(device_id):
    """reported 위에 desired 를 덮은 '앞으로 적용될 값'"""
    try:
        resp_ = iot.get_thing_shadow(thingName=device_id)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return {}
        raise
    state = json.loads(resp_["payload"].read()).get("state", {})
    return {**(state.get("reported") or {}), **(state.get("desired") or {})}


def current_settings(device_id):
    state = get_shadow_state(device_id)
    return {k: v for k, v in state.items() if k in RULES}


def update_desired(device_id, desired):
    payload = json.dumps({"state": {"desired": desired}}).encode("utf-8")
    resp_ = iot.update_thing_shadow(thingName=device_id, payload=payload)
    version = json.loads(resp_["payload"].read()).get("version")
    log("shadow_desired_updated", device_id=device_id, desired=desired, version=version)
    return version


def check_value(name, value):
    kind, lo, hi = RULES[name]
    if kind == "bool":
        if not isinstance(value, bool):
            raise BadRequest(f"{name} 는 true/false")
        return
    ok = is_int(value) if kind == "int" else is_num(value)
    if not ok or not lo <= value <= hi:
        raise BadRequest(f"{name} 는 {lo}~{hi} {'정수' if kind == 'int' else '숫자'}")


# ───────── 작은 도구들 ─────────
def read_body(event):
    raw = event.get("body")
    if raw is None or raw == "":
        return None
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        return json.loads(raw)
    except ValueError:
        raise BadRequest("본문이 올바른 JSON 이 아니에요")


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_default(o):
    if isinstance(o, Decimal):
        return int(o) if o == int(o) else float(o)
    return str(o)


def resp(code, obj):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json; charset=utf-8"},
        "body": json.dumps(obj, ensure_ascii=False, default=_json_default),
    }


def log(msg, **kw):
    print(json.dumps({"msg": msg, **kw}, ensure_ascii=False, default=_json_default))