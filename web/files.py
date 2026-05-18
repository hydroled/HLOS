from .nanowebapi import send_file, HttpError
from .webserver import authenticate, CREDENTIALS
from lib.kernel import Service
import os, gc, uos


class Files(Service):
    def __init__(self, name, web):
        super().__init__(name)
        web.web_services.append(self.__class__.__name__)
        self.web = web

        self.web.app.route('/api/ls*')(self.api_ls)
        self.web.app.route('/api/mkdir/*')(self.api_mkdir)
        self.web.app.route('/api/download/*')(self.api_download)
        self.web.app.route('/api/delete/*')(self.api_delete)
        self.web.app.route('/api/upload/*')(self.upload)
        self.web.app.route('/show_content*')(self.show_content)

    async def api_ls(self, request):
        qs = str(request.url).split('?')
        if len(qs) > 1:
            params = qs[1].split('&')
            for p in params:
                if p.startswith('chdir='):
                    try:
                        val = p.split('=')[1]
                        # Простейший urldecode для / и пробелов
                        val = val.replace('%2F', '/').replace('%20', ' ')
                        os.chdir(val)
                        break
                    except:
                        pass

        currdir = os.getcwd()
        files = os.listdir()

        # Получаем данные о файлах
        file_stats = []
        for f in files:
            try:
                file_stats.append((f, os.stat(f)))
            except:
                continue

        # Умная сортировка (Папки сверху, файлы снизу по алфавиту)
        S_IFDIR = 16384
        sorted_files = sorted(file_stats, key=lambda x: (0 if (x[1][0] & S_IFDIR) else 1, x[0].lower()))

        dd = []
        if currdir != '/': dd.append(['..', S_IFDIR, 0])
        for f, s in sorted_files:
            dd.append([f, s[0], s[6]])

        ffd = uos.statvfs('/')
        await self.web.api_send_response(request, data={
            "files": dd, "currdir": currdir,
            "total": ffd[0] * ffd[2], "free": ffd[1] * ffd[3]
        })

    async def api_mkdir(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        dirname = request.url.split('/')[-1]
        try:
            os.mkdir(dirname)
            await self.web.api_send_response(request)
        except:
            raise HttpError(request, 500, "Mkdir error")

    async def api_delete(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        filename = request.url.split('/')[-1]
        try:
            os.remove(filename)
            await self.web.api_send_response(request)
        except:
            raise HttpError(request, 500, "Delete error")

    @authenticate(CREDENTIALS)
    async def api_download(self, request):
        filename = request.url.split('/')[-1]
        await request.write("HTTP/1.1 200 OK\r\nContent-Type: application/octet-stream\r\n")
        await request.write(f"Content-Disposition: attachment; filename={filename}\r\n\r\n")
        await send_file(request, filename, binary=True)

    async def show_content(self, request):
        qs = request.url.split('?')[1] if '?' in request.url else ''
        file_name = '';
        is_raw = False
        for p in qs.split('&'):
            if p.startswith('file_name='): file_name = p.split('=')[1]
            if p == 'raw=true': is_raw = True

        if not file_name: return 'No filename', 400

        await request.write(b"HTTP/1.1 200 OK\r\n")
        if is_raw:
            await request.write("Content-Type: text/plain; charset=utf-8\r\n\r\n")
            await send_file(request, file_name)
        else:
            await request.write("Content-Type: text/html; charset=utf-8\r\n\r\n")
            await request.write(
                "<html><body style='background:#eee;padding:20px;'><pre style='background:#fff;padding:15px;border-radius:8px;font-size:18px;white-space:pre-wrap;'>")
            await send_file(request, file_name)
            await request.write("</pre></body></html>")

    async def upload(self, request):
        if request.method == "OPTIONS": return await self.web.api_send_response(request)
        output_file = request.url.split('/')[-1]
        tmp_file = output_file + '.tmp'
        cl = request.headers.get('content-length', request.headers.get('Content-Length', 0))
        bytesleft = int(cl)

        try:
            with open(tmp_file, 'wb') as f:
                while bytesleft > 0:
                    chunk = await request.read(min(bytesleft, 128))
                    if not chunk: break
                    f.write(chunk)
                    bytesleft -= len(chunk)

            # Подменяем старый файл новым
            try:
                os.remove(output_file)
            except:
                pass
            os.rename(tmp_file, output_file)

            await self.web.api_send_response(request)
        except Exception:
            try:
                os.remove(tmp_file)  # Удаляем битый кусок при ошибке
            except:
                pass
            raise HttpError(request, 500, "Upload error")
