# gts_rx.py
import machine, uasyncio as asyncio, ujson as json
import ustruct as struct
import time
import usocket as socket
from lib.kernel import Service
from .webserver import authenticate, CREDENTIALS, read_json, send_header_api
from modules.lora_heltec_v2 import LoRaNode


class SyslogClient:
    """Простой клиент для отправки логов на удаленный Syslog сервер по UDP"""

    def __init__(self, host, port=514, hostname="HLOS_GTS", app_name="gts_rx"):
        self.host = host
        self.port = port
        self.hostname = hostname
        self.app_name = app_name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Названия месяцев для стандарта RFC 3164
        self.months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    def send(self, message):
        if not self.host:
            return
        try:
            # Получаем актуальное время с часов микроконтроллера
            t = time.localtime()
            # Форматируем дату строго по стандарту Syslog: "Oct 11 22:14:15"
            ts = f"{self.months[t[1] - 1]} {t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"

            # Собираем пакет
            packet = f"<14>{ts} {self.hostname} {self.app_name}: {message}"
            self.sock.sendto(packet.encode('utf-8'), (self.host, self.port))
        except Exception as e:
            print(f"[Syslog] Ошибка отправки: {e}")

class GtsRxApi(Service):
    def __init__(self, name, web):
        super().__init__(name)
        self.web = web
        self.web.web_services.append(self.__class__.__name__)

        self.lora_node = None
        self.lora_lock = asyncio.Lock()

        self.rx_task = None
        self.rx_active = False

        # Настройки по умолчанию
        self.autostart = False
        self.syslog_ip = ""
        self.syslog_port = 514

        self.last_data = {"status": "waiting", "data": None, "rssi": 0, "time": ""}

        self.load_config()

        # Инициализация клиента Syslog
        self.syslog = SyslogClient(host=self.syslog_ip, port=self.syslog_port)

        self.web.app.route('/gts_rx')(self.rx_page)
        self.web.app.route('/api/gts_rx/data')(self.api_data)
        self.web.app.route('/api/gts_rx/control')(self.api_control)

        if self.autostart:
            self.start_rx()

    def load_config(self):
        try:
            with open('hardware.json', 'r') as f:
                hw = json.load(f)
                rx_conf = hw.get('gts_rx', {})
                self.autostart = rx_conf.get('autostart', False)
                self.syslog_ip = rx_conf.get('syslog_ip', "")
                self.syslog_port = int(rx_conf.get('syslog_port', 514))
        except:
            pass  # Оставляем дефолтные значения

    async def _get_lora(self):
        if self.lora_node is None:
            self.lora_node = LoRaNode()
            await self.lora_node.boot()
        return self.lora_node

    def start_rx(self):
        if not self.rx_active:
            self.rx_active = True
            self.rx_task = asyncio.create_task(self.rx_daemon())

    def stop_rx(self):
        self.rx_active = False
        if self.rx_task:
            self.rx_task.cancel()
            self.rx_task = None

    async def rx_daemon(self):
        print("[GTS_RX] Демон приемника запущен")
        if self.syslog_ip:
            print(f"[GTS_RX] Syslog активирован: отправка на {self.syslog_ip}:{self.syslog_port}")

        lora = await self._get_lora()

        while self.rx_active:
            try:
                async with self.lora_lock:
                    data, rssi = await lora.listen(timeout_ms=0)

                if data:
                    if len(data) == 21:
                        unpacked = struct.unpack('<HhB8h', data)

                        bat_v = unpacked[0] / 1000.0
                        air_t = unpacked[1] / 100.0
                        air_h = unpacked[2]
                        soil = [s / 100.0 for s in unpacked[3:11]]

                        t_str = '{:02d}:{:02d}:{:02d}'.format(*time.localtime()[3:6])

                        parsed = {
                            "bat": bat_v, "air_t": air_t, "air_h": air_h, "soil": soil
                        }

                        self.last_data = {
                            "status": "ok", "data": parsed, "rssi": rssi, "time": t_str
                        }

                        # Печать в консоль
                        log_msg = f"RSSI:{rssi} Bat:{bat_v} AirT:{air_t} AirH:{air_h} Soil:{soil}"
                        print(f"[GTS_RX] {t_str} | {log_msg}")

                        # --- ОТПРАВКА В SYSLOG ---
                        if self.syslog_ip:
                            # Отправляем JSON строку для удобного парсинга на сервере
                            syslog_payload = json.dumps({"rssi": rssi, "data": parsed})
                            self.syslog.send(syslog_payload)

                    elif data.startswith(b'TEST'):
                        pass  # Игнорируем тестовые пакеты

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[GTS_RX] Сбой приема: {e}")
                await asyncio.sleep(1)

            await asyncio.sleep_ms(10)

    @authenticate(CREDENTIALS)
    async def rx_page(self, request):
        await self.web.render_page(request, 'gts_rx.html')

    async def api_data(self, request):
        res = {
            "active": self.rx_active,
            "autostart": self.autostart,
            "syslog_ip": self.syslog_ip,
            "last_packet": self.last_data
        }
        await send_header_api(request)
        await request.write(json.dumps(res))

    async def api_control(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        conf = await read_json(request)
        if conf:
            action = conf.get("action")
            if action == "start":
                self.start_rx()
            elif action == "stop":
                self.stop_rx()
            elif action == "save_settings":
                self.autostart = conf.get("autostart", False)
                new_ip = conf.get("syslog_ip", "").strip()
                self.syslog_ip = new_ip

                # Обновляем инстанс syslog клиента
                self.syslog.host = self.syslog_ip

                try:
                    with open('hardware.json', 'r') as f:
                        hw = json.load(f)
                except:
                    hw = {}

                if 'gts_rx' not in hw: hw['gts_rx'] = {}
                hw['gts_rx']['autostart'] = self.autostart
                hw['gts_rx']['syslog_ip'] = self.syslog_ip

                with open('hardware.json', 'w') as f:
                    json.dump(hw, f)

        await send_header_api(request)
        await request.write(json.dumps({"status": "ok"}))