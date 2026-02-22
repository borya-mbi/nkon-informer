#!/bin/bash
# Скрипт автоматичного налаштування logrotate для NKON Monitor
# Потрібні права root для запису в /etc/logrotate.d/

set -e

# Кольори
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Параметри
DRY_RUN=false
if [[ "$1" == "--dry-run" ]]; then
    DRY_RUN=true
fi

# Отримання директорії скрипта
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="$SCRIPT_DIR/nkon_cron.log"
CONF_FILE="/etc/logrotate.d/nkon-monitor"

echo -e "${CYAN}==========================================${NC}"
echo -e "${CYAN}  NKON Monitor - Налаштування Logrotate   ${NC}"
echo -e "${CYAN}==========================================${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}⚠️  РЕЖИМ ІМІТАЦІЇ (DRY RUN) - змін не буде внесено${NC}\n"
fi

# Перевірка наявності logrotate
if ! command -v logrotate &> /dev/null; then
    echo -e "${RED}❌ logrotate не встановлено!${NC}"
    echo -e "   Встановіть його: ${YELLOW}apt install logrotate${NC}"
    exit 1
fi
echo -e "${GREEN}✅ logrotate знайдено:${NC} $(logrotate --version 2>&1 | head -1)"

# Перевірка наявності файлу лога
if [ ! -f "$LOG_FILE" ]; then
    echo -e "📝 Файл лога ще не створено, створюємо: ${GRAY}$LOG_FILE${NC}"
    if [ "$DRY_RUN" = false ]; then
        touch "$LOG_FILE"
        chmod 644 "$LOG_FILE"
    fi
fi

echo -e "🔍 Директорія проекту: ${CYAN}$SCRIPT_DIR${NC}"
echo -e "🔍 Файл лога: ${CYAN}$LOG_FILE${NC}"
echo ""

# Створення конфігурації
echo -e "⚙️  Формування конфігурації в ${YELLOW}$CONF_FILE${NC}..."

CONF_CONTENT="$LOG_FILE {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}"

if [ "$DRY_RUN" = true ]; then
    echo -e "\n${YELLOW}--- Вміст конфігурації (тестовий вивід) ---${NC}"
    echo "$CONF_CONTENT"
    echo -e "${YELLOW}------------------------------------------${NC}"
else
    # Запис у файл через sudo tee
    echo "$CONF_CONTENT" | sudo tee "$CONF_FILE" > /dev/null
    echo -e "${GREEN}✅ Конфігурацію logrotate успішно створено!${NC}"
    echo ""
    echo -e "Вміст файлу ${YELLOW}$CONF_FILE${NC}:"
    cat "$CONF_FILE"
fi

echo ""
echo -e "💡 Для перевірки (dry-run) виконайте:"
echo -e "   ${YELLOW}logrotate -d $CONF_FILE${NC}"
echo ""
echo -e "💡 Для негайної ротації (force) виконайте:"
echo -e "   ${YELLOW}sudo logrotate -f $CONF_FILE${NC}"
echo ""
echo -e "${CYAN}==========================================${NC}"
