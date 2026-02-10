#!/bin/bash
# Скрипт автоматичного налаштування cron для NKON Monitor

set -e  # Вийти при помилці

echo "=========================================="
echo "NKON Monitor - Налаштування Cron"
echo "=========================================="
echo ""

# Отримання директорії скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$SCRIPT_DIR/nkon_monitor.py"
LOG_FILE="$SCRIPT_DIR/nkon_cron.log"

# Перевірка Python
echo "Перевірка Python..."

# Перевірка наявності віртуального середовища
if [ -d "$SCRIPT_DIR/venv" ]; then
    echo "✅ Знайдено віртуальне середовище"
    PYTHON_PATH="$SCRIPT_DIR/venv/bin/python3"
    if [ ! -f "$PYTHON_PATH" ]; then
        PYTHON_PATH="$SCRIPT_DIR/venv/bin/python"
    fi
    echo "Використовуватиметься: $PYTHON_PATH"
else
    echo "⚠️  Віртуальне середовище не знайдено (рекомендується)"
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python 3 не знайдено! Встановіть Python 3."
        exit 1
    fi
    PYTHON_PATH=$(which python3)
    echo "Використовуватиметься системний Python: $PYTHON_PATH"
    echo ""
    echo "💡 Рекомендація: створіть віртуальне середовище:"
    echo "   python3 -m venv venv"
    echo "   source venv/bin/activate"
    echo "   pip install -r requirements.txt"
    echo ""
fi

echo "✅ Python: $PYTHON_PATH"
echo ""

# Перевірка наявності скрипта
if [ ! -f "$PYTHON_SCRIPT" ]; then
    echo "❌ Скрипт не знайдено: $PYTHON_SCRIPT"
    exit 1
fi
echo "✅ Скрипт знайдено: $PYTHON_SCRIPT"
echo ""

# Перевірка конфігурації
CONFIG_FILE="$SCRIPT_DIR/config.json"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    echo "✅ Конфігурація знайдена: $ENV_FILE"
elif [ -f "$CONFIG_FILE" ]; then
    echo "✅ Конфігурація знайдена: $CONFIG_FILE"
else
    echo "❌ Конфігурація не знайдена!"
    echo "   Запустіть ./setup_env.sh для автоматичного налаштування"
    echo "   Або скопіюйте config.example.json → config.json"
    exit 1
fi
echo ""

# Перевірка залежностей
echo "Перевірка Python залежностей..."
if ! $PYTHON_PATH -c "import selenium, bs4, requests, dotenv, webdriver_manager" &> /dev/null; then
    echo "⚠️  Деякі залежності відсутні."
    read -p "Встановити зараз? (y/n) " -n 1 -r >&2
    echo "" >&2
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        $PYTHON_PATH -m pip install -r "$SCRIPT_DIR/requirements.txt"
        echo "✅ Залежності встановлено"
    else
        echo "❌ Встановіть залежності вручну: pip install -r requirements.txt"
        exit 1
    fi
else
    echo "✅ Всі залежності встановлені"
fi
echo ""

# Вибір розкладу
echo "Оберіть розклад запуску:"
echo "1) Щодня о 9:00"
echo "2) Кожні 6 годин"
echo "3) Тричі на день (9:00, 15:00, 21:00)"
echo "4) Власний розклад (введіть вручну)"
echo ""
read -p "Ваш вибір (1-4): " choice >&2

case $choice in
    1)
        CRON_SCHEDULE="0 9 * * *"
        DESCRIPTION="щодня о 9:00"
        ;;
    2)
        CRON_SCHEDULE="0 */6 * * *"
        DESCRIPTION="кожні 6 годин"
        ;;
    3)
        CRON_SCHEDULE="0 9,15,21 * * *"
        DESCRIPTION="тричі на день о 9:00, 15:00 та 21:00"
        ;;
    4)
        read -p "Введіть cron вираз (наприклад, '0 9 * * *'): " CRON_SCHEDULE >&2
        DESCRIPTION="власний розклад: $CRON_SCHEDULE" >&2
        ;;
    *)
        echo "❌ Невірний вибір"
        exit 1
        ;;
esac

echo ""
echo "Обраний розклад: $DESCRIPTION"
echo "Cron вираз: $CRON_SCHEDULE"
echo ""

# Створення cron job
CRON_COMMAND="$CRON_SCHEDULE cd $SCRIPT_DIR && $PYTHON_PATH $PYTHON_SCRIPT >> $LOG_FILE 2>&1"

# Перевірка чи такий job вже існує
if crontab -l 2>/dev/null | grep -q "$PYTHON_SCRIPT"; then
    echo "⚠️  Cron job для цього скрипта вже існує!"
    crontab -l | grep "$PYTHON_SCRIPT"
    echo ""
    read -p "Замінити? (y/n) " -n 1 -r >&2
    echo "" >&2
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Операцію скасовано"
        exit 0
    fi
    # Видалення старого job
    crontab -l 2>/dev/null | grep -v "$PYTHON_SCRIPT" | crontab -
fi

# Додавання нового job
(crontab -l 2>/dev/null; echo "$CRON_COMMAND") | crontab -

echo ""
echo "=========================================="
echo "✅ Cron job успішно налаштовано!"
echo "=========================================="
echo ""
echo "Розклад: $DESCRIPTION"
echo "Команда: $CRON_COMMAND"
echo ""
echo "Перегляд активних завдань:"
echo "  crontab -l"
echo ""
echo "Перегляд логів:"
echo "  tail -f $LOG_FILE"
echo ""
echo "Видалення cron job:"
echo "  crontab -e  # видаліть відповідний рядок"
echo ""
echo "=========================================="
