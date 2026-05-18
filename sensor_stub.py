import machine
import onewire
import ds18x20
import dht
import ustruct as struct
import uasyncio as asyncio
from modules.lora_heltec_v2 import LoRaNode

async def send_lora(payload):
    """Асинхронная обертка для отправки бинарного пакета"""
    try:
        lora = LoRaNode()
        await lora.boot()
        await lora.send(payload)
        print(f"[Stub] Пакет {len(payload)} байт успешно отправлен в эфир!")
    except Exception as e:
        print("[Stub] Ошибка LoRa:", e)

def run():
    rtc = machine.RTC()
    mem = rtc.memory()

    # Проверка валидности данных в RTC
    if len(mem) < 10 or mem[0:4] != b'GTS1':
        print("[Stub] Нет данных в RTC! Сплю 10 минут.")
        machine.deepsleep(600000)

    # Распаковка конфигурации из RTC
    ow_pin, dht_pin = mem[4], mem[5]
    pwr_ow_pin, pwr_dht_pin = mem[6], mem[7]
    rom_count = mem[8]
    sleep_interval_ms = mem[9] * 60 * 1000
    device_id = struct.unpack('<H', mem[10:12])[0]

    roms = []
    offset = 16
    for _ in range(rom_count):
        roms.append(mem[offset:offset + 8])
        offset += 8

    print(f"[Stub] Подъем! ID:{hex(device_id)}, OW:{ow_pin}, DHT:{dht_pin}. Датчиков: {rom_count}")

    # Подаем питание на датчики
    p_ow_pwr = machine.Pin(pwr_ow_pin, machine.Pin.OUT, value=1)
    p_dht_pwr = machine.Pin(pwr_dht_pin, machine.Pin.OUT, value=1)

    # Даем датчикам время на включение
    machine.lightsleep(2000)

    soil, air_t, air_h, bat = [0] * 6, 0, 0, 0

    # 1. Чтение батареи
    try:
        adc = machine.ADC(machine.Pin(34))
        adc.atten(machine.ADC.ATTN_11DB)
        bat = int((adc.read() / 4095) * 3.3 * 2 * 1000)
    except:
        pass

    # 2. Чтение воздуха (DHT22)
    try:
        s_dht = dht.DHT22(machine.Pin(dht_pin))
        s_dht.measure()
        air_t, air_h = int(s_dht.temperature() * 100), int(s_dht.humidity())
    except:
        pass

    # 3. Чтение почвы (DS18B20)
    try:
        if rom_count > 0:
            ow = ds18x20.DS18X20(onewire.OneWire(machine.Pin(ow_pin)))
            ow.convert_temp()
            machine.lightsleep(750)

            for i, rom in enumerate(roms):
                if i < 6: # Строго 6 датчиков
                    soil[i] = int(ow.read_temp(rom) * 100)
    except:
        pass

    # Пакуем 22-байтный бинарный пакет: <H(magic), H(id), H(bat), h(air_t), B(air_h), B(mode=1), 6h(soil)
    vals = [0x4753, int(device_id), int(bat), int(air_t), int(air_h), 1]
    vals.extend([int(s) for s in soil])
    payload = struct.pack('<HHHhBB6h', *vals)
    print(f"[Stub] Данные собраны. DevID: {hex(device_id)}. Bat: {bat/1000}V. Размер: {len(payload)} байт.")

    # Запускаем микро-сессию asyncio только ради отправки LoRa
    asyncio.run(send_lora(payload))

    # Обесточиваем шины и переводим пины в режим входа (высокое сопротивление) для экономии
    p_ow_pwr.value(0)
    p_dht_pwr.value(0)
    machine.Pin(ow_pin, machine.Pin.IN, None)
    machine.Pin(dht_pin, machine.Pin.IN, None)

    print(f"[Stub] Оборудование обесточено. Ухожу в сон на {mem[9]} мин.")
    machine.deepsleep(sleep_interval_ms)