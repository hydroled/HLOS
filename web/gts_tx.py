import ujson as json
from lib.kernel import Service, os_kernel
from .webserver import authenticate, CREDENTIALS, read_json, send_header_api

class GtsTxApi(Service):
    def __init__(self, name, web):
        super().__init__(name)
        self.web = web
        self.web.web_services.append(self.__class__.__name__)
        
        self.web.app.route('/gts_tx')(self.tx_page)
        self.web.app.route('/api/gts_tx/read_all')(self.api_read_all)
        self.web.app.route('/api/gts_tx/scan')(self.api_scan_ow)
        self.web.app.route('/api/gts_tx/save')(self.api_save_config)
        self.web.app.route('/api/gts_tx/lora_os')(self.api_lora_os)
        self.web.app.route('/api/gts_tx/deepsleep')(self.api_go_sleep)
        self.web.app.route('/api/gts_tx/fast_mode')(self.api_fast_mode)

    def _get_sensor(self):
        return os_kernel.find_task("GTS_Sensor")

    @authenticate(CREDENTIALS)
    async def tx_page(self, request):
        await self.web.render_page(request, 'gts_tx.html')

    async def api_fast_mode(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf is not None:
            sensor = self._get_sensor()
            if sensor: sensor.fast_mode = conf.get("fast_mode", False)
        await send_header_api(request)
        await request.write(json.dumps({"status": "ok"}))

    async def api_read_all(self, request):
        sensor = self._get_sensor()
        if not sensor:
            await send_header_api(request)
            await request.write(json.dumps({"error": "Service not running"}))
            return
            
        data = {
            "onewire": sensor.sensor_cache['ow_ui'],
            "dht": sensor.sensor_cache['dht_ui'],
            "device_id": sensor.device_id,
            "config": {
                "ow_pin": sensor.ow_pin,
                "dht_pin": sensor.dht_pin,
                "measure_interval": sensor.measure_interval,
                "lora_interval": sensor.lora_interval,
                "autostart": sensor.autostart,
                "use_deepsleep": sensor.use_deepsleep,
                "sleep_interval": sensor.sleep_interval
            },
            "lora_os": {"active": sensor.lora_active, "interval": sensor.lora_interval}
        }
        await send_header_api(request)
        await request.write(json.dumps(data))

    async def api_scan_ow(self, request):
        import machine, onewire, ds18x20, ubinascii
        roms_hex = []
        sensor = self._get_sensor()
        if sensor:
            async with sensor.sensor_lock:
                try:
                    ow_bus = onewire.OneWire(machine.Pin(sensor.ow_pin))
                    ow = ds18x20.DS18X20(ow_bus)
                    roms_hex = [ubinascii.hexlify(r).decode() for r in ow.scan()]
                except: pass
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

                if 'gts' not in full: full['gts'] = {}
                
                full['gts']['ow_pin'] = int(conf.get('ow_pin', 21))
                full['gts']['dht_pin'] = int(conf.get('dht_pin', 22))
                full['gts']['measure_interval'] = int(conf.get('measure_interval', 60))
                full['gts']['ow_order'] = conf.get('ow_order', [])
                full['gts']['lora_interval'] = int(conf.get('lora_interval', 60))
                full['gts']['autostart'] = bool(conf.get('autostart', False))
                full['gts']['use_deepsleep'] = bool(conf.get('use_deepsleep', False))
                full['gts']['sleep_interval'] = int(conf.get('sleep_interval', 10))

                with open('hardware.json', 'w') as f:
                    json.dump(full, f)
                
                sensor = self._get_sensor()
                if sensor: sensor.load_config()
            except Exception as e:
                print("Save config error:", e)
        await send_header_api(request)
        await request.write(json.dumps({"status": "ok"}))

    async def api_lora_os(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf:
            sensor = self._get_sensor()
            if not sensor: return
            
            action = conf.get("action")
            if action == "start":
                sensor.lora_interval = int(conf.get("interval", 60))
                sensor.start_lora()
                msg = f"Запущено (Интервал: {sensor.lora_interval}с)"
            elif action == "stop":
                sensor.stop_lora()
                msg = "Остановлено"

            await send_header_api(request)
            await request.write(json.dumps({"status": True, "msg": msg}))

    async def api_go_sleep(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        data = await read_json(request)
        sensor = self._get_sensor()
        if sensor and data:
            import uasyncio as asyncio
            # Обновляем интервал перед сном
            sensor.sleep_interval = int(data.get("sleep_int", 10))
            asyncio.create_task(sensor.run_once_and_sleep())
        await send_header_api(request)
        await request.write(json.dumps({"status": "ok"}))
