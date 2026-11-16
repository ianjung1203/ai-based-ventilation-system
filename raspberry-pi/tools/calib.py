#!/usr/bin/env python3
"""출입 감지 기준값 측정 도구.

1) 10초 동안 빈 상태의 거리를 재서 기준값을 잡는다.
2) 그 뒤로는 손이 지나갈 때마다 어느 센서가 가려졌는지 기호로 보여준다.

   #.  = 1번만 가려짐 (바깥쪽)
   ##  = 둘 다 가려짐
   .#  = 2번만 가려짐 (안쪽)

   #. -> ## -> .#  순서면 들어옴, 반대면 나감.
"""

import time, board, adafruit_vl53l0x
from adafruit_extended_bus import ExtendedI2C

s1 = adafruit_vl53l0x.VL53L0X(board.I2C())
s2 = adafruit_vl53l0x.VL53L0X(ExtendedI2C(3))
for s in (s1, s2):
    s.measurement_timing_budget = 33000   # 33ms, 빠른 응답 우선

print("1) 아무것도 없는 상태로 10초 둡니다...")
base1, base2 = [], []
t0 = time.time()
while time.time() - t0 < 10:
    base1.append(s1.range)
    base2.append(s2.range)
    time.sleep(0.05)

b1 = sorted(base1)[len(base1) // 2]
b2 = sorted(base2)[len(base2) // 2]
print(f"기준 거리: 1번 {b1}mm (흔들림 {min(base1)}~{max(base1)})")
print(f"           2번 {b2}mm (흔들림 {min(base2)}~{max(base2)})")

print("\n2) 이제 손을 통과시켜 보세요. 멈추려면 Ctrl+C.")
while True:
    d1, d2 = s1.range, s2.range
    m1 = "#" if d1 < b1 * 0.7 else "."
    m2 = "#" if d2 < b2 * 0.7 else "."
    print(f"{m1}{m2}  1번 {d1:5d} | 2번 {d2:5d}")
    time.sleep(0.05)
