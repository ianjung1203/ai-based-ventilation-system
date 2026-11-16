#!/usr/bin/env python3
"""LED 배선 확인용. GPIO18에 연결한 LED를 5번 깜빡인다."""

import time, board, digitalio

led = digitalio.DigitalInOut(board.D18)
led.switch_to_output(value=False)

print("LED를 5번 깜빡입니다.")
for _ in range(5):
    led.value = True
    time.sleep(0.5)
    led.value = False
    time.sleep(0.5)

led.deinit()
print("끝")
