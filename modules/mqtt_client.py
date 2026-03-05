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
        # Уникальный ID клиента из MAC-адреса
        self.client_id = ubinascii.hexlify(machine.unique_id())

    def load_config(self):
        try:
            with open('mqtt.json', 'r') as f:
                return json.loads(f.read())
        except Exception:
            # Дефолтный конфиг, если файла нет
            return {
                "server": "",
                "port": 1883,
                "user": "",
                "password": "",
                "topic": "hlos/device"
            }

    def _safe_disconnect(self):
        """Безопасное закрытие сокетов для экономии памяти"""
        if self.client:
            try:
                self.client.disconnect()
            except Exception:
                pass
        self.client = None
        gc.collect()

    def connect(self):
        self.config = self.load_config()
        if not self.config.get('server'):
            return False

        self._safe_disconnect()

        try:
            self.client = MQTTClient(
                client_id=self.client_id,
                server=self.config['server'],
                port=self.config.get('port', 1883),
                user=self.config.get('user'),
                password=self.config.get('password'),
                keepalive=30
            )
            # Привязываем функцию, которая будет обрабатывать входящие команды
            self.client.set_callback(self.sub_cb)

            # Подключаемся
            self.client.connect()

            # Подписываемся на топик команд
            cmd_topic = self.config.get('topic', 'hlos/device') + "/cmd"
            self.client.subscribe(cmd_topic)

            self.connected = True
            print(f"[MQTT] Подключено к {self.config['server']}")
            return True
        except Exception as e:
            print("[MQTT] Ошибка подключения:", e)
            self._safe_disconnect()
            self.connected = False
            return False

    def sub_cb(self, topic, msg):
        """Здесь мы будем ловить входящие команды от брокера"""
        print("[MQTT] Получена команда:", topic.decode(), msg.decode())
        # В будущем мы сможем передавать эти команды в наш cron_registry!

    async def run(self):
        while True:
            # Отдаем управление ядру
            await asyncio.sleep(1)

            # Если нет Wi-Fi - даже не пытаемся
            if self.net and not self.net.sta.isconnected():
                self.connected = False
                continue

            # Если не подключены к MQTT - пробуем подключиться
            if not self.connected:
                if not self.connect():
                    await asyncio.sleep(5)  # Пауза перед следующей попыткой
                continue

            # Если всё Ок - работаем
            try:
                # check_msg() НЕ БЛОКИРУЕТ ядро. Если есть сообщение, вызовет sub_cb
                self.client.check_msg()

                # Публикуем статистику (например, раз в 10 секунд)
                now = time.time()
                if now - self.last_pub > 10:
                    self.last_pub = now
                    state_topic = self.config.get('topic', 'hlos/device') + "/state"

                    payload = json.dumps({
                        "ram_free": gc.mem_free(),
                        "uptime_sec": time.ticks_ms() // 1000
                    })

                    self.client.publish(state_topic, payload)

                    # ПРИНУДИТЕЛЬНО собираем мусор после формирования JSON
                    gc.collect()

            except Exception as e:
                print("[MQTT] Сбой в цикле (потеря связи?):", e)
                self.connected = False
                self._safe_disconnect()
