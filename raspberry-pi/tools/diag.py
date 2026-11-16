#!/usr/bin/env python3
"""출입 감지 진단 도구.

두 센서의 기준 거리와 실시간 값, 가려짐 판정을 나란히 보여준다.
어느 센서가 왜 반응하지 않는지 눈으로 확인하는 용도.
"""

import time, board, adafruit_vl53l0x
from adafruit_extended_bus import ExtendedI2C

BLOCK_RATIO = 0.70
OUT_OF_RANGE = 8000      # 이 이상은 '앞에 아무것도 없음'

s1 = adafruit_vl53l0x.VL53L0X(board.I2C())
s2 = adafruit_vl53l0x.VL53L0X(ExtendedI2C(3))
for s in (s1, s2):
    s.measurement_timing_budget = 33000

print("기준 거리 측정 10초. 센서 앞을 비워 두세요.")
a, b = [], []
t0 = time.time()
while time.time() - t0 < 10:
    a.append(s1.range)
    b.append(s2.range)
    time.sleep(0.05)

b1 = sorted(a)[len(a) // 2]
b2 = sorted(b)[len(b) // 2]
oor1 = sum(1 for v in a if v >= OUT_OF_RANGE)
oor2 = sum(1 for v in b if v >= OUT_OF_RANGE)

print()
print(f"1번: 기준 {b1:5d}mm | 범위 {min(a):5d}~{max(a):5d} | "
      f"측정실패 {oor1}/{len(a)}회 | 가려짐 기준 {int(b1*BLOCK_RATIO)}mm 미만")
print(f"2번: 기준 {b2:5d}mm | 범위 {min(b):5d}~{max(b):5d} | "
      f"측정실패 {oor2}/{len(b)}회 | 가려짐 기준 {int(b2*BLOCK_RATIO)}mm 미만")

for n, base, oor in ((1, b1, oor1), (2, b2, oor2)):
    if base >= OUT_OF_RANGE:
        print(f"  [문제] {n}번 기준이 측정 범위 밖입니다. "
              f"맞은편이 너무 멀거나 반사가 안 됩니다. 흰 종이를 대보세요.")
    elif oor > len(a) * 0.2:
        print(f"  [주의] {n}번이 측정에 자주 실패합니다. 고정 상태를 확인하세요.")

print("\n손을 통과시켜 보세요. 멈추려면 Ctrl+C.")
print("  #. = 1번만 가려짐 / ## = 둘 다 / .# = 2번만")
print("  #. -> ## -> .# 순서면 들어옴, 반대면 나감\n")

th1, th2 = b1 * BLOCK_RATIO, b2 * BLOCK_RATIO
while True:
    d1, d2 = s1.range, s2.range
    k1 = "#" if 0 < d1 < th1 else "."
    k2 = "#" if 0 < d2 < th2 else "."
    print(f"{k1}{k2}  1번 {d1:5d} | 2번 {d2:5d}")
    time.sleep(0.05)
