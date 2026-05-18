import ujson as json
from lib.kernel import Service, os_kernel
from .webserver import authenticate, CREDENTIALS, read_json, send_header_api

class GtsRxApi(Service):
    def __init__(self, name, web):
        super().__init__(name)
        self.web = web
        self.web.web_services.append(self.__class__.__name__)

        self.web.app.route('/gts_rx')(self.rx_page)
        self.web.app.route('/api/gts_rx/data')(self.api_data)
        self.web.app.route('/api/gts_rx/control')(self.api_control)

    def _get_gateway(self):
        return os_kernel.find_task("GTS_Gateway")

    @authenticate(CREDENTIALS)
    async def rx_page(self, request):
        await self.web.render_page(request, 'gts_rx.html')

    async def api_data(self, request):
        gw = self._get_gateway()
        if not gw:
            await send_header_api(request)
            await request.write(json.dumps({"error": "Service not running"}))
            return
            
        res = {
            "active": gw.rx_active,
            "autostart": gw.autostart,
            "syslog_ip": gw.syslog_ip,
            "device_id": gw.device_id,
            "local_bat": gw.local_bat,
            "last_packet": gw.last_data
        }
        await send_header_api(request)
        await request.write(json.dumps(res))

    async def api_control(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf:
            gw = self._get_gateway()
            if not gw: return
            
            action = conf.get("action")
            if action == "start":
                gw.start_rx()
            elif action == "stop":
                gw.stop_rx()
            elif action == "save_settings":
                gw.autostart = conf.get("autostart", False)
                new_ip = conf.get("syslog_ip", "").strip()
                gw.syslog_ip = new_ip
                gw.syslog.host = gw.syslog_ip

                try:
                    with open('hardware.json', 'r') as f:
                        hw = json.load(f)
                except:
                    hw = {}

                if 'gts_rx' not in hw: hw['gts_rx'] = {}
                hw['gts_rx']['autostart'] = gw.autostart
                hw['gts_rx']['syslog_ip'] = gw.syslog_ip

                with open('hardware.json', 'w') as f:
                    json.dump(hw, f)

        await send_header_api(request)
        await request.write(json.dumps({"status": "ok"}))
