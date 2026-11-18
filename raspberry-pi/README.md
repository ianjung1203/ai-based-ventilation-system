# AirTiming 라즈베리파이 (센서 노드)

AI 기반 환기 추천 시스템의 하드웨어 파트입니다.
라즈베리파이 4에 센서 4개와 LED를 연결해 실내 공기질과 출입을 측정하고,
CO₂ 농도에 따라 창문 열림을 LED로 표시합니다. (실제 창문 모터는 범위 밖이라 LED로 대체)

## 현재 상태 (2026-11-18)

| 항목 | 상태 |
| --- | --- |
| SCD41 (CO₂·온도·습도) | 동작 확인 |
| PMS5003 (PM1.0 / PM2.5 / PM10) | 동작 확인 |
| VL53L0X ×2 (출입 감지) | 동작 확인, 아크릴 상자에서 판정 검증 중 |
| LED (창문 개폐 표시) | 코드 작성 완료 |
| 통합 수집 + 로컬 저장 (SQLite) | 완료 |
| AWS IoT Core 연결 (`vent-01`) | 확인 완료 — 상태 보고(heartbeat), 대시보드 수동 명령 수신·응답 |
| 센서값 주기 전송 (telemetry) | 예정 — 서버 형식(SAD 4.2)으로 10초마다, 끊기면 재전송 |
| 외부 공기질·기온, AI 모델 연결 | 예정 |

## 구성

| 부품 | 연결 | 역할 |
| --- | --- | --- |
| Raspberry Pi 4 (4GB) | 호스트명 `claudeaiot` | 수집·판정·저장 |
| SCD41 | I²C bus 1, 주소 `0x62` | CO₂, 온도, 습도 |
| PMS5003 | UART `/dev/serial0` | 미세먼지 |
| VL53L0X 1번 (바깥쪽) | I²C bus 1, 주소 `0x29` | 출입 감지 |
| VL53L0X 2번 (안쪽) | I²C bus 3 (GPIO23/24), 주소 `0x29` | 출입 감지 |
| LED + 저항 220~330Ω | GPIO18 | 창문 열림 표시 |
| AWS IoT Core (ap-southeast-2) | MQTT over TLS, 포트 8883 (막히면 443) | 서버 (사물 이름 `vent-01`) |

