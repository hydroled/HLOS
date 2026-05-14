import machine
import uasyncio as asyncio
import ujson as json
import ustruct as struct
import time
import usocket as socket
from lib.kernel import Service
from modules.lora_heltec_v2 import LoRaNode

class SyslogClient:
    def __init__(self, host, port=514, hostname="HLOS_GTS", app_name="gts_rx"):
        self.host = host
        self.port = port
        self.hostname = hostname
        self.app_name = app_name
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

    def send(self, message):
        if not self.host: return
        try:
            t = time.localtime()
            ts = f"{self.months[t[1] - 1]} {t[2]:02d} {t[3]:02d}:{t[4]:02d}:{t[5]:02d}"
            packet = f"<14>{ts} {self.hostname} {self.app_name}: {message}"
            self.sock.sendto(packet.encode('utf-8'), (self.host, self.port))
        except: pass

class GtsGateway(Service):
    def __init__(self, name="GTS_Gateway"):
        super().__init__(name)
        self.lora_node = None
        self.lora_lock = asyncio.Lock()

        self.rx_task = None
        self.rx_active = False
        self.autostart = False
        self.syslog_ip = ""
        self.syslog_port = 514

        self.last_data = {"status": "waiting", "data": None, "rssi": 0, "time": ""}
        self.packet_log = []

        # Local logging buffer
        self.log_buffer = []
        self.log_last_flush = time.ticks_ms()

        self.load_config()
        self.syslog = SyslogClient(host=self.syslog_ip, port=self.syslog_port)

    def flush_log_buffer(self):
        if not self.log_buffer:
            return
        try:
            # Открываем файл на дозапись ('a')
            with open('lora_log.csv', 'a') as f:
                for line in self.log_buffer:
                    f.write(line + '\n')
            self.log_buffer = []
            self.log_last_flush = time.ticks_ms()
            print(f"[{self.name}] Буфер логов сброшен на флеш.")
        except Exception as e:
            print(f"[{self.name}] Ошибка записи лога на флеш: {e}")

    def load_config(self):
    ...
            with open('hardware.json', 'r') as f:
                hw = json.load(f)
                rx_conf = hw.get('gts_rx', {})
                self.autostart = rx_conf.get('autostart', False)
                self.syslog_ip = rx_conf.get('syslog_ip', "")
                self.syslog_port = int(rx_conf.get('syslog_port', 514))
        except: pass

    async def _get_lora(self):
        if self.lora_node is None:
            self.lora_node = LoRaNode()
            await self.lora_node.boot()
        return self.lora_node

    async def run(self):
        print(f"[{self.name}] Служба шлюза запущена.")
        if self.autostart:
            self.start_rx()
        while True:
            await asyncio.sleep(60)
            
    def log_packet(self, rssi, data):
        t_str = '{:02d}:{:02d}:{:02d}'.format(*time.localtime()[3:6])
        self.packet_log.insert(0, {"time": t_str, "rssi": rssi, "bat": data.get('bat', 0)})
        if len(self.packet_log) > 10:
            self.packet_log.pop()

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
        print(f"[{self.name}] Демон приемника запущен")
        lora = await self._get_lora()
        while self.rx_active:
            try:
                async with self.lora_lock:
                    data, rssi = await lora.listen(timeout_ms=0)

                if data:
                    if len(data) == 17:
                        unpacked = struct.unpack('<HhB6h', data)
                        parsed = {
                            "bat": unpacked[0] / 1000.0,
                            "air_t": unpacked[1] / 100.0,
                            "air_h": unpacked[2],
                            "soil": [s / 100.0 for s in unpacked[3:9]]
                        }
                        # Получаем текущее время для логов
                        t = time.localtime()
                        t_str = '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5])
                        date_str = '{:04d}-{:02d}-{:02d}'.format(t[0], t[1], t[2])
                        
                        self.last_data = {"status": "ok", "data": parsed, "rssi": rssi, "time": t_str}
                        self.log_packet(rssi, parsed)
                        print(f"[{self.name}] Принят пакет. RSSI:{rssi}")
                        
                        # Сохраняем в локальный буфер (CSV)
                        # Формат: YYYY-MM-DD HH:MM:SS, rssi, bat, air_t, air_h, soil0..soil5
                        soil_csv = ",".join([str(s) for s in parsed["soil"]])
                        csv_line = f"{date_str} {t_str},{rssi},{parsed['bat']},{parsed['air_t']},{parsed['air_h']},{soil_csv}"
                        self.log_buffer.append(csv_line)
                        
                        # Сбрасываем буфер, если записей > 20 или прошло больше часа
                        time_since_flush = time.ticks_diff(time.ticks_ms(), self.log_last_flush)
                        if len(self.log_buffer) >= 20 or time_since_flush > 3600000:
                            self.flush_log_buffer()
                        
                        if self.syslog_ip:
                            self.syslog.send(json.dumps({"rssi": rssi, "data": parsed}))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{self.name}] Ошибка приема: {e}")
                await asyncio.sleep(1)
            await asyncio.sleep_ms(10)
