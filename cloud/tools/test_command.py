"""vent-command-api 시험 도구 (노트북에서 실행)

먼저 같은 cmd 창에서 API 주소를 넣는다 (주소는 깃에 올리지 않음):
  set VENT_API_URL=https://xxxx.execute-api.ap-southeast-2.amazonaws.com

사용:
  py -3.12 cloud\\tools\\test_command.py open 30          수동 환기 30초 -> 결과까지 기다림
  py -3.12 cloud\\tools\\test_command.py close
  py -3.12 cloud\\tools\\test_command.py settings co2_threshold_ppm=1100 auto_actuate=true
  py -3.12 cloud\\tools\\test_command.py scenario pm25=35 temp=22 occupancy=2
  py -3.12 cloud\\tools\\test_command.py scenario clear
  py -3.12 cloud\\tools\\test_command.py occupancy 3        (해제: occupancy clear)
  py -3.12 cloud\\tools\\test_command.py run start 첫실험   /  run stop
  py -3.12 cloud\\tools\\test_command.py shadow             Shadow 현재 값 보기 (aws login 권한)
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEVICE = os.environ.get("VENT_DEVICE", "vent-01")
IOT_ENDPOINT = "https://a3kpxm984jauzv-ats.iot.ap-southeast-2.amazonaws.com"


def api():
    url = os.environ.get("VENT_API_URL", "").rstrip("/")
    if not url:
        sys.exit("먼저 set VENT_API_URL=https://... 를 실행해 주세요")
    return url


def call(method, path, body=None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        api() + path, data=data, method=method,
        headers={"Content-Type": "application/json", "User-Agent": "vent-test/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def show(method, path, body=None):
    t0 = time.time()
    status, data = call(method, path, body)
    print(f"{method} {path} {json.dumps(body, ensure_ascii=False) if body is not None else ''}")
    print(f"  -> {status} ({time.time() - t0:.2f}초) {json.dumps(data, ensure_ascii=False)}")
    return status, data


def parse_kv(items):
    out = {}
    for item in items:
        k, v = item.split("=", 1)
        try:
            out[k] = json.loads(v)  # 숫자, true/false, null 은 그 형태로
        except ValueError:
            out[k] = v
    return out


def command(action, duration=None):
    body = {"action": action}
    if duration is not None:
        body["duration_sec"] = duration
    t0 = time.time()
    status, data = show("POST", f"/devices/{DEVICE}/actuator", body)
    if status != 202:
        return
    cmd_id = data["cmd_id"]
    print("  확인 중...")
    while time.time() - t0 < 30:  # SAD: 30초 전에는 '응답 없음' 을 띄우지 않음
        time.sleep(0.5)
        _, r = call("GET", f"/commands/{cmd_id}")
        if r and r.get("status") == "DONE":
            print(f"  결과: {r.get('result')} / 상태 {r.get('state')} ({time.time() - t0:.2f}초)")
            return
    print("  응답 없음 (30초)")


def shadow():
    import boto3
    iot = boto3.client("iot-data", region_name="ap-southeast-2", endpoint_url=IOT_ENDPOINT)
    doc = json.loads(iot.get_thing_shadow(thingName=DEVICE)["payload"].read())
    print(json.dumps(doc.get("state", {}), ensure_ascii=False, indent=2))
    print("version:", doc.get("version"))


def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0].lower(), argv[1:]
    if cmd == "open":
        command("OPEN", int(rest[0]) if rest else 30)
    elif cmd == "close":
        command("CLOSE")
    elif cmd == "settings":
        show("PUT", f"/devices/{DEVICE}/settings", parse_kv(rest))
    elif cmd == "scenario":
        body = {} if rest == ["clear"] else parse_kv(rest)
        show("PUT", f"/devices/{DEVICE}/scenario", body)
    elif cmd == "occupancy":
        value = None if rest == ["clear"] else int(rest[0])
        show("PUT", f"/devices/{DEVICE}/occupancy", {"occupancy_set": value})
    elif cmd == "run":
        body = {"action": rest[0].upper()}
        if len(rest) > 1:
            body["note"] = " ".join(rest[1:])
        show("PUT", f"/devices/{DEVICE}/run", body)
    elif cmd == "shadow":
        shadow()
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])