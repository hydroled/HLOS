import ujson as json
import machine
import os
import sys
import gc
from .nanowebapi import HttpError
from .webserver import read_json, CREDENTIALS
import uasyncio as asyncio

class SystemApi():
    def __init__(self, name, web):
        web.web_services.append(self.__class__.__name__)
        self.web = web
        self.web.app.route('/api/system/info')(self.api_sys_info)
        self.web.app.route('/api/system/config')(self.api_config)
        self.web.app.route('/api/system/settime')(self.api_set_time)
        self.web.app.route('/api/system/setauth')(self.api_set_auth)
        self.web.app.route('/api/system/reboot')(self.api_reboot)
        self.web.app.route('/api/system/factory_reset')(self.api_factory_reset)

    # --- БЕЗОПАСНЫЕ ФУНКЦИИ РАБОТЫ С КОНФИГОМ ---
    def _get_sys_config(self):
        """Читает system.json или возвращает безопасный дефолт"""
        default_conf = {
            "name": "MyDevice",
            "timezone": 3,
            "login": "admin",
            "password": "password",
            "version": "0.1"
        }
        try:
            with open('system.json', 'r') as f:
                saved = json.load(f)
                if isinstance(saved, dict):
                    default_conf.update(saved)
        except Exception:
            pass
        return default_conf

    def _save_sys_config(self, updates):
        """Аккуратно обновляет только переданные ключи, не затирая остальные"""
        conf = self._get_sys_config()
        conf.update(updates)
        try:
            with open('system.json', 'w') as f:
                json.dump(conf, f)
            return True
        except Exception as e:
            print("Ошибка записи system.json:", e)
            return False
    # ---------------------------------------------

    async def api_sys_info(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        gc.collect()

        data = {
            "platform": "Unknown", "python_version": "Unknown", "release": "Unknown",
            "version": "Unknown", "machine": "Unknown", "cpu_freq_mhz": 0,
            "unique_id": "Unknown", "ram_alloc_kb": 0, "ram_free_kb": 0,
            "rom_total_kb": 0, "rom_free_kb": 0
        }

        try: data["platform"] = sys.platform
        except: pass

        try: data["python_version"] = sys.version.split(' ')[0]
        except: pass

        try:
            u = os.uname()
            data["release"] = u[2] if len(u)>2 else "unk"
            data["version"] = u[3] if len(u)>3 else "unk"
            data["machine"] = u[4] if len(u)>4 else "unk"
        except: pass

        try: data["cpu_freq_mhz"] = machine.freq() // 1000000
        except: pass

        try: data["unique_id"] = "".join(["{:02x}".format(b) for b in machine.unique_id()])
        except: pass

        try:
            ffd = os.statvfs('/')
            data["rom_total_kb"] = (ffd[0] * ffd[2]) // 1024
            data["rom_free_kb"] = (ffd[1] * ffd[3]) // 1024
        except: pass

        data["ram_alloc_kb"] = gc.mem_alloc() // 1024
        data["ram_free_kb"] = gc.mem_free() // 1024

        await self.web.api_send_response(request, data=data)

    async def api_config(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)

        if request.method == "GET":
            conf = self._get_sys_config()
            safe_conf = {"name": conf.get("name"), "timezone": conf.get("timezone")}
            await self.web.api_send_response(request, data=safe_conf)

        elif request.method == "POST":
            data = await read_json(request)
            if data:
                updates = {}
                if "name" in data:
                    updates['name'] = data['name']
                    self.web.name = data['name']
                if "timezone" in data:
                    updates['timezone'] = int(data['timezone'])

                if self._save_sys_config(updates):
                    await self.web.api_send_response(request, data={"status": "ok"})
                else:
                    raise HttpError(request, 500, "Save failed")
            else:
                raise HttpError(request, 400, "Bad Request")

    async def api_set_auth(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        data = await read_json(request)
        if data and "login" in data and "password" in data:
            updates = {
                'login': data['login'],
                'password': data['password']
            }
            if self._save_sys_config(updates):
                CREDENTIALS[0] = data['login']
                CREDENTIALS[1] = data['password']
                await self.web.api_send_response(request, data={"status": "ok"})
            else:
                raise HttpError(request, 500, "Save failed")
        else:
            raise HttpError(request, 400, "Bad Request")

    async def api_set_time(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        data = await read_json(request)
        if data:
            rtc = machine.RTC()
            rtc.datetime((data.get('year', 2020), data.get('month', 1), data.get('day', 1), 0, data.get('hour', 0), data.get('minute', 0), data.get('second', 0), 0))
            await self.web.api_send_response(request, data={"status": "ok"})
        else: raise HttpError(request, 400, "Bad Request")

    async def api_reboot(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        await self.web.api_send_response(request, data={"status": "rebooting"})
        async def do_reset():
            await asyncio.sleep(1)
            machine.reset()
        asyncio.create_task(do_reset())

    async def api_factory_reset(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        try: os.remove('wifi.json')
        except OSError: pass
        await self.web.api_send_response(request, data={"status": "resetting"})
        async def do_reset():
            await asyncio.sleep(1)
            machine.reset()
        asyncio.create_task(do_reset())