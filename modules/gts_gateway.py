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
        
        self.load_config()
        self.syslog = SyslogClient(host=self.syslog_ip, port=self.syslog_port)

    def load_config(self):
        try:
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
                    data, rssi = await lora.listen(timeout_ms=1000)

                if data:
                    if len(data) == 21:
                        unpacked = struct.unpack('<HhB8h', data)
                        parsed = {
                            "bat": unpacked[0] / 1000.0,
                            "air_t": unpacked[1] / 100.0,
                            "air_h": unpacked[2],
                            "soil": [s / 100.0 for s in unpacked[3:11]]
                        }
                        t_str = '{:02d}:{:02d}:{:02d}'.format(*time.localtime()[3:6])
                        self.last_data = {"status": "ok", "data": parsed, "rssi": rssi, "time": t_str}
                        
                        self.log_packet(rssi, parsed)
                        print(f"[{self.name}] Принят пакет. RSSI:{rssi}")
                        
                        if self.syslog_ip:
                            self.syslog.send(json.dumps({"rssi": rssi, "data": parsed}))
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[{self.name}] Ошибка приема: {e}")
                await asyncio.sleep(1)
            await asyncio.sleep_ms(10)
