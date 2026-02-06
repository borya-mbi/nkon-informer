# ✅ Proxmox LXC Deployment Checklist

Швидкий чеклист для розгортання NKON Monitor на Proxmox LXC.

## 📋 Підготовка

- [ ] Proxmox сервер доступний та працює
- [ ] Telegram бот створений (Bot Token отриманий)
- [ ] Telegram Chat ID(s) отримані
- [ ] Файли проєкту готові до перенесення

---

## 🐧 Створення LXC контейнера

### Варіант A: Автоматично через скрипт (ШВИДКО!)

- [ ] Скопіюйте `create_lxc.sh` на Proxmox хост
- [ ] Відредагуйте параметри (CTID, PASSWORD)
- [ ] Запустіть: `bash create_lxc.sh`
- [ ] Дочекайтеся завершення

### Варіант B: Вручну через Web UI

- [ ] **Create CT** в Proxmox Web UI
  - [ ] Hostname: `nkon-monitor`
  - [ ] Template: `ubuntu-22.04-standard` або `debian-12-standard`
  - [ ] RAM: `512 MB`
  - [ ] CPU: `1 core`
  - [ ] Disk: `4 GB`
  - [ ] Network: DHCP або статичний IP
  - [ ] Unprivileged: ✓
- [ ] **Start** контейнер
- [ ] **Налаштувати автозапуск:** `pct set <CTID> -onboot 1`

---

## 🔧 Встановлення в LXC

### Підключення
```bash
pct enter <CTID>
```

### Крок 1: Система
- [ ] `apt update && apt upgrade -y`
- [ ] `apt install -y python3 python3-pip python3-venv git`

### Крок 2: Chrome
- [ ] `wget https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb`
- [ ] `apt install -y ./google-chrome-stable_current_amd64.deb`
- [ ] `rm google-chrome-stable_current_amd64.deb`
- [ ] Перевірка: `google-chrome --version`

### Крок 3: Проєкт
- [ ] Створити директорію: `cd /root && mkdir nkon-informer`
- [ ] Завантажити файли (Git / SCP / вручну)
- [ ] `cd /root/nkon-informer`

### Крок 4: Python середовище
- [ ] `python3 -m venv venv`
- [ ] `source venv/bin/activate`
- [ ] `pip install -r requirements.txt`

### Крок 5: Конфігурація (Рекомендовано!)
- [ ] `./setup_env.sh` - запустити інтерактивне налаштування
- [ ] Дотримуватися інструкцій (ввести Bot Token та розділити Chat IDs)
- [ ] Переконатися, що створено файл `.env`
- [ ] `chmod 600 .env`

### Крок 6: Тестування
- [ ] **Dry-run:** `python nkon_monitor.py --dry-run`
- [ ] Перевірити вивід в консолі
- [ ] **Реальний запуск:** `python nkon_monitor.py`
- [ ] Отримано Telegram повідомлення ✓

---

## ⏰ Налаштування Cron

### Команда
- [ ] `crontab -e`
- [ ] Вибрати редактор (nano)

### Додати рядок
```cron
# Щодня о 9:00
0 9 * * * cd /root/nkon-informer && /root/nkon-informer/venv/bin/python /root/nkon-informer/nkon_monitor.py >> /root/nkon-informer/nkon_cron.log 2>&1
```

### Альтернативні розклади
```cron
# Кожні 6 годин
0 */6 * * * cd /root/nkon-informer && /root/nkon-informer/venv/bin/python /root/nkon-informer/nkon_monitor.py >> /root/nkon-informer/nkon_cron.log 2>&1

# Тричі на день (9:00, 15:00, 21:00)
0 9,15,21 * * * cd /root/nkon-informer && /root/nkon-informer/venv/bin/python /root/nkon-informer/nkon_monitor.py >> /root/nkon-informer/nkon_cron.log 2>&1
```

### Перевірка
- [ ] `crontab -l` - список завдань
- [ ] Дочекатися наступного запуску
- [ ] `tail -f /root/nkon-informer/nkon_cron.log` - перевірити логи

---

## ✅ Фінальна перевірка

- [ ] LXC контейнер працює
- [ ] Cron налаштований
- [ ] Отримано тестове Telegram повідомлення
- [ ] Логи пишуться: `tail -f nkon_monitor.log`
- [ ] Автозапуск LXC увімкнений: `pct config <CTID> | grep onboot`

---

## 📁 Файли в контейнері

```
/root/nkon-informer/
├── nkon_monitor.py       ✓
├── requirements.txt      ✓
├── .env                  ✓ (з вашими credentials)
├── .env.example          ✓
├── state.json           (створюється автоматично)
├── nkon_monitor.log     (логи скрипта)
├── nkon_cron.log        (логи cron)
└── venv/                ✓ (Python віртуальне середовище)
```

---

## 🛡️ Безпека

- [ ] `chmod 600 /root/nkon-informer/.env`
- [ ] Не публікувати .env в Git
- [ ] Регулярні оновлення: `apt update && apt upgrade`

---

## 💾 Бекап

### Створення бекапу (Proxmox Web UI)
- [ ] Datacenter → Backup → Create
- [ ] Select: ваш NKON container
- [ ] Mode: Snapshot
- [ ] Compression: ZSTD

### Або через CLI
```bash
vzdump <CTID> --mode snapshot --compress zstd
```

---

## 🔄 Оновлення скрипта

> **Важливо:** Варіант оновлення залежить від того, як ви встановлювали проєкт!

### Варіант A: Git Clone

```bash
pct enter <CTID>
cd /root/nkon-informer
source venv/bin/activate
git pull
pip install -r requirements.txt
python nkon_monitor.py --dry-run
```

### Варіант B: SCP

```bash
# Windows (PowerShell):
scp -r H:\Work\MBI\Education\AG\nkon-informer\*.py root@<LXC_IP>:/root/nkon-informer/

# LXC:
pct enter <CTID>
cd /root/nkon-informer
source venv/bin/activate
pip install -r requirements.txt
python nkon_monitor.py --dry-run
```

### Варіант C: Ручне редагування

```bash
nano /root/nkon-informer/nkon_monitor.py
# (вставити оновлений код)
source venv/bin/activate
pip install -r requirements.txt
python nkon_monitor.py --dry-run
```

---

## 📊 Моніторинг

### Перегляд логів
```bash
# Основний лог
tail -f /root/nkon-informer/nkon_monitor.log

# Cron лог
tail -f /root/nkon-informer/nkon_cron.log

# Системний cron лог
grep CRON /var/log/syslog | tail -20
```

---

## ❌ Troubleshooting

### Chrome не працює
```bash
apt install -y fonts-liberation libasound2 libatk-bridge2.0-0 libatk1.0-0 \
  libatspi2.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 libgtk-3-0 libnspr4 \
  libnss3 libwayland-client0 libxcomposite1 libxdamage1 libxfixes3 \
  libxkbcommon0 libxrandr2 xdg-utils
```

### Cron не виконується
```bash
systemctl status cron
systemctl restart cron
```

### Немає інтернету
```bash
ping google.com
echo "nameserver 8.8.8.8" >> /etc/resolv.conf
```

---

**🎉 Готово! Ваш NKON Monitor запущений на Proxmox LXC!**
