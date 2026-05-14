import machine
import uasyncio as asyncio
import ujson as json
import ubinascii
import dht
import onewire
import ds18x20
import ustruct as struct
import time
from lib.kernel import Service
from modules.lora_heltec_v2 import LoRaNode

class GtsSensor(Service):
    def __init__(self, name="GTS_Sensor"):
        super().__init__(name)
        self.lora_node = None
        self.sensor_lock = asyncio.Lock()
        self.lora_lock = asyncio.Lock()
        
        self.lora_task = None
        self.lora_active = False
        self.fast_mode = False
        
        # Конфигурация по умолчанию
        self.ow_pin = 21
        self.dht_pin = 22
        self.ow_order = []
        self.measure_interval = 60
        self.lora_interval = 60
        self.autostart = False
        self.use_deepsleep = False
        self.sleep_interval = 10
        
        self.sensor_cache = {
            "bat": 0, "air_t": 0, "air_h": 0, "soil": [0] * 8,
            "dht_ui": {"error": True},
            "ow_ui": []
        }
        
        self.packet_log = []
        self.load_config()

    def load_config(self):
        try:
            with open('hardware.json', 'r') as f:
                hw = json.load(f)
                conf = hw.get('gts_tx', hw.get('gts', {}))
                self.ow_pin = int(conf.get('ow_pin', 21))
                self.dht_pin = int(conf.get('dht_pin', 22))
                self.ow_order = conf.get('ow_order', [])
                self.measure_interval = int(conf.get('measure_interval', 60))
                self.lora_interval = int(conf.get('lora_interval', 60))
                self.autostart = conf.get('autostart', False)
                self.use_deepsleep = conf.get('use_deepsleep', False)
                self.sleep_interval = int(conf.get('sleep_interval', 10))
        except Exception as e:
            print(f"[{self.name}] Ошибка загрузки конфига: {e}")

    async def _get_lora(self):
        if self.lora_node is None:
            self.lora_node = LoRaNode()
            await self.lora_node.boot()
        return self.lora_node

    async def run(self):
        print(f"[{self.name}] Служба запущена. DeepSleep: {self.use_deepsleep}")
        if self.use_deepsleep:
            await self.run_once_and_sleep()
        else:
            asyncio.create_task(self.measure_daemon())
            if self.autostart:
                self.start_lora()
            while True:
                await asyncio.sleep(60)

    def log_packet(self, status, payload_size):
        t_str = '{:02d}:{:02d}:{:02d}'.format(*time.localtime()[3:6])
        self.packet_log.insert(0, {"time": t_str, "status": status, "size": payload_size})
        if len(self.packet_log) > 10:
            self.packet_log.pop()

    async def measure_daemon(self):
        print(f"[{self.name}] Фоновый опрос датчиков запущен")
        p13 = machine.Pin(13, machine.Pin.OUT, value=0)
        p23 = machine.Pin(23, machine.Pin.OUT, value=0)
        counter = 0

        while True:
            target_sleep = 5 if self.fast_mode else self.measure_interval
            if counter >= target_sleep:
                counter = 0
                p13.value(1)
                p23.value(1)
                await asyncio.sleep(1)

                try:
                    adc = machine.ADC(machine.Pin(37))
                    adc.atten(machine.ADC.ATTN_11DB)
                    self.sensor_cache['bat'] = int((adc.read() / 4095) * 3.3 * 2 * 1000)
                except: pass

                async with self.sensor_lock:
                    try:
                        s_dht = dht.DHT22(machine.Pin(self.dht_pin))
                        s_dht.measure()
                        t, h = s_dht.temperature(), s_dht.humidity()
                        self.sensor_cache['air_t'] = int(t * 100)
                        self.sensor_cache['air_h'] = int(h)
                        self.sensor_cache['dht_ui'] = {"t": t, "h": h, "error": False}
                    except:
                        self.sensor_cache['dht_ui'] = {"error": True}

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
                                    if temp == 85.0:
                                        ow_ui.append({"rom": rom_hex, "temp": "N/A"})
                                    else:
                                        ow_ui.append({"rom": rom_hex, "temp": temp})
                                        if i < 8:
                                            self.sensor_cache['soil'][i] = int(temp * 100)
                                except Exception:
                                    ow_ui.append({"rom": rom_hex, "temp": "N/A"})
                            self.sensor_cache['ow_ui'] = ow_ui
                        except: pass

                if not self.fast_mode:
                    p13.value(0)
                    p23.value(0)
            else:
                await asyncio.sleep(1)
                counter += 1

    def start_lora(self):
        if not self.lora_active:
            self.lora_active = True
            self.lora_task = asyncio.create_task(self.lora_os_loop())

    def stop_lora(self):
        self.lora_active = False
        if self.lora_task:
            self.lora_task.cancel()
            self.lora_task = None

    async def lora_os_loop(self):
        print(f"[{self.name}] Демон передатчика запущен. Интервал: {self.lora_interval}с")
        try:
            lora = await self._get_lora()
            while self.lora_active:
                c = self.sensor_cache
                payload = struct.pack('<HhB8h', c['bat'], c['air_t'], c['air_h'], *c['soil'])
                try:
                    async with self.lora_lock:
                        success = await lora.send(payload)
                        self.log_packet("OK" if success else "FAIL", len(payload))
                except Exception as e:
                    print(f"[{self.name}] Ошибка LoRa TX: {e}")
                    self.log_packet("ERR", 0)

                for _ in range(self.lora_interval):
                    if not self.lora_active: break
                    await asyncio.sleep(1)
        except asyncio.CancelledError:
            pass
        finally:
            self.lora_active = False

    async def run_once_and_sleep(self):
        print(f"[{self.name}] Цикл глубокого сна активирован. Измеряем...")
        
        p13 = machine.Pin(13, machine.Pin.OUT, value=1)
        p23 = machine.Pin(23, machine.Pin.OUT, value=1)
        await asyncio.sleep(2)
        
        c = self.sensor_cache
        try:
            adc = machine.ADC(machine.Pin(37))
            adc.atten(machine.ADC.ATTN_11DB)
            c['bat'] = int((adc.read() / 4095) * 3.3 * 2 * 1000)
        except: pass

        try:
            s_dht = dht.DHT22(machine.Pin(self.dht_pin))
            s_dht.measure()
            c['air_t'], c['air_h'] = int(s_dht.temperature() * 100), int(s_dht.humidity())
        except: pass

        if self.ow_order:
            try:
                ow_bus = onewire.OneWire(machine.Pin(self.ow_pin))
                ow = ds18x20.DS18X20(ow_bus)
                ow.convert_temp()
                await asyncio.sleep(0.75)
                for i, rom_hex in enumerate(self.ow_order):
                    if i < 8:
                        rom_bytes = ubinascii.unhexlify(rom_hex)
                        c['soil'][i] = int(ow.read_temp(rom_bytes) * 100)
            except: pass
            
        payload = struct.pack('<HhB8h', c['bat'], c['air_t'], c['air_h'], *c['soil'])
        
        try:
            lora = await self._get_lora()
            await lora.send(payload)
            print(f"[{self.name}] Пакет отправлен!")
        except Exception as e:
            print(f"[{self.name}] Ошибка отправки перед сном: {e}")
            
        p13.value(0)
        p23.value(0)
        machine.Pin(self.ow_pin, machine.Pin.IN, None)
        machine.Pin(self.dht_pin, machine.Pin.IN, None)
        
        print(f"[{self.name}] Уходим в сон на {self.sleep_interval} минут...")
        await asyncio.sleep(1)
        machine.deepsleep(self.sleep_interval * 60 * 1000)