VL53L0X 2대는 주소가 같아서 소프트웨어 I²C 버스(bus 3)를 하나 더 만들어 분리했습니다.
자세한 배선은 [docs/SETUP.md](docs/SETUP.md#4-배선)에 있습니다.

## 폴더 구조

이 폴더는 라즈베리파이의 `~/airtiming` 폴더와 같은 구조입니다.

```
raspberry-pi/
├── collector.py                  통합 수집 스크립트 (센서 4종 + 출입 감지 + LED)
├── airtiming-collector.service   부팅 시 자동 실행 설정 (systemd)
├── requirements.txt              파이썬 라이브러리 목록
├── tools/
│   ├── scd41_test.py             SCD41 단독 테스트
│   ├── pms_test.py               PMS5003 단독 테스트
│   ├── tof2_test.py              VL53L0X 2대 동시 테스트
│   ├── led_test.py               LED 배선 확인
│   ├── calib.py                  출입 감지 기준 거리 측정
│   ├── diag.py                   출입 감지 진단 (한쪽만 반응할 때)
│   └── cloud_test.py             서버(AWS IoT Core) 연결 테스트
├── config/
│   └── boot-config.txt           /boot/firmware/config.txt에 추가할 설정
└── docs/
    ├── SETUP.md                  SD카드 굽기부터 서버 연결 확인까지 전체 절차
    └── TROUBLESHOOTING.md        겪었던 문제와 해결법
```

## 빠른 시작

처음부터 세팅하려면 [docs/SETUP.md](docs/SETUP.md)를 따라가세요. 이미 세팅된 파이라면:

```bash
source ~/venv/bin/activate
python3 ~/airtiming/collector.py
```

시작 후 5초 동안은 거리센서 앞을 비워 두세요. 빈 상태의 거리를 재서 출입 판정 기준을 잡습니다.

## 동작 방식

두 가지 리듬이 동시에 돌아갑니다.

| 루프 | 주기 | 하는 일 |
| --- | --- | --- |
| 빠른 루프 (메인 스레드) | 0.05초 | VL53L0X 2대로 출입 판정 |
| 느린 루프 (별도 스레드) | 10초 | SCD41·PMS5003 측정, 창문(LED) 판단, DB 저장 |

### 창문(LED) 제어

| 조건 | 동작 |
| --- | --- |
| CO₂ ≥ 1500 ppm | 창문 열림 → LED 켜짐 |
| CO₂ < 1000 ppm | 창문 닫힘 → LED 꺼짐 |
| 그 사이 | 직전 상태 유지 |

닫힘 기준을 따로 둔 이유: 열림·닫힘 기준이 같으면 1500 근처에서 값이 오르내릴 때마다
창문이 열렸다 닫혔다를 반복합니다. 기준값은 `collector.py` 위쪽 `CO2_OPEN_PPM`, `CO2_CLOSE_PPM`에서 바꿀 수 있습니다.

### 출입 감지

두 센서를 입구에 나란히 두고 맞은편을 겨눕니다. 손이나 사람이 지나가면 거리가 짧아지는데,
**어느 센서가 먼저 가려졌는지**로 방향을 판정합니다.

```
1번(바깥) 먼저 → 2번(안쪽)  =  들어옴
2번(안쪽) 먼저 → 1번(바깥)  =  나감
```

- 시작할 때 빈 상태 거리를 재고, 그 70% 아래로 내려가면 "가려짐"으로 봅니다.
- 양쪽이 모두 반응해야 통과로 인정합니다. 한쪽만 가렸다 치우면 무시합니다.
- 들어옴/나감을 누적해 현재 재실 인원(`occupancy`)을 추정합니다.

## 서버 연결 (AWS IoT Core)

서버(대원)와 대시보드(정훈)는 SAD 4.2의 MQTT 규약을 따릅니다. 파이는 AWS IoT 사물 `vent-01`로 접속합니다.

| 토픽 | 방향 | 내용 |
| --- | --- | --- |
| `vent/vent-01/heartbeat` | 파이 → 서버 | 상태 보고(규약은 5분마다, 지금은 테스트 때 1회). 대시보드 온라인 표시 |
| `vent/vent-01/telemetry` | 파이 → 서버 | 10초마다 센서값 (`co2_ppm`, `pm25_ugm3`, `temp_c`, `humidity_pct`, `occupancy`, 외부값) — 다음 단계에서 구현 |
| `vent/vent-01/cmd` | 서버 → 파이 | 대시보드 수동 열기/닫기 (`cmd_id`, `action`, `duration_sec`, `issued_ts`) |
| `vent/vent-01/actuator` | 파이 → 서버 | 명령 처리 결과 (`state`, `trigger`, `cmd_id`, `result`) |

모든 메시지에는 공통으로 `schema_version`(1), `ts`(UTC), `msg_id`(`vent-01-<seq>`), `seq`, `run_id`가 붙습니다.
`seq`는 껐다 켜도 이어지도록 파이의 `~/airtiming/.vent_seq`에 저장합니다.
명령은 발행 후 30초가 지났으면 `EXPIRED`, 이미 처리한 `cmd_id`면 `DUPLICATE`로 응답합니다.

### 인증서

대원에게 받은 `vent-01` 인증서 3개는 **파이의 `~/airtiming/certs/`에만** 둡니다. 저장소에는 절대 넣지 않습니다(`.gitignore`에 등록).

```
AmazonRootCA1.pem
xxxx-certificate.pem.crt
xxxx-private.pem.key      <- 비밀번호와 같다. 유출되면 대원이 AWS에서 비활성화 후 재발급
```

### 연결 확인 결과 (2026-11-18)

`tools/cloud_test.py`로 실제 서버에 접속해 확인했습니다.

- 파이 → 서버: heartbeat 전송, 대시보드에 온라인 표시
- 서버 → 파이: 대시보드 수동 열기 명령이 **0.5초** 만에 도착(SAD 목표 3초), `actuator`로 결과 응답
- 대시보드 측정값 카드는 `telemetry`만 읽습니다. 센서값 주기 전송은 다음 단계입니다.

## 데이터 형식 (로컬 DB)

모든 데이터는 파이의 `~/airtiming/readings.db` (SQLite)에 저장됩니다.
서버로 보낼 때는 위 표의 SAD 4.2 이름(`co2` → `co2_ppm` 등)으로 바꿔서 보냅니다.
**시각은 전부 UTC**이며 ISO 8601 형식입니다. 예: `2026-11-16T05:12:30.123Z`
센서가 실패한 필드는 `null`로 들어갑니다.

### `readings` — 10초마다 1행

| 컬럼 | 단위 | 설명 |
| --- | --- | --- |
| `device_id` | | 기기 구분 (`pi01`) |
| `ts` | UTC | 측정 시각 |
| `co2` | ppm | SCD41 |
| `temp` | °C | SCD41 |
| `rh` | % | SCD41 상대습도 |
| `pm1`, `pm25`, `pm10` | µg/m³ | PMS5003 대기환경 기준값 |
| `occupancy` | 명 | 출입 이벤트로 추정한 현재 재실 인원 |
| `window_open` | 0 / 1 | 창문(LED) 상태 |
| `synced` | 0 / 1 | 클라우드 전송 여부 (전송 기능 추가 시 사용) |

예시:

```json
{"device_id": "pi01", "ts": "2026-11-16T05:12:30.123Z", "co2": 712, "temp": 23.4, "rh": 41.2,
 "pm1": 5, "pm25": 13, "pm10": 14, "occupancy": 1, "window_open": 0}
```

### `events` — 통과할 때마다 1행

| 컬럼 | 설명 |
| --- | --- |
| `ts` | 통과가 끝난 시각 (UTC) |
| `direction` | `in` / `out` / `unknown` |
| `duration_ms` | 가려져 있던 시간 |
| `occupancy` | 이 이벤트 직후 재실 인원 |

### `window_events` — 창문이 열리거나 닫힐 때마다 1행

| 컬럼 | 설명 |
| --- | --- |
| `ts` | 바뀐 시각 (UTC) |
| `action` | `open` / `close` |
| `co2` | 그때의 CO₂ 농도 (ppm) |

## 다음 할 일

- [ ] 아크릴 상자에서 출입 감지 정확도 검증 (`tools/calib.py`, `tools/diag.py`)
- [ ] 상자 누기율(빈 상자에서 CO₂ 자연 감소 속도) 측정
- [x] 서버 연결 확인 (heartbeat, 대시보드 수동 명령)
- [ ] 센서값을 서버 형식으로 10초마다 전송, 끊기면 쌓아뒀다가 재전송
- [ ] 외부 공기질(에어코리아)·외부 기온(기상청) 수집
- [ ] AI 모델 연결 (CO₂ 예측, 환기 권고 → LED)
- [ ] 네트워크 끊김 → 복구 시 누락 없이 올라가는지 테스트

## 참고

- 설치 절차: [docs/SETUP.md](docs/SETUP.md)
- 문제 해결: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md)
