# 문제 해결

프로젝트를 진행하며 실제로 겪은 문제들입니다. 같은 증상이 나오면 여기부터 보세요.

## 접속

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| Imager에 학교 와이파이를 넣었는데 접속 안 됨 | 학교 와이파이는 학번 로그인 방식이라 파이가 붙지 못함 | 핫스팟 또는 랜선 직결 |
| `ssh: Could not resolve hostname claudeaiot.local` | 노트북과 파이가 다른 네트워크에 있거나, 이름 찾기가 막힘 | 같은 네트워크인지 확인 후 `arp -a`로 IP를 찾아 IP로 접속 |
| `Connection refused` | 파이는 켜졌지만 SSH가 꺼져 있거나 아직 부팅 중 | 2~3분 대기. 계속되면 Imager에서 SSH 켜고 다시 굽기, 또는 모니터 연결 후 `sudo systemctl enable --now ssh` |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | SD카드를 새로 구워 파이의 지문이 바뀜 (정상) | `ssh-keygen -R claudeaiot.local` |
| `scp: stat local "collector.py": No such file` | `scp`를 파이 창에서 침 | **PC의 PowerShell 창**에서 실행 |
| 아이폰 핫스팟에 파이가 안 보임 | 아이폰은 연결 기기 목록을 안 보여줌 | 핫스팟 화면 상단의 연결 수 확인, 또는 랜선 사용 |
| 첫 부팅 때 초록불이 깜빡이지 않음 | 전원을 먼저 넣고 SD카드를 나중에 꽂음 | 전원 뽑기 → SD카드 꽂기 → 전원 넣기 순서 |
| 부팅 후 초록불이 꺼짐 | 정상. 초록불은 SD카드를 읽을 때만 켜짐 | 빨간불이 켜져 있으면 문제없음 |

## 설치

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `pip`가 `Temporary failure in name resolution` | 파이가 인터넷에 못 나감 | 랜선이면 노트북 인터넷 공유 켜기 |
| `externally-managed-environment` | 가상환경 없이 `pip` 사용 | `source ~/venv/bin/activate` 후 설치 |
| `No module named 'board'` | 가상환경이 꺼져 있음 | 맨 앞에 `(venv)`가 보이는지 확인 |
| 여러 줄 명령을 붙여넣었더니 섞임 (`cd ~/airtimingmkdir`) | 붙여넣기 중 줄이 합쳐짐 | 한 줄씩 복사해서 실행 |

## 센서

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| SCD41이 `i2cdetect`에 안 잡힘 | 배선 또는 납땜 접촉 | 행 번호 재확인, 납이 패드에 퍼지도록 2초 재가열 |
| VL53L0X가 `29`로 잡히는데 읽기만 `OSError: [Errno 5]` | 전원 부족 | **VCC를 5V로 옮기면 해결** |
| 같은 오류가 다시 남 | **점퍼선 불량.** 여러 번 뽑았다 꽂으면 끝이 헐거워짐 | 새 선으로 교체 (실제 원인이었음) |
| VL53L0X 2대를 XSHUT으로 나누려 했으나 계속 실패 | XSHUT 핀 접촉 불량 | XSHUT 포기, **i2c-gpio로 버스 분리** |
| `busio.I2C(board.D24, board.D23)` → `No Hardware I2C` | 소프트웨어 버스는 busio로 못 엶 | `ExtendedI2C(3)` 사용 |
| `i2cdetect -y 3`이 모든 주소로 가득 참 | 3번 버스에 선이 안 꽂혔거나 GND에 닿음 | GPIO23/24 배선 확인 |
| VL53L0X가 계속 8190 | 앞에 아무것도 없거나 투명 아크릴이라 반사가 안 됨 | 맞은편에 흰 종이 부착 |
| 출입 감지가 한쪽만 반응 | 시작할 때 한 센서의 기준 거리가 8190으로 잡힘 | `collector.py` v3에서 수정됨. `tools/diag.py`로 기준값 확인 |
| PMS5003 값이 전부 0이거나 안 나옴 | 워밍업 부족 또는 TX/RX를 같은 이름끼리 연결 | 30초 대기, 센서 TXD → 파이 `RXD0` |
| PMS5003 체크섬 불일치 반복 | 파이4 기본 시리얼 불안정 | `config.txt`에 `dtoverlay=disable-bt` |
| LED가 안 켜짐 | LED 방향이 반대거나 두 다리가 같은 행 | LED 뒤집기, 다리를 서로 다른 행에 |

## 서버 연결 (AWS IoT Core)

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `can't open file '.../cloud_test.py'` | 파일을 파이로 안 옮김 | PC 창에서 `scp`로 `~/airtiming/tools/`에 보내기 |
| `... 파일을 찾지 못했습니다` (인증서) | `~/airtiming/certs/`에 파일이 없거나 개인 키 끝에 `.txt`가 붙음 | `ls ~/airtiming/certs`, 이름 끝의 `.txt` 떼기 |
| `TLS 오류` | 파이 시계가 틀림, 또는 인증서·키 짝이 안 맞음 | `timedatectl`에서 `synchronized: yes` 확인 |
| `8883 포트가 막혔을 수 있습니다` | 학교망 포트 차단 | `--port 443` |
| 접속 직후 끊김 | 같은 `vent-01`로 다른 프로그램(`fake_pi.py` 등)이 접속 중 | 다른 쪽을 끄고 다시 |
| 발행 후 끊김 | 정책이 `vent/vent-01/*` 발행을 허용하지 않음 | 대원에게 정책 확인 요청 |
| 명령 수신: 없음 | 기다리는 동안 대시보드 버튼을 안 누름 | `--wait 600`으로 시간을 늘리고 수동 열기 누르기 |
| 대시보드에 온라인인데 측정값이 안 나옴 | 측정값 카드는 `telemetry`만 읽는데, 아직 heartbeat만 보냄 (서버·대시보드 문제 아님) | `--telemetry`로 1건 보내 확인. 주기 전송은 다음 단계 |
