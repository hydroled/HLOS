import uasyncio as asyncio
from modules.lora_heltec_v2 import LoRaService  # Путь, как ты просил
from lib.kernel import os_kernel, Service


class LoRaTestSender(Service):
    """Служба для динамического тестирования LoRa"""

    def __init__(self, lora_instance, name="LoRa_Test_Sender"):
        super().__init__(name=name)
        self.lora = lora_instance
        self.counter = 0

    async def run(self):
        # Этот принт должен появиться СРАЗУ
        print(f"[{self.name}] ТЕСТОВЫЙ ПОТОК АКТИВИРОВАН")

        # Даем время на boot() основного сервиса
        await asyncio.sleep(5)

        while True:
            try:
                # Научный мониторинг батареи
                v_bat = 1
                payload = "STEST|#{:d}|V:{:.2f}".format(self.counter, v_bat)

                print(f"[{self.name}] >>> ПОПЫТКА ОТПРАВКИ: {payload}")

                # Отправка. Lock в lora_heltec_v2 защитит SPI
                await self.lora.node.send(payload)

                print(f"[{self.name}] ПАКЕТ УШЕЛ")
                self.counter += 1
            except Exception as e:
                print(f"[{self.name}] ОШИБКА ТЕСТА: {e}")

            await asyncio.sleep(10)


# --- ДИНАМИЧЕСКАЯ ИНЖЕКЦИЯ ---
print("--- Dynamic Injection: LoRa -> HLOS Kernel ---")

# 1. Создаем сервис приема
lora = LoRaService(name="LoRa_Science")
os_kernel.add_task(lora)  # Регистрируем в списке ядра

# КРИТИЧНО: Явно запускаем корутину в уже работающем loop
asyncio.create_task(lora.run())

# 2. Создаем сервис отправки
test_sender = LoRaTestSender(lora)
os_kernel.add_task(test_sender)  #

# КРИТИЧНО: Явно запускаем вторую корутину
asyncio.create_task(test_sender.run())

print("--- Команды на запуск задач отданы. Проверь вывод. ---")