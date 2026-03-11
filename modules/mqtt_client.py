from umqtt.simple import MQTTClient
import uasyncio as asyncio
import json
import machine
import ubinascii
import gc
import time
from lib.kernel import Service


class SimpleMQTT(Service):
    def __init__(self, name="MQTT", net_manager=None):
        super().__init__(name)
        self.net = net_manager
        self.client = None
        self.config = {}
        self.connected = False
        self.last_pub = 0
        self.client_id = b"HLOS_" + ubinascii.hexlify(machine.unique_id())

    def load_config(self):
        try:
            with open('mqtt.json', 'r') as f:
                return json.loads(f.read())
        except Exception as e:
            print("[MQTT-DEBUG] Ошибка чтения mqtt.json:", e)
            return {}

    def _safe_disconnect(self):
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None
        gc.collect()
        print("[MQTT-DEBUG] Соединение разорвано, память очищена.")

    def connect(self):
        print("[MQTT-DEBUG] Чтение конфига...")
        self.config = self.load_config()

        server = self.config.get('server')
        port = self.config.get('port', 1883)
        user = self.config.get('user')
        password = self.config.get('password')
        topic = self.config.get('topic', 'hlos/device')

        if not server:
            print("[MQTT-DEBUG] Сервер не задан, отмена подключения.")
            return False

        self._safe_disconnect()

        print(f"[MQTT-DEBUG] Подключение к {server}:{port} от имени '{user}'...")
        try:
            self.client = MQTTClient(
                client_id=self.client_id,
                server=server,
                port=port,
                user=user,
                password=password,
                keepalive=60
            )
            self.client.set_callback(self.sub_cb)

            print("[MQTT-DEBUG] Устанавливаем сокет (может занять пару секунд)...")
            self.client.connect()

            cmd_topic = topic + "/cmd"
            print(f"[MQTT-DEBUG] Подписка на {cmd_topic}...")
            self.client.subscribe(cmd_topic)

            self.connected = True
            print("[MQTT] ✅ Успешно подключено к брокеру!")
            return True

        except OSError as e:
            print(f"[MQTT-DEBUG] ❌ Сетевая ошибка сокета (OSError): {e}")
            self._safe_disconnect()
            self.connected = False
            return False
        except Exception as e:
            print(f"[MQTT-DEBUG] ❌ Ошибка подключения: {e}")
            self._safe_disconnect()
            self.connected = False
            return False

    def sub_cb(self, topic, msg):
        print(f"[MQTT] 📥 Получена команда: {topic.decode()} -> {msg.decode()}")

    async def run(self):
        print("[MQTT] Служба запущена. Ожидание сети...")
        while True:
            await asyncio.sleep(1)

            if self.net and not self.net.sta.isconnected():
                if self.connected:
                    print("[MQTT-DEBUG] Wi-Fi потерян. Ждем сеть...")
                    self.connected = False
                    self._safe_disconnect()
                continue

            if not self.connected:
                if not self.connect():
                    print("[MQTT-DEBUG] Ждем 5 сек перед новой попыткой...")
                    await asyncio.sleep(5)
                continue

            try:
                self.client.check_msg()

                now = time.time()
                # Берем интервал из конфига (по умолчанию 60 сек)
                pub_interval = self.config.get('pub_interval', 60)

                if now - self.last_pub > pub_interval:
                    self.last_pub = now
                    state_topic = self.config.get('topic', 'hlos/device') + "/state"

                    payload = json.dumps({
                        "ram_free": gc.mem_free(),
                        "uptime_sec": time.ticks_ms() // 1000
                    })

                    print(f"[MQTT-DEBUG] 📤 Публикация в {state_topic}: {payload}")
                    self.client.publish(state_topic, payload)
                    gc.collect()

            except OSError as e:
                print(f"[MQTT-DEBUG] ❌ Обрыв связи при передаче (OSError): {e}")
                self.connected = False
                self._safe_disconnect()
            except Exception as e:
                print(f"[MQTT-DEBUG] ❌ Неизвестный сбой в рабочем цикле: {e}")
                self.connected = False
                self._safe_disconnect()