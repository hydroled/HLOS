import machine
import uasyncio as asyncio
import ujson as json
import ustruct as struct
import time
import usocket as socket
import gc
from lib.kernel import Service
from modules.lora_heltec_v2 import LoRaNode

class GtsGateway(Service):
    def __init__(self, name="GTS_Gateway"):
        super().__init__(name)
        self.lora_node = None
        self.lora_lock = asyncio.Lock()
        self.rx_task = None
        self.rx_active = False
        self.autostart = False
        self.syslog_ip = ""
        self.last_data = {"status": "waiting", "data": None, "rssi": 0, "time": "", "date": ""}
        self.packet_log = []
        self.local_bat = 0.0
        try:
            uid = machine.unique_id()
            self.device_id = struct.unpack('>H', uid[-2:])[0]
        except: self.device_id = 0
        self.log_buffer = []
        self.log_last_flush = time.ticks_ms()
        self.load_config()

    def flush_log_buffer(self):
        if not self.log_buffer: return
        try:
            with open('/lora_log.csv', 'a') as f:
                for line in self.log_buffer: f.write(line + '\n')
            self.log_buffer = []
            self.log_last_flush = time.ticks_ms()
        except: pass

    def load_config(self):
        try:
            try: os.chdir('/')
            except: pass
            with open('hardware.json', 'r') as f:
                hw = json.load(f)
                rx_conf = hw.get('gts_rx', hw.get('gts', {}))
                self.autostart = rx_conf.get('autostart', False)
                self.syslog_ip = rx_conf.get('syslog_ip', "")
        except: pass

    async def _get_lora(self):
        if self.lora_node is None:
            self.lora_node = LoRaNode()
            await self.lora_node.boot()
        return self.lora_node

    async def run(self):
        if self.autostart: self.start_rx()
        while True:
            gc.collect()
            await asyncio.sleep(60)
            
    def log_packet(self, rssi, data):
        t = time.localtime()
        t_str = '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5])
        date_str = '{:04d}-{:02d}-{:02d}'.format(t[0], t[1], t[2])
        self.packet_log.insert(0, {
            "time": t_str, "date": date_str, "rssi": rssi, 
            "bat": data.get('bat', 0), "device_id": data.get('device_id', 0),
            "mode": data.get('mode', 0)
        })
        if len(self.packet_log) > 10: self.packet_log.pop()

    def start_rx(self):
        if not self.rx_active:
            self.rx_active = True
            self.rx_task = asyncio.create_task(self.rx_daemon())

    def stop_rx(self):
        self.rx_active = False
        if self.rx_task: self.rx_task.cancel(); self.rx_task = None

    async def rx_daemon(self):
        lora = await self._get_lora()
        while self.rx_active:
            try:
                async with self.lora_lock:
                    data, rssi = await lora.listen(timeout_ms=0)
                if data and len(data) == 22:
                    unpacked = struct.unpack('<HHHhBB6h', data)
                    if unpacked[0] == 0x4753:
                        parsed = {
                            "device_id": unpacked[1], "bat": unpacked[2] / 1000.0,
                            "air_t": unpacked[3] / 100.0, "air_h": unpacked[4],
                            "mode": unpacked[5], "soil": [s / 100.0 for s in unpacked[6:12]]
                        }
                        t = time.localtime()
                        t_str = '{:02d}:{:02d}:{:02d}'.format(t[3], t[4], t[5])
                        date_str = '{:04d}-{:02d}-{:02d}'.format(t[0], t[1], t[2])
                        self.last_data = {"status": "ok", "data": parsed, "rssi": rssi, "time": t_str, "date": date_str}
                        self.log_packet(rssi, parsed)
                        
                        soil_csv = ",".join([str(s) for s in parsed["soil"]])
                        self.log_buffer.append(f"{date_str} {t_str},{parsed['device_id']},{parsed['mode']},{rssi},{parsed['bat']},{parsed['air_t']},{parsed['air_h']},{soil_csv}")
                        if len(self.log_buffer) >= 5: self.flush_log_buffer()
            except:
                await asyncio.sleep(1)
            await asyncio.sleep_ms(100) # Мягкий цикл
