import machine
import uasyncio as asyncio
from lib.kernel import Service
import time

class WatchdogService(Service):
    def __init__(self, name="Watchdog", timeout=60000):
        super().__init__(name)
        self.timeout = timeout
        self.wdt = None
        self.last_cause = machine.reset_cause()
        self.cause_str = self._get_cause_str(self.last_cause)
        
        # Если сброс был по WDT, пишем в лог
        if self.last_cause == 3: # WDT_RESET
            print(f"[{self.name}] ВНИМАНИЕ: Обнаружен сброс по Watchdog!")
            try:
                with open('/lora_log.csv', 'a') as f:
                    t = time.localtime()
                    ts = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(t[0], t[1], t[2], t[3], t[4], t[5])
                    f.write(f"{ts},0,0,0,0,0,0,CRITICAL: WDT REBOOT\n")
            except:
                pass

    def _get_cause_str(self, cause):
        # Коды сброса для ESP32
        causes = {
            1: "Power On (Включение)",
            2: "Hard Reset (Аппаратный)",
            3: "Watchdog Timer (Зависание)",
            4: "Deep Sleep (Выход из сна)",
            5: "Software Reset (Программный)"
        }
        return causes.get(cause, f"Unknown ({cause})")

    async def run(self):
        print(f"[{self.name}] Аппаратный Watchdog запущен ({self.timeout}мс)")
        # Инициализация аппаратного WDT
        self.wdt = machine.WDT(timeout=self.timeout)
        
        while True:
            # "Кормим" собаку каждые 1/4 периода таймаута
            self.wdt.feed()
            await asyncio.sleep(self.timeout / 4000)
            
    def get_status(self):
        return {
            "last_cause": self.cause_str,
            "raw_cause": self.last_cause,
            "timeout": self.timeout
        }
