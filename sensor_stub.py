import machine
import onewire
import ds18x20
import dht
import time
import ujson as json
import uasyncio as asyncio
from modules.lora_heltec_v2 import LoRaNode


async def send_lora(point):
    """Асинхронная обертка для отправки одного пакета"""
    try:
        lora = LoRaNode()
        await lora.boot()
        await lora.send(json.dumps(point))
        print("[Stub] Пакет успешно отправлен в эфир!")
    except Exception as e:
        print("[Stub] Ошибка LoRa:", e)


def run():
    rtc = machine.RTC()
    mem = rtc.memory()

    if len(mem) < 10 or mem[0:4] != b'GTS1':
        print("[Stub] Нет данных в RTC! Сплю.")
        machine.deepsleep(600000)

    ow_pin, dht_pin = mem[4], mem[5]
    pwr_ow_pin, pwr_dht_pin = mem[6], mem[7]
    rom_count = mem[8]
    sleep_interval_ms = mem[9] * 60 * 1000

    roms = []
    offset = 16
    for _ in range(rom_count):
        roms.append(mem[offset:offset + 8])
        offset += 8

    print(f"[Stub] Подъем! OW:{ow_pin}, DHT:{dht_pin}. Датчиков: {rom_count}")

    p_ow_pwr = machine.Pin(pwr_ow_pin, machine.Pin.OUT, value=1)
    p_dht_pwr = machine.Pin(pwr_dht_pin, machine.Pin.OUT, value=1)

    machine.lightsleep(2000)

    soil, air_t, air_h, bat = [0] * 8, 0, 0, 0

    try:
        adc = machine.ADC(machine.Pin(37))
        adc.atten(machine.ADC.ATTN_11DB)
        bat = int((adc.read() / 4095) * 3.3 * 2 * 1000)
    except:
        pass

    try:
        s_dht = dht.DHT22(machine.Pin(dht_pin))
        s_dht.measure()
        air_t, air_h = int(s_dht.temperature() * 100), int(s_dht.humidity())
    except:
        pass

    try:
        if rom_count > 0:
            ow = ds18x20.DS18X20(onewire.OneWire(machine.Pin(ow_pin)))
            ow.convert_temp()
            machine.lightsleep(750)

            for i, rom in enumerate(roms):
                if i < 8:
                    soil[i] = int(ow.read_temp(rom) * 100)
    except:
        pass

    # Пакуем все данные строго в том же формате, что и в режиме ОС
    point = {"bat": bat, "air_t": air_t, "air_h": air_h, "soil": soil[:rom_count]}
    print(f"[Stub] Данные: {point}")

    # Запускаем микро-сессию asyncio только ради отправки пакета
    asyncio.run(send_lora(point))

    # Обесточиваем шины
    p_ow_pwr.value(0)
    p_dht_pwr.value(0)
    machine.Pin(ow_pin, machine.Pin.IN, None)
    machine.Pin(dht_pin, machine.Pin.IN, None)

    print(f"[Stub] Оборудование обесточено. Сплю {mem[9]} мин.")
    machine.deepsleep(sleep_interval_ms)