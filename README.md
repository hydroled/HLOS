HLOS — MicroPython OS Framework

Система управления для контроллеров ESP32, оптимизированная для задач автоматизации и гидропоники. Установка и обновление осуществляются напрямую из репозитория через стандартный инструмент mip.
🚀 Быстрый старт
1. Установка MicroPython

Прежде чем устанавливать HLOS, необходимо прошить контроллер свежей версией MicroPython.

    Скачайте последнюю прошивку (v1.20+) с официального сайта micropython.org.

    Установите утилиту esptool:
    pip install esptool

    Очистите память и прошейте устройство:

    ESP32
    esptool.py --chip esp32 --port /dev/ttyUSB0 erase_flash
    esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 460800 write_flash -z 0x1000 ESP32_GENERIC_S3-20251209-v1.27.0.bin

    ESP32-c3
    esptool.py --port /dev/ttyACM0 erase_flash
    esptool.py --port /dev/ttyACM0 --baud 460800 write_flash 0 ESP32_GENERIC_C3-20251209-v1.27.0.bin

    (Замените /dev/ttyUSB0 на ваш COM-порт и укажите имя скачанного файла прошивки).

2. Подключение к сети

Для загрузки HLOS устройство должно иметь доступ к интернету. Подключитесь к Wi-Fi через REPL:
Python

import network
import time

ssid = 'ВАШ_WIFI_SSID'
password = 'ВАШ_ПАРОЛЬ'

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(ssid, password)

while not wlan.isconnected():
    print("Connecting...")
    time.sleep(1)

print("Connected!", wlan.ifconfig())

3. Установка HLOS через mip

Как только интернет настроен, установите систему одной командой. Мы используем параметр target="/", чтобы системные файлы (main.py, boot.py) попали в корневую директорию, а не в /lib.
Python

import mip
mip.install("github:HydroLED/HLOS", target="/")

🛠 Обновление проекта

Если Вы хотите обновить систему из GitHub, просто перезапустите команду установки на устройстве. mip скачает обновленные файлы и перезапишет старые версии.
Python

import mip
mip.install("github:HydroLED/HLOS", target="/")

📂 Структура проекта

    boot.py — Начальная инициализация железа.

    main.py — Точка входа в HLOS.

    /lib — Вспомогательные библиотеки и драйверы.

    package.json — Манифест для автоматической установки.

Устранение неполадок

    Ошибка OSError -202: Проблема с DNS. Попробуйте прописать 8.8.8.8 в настройках wlan.ifconfig().

    Ошибка OSError -40: Ошибка SSL. Синхронизируйте время с помощью модуля ntptime.

