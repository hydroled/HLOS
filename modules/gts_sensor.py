import machine
import uasyncio as asyncio
import ujson as json
import ubinascii
import dht
import onewire
import ds18x20
import ustruct as struct
import time
import gc
from lib.kernel import Service
from modules.lora_heltec_v2 import LoRaNode

class GtsSensor(Service):
    def __init__(self, name="GTS_Sensor"):
        super().__init__(name)
        self.lora_node = None
        self.sensor_lock = asyncio.Lock()
        self.lora_lock = asyncio.Lock()
        self.lora_active = False
        self.fast_mode = False
        try:
            uid = machine.unique_id()
            self.device_id = struct.unpack('>H', uid[-2:])[0]
        except: self.device_id = 0
        self.ow_pin = 21
        self.dht_pin = 22
        self.ow_order = []
        self.measure_interval = 60
        self.lora_interval = 60
        self.autostart = False
        self.use_deepsleep = False
        self.sleep_interval = 10
        self.sensor_cache = {"bat": 0, "air_t": 0, "air_h": 0, "soil": [0] * 6, "dht_ui": {"error": True}, "ow_ui": []}
        self.packet_log = []
        self.load_config()

    def load_config(self):
        try:
            with open('hardware.json', 'r') as f:
                hw = json.load(f)
                conf = hw.get('gts', {})
                self.ow_pin = int(conf.get('ow_pin', 21))
                self.dht_pin = int(conf.get('dht_pin', 22))
                self.ow_order = conf.get('ow_order', [])
                self.measure_interval = int(conf.get('measure_interval', 60))
                self.lora_interval = int(conf.get('lora_interval', 60))
                self.autostart = conf.get('autostart', False)
                self.use_deepsleep = conf.get('use_deepsleep', False)
                self.sleep_interval = int(conf.get('sleep_interval', 10))
                # СРАЗУ ВКЛЮЧАЕМ LORA ПРИ СТАРТЕ ЕСЛИ НУЖНО
                if self.autostart: self.lora_active = True
        except: pass

    async def _get_lora(self):
        if self.lora_node is None:
            self.lora_node = LoRaNode()
            await self.lora_node.boot()
        return self.lora_node

    async def run(self):
        if self.use_deepsleep: await self.run_once_and_sleep()
        else:
            asyncio.create_task(self.measure_daemon())
            while True:
                gc.collect()
                await asyncio.sleep(60)

    def log_packet(self, status, cache):
        t = time.localtime()
        t_str = '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5])
        date_str = '{:04d}-{:02d}-{:02d}'.format(t[0], t[1], t[2])
        self.packet_log.insert(0, {
            "time": t_str, "date": date_str, "status": status, 
            "air_t": cache['air_t'] / 100.0, "air_h": cache['air_h'], 
            "bat": cache['bat'] / 1000.0, "device_id": self.device_id, "mode": 0
        })
        if len(self.packet_log) > 10: self.packet_log.pop()

    async def measure_daemon(self):
        print(f"[{self.name}] Цикл запущен. Интервал: {self.measure_interval}с")
        p13 = machine.Pin(13, machine.Pin.OUT, value=0)
        p23 = machine.Pin(23, machine.Pin.OUT, value=0)
        
        while True:
            # 1. ВКЛЮЧАЕМ ДАТЧИКИ И ИЗМЕРЯЕМ
            p13.value(1); p23.value(1)
            await asyncio.sleep(2)

            async with self.sensor_lock:
                try:
                    s_dht = dht.DHT22(machine.Pin(self.dht_pin))
                    s_dht.measure()
                    t, h = s_dht.temperature(), s_dht.humidity()
                    self.sensor_cache['air_t'], self.sensor_cache['air_h'] = int(t * 100), int(h)
                    self.sensor_cache['dht_ui'] = {"t": t, "h": h, "error": False}
                except: self.sensor_cache['dht_ui'] = {"error": True}

                if self.ow_order:
                    ow_ui = []
                    try:
                        ow_bus = onewire.OneWire(machine.Pin(self.ow_pin))
                        ow = ds18x20.DS18X20(ow_bus)
                        ow.convert_temp()
                        await asyncio.sleep(0.75)
                        for i, rom_hex in enumerate(self.ow_order):
                            try:
                                rom_bytes = ubinascii.unhexlify(rom_hex)
                                temp = round(ow.read_temp(rom_bytes), 1)
                                ow_ui.append({"rom": rom_hex, "temp": temp})
                                if i < 6: self.sensor_cache['soil'][i] = int(temp * 100)
                            except: ow_ui.append({"rom": rom_hex, "temp": "N/A"})
                        self.sensor_cache['ow_ui'] = ow_ui
                    except: pass
            
            # 2. ОТКЛЮЧАЕМ ДАТЧИКИ
            if not self.fast_mode: p13.value(0); p23.value(0)
            await asyncio.sleep_ms(500)

            # 3. ОТПРАВЛЯЕМ LORA (только если активна)
            if self.lora_active:
                c = self.sensor_cache
                try:
                    vals = [0x4753, int(self.device_id), 0, int(c['air_t']), int(c['air_h']), 0]
                    vals.extend([int(s) for s in c['soil']])
                    payload = struct.pack('<HHHhBB6h', *vals)
                    lora = await self._get_lora()
                    async with self.lora_lock:
                        success = await lora.send(payload)
                        self.log_packet("OK" if success else "FAIL", c)
                except Exception as e: print(f"LoRa ERR: {e}")

            # 4. СПИМ ДО СЛЕДУЮЩЕГО ЗАМЕРА
            target_sleep = 5 if self.fast_mode else self.measure_interval
            await asyncio.sleep(target_sleep)

    def start_lora(self): self.lora_active = True
    def stop_lora(self): self.lora_active = False

    async def run_once_and_sleep(self):
        print(f"[{self.name}] Подготовка RTC и быстрый переход в Stub...")
        
        # --- Подготовка RTC памяти ---
        rtc = machine.RTC()
        mem = bytearray(100) # Инициализируем чистый буфер
        
        # Сигнатура GTS1
        mem[0:4] = b'GTS1'
        mem[4] = self.ow_pin
        mem[5] = self.dht_pin
        mem[6] = 13 # pwr_ow_pin (фиксировано для Heltec GTS)
        mem[7] = 23 # pwr_dht_pin (фиксировано для Heltec GTS)
        
        # Ограничиваем до 6 датчиков для Stub
        roms_to_save = self.ow_order[:6]
        mem[8] = len(roms_to_save)
        mem[9] = self.sleep_interval # Сохраняем целевой интервал для Stub
        
        # Сохраняем Device ID (2 байта)
        mem[10:12] = struct.pack('<H', self.device_id)
        
        # Запись бинарных ROM-адресов OneWire
        offset = 16
        for rom_hex in roms_to_save:
            try:
                mem[offset:offset+8] = ubinascii.unhexlify(rom_hex)
                offset += 8
            except: pass
            
        # Сохраняем массив в RTC
        rtc.memory(mem)
        
        print(f"[{self.name}] Конфиг сохранен. Тестовое пробуждение через 5 сек...")
        await asyncio.sleep_ms(500)
        # Уходим в первый сон на 5 секунд, чтобы Stub сразу проснулся и отправил пакет
        machine.deepsleep(5000)
