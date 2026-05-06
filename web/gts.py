import machine, uasyncio as asyncio, ujson as json, ubinascii, dht, onewire, ds18x20
from lib.kernel import Service
from .webserver import authenticate, CREDENTIALS, read_json, send_header_api
from modules.lora_heltec_v2 import LoRaNode


class GtsApi(Service):
    def __init__(self, name, web):
        super().__init__(name)
        self.web = web
        self.web.web_services.append(self.__class__.__name__)
        self.load_config()

        # Датчики всегда запитаны в режиме ОС
        machine.Pin(13, machine.Pin.OUT, value=1)
        machine.Pin(23, machine.Pin.OUT, value=1)

        self.lora_node = None
        self.sensor_lock = asyncio.Lock()  # Светофор для датчиков
        self.lora_lock = asyncio.Lock()  # НОВОЕ: Светофор для радиомодуля (SPI)

        self.lora_task = None
        self.lora_active = False
        self.lora_interval = 15

        self.web.app.route('/gts')(self.gts_page)
        self.web.app.route('/api/gts/read_all')(self.api_read_all)
        self.web.app.route('/api/gts/scan')(self.api_scan_ow)
        self.web.app.route('/api/gts/save')(self.api_save_config)
        self.web.app.route('/api/gts/lora_os')(self.api_lora_os)
        self.web.app.route('/api/gts/lora_test')(self.api_lora_test)
        self.web.app.route('/api/gts/deepsleep')(self.api_go_sleep)

    def load_config(self):
        try:
            with open('hardware.json', 'r') as f:
                hw = json.load(f).get('gts', {})
                self.ow_pin = int(hw.get('ow_pin', 21))
                self.dht_pin = int(hw.get('dht_pin', 22))
                self.ow_order = hw.get('ow_order', [])
        except:
            self.ow_pin, self.dht_pin, self.ow_order = 21, 22, []

    async def _get_lora(self):
        # Инициализируем LoRa только один раз (защита от размножения IRQ)
        if self.lora_node is None:
            self.lora_node = LoRaNode()
            await self.lora_node.boot()
        return self.lora_node

    @authenticate(CREDENTIALS)
    async def gts_page(self, request):
        await self.web.render_page(request, 'gts.html')

    async def api_read_all(self, request):
        data = {"onewire": [], "dht": {}, "config": {"ow_pin": self.ow_pin, "dht_pin": self.dht_pin}}

        async with self.sensor_lock:
            try:
                s = dht.DHT22(machine.Pin(self.dht_pin))
                s.measure()
                data["dht"] = {"t": s.temperature(), "h": s.humidity()}
            except:
                data["dht"] = {"error": True}

            if self.ow_order:
                try:
                    ow_bus = onewire.OneWire(machine.Pin(self.ow_pin))
                    ow = ds18x20.DS18X20(ow_bus)
                    ow.convert_temp()
                    await asyncio.sleep(0.75)

                    for rom_hex in self.ow_order:
                        try:
                            rom_bytes = ubinascii.unhexlify(rom_hex)
                            temp = round(ow.read_temp(rom_bytes), 1)
                            if temp == 85.0:
                                data["onewire"].append({"rom": rom_hex, "temp": "N/A"})
                            else:
                                data["onewire"].append({"rom": rom_hex, "temp": temp})
                        except Exception:
                            data["onewire"].append({"rom": rom_hex, "temp": "N/A"})
                except Exception:
                    for rom_hex in self.ow_order:
                        data["onewire"].append({"rom": rom_hex, "temp": "N/A"})

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

                full['gts'] = {
                    'ow_pin': int(conf['ow_pin']),
                    'dht_pin': int(conf['dht_pin']),
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
            data = {"sys": "GTS", "test": True, "bat": 0}

            try:
                adc = machine.ADC(machine.Pin(37))
                adc.atten(machine.ADC.ATTN_11DB)
                data["bat"] = int((adc.read() / 4095) * 3.3 * 2 * 1000)
            except:
                pass

            # Блокируем радиомодуль на время отправки
            async with self.lora_lock:
                success = await lora.send(json.dumps(data))

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
                self.lora_interval = int(conf.get("interval", 15))

                if self.lora_task:
                    self.lora_task.cancel()

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
        print("[OS LoRa] Демон запущен.")
        try:
            lora = await self._get_lora()

            while self.lora_active:
                soil, air_t, air_h, bat = [0] * 8, 0, 0, 0

                try:
                    adc = machine.ADC(machine.Pin(37))
                    adc.atten(machine.ADC.ATTN_11DB)
                    bat = int((adc.read() / 4095) * 3.3 * 2 * 1000)
                except:
                    pass

                async with self.sensor_lock:
                    try:
                        s_dht = dht.DHT22(machine.Pin(self.dht_pin))
                        s_dht.measure()
                        air_t, air_h = int(s_dht.temperature() * 100), int(s_dht.humidity())
                    except:
                        pass

                    try:
                        if self.ow_order:
                            ow_bus = onewire.OneWire(machine.Pin(self.ow_pin))
                            ow = ds18x20.DS18X20(ow_bus)
                            ow.convert_temp()
                            await asyncio.sleep(0.75)
                            for i, rom_hex in enumerate(self.ow_order):
                                if i < 8:
                                    try:
                                        rom_bytes = ubinascii.unhexlify(rom_hex)
                                        soil[i] = int(ow.read_temp(rom_bytes) * 100)
                                    except:
                                        pass
                    except:
                        pass

                point = {"bat": bat, "air_t": air_t, "air_h": air_h, "soil": soil[:len(self.ow_order)]}

                # Блокируем радиомодуль на время фоновой отправки
                try:
                    async with self.lora_lock:
                        await lora.send(json.dumps(point))
                    print(f"[OS LoRa] Отправлено: {point}")
                except Exception as e:
                    print(f"[OS LoRa] Ошибка отправки: {e}")

                for _ in range(self.lora_interval):
                    if not self.lora_active: break
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("[OS LoRa] Демон отменен.")
        except Exception as e:
            print(f"[OS LoRa] Сбой: {e}")
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