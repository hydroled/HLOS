import machine
import time
from lib.kernel import Service
import ujson as json


class HardResetButton(Service):
    def __init__(self, pin_num=0, **kwargs):
        super().__init__(**kwargs)
        self.button = machine.Pin(pin_num, machine.Pin.IN, machine.Pin.PULL_UP)
        self.last_press = 0
        print(f"[{self.name}] Пин сброса: {pin_num}")

    def enable_stub_mode(self):
        rtc = machine.RTC()
        mem = bytearray(rtc.memory())

        # 1. Читаем пины из конфига для передачи в Stub
        try:
            with open('hardware.json', 'r') as f:
                config = json.load(f)
                ow_pin = config.get('pins', {}).get('ow_pin', 21)
                dht_pin = config.get('pins', {}).get('dht_pin', 22)
        except:
            ow_pin, dht_pin = 21, 22

        # 2. Инициализируем структуру RTC, если она пуста[cite: 3]
        if len(mem) < 16:
            import sensor_stub
            mem = sensor_stub.init_rtc_mem(rtc)

        # 3. Сохраняем флаг и пины (байты 4 и 5)[cite: 2]
        mem[2] = 0  # 0 = Режим датчика (Stub)
        mem[4] = ow_pin
        mem[5] = dht_pin

        rtc.memory(mem)
        print(f"Конфиг передан в RTC (OW:{ow_pin}, DHT:{dht_pin}). Сон...")
        time.sleep(1)
        machine.reset()

    async def tic(self):
        # Логика обработки нажатий (двойное удержание и т.д.)[cite: 3]
        if not self.button.value():
            # ... твоя существующая логика таймингов ...
            pass
        return False