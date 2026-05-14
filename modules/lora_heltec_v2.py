# lora_heltec_v2.py
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

        self.dio0 = machine.Pin(26, machine.Pin.IN)

        self.spi = machine.SPI(1, baudrate=1000000, polarity=0, phase=0,
                               sck=machine.Pin(5), mosi=machine.Pin(27), miso=machine.Pin(19))

        self.lock = asyncio.Lock()
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

        # === ИСПРАВЛЕНИЕ: Правильный вход в режим LoRa ===
        # 1. Переходим в Sleep, чтобы разблокировать бит LoRa
        await self._rw(0x01, 0x80)
        await asyncio.sleep_ms(10)
        # 2. Только теперь переходим в рабочий Standby
        await self._rw(0x01, 0x81)
        await asyncio.sleep_ms(10)

        if await self._rw(0x42) != 0x12: raise RuntimeError("LoRa Error")

        await self._rw(0x06, 108);
        await self._rw(0x07, 64);
        await self._rw(0x08, 0)
        await self._rw(0x1D, 0x72);
        await self._rw(0x1E, 0xA4);
        await self._rw(0x09, 0x8F)
        await self._rw(0x0E, 0x00)  # TxBaseAddr
        await self._rw(0x0F, 0x00)  # RxBaseAddr

        await self._rw(0x40, 0x00)
        print("LoRa Hardware Init OK (LoRa Mode Active)")

    async def send(self, data):
        payload = data.encode() if isinstance(data, str) else data

        await self._rw(0x01, 0x81)  # Убеждаемся, что мы в Standby
        await self._rw(0x40, 0x40)  # DIO0 -> TxDone
        await self._rw(0x0D, 0x00)  # Сброс указателя FIFO
        await self._rw(0x22, len(payload))

        async with self.lock:
            self.cs.value(0)
            self.spi.write(b'\x80' + payload)
            self.cs.value(1)

        await self._rw(0x01, 0x83)  # TX Mode

        start = time.ticks_ms()
        try:
            # На SF10 21 байт передается ~370 мс. Таймаута в 3000 мс хватит с запасом.
            while self.dio0.value() == 0:
                if time.ticks_diff(time.ticks_ms(), start) > 3000:
                    print("[LoRa] Send Timeout!")
                    await self._rw(0x01, 0x81)
                    return False
                await asyncio.sleep_ms(50)
                
            await self._rw(0x12, 0x08)  # Очищаем флаг TxDone в чипе
            return True
        except Exception as e:
            print(f"[LoRa] Send Error: {e}")
            await self._rw(0x01, 0x81)
            return False

    async def listen(self, timeout_ms=0):
        await self._rw(0x01, 0x81)
        await self._rw(0x40, 0x00)
        await self._rw(0x01, 0x85)
        
        start_time = time.ticks_ms()
        try:
            while self.dio0.value() == 0:
                if timeout_ms > 0 and time.ticks_diff(time.ticks_ms(), start_time) > timeout_ms:
                    return None, None
                await asyncio.sleep_ms(50)

            flags = await self._rw(0x12)
            if flags & 0x40:
                length = await self._rw(0x13)
                await self._rw(0x0D, await self._rw(0x10))
                async with self.lock:
                    self.cs.value(0)
                    self.spi.write(bytes([0x00]))
                    data = self.spi.read(length)
                    self.cs.value(1)
                rssi = await self._rw(0x1A) - 164
                await self._rw(0x12, 0xFF)
                return data, rssi
        except Exception as e:
            print(f"[LoRa] Listen Error: {e}")
        return None, None

    def get_battery(self):
        return (self.adc.read() / 4095) * 3.3 * 2