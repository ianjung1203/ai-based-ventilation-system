#!/usr/bin/env python3
"""SCD41 단독 테스트 — CO2, 온도, 습도를 5초마다 출력."""

import time, board, adafruit_scd4x

scd = adafruit_scd4x.SCD4X(board.I2C())
print("센서 일련번호:", [hex(i) for i in scd.serial_number])
scd.start_periodic_measurement()
print("측정 시작. 첫 값까지 5초 정도 걸립니다. 멈추려면 Ctrl+C.")

while True:
    if scd.data_ready:
        print(f"CO2 {scd.CO2} ppm | 온도 {scd.temperature:.1f} C | 습도 {scd.relative_humidity:.1f} %")
    time.sleep(1)
