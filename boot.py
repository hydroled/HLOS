import machine
import time

rtc = machine.RTC()
mem = rtc.memory()


def check_boot_mode():
    # Если память RTC пустая (холодный старт, только подали питание)
    if len(mem) < 4:
        return True  # Грузим HLOS для первоначальной настройки

    # Проверяем флаг загрузки: 1 - загрузка HLOS, 0 - режим сна (Sensor Stub)
    return mem[2] == 1


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
        machine.reset()