# 라즈베리파이 설치 절차

SD카드를 새로 구울 때 이 문서를 순서대로 따라가면 지금 구성으로 돌아올 수 있습니다.
명령어 앞에 **[PC]**가 붙은 건 노트북의 PowerShell에서, **[파이]**는 SSH로 접속한 창에서 칩니다.

---

## 0. SD카드 굽기

Raspberry Pi Imager에서 "설정 편집"을 반드시 누르고 아래를 입력합니다.
건너뛰면 모니터 없이 접속할 수 없습니다.

| 항목 | 값 |
| --- | --- |
| 장치 | Raspberry Pi 4 |
| OS | Raspberry Pi OS (64-bit) — Lite 아님 |
| 호스트 이름 | `claudeaiot` |
| 사용자 이름 | `yuno` |
| 비밀번호 | 팀에서 정한 것 (메모해 둘 것) |
| Wi-Fi | 핸드폰 핫스팟 이름·비밀번호, 국가 `KR` (랜선만 쓸 거면 비워도 됨) |
| 로컬화 | 시간대 `Asia/Seoul`, 키보드 `us` |
| 원격 접근 | **SSH 사용 + 비밀번호 인증** |
| 라즈베리 파이 커넥트 | 끔 |

학교 와이파이는 학번 로그인 방식이라 이 화면에서 설정할 수 없습니다.

---

## 1. 접속

### 권장: 랜선 직결 + 인터넷 공유

핫스팟보다 안정적이고 데이터도 들지 않습니다.

1. CAT.6 랜선으로 노트북과 파이를 직접 연결
2. **[PC]** `Win + R` → `ncpa.cpl`
3. 인터넷이 들어오는 어댑터(Wi-Fi) 우클릭 → 속성 → **공유** 탭
4. "다른 네트워크 사용자가 이 컴퓨터의 인터넷 연결을 통해 연결할 수 있도록 허용" 체크 → 목록에서 **이더넷** 선택

이러면 노트북이 학교 와이파이에 붙어 있어도 파이가 노트북을 거쳐 인터넷을 씁니다.

### 대안: 핸드폰 핫스팟

노트북과 파이를 **둘 다** 같은 핫스팟에 연결합니다.
아이폰은 설정 → 개인용 핫스팟에서 "최대 호환성"을 켜고, 핫스팟 이름에 한글이 없어야 합니다.

### SSH 접속

```
[PC] ssh yuno@claudeaiot.local
```

이름으로 못 찾으면 IP로 접속합니다. 랜선은 보통 `192.168.137.x`, 아이폰 핫스팟은 `172.20.10.x`입니다.

```
[PC] arp -a
[PC] ssh yuno@192.168.137.2
```

SD카드를 새로 구운 뒤 `REMOTE HOST IDENTIFICATION HAS CHANGED` 경고가 뜨면 정상입니다. 옛 기록만 지우세요.

```
[PC] ssh-keygen -R claudeaiot.local
```

---

## 2. 기본 설정

```
[파이] sudo apt update && sudo apt full-upgrade -y
[파이] sudo apt install -y i2c-tools sqlite3
[파이] sudo raspi-config
```

`3 Interface Options` → `I5 I2C` → **Yes** 만 합니다.
시리얼(UART)은 다음 단계에서 설정 파일로 켜므로 raspi-config의 Serial Port는 건드리지 않습니다.

---

## 3. config.txt

```
[파이] sudo nano /boot/firmware/config.txt
```

맨 아래 `[all]` 아래에 다음이 있어야 합니다. ([config/boot-config.txt](../config/boot-config.txt)와 같은 내용)

```
[all]
enable_uart=1
dtoverlay=disable-bt
dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24
```

| 줄 | 이유 |
| --- | --- |
| `enable_uart=1` | PMS5003용 UART 켜기 |
| `disable-bt` | 파이4 기본 시리얼은 속도가 흔들려 PMS5003 데이터가 깨진다. 블루투스가 쓰던 안정적인 UART를 센서에 넘긴다 |
| `i2c-gpio ... bus=3` | VL53L0X 2대가 같은 주소(0x29)라 I²C 버스를 하나 더 만들어 분리한다 |

줄 앞이나 `=` 양옆에 공백이 없어야 합니다.
`Ctrl+O` → 엔터 → `Ctrl+X`로 저장하고 `sudo reboot`.

---

## 4. 배선

**배선은 반드시 전원을 끄고** 합니다.

```
[파이] sudo shutdown -h now
```

초록불이 꺼진 뒤 전원을 뽑습니다. 전원을 그냥 뽑으면 SD카드가 깨질 수 있습니다.

확장보드(GPIO Extension Board)에 **인쇄된 글자**를 기준으로 꽂습니다.

| 부품 | 핀 | 연결 | 주의 |
| --- | --- | --- | --- |
| SCD41 | VCC | `3V3` | 불안정하면 `5V0`로 (모듈이 둘 다 지원) |
| SCD41 | GND / SDA / SCL | `GND` / `SDA1` / `SCL1` | |
| VL53L0X 1번 (바깥) | VCC | **`5V0`** | **3.3V에서는 통신 실패함** |
| VL53L0X 1번 | GND / SDA / SCL | `GND` / `SDA1` / `SCL1` | SCD41과 같은 행, 다른 칸 |
| VL53L0X 2번 (안쪽) | VCC | **`5V0`** (1번과 다른 칸) | |
| VL53L0X 2번 | GND | `GND` (다른 칸) | |
| VL53L0X 2번 | SDA / SCL | **`GPIO23` / `GPIO24`** | 3번 버스 |
| PMS5003 | VCC | `5V0` | 3.3V로는 팬이 안 돈다 |
| PMS5003 | GND | `GND` | |
| PMS5003 | TXD | `RXD0` (GPIO15) | **엇갈려 꽂는다.** 센서 송신 → 파이 수신 |
| LED | | `GPIO18` → 저항 → LED 긴 다리, LED 짧은 다리 → `GND` | 저항 220~330Ω 필수 |

