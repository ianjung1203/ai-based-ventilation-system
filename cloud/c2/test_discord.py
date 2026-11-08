import json
import urllib.request
from pathlib import Path

# 같은 폴더의 .env에서 DISCORD_WEBHOOK_URL 읽기
env = {}
env_path = Path(__file__).parent / ".env"
for line in env_path.read_text(encoding="utf-8-sig").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()

url = env["DISCORD_WEBHOOK_URL"]
body = json.dumps({"content": "✅ [vent_test] 장정훈과 김대원의 찬란한 가을 밤"}).encode("utf-8")

req = urllib.request.Request(
    url,
    data=body,
    method="POST",
    headers={
        "Content-Type": "application/json",
        "User-Agent": "vent-aiot-test/1.0",
    },
)
with urllib.request.urlopen(req, timeout=10) as res:
    print("상태 코드:", res.status)