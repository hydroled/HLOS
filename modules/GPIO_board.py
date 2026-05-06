import uasyncio as asyncio
from lib.kernel import Service
import time
from machine import Pin


class GPIO_board(Service):
    def __init__(self, pins: list, **kwargs):
        super().__init__(**kwargs)
        self.pins = {}
        self.state = {'time': None, "name": kwargs.get('name') or self.name,
                      "label": kwargs.get('label') or "Управление оборудованием", "type": "web_standard", "data": []}

        print(f"[{self.name}] Инициализация пинов: {pins}")
        for p in pins:
            try:
                # Пытаемся поднять пин. Ошибка не остановит загрузку.
                p_ = Pin(p[0], p[1])
                self.pins[p[0]] = p_

                friendly_name = p[2] if len(p) > 2 else "GPIO-" + str(p[0])
                el_ = {"id": p[0], "value": p_.value(), "name": friendly_name, "indicator": "digital"}
                if Pin.OUT == p[1]:
                    el_["control"] = "digital"
                self.state['data'].append(el_)
            except ValueError:
                print(f" !!! ПРЕДУПРЕЖДЕНИЕ: Пин {p[0]} не поддерживается. Пропускаю.")
                continue

    def set_value(self, id, value):
        if id in self.pins:
            self.pins[id].value(1 if value else 0)
            for i in self.state['data']:
                if i['id'] == id:
                    i['value'] = self.pins[id].value()
                    self.state['time'] = time.time()
                    asyncio.create_task(self.subscribe_handler())

    async def tic(self):
        tt = time.time()
        changed = False
        for i in self.state['data']:
            if i["id"] in self.pins and i['value'] != self.pins[i["id"]].value():
                i['value'] = self.pins[i["id"]].value()
                self.state['time'] = tt
                changed = True
        return changed