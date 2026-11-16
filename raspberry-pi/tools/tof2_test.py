#!/usr/bin/env python3
"""VL53L0X 2대 동시 측정 테스트.

1번은 기본 I2C 버스(bus 1), 2번은 소프트웨어 I2C 버스(bus 3)에 물린다.
주소가 둘 다 0x29로 같아서 버스를 나누는 방식을 쓴다. XSHUT은 쓰지 않는다.

필요 설정 (/boot/firmware/config.txt):
    dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=23,i2c_gpio_scl=24
"""

import time, board, adafruit_vl53l0x
from adafruit_extended_bus import ExtendedI2C

s1 = adafruit_vl53l0x.VL53L0X(board.I2C())
s2 = adafruit_vl53l0x.VL53L0X(ExtendedI2C(3))

for s in (s1, s2):
    s.measurement_timing_budget = 100000

print("측정 시작. 멈추려면 Ctrl+C.")
while True:
    # 8190 전후의 큰 값은 '측정 범위 밖'이라는 뜻이며 고장이 아니다
    print(f"1번 {s1.range:5d} mm | 2번 {s2.range:5d} mm")
    time.sleep(0.2)
