document.addEventListener('DOMContentLoaded', () => {
    // Настройки
    const nameInput = document.getElementById('sys-name');
    const tzInput = document.getElementById('sys-timezone');
    const saveSysBtn = document.getElementById('save-sys-btn');
    const sysStatus = document.getElementById('sys-status');

    // Безопасность
    const loginInput = document.getElementById('auth-login');
    const passInput = document.getElementById('auth-pass');
    const saveAuthBtn = document.getElementById('save-auth-btn');
    const authStatus = document.getElementById('auth-status');

    // Время
    const timeInput = document.getElementById('datetime-input');
    const saveTimeBtn = document.getElementById('save-time-btn');
    const timeStatus = document.getElementById('time-status');

    // Инфо
    const infoList = document.getElementById('system-info-list');

    async function fetchInfo() {
        try {
            const res = await fetch('/api/system/info');
            const data = await res.json();

            if (!data || !data.platform) throw new Error("Неверный формат");

            infoList.innerHTML = `
                <li><span class="info-label">Платформа:</span> <span class="info-value">${data.platform} (${data.machine})</span></li>
                <li><span class="info-label">Python:</span> <span class="info-value">${data.python_version}</span></li>
                <li><span class="info-label">CPU:</span> <span class="info-value">${data.cpu_freq_mhz} МГц</span></li>
                <li><span class="info-label">UID:</span> <span class="info-value">${data.unique_id}</span></li>
                <li><span class="info-label">RAM (Free/Total):</span> <span class="info-value">${data.ram_free_kb} / ${data.ram_free_kb + data.ram_alloc_kb} KB</span></li>
                <li><span class="info-label">ROM (Free/Total):</span> <span class="info-value">${data.rom_free_kb} / ${data.rom_total_kb} KB</span></li>
            `;
        } catch (e) { infoList.innerHTML = '<li><span style="color:red">Ошибка загрузки данных системы</span></li>'; }
    }

    async function fetchConfig() {
        try {
            const res = await fetch('/api/system/config');
            const data = await res.json();
            if (data.name) nameInput.value = data.name;
            if (data.timezone !== undefined) tzInput.value = data.timezone;
        } catch (e) {}
    }

    saveSysBtn.addEventListener('click', async () => {
        saveSysBtn.disabled = true; sysStatus.textContent = "Сохранение...";
        try {
            const res = await fetch('/api/system/config', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: nameInput.value.trim(), timezone: tzInput.value })
            });
            if (res.ok) { sysStatus.style.color="green"; sysStatus.textContent = "✅ Сохранено"; }
            else throw new Error();
        } catch (e) { sysStatus.style.color="red"; sysStatus.textContent = "❌ Ошибка"; }
        finally { saveSysBtn.disabled = false; }
    });

    saveAuthBtn.addEventListener('click', async () => {
        const login = loginInput.value.trim();
        const pass = passInput.value.trim();
        if (!login || !pass) { alert("Логин и пароль не могут быть пустыми"); return; }
        if(!confirm("Вы меняете пароль. Сразу после этого браузер попросит войти заново. Продолжить?")) return;

        saveAuthBtn.disabled = true; authStatus.textContent = "Меняем...";
        try {
            const res = await fetch('/api/system/setauth', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ login: login, password: pass })
            });
            if (res.ok) {
                alert("Пароль изменен! Сейчас браузер попросит войти с новыми данными.");
                window.location.reload();
            }
            else throw new Error();
        } catch (e) { authStatus.style.color="red"; authStatus.textContent = "❌ Ошибка"; }
        finally { saveAuthBtn.disabled = false; }
    });

    const now = new Date();
    now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
    timeInput.value = now.toISOString().slice(0, 16);

    saveTimeBtn.addEventListener('click', async () => {
        const dt = new Date(timeInput.value);
        if (isNaN(dt)) return;
        saveTimeBtn.disabled = true; timeStatus.textContent = "Отправка...";
        const payload = { year: dt.getFullYear(), month: dt.getMonth() + 1, day: dt.getDate(), hour: dt.getHours(), minute: dt.getMinutes(), second: dt.getSeconds() };
        try {
            const res = await fetch('/api/system/settime', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
            if (res.ok) { timeStatus.style.color="green"; timeStatus.textContent = "✅ Время установлено!"; }
            else throw new Error();
        } catch (e) { timeStatus.style.color="red"; timeStatus.textContent = "❌ Ошибка"; }
        finally { saveTimeBtn.disabled = false; }
    });

    document.getElementById('reboot-btn')?.addEventListener('click', async () => {
        if (!confirm("Перезагрузить устройство?")) return;
        try { await fetch('/api/system/reboot', { method: 'POST' }); } catch(e) {}
        setTimeout(() => window.location.href = '/', 6000);
    });

    document.getElementById('factory-reset-btn')?.addEventListener('click', async () => {
        if (!confirm("СБРОС WI-FI. Продолжить?")) return;
        try { await fetch('/api/system/factory_reset', { method: 'POST' }); } catch(e) {}
        alert("Сброс выполнен.");
    });

    fetchInfo();
    fetchConfig();
});