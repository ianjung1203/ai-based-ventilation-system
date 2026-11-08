"""노트북에서 vent-notify를 실행해 보는 파일 (AWS에 올리지 않음)"""
import os
from pathlib import Path

# cloud/c2/.env 에서 DISCORD_WEBHOOK_URL 읽기
env_path = Path(__file__).parent.parent / ".env"
for line in env_path.read_text(encoding="utf-8-sig").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())

os.environ.setdefault("SNS_TOPIC_ARN", "arn:aws:sns:ap-southeast-2:272734468248:vent-alerts")

from app import lambda_handler  # 환경변수를 넣은 '뒤에' 불러와야 함

event = {"rec_id": "test-rec-001", "ts": "2026-11-08T11:30:00Z"}
print("1회차:", lambda_handler(event, None))
print("2회차:", lambda_handler(event, None))  # 같은 rec_id -> skipped 여야 함