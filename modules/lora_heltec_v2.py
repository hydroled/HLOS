import machine
import uasyncio as asyncio
import time
from lib.kernel import Service


class LoRaNode:
    def __init__(self):
        # Пины Heltec V2
        self.cs = machine.Pin(18, machine.Pin.OUT, value=1)
        self.rst = machine.Pin(14, machine.Pin.OUT)
        self.vext = machine.Pin(21, machine.Pin.OUT)

        # Жесткое притягивание пина DIO0 к земле (защита от наводок Wi-Fi)
        self.dio0 = machine.Pin(26, machine.Pin.IN, machine.Pin.PULL_DOWN)

        # Скорость 1 МГц оптимальна для работы в фоновом потоке
        self.spi = machine.SPI(1, baudrate=1000000, polarity=0, phase=0,
                               sck=machine.Pin(5), mosi=machine.Pin(27), miso=machine.Pin(19))

        self.lock = asyncio.Lock()
        self.irq_flag = asyncio.ThreadSafeFlag()
        self.adc = machine.ADC(machine.Pin(37))
        self.adc.atten(machine.ADC.ATTN_11DB)

    async def _rw(self, reg, val=None):
        async with self.lock:
            self.cs.value(0)
            if val is None:
                self.spi.write(bytes([reg & 0x7F]))
                res = self.spi.read(1)[0]
            else:
                self.spi.write(bytes([reg | 0x80, val]))
                res = None
            self.cs.value(1)
            return res

    async def boot(self):
        self.vext.value(0)
        await asyncio.sleep_ms(500)
        self.rst.value(0)
        await asyncio.sleep_ms(100)
        self.rst.value(1)
        await asyncio.sleep_ms(200)

        # Режим 0x81 (Standby) — критичен для стабильности DIO0
        await self._rw(0x01, 0x81)
        if await self._rw(0x42) != 0x12: raise RuntimeError("LoRa Error")

        await self._rw(0x06, 108)
        await self._rw(0x07, 64)
        await self._rw(0x08, 0)
        await self._rw(0x1D, 0x72)
        await self._rw(0x1E, 0xA4)
        await self._rw(0x09, 0x8F)

        await self._rw(0x40, 0x00)
        self.dio0.irq(handler=lambda t: self.irq_flag.set(), trigger=machine.Pin.IRQ_RISING)
        print("LoRa Hardware Init OK (1MHz, Standby Mode)")

    async def send(self, data):
        payload = data.encode() if isinstance(data, str) else data
        await self._rw(0x01, 0x81)  # Standby
        await self._rw(0x40, 0x40)  # DIO0 -> TxDone
        await self._rw(0x0D, 0x00)  # FIFO pointer
        await self._rw(0x22, len(payload))

        # --- ИСПРАВЛЕНИЕ: Пакетная запись ---
        # Вместо цикла с await, записываем все данные в один заход через SPI.
        # Это предотвращает переполнение стека при длинных JSON-пакетах.
        async with self.lock:
            self.cs.value(0)
            self.spi.write(b'\x80' + payload)  # 0x80 - бит записи в FIFO (регистр 0x00)
            self.cs.value(1)

        await self._rw(0x01, 0x83)  # Переход в режим передачи (TX)

        try:
            # Ждем прерывания от модуля (TxDone)
            await asyncio.wait_for_ms(self.irq_flag.wait(), 3000)
            await self._rw(0x12, 0x08)  # Сброс флага TxDone в чипе
            return True
        except asyncio.TimeoutError:
            print("[LoRa] Send Timeout!")
            await self._rw(0x01, 0x81)
            return False

    async def listen(self, timeout_ms=0):
        await self._rw(0x01, 0x81)
        await self._rw(0x40, 0x00)
        await self._rw(0x01, 0x85)
        try:
            if timeout_ms > 0:
                await asyncio.wait_for_ms(self.irq_flag.wait(), timeout_ms)
            else:
                await self.irq_flag.wait()

            flags = await self._rw(0x12)
            if flags & 0x40:
                length = await self._rw(0x13)
                await self._rw(0x0D, await self._rw(0x10))
                data = bytearray()

                # --- ИСПРАВЛЕНИЕ: Пакетное чтение ---
                async with self.lock:
                    self.cs.value(0)
                    self.spi.write(bytes([0x00]))  # Адрес FIFO для чтения
                    data = self.spi.read(length)
                    self.cs.value(1)

                rssi = await self._rw(0x1A) - 164
                await self._rw(0x12, 0xFF)
                return data, rssi
        except asyncio.TimeoutError:
            pass
        return None, None

    def get_battery(self):
        val = self.adc.read()
        return (val / 4095) * 3.3 * 2