- VL53L0X의 XSHUT 핀은 쓰지 않습니다.
- 5V 자리가 모자라면 점퍼선으로 `5V0` → 브레드보드 빨강 레일을 잇고 거기서 끌어 씁니다.
- 한 구멍에 여러 선을 몰지 말고 칸을 나눠 꽂습니다. 접촉이 나빠지면 전압이 떨어집니다.
- LED는 긴 다리가 +입니다. 반대로 꽂으면 안 켜질 뿐 고장나지는 않습니다.

---

## 5. 파일 옮기기

`scp`는 **PC 창에서** 칩니다. 파이에 접속한 창에서 치면 "파일이 없다"는 오류가 납니다.

이 저장소의 `raspberry-pi` 폴더가 있는 곳에서:

```
[PC] scp -r raspberry-pi yuno@claudeaiot.local:~/
[파이] mkdir -p ~/airtiming
[파이] cp -r ~/raspberry-pi/. ~/airtiming/
```

---

## 6. 파이썬 환경

```
[파이] python3 -m venv ~/venv
[파이] source ~/venv/bin/activate
[파이] pip install -r ~/airtiming/requirements.txt
```

`source ~/venv/bin/activate`는 **터미널을 새로 열 때마다** 다시 칩니다. 맨 앞에 `(venv)`가 보이면 적용된 상태입니다.

`pip`가 `Temporary failure in name resolution`으로 실패하면 파이가 인터넷에 못 나가는 것입니다. 1단계의 인터넷 공유를 확인하세요.

---

## 7. 동작 확인

```
[파이] i2cdetect -y 1        # 29(VL53L0X 1번)와 62(SCD41)
[파이] i2cdetect -y 3        # 29(VL53L0X 2번)
[파이] ls -l /dev/serial0    # ttyAMA0를 가리켜야 함
```

센서별 테스트 (하나씩, `Ctrl+C`로 종료):

| 명령 | 정상이면 |
| --- | --- |
| `python3 ~/airtiming/tools/scd41_test.py` | 실내 400~1200 ppm. 입김 불면 수천까지 올랐다 1~2분에 걸쳐 하강 |
| `python3 ~/airtiming/tools/pms_test.py` | 30초 뒤부터 출력. 실내 PM2.5는 보통 5~30 |
| `python3 ~/airtiming/tools/tof2_test.py` | 1번·2번이 각각 따로 반응. 아무것도 없으면 8190 (정상) |
| `python3 ~/airtiming/tools/led_test.py` | LED가 5번 깜빡임 |
| `python3 ~/airtiming/tools/calib.py` | 손이 지나갈 때 `#.` → `##` → `.#` 순서 표시 |

---

## 8. 실행과 자동 실행 등록

손으로 먼저 돌려 봅니다.

```
[파이] python3 ~/airtiming/collector.py
```

정상 로그:

```
창문(LED) 준비 완료: CO2 1500 ppm 이상 열림 / 1000 ppm 미만 닫힘
VL53L0X 2대 준비 완료
기준 거리 측정 중 (5초). 센서 앞을 비워 두세요.
1번 기준 거리 248mm (241~255) -> 173mm 미만이면 가려짐
출입 감지 시작
ENV {"device_id": "pi01", "co2": 712, ...}
출입: 들어옴 (0.42s) -> 현재 1명
창문 열림 (CO2 1623 ppm >= 1500) -> LED 켜짐
```

잘 되면 부팅할 때 자동으로 돌게 등록합니다.

```
[파이] sudo cp ~/airtiming/airtiming-collector.service /etc/systemd/system/
[파이] sudo systemctl enable --now airtiming-collector
[파이] journalctl -u airtiming-collector -f
```

사용자 이름이 `yuno`가 아니면 `.service` 파일 안의 경로를 바꿔야 합니다.

---

## 9. 데이터 확인

```
[파이] sqlite3 ~/airtiming/readings.db "SELECT * FROM readings ORDER BY id DESC LIMIT 5;"
[파이] sqlite3 ~/airtiming/readings.db "SELECT * FROM events ORDER BY id DESC LIMIT 10;"
[파이] sqlite3 ~/airtiming/readings.db "SELECT * FROM window_events ORDER BY id DESC LIMIT 10;"
```

---

## 센서 메모

- **SCD41**: 측정 주기 5초. 밀폐 상자에서는 자동보정(ASC)을 꺼야 합니다.
  켜두면 "최근 일주일 최저값 = 외기 400ppm"으로 기준을 잘못 잡습니다.
  `collector.py`의 `SEAL_BOX_MODE = True`가 이를 처리합니다.
- **PMS5003**: 전원 후 30초 워밍업 필요. 1000 µg/m³ 부근에서 포화됩니다.
- **VL53L0X**: 8190은 "측정 범위 밖"이지 고장이 아닙니다.
  투명 아크릴은 적외선이 통과해 잘 안 잡히므로 맞은편에 흰 종이를 붙입니다.
- **LED**: 실제로 환기를 하지 않으므로, 밀폐 상자에서 LED가 꺼지는 것까지 보려면 뚜껑을 열어 직접 환기해야 합니다.
