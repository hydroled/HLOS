import machine
import time

rtc = machine.RTC()
mem = rtc.memory()

def check_boot_mode():
    # Если памяти мало или нет нашей сигнатуры - грузим полную ОС
    if len(mem) < 10 or mem[0:4] != b'GTS1':
        return True  # True означает "Грузить HLOS"

    # Если сигнатура есть, значит мы в цикле глубокого сна
    return False

if check_boot_mode():
    print(">>> [BOOT] Режим: Полноценная ОС (HLOS)")
    # Ничего не блокируем, система сама перейдет к main.py
else:
    print(">>> [BOOT] Режим: Энергосбережение (Sensor Stub)")
    try:
        import sensor_stub
        sensor_stub.run()
    except Exception as e:
        print(">>> [КРИТИЧЕСКАЯ ОШИБКА] в Stub-режиме:", e)
        print(">>> У вас есть 10 секунд на нажатие Ctrl+C для выхода в REPL...")
        time.sleep(10)
        # Очищаем память, чтобы при рестарте загрузилась ОС
        rtc.memory(b'')
        machine.reset()