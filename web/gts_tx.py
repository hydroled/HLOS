import machine, uasyncio as asyncio, ujson as json, ubinascii, dht, onewire, ds18x20
import ustruct as struct
from lib.kernel import Service
from .webserver import authenticate, CREDENTIALS, read_json, send_header_api
from modules.lora_heltec_v2 import LoRaNode


class GtsTxApi(Service):
    def __init__(self, name, web):
        super().__init__(name)
        self.web = web
        self.web.web_services.append(self.__class__.__name__)
        self.load_config()

        self.lora_node = None
        self.sensor_lock = asyncio.Lock()
        self.lora_lock = asyncio.Lock()

        self.lora_task = None
        self.lora_active = False
        self.lora_interval = 60  # По умолчанию теперь 60 сек

        self.fast_mode = False  # Флаг турбо-режима для сортировки датчиков

        self.sensor_cache = {
            "bat": 0, "air_t": 0, "air_h": 0, "soil": [0] * 8,
            "dht_ui": {"error": True},
            "ow_ui": []
        }

        asyncio.create_task(self.measure_daemon())

        self.web.app.route('/gts_tx')(self.tx_page)
        self.web.app.route('/api/gts_tx/read_all')(self.api_read_all)
        self.web.app.route('/api/gts_tx/scan')(self.api_scan_ow)
        self.web.app.route('/api/gts_tx/save')(self.api_save_config)
        self.web.app.route('/api/gts_tx/lora_os')(self.api_lora_os)
        self.web.app.route('/api/gts_tx/lora_test')(self.api_lora_test)
        self.web.app.route('/api/gts_tx/deepsleep')(self.api_go_sleep)
        self.web.app.route('/api/gts_tx/fast_mode')(self.api_fast_mode)

    def load_config(self):
        try:
            with open('hardware.json', 'r') as f:
                hw = json.load(f)
                # Поддерживаем старый ключ gts для совместимости
                conf = hw.get('gts_tx', hw.get('gts', {}))
                self.ow_pin = int(conf.get('ow_pin', 21))
                self.dht_pin = int(conf.get('dht_pin', 22))
                self.ow_order = conf.get('ow_order', [])
                self.measure_interval = int(conf.get('measure_interval', 60))
        except:
            self.ow_pin, self.dht_pin, self.ow_order = 21, 22, []
            self.measure_interval = 60

    async def _get_lora(self):
        if self.lora_node is None:
            self.lora_node = LoRaNode()
            await self.lora_node.boot()
        return self.lora_node

    async def measure_daemon(self):
        print("[GTS_TX] Фоновый опрос датчиков запущен")
        p13 = machine.Pin(13, machine.Pin.OUT)
        p23 = machine.Pin(23, machine.Pin.OUT)

        # Начинаем с выключенным питанием
        p13.value(0)
        p23.value(0)
        counter = 0

        while True:
            target_sleep = 5 if self.fast_mode else self.measure_interval

            # Если счетчик достиг нужного интервала (или мы резко переключились в fast_mode)
            if counter >= target_sleep:
                counter = 0

                # Включаем питание перед замером
                p13.value(1)
                p23.value(1)
                await asyncio.sleep(1)  # Ждем загрузки чипов

                try:
                    adc = machine.ADC(machine.Pin(37))
                    adc.atten(machine.ADC.ATTN_11DB)
                    self.sensor_cache['bat'] = int((adc.read() / 4095) * 3.3 * 2 * 1000)
                except:
                    pass

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
                        except:
                            pass

                # Выключаем питание только в обычном режиме. 
                # В турбо-режиме держим включенным для стабильности.
                if not self.fast_mode:
                    p13.value(0)
                    p23.value(0)
            else:
                # Спим короткими интервалами, чтобы мгновенно реагировать на включение fast_mode
                await asyncio.sleep(1)
                counter += 1

    @authenticate(CREDENTIALS)
    async def tx_page(self, request):
        await self.web.render_page(request, 'gts_tx.html')

    async def api_fast_mode(self, request):
        """Управление турбо-режимом для сортировки датчиков"""
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf is not None:
            self.fast_mode = conf.get("fast_mode", False)
            # Принудительно выключаем питание, если вышли из турбо-режима
            if not self.fast_mode:
                machine.Pin(13, machine.Pin.OUT).value(0)
                machine.Pin(23, machine.Pin.OUT).value(0)
        await send_header_api(request)
        await request.write(json.dumps({"status": "ok"}))

    async def api_read_all(self, request):
        data = {
            "onewire": self.sensor_cache['ow_ui'],
            "dht": self.sensor_cache['dht_ui'],
            "config": {
                "ow_pin": self.ow_pin,
                "dht_pin": self.dht_pin,
                "measure_interval": self.measure_interval
            },
            "lora_os": {"active": self.lora_active, "interval": self.lora_interval}
        }
        await send_header_api(request)
        await request.write(json.dumps(data))

    async def api_scan_ow(self, request):
        roms_hex = []
        async with self.sensor_lock:
            try:
                ow_bus = onewire.OneWire(machine.Pin(self.ow_pin))
                ow = ds18x20.DS18X20(ow_bus)
                roms_hex = [ubinascii.hexlify(r).decode() for r in ow.scan()]
            except:
                pass
        await send_header_api(request)
        await request.write(json.dumps(roms_hex))

    async def api_save_config(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf:
            try:
                try:
                    with open('hardware.json', 'r') as f:
                        full = json.load(f)
                except:
                    full = {"pins": [], "cron_commands": []}

                full['gts_tx'] = {
                    'ow_pin': int(conf['ow_pin']),
                    'dht_pin': int(conf['dht_pin']),
                    'measure_interval': int(conf.get('measure_interval', 60)),
                    'ow_order': conf['ow_order']
                }
                with open('hardware.json', 'w') as f:
                    json.dump(full, f)
                self.load_config()
            except:
                pass
        await send_header_api(request)
        await request.write(json.dumps({"status": "ok"}))

    async def api_lora_test(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        try:
            lora = await self._get_lora()
            bat = self.sensor_cache['bat']
            payload = b'TEST' + struct.pack('<H', bat)

            async with self.lora_lock:
                success = await lora.send(payload)

            await send_header_api(request)
            await request.write(json.dumps({"status": success}))
        except Exception as e:
            await send_header_api(request)
            await request.write(json.dumps({"status": False, "error": str(e)}))

    async def api_lora_os(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf:
            action = conf.get("action")
            if action == "start":
                self.lora_interval = int(conf.get("interval", 60))
                if self.lora_task: self.lora_task.cancel()

                self.lora_active = True
                self.lora_task = asyncio.create_task(self.lora_os_loop())
                msg = f"Запущено (Интервал: {self.lora_interval}с)"
            elif action == "stop":
                self.lora_active = False
                if self.lora_task:
                    self.lora_task.cancel()
                    self.lora_task = None
                msg = "Остановлено"

            await send_header_api(request)
            await request.write(json.dumps({"status": True, "msg": msg}))

    async def lora_os_loop(self):
        print("[OS LoRa] Демон передатчика запущен.")
        try:
            lora = await self._get_lora()

            while self.lora_active:
                c = self.sensor_cache
                payload = struct.pack('<HhB8h',
                                      c['bat'], c['air_t'], c['air_h'], *c['soil']
                                      )

                try:
                    async with self.lora_lock:
                        await lora.send(payload)
                except:
                    pass

                for _ in range(self.lora_interval):
                    if not self.lora_active: break
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            pass
        finally:
            self.lora_active = False

    async def api_go_sleep(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf:
            try:
                rtc = machine.RTC()
                mem = bytearray(128)
                mem[0:4] = b'GTS1'
                mem[4] = int(conf['ow_pin'])
                mem[5] = int(conf['dht_pin'])
                mem[6] = 13
                mem[7] = 23
                mem[8] = len(conf['ow_order'])
                mem[9] = int(conf['sleep_int'])

                offset = 16
                for rom_hex in conf['ow_order']:
                    mem[offset:offset + 8] = ubinascii.unhexlify(rom_hex)
                    offset += 8
                rtc.memory(mem)

                await send_header_api(request)
                await request.write(json.dumps({"status": "ok"}))
                await asyncio.sleep(1)

                machine.Pin(13, machine.Pin.OUT).value(0)
                machine.Pin(23, machine.Pin.OUT).value(0)
                machine.Pin(int(conf['ow_pin']), machine.Pin.IN, None)
                machine.Pin(int(conf['dht_pin']), machine.Pin.IN, None)

                machine.deepsleep(int(conf['sleep_int']) * 60 * 1000)
            except:
                pass