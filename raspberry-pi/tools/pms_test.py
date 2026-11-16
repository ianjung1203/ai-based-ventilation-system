#!/usr/bin/env python3
"""PMS5003 단독 테스트 — PM1.0 / PM2.5 / PM10 출력.

주의: 전원을 넣고 30초는 팬이 안정되기를 기다려야 값이 제대로 나온다.
"""

import time, struct, serial

ser = serial.Serial('/dev/serial0', 9600, timeout=2)
print("워밍업 30초 대기 중...")
time.sleep(30)
print("측정 시작. 멈추려면 Ctrl+C.")

while True:
    ser.reset_input_buffer()
    if ser.read(1) != b'\x42':
        continue
    if ser.read(1) != b'\x4d':
        continue
    f = ser.read(30)
    if len(f) != 30:
        continue
    if 0x42 + 0x4D + sum(f[:28]) != int.from_bytes(f[28:30], 'big'):
        print("체크섬 불일치")
        continue
    v = struct.unpack('>13H', f[2:28])
    # v[0:3] = CF=1 기준(실험실), v[3:6] = 대기환경 기준
    print(f"PM1.0 {v[3]:3d} | PM2.5 {v[4]:3d} | PM10 {v[5]:3d} (ug/m3)")
    time.sleep(1)
