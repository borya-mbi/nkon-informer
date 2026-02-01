#!/bin/bash

# Setup environment variables for NKON Monitor (Linux/Mac)
# This script interactively asks for configuration and saves it to a .env file.
# This ensures variables are available for Cron jobs and the Python script.

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check and set Timezone
CURRENT_TZ=$(cat /etc/timezone 2>/dev/null || date +%Z)
TARGET_TZ="Europe/Kyiv"

echo -e "${CYAN}--- System Timezone Setup ---${NC}"
echo -e "Current timezone: ${YELLOW}$CURRENT_TZ${NC}"

if [[ "$CURRENT_TZ" != "$TARGET_TZ" ]]; then
    read -p "Do you want to set timezone to $TARGET_TZ (Ukraine)? (y/N) " tz_confirm
    if [[ $tz_confirm =~ ^[Yy]$ ]]; then
        if command -v timedatectl &> /dev/null; then
            sudo timedatectl set-timezone $TARGET_TZ
            echo -e "${GREEN}Timezone set to $TARGET_TZ${NC}"
            echo -e "Current time: $(date)"
        else
            echo -e "${RED}Error: timedatectl not found. Please set timezone manually.${NC}"
        fi
    fi
else
    echo -e "${GREEN}Timezone is already correct.${NC}"
fi

echo ""
echo -e "${CYAN}--- NKON Monitor Setup (Linux) ---${NC}"
echo -e "This script will generate a ${YELLOW}.env${NC} file for configuration."

# Check if .env exists
if [ -f ".env" ]; then
    echo -e "${YELLOW}Warning: .env file already exists and will be overwritten.${NC}"
    read -p "Continue? (y/N) " confirm
    if [[ ! $confirm =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 1. Telegram Token
while true; do
    echo ""
    read -p "Enter TELEGRAM_BOT_TOKEN: " token
    if [ -n "$token" ]; then
        break
    else
        echo -e "${RED}Token cannot be empty!${NC}"
    fi
done

# 2. Chat IDs
echo ""
echo -e "Enter Chat IDs (separated by comma, e.g. 123456789,-100987654321)"
while true; do
    read -p "Enter TELEGRAM_CHAT_IDS: " chat_ids
    if [ -n "$chat_ids" ]; then
        break
    else
        echo -e "${RED}Chat IDs cannot be empty!${NC}"
    fi
done

# 3. Min Capacity
echo ""
read -p "Enter MIN_CAPACITY_AH (Default: 200): " min_cap
min_cap=${min_cap:-200}

# 4. Price Threshold
echo ""
read -p "Enter PRICE_ALERT_THRESHOLD (Default: 5): " threshold
threshold=${threshold:-5}

# Write to .env
cat > .env <<EOL
TELEGRAM_BOT_TOKEN=$token
TELEGRAM_CHAT_IDS=$chat_ids
MIN_CAPACITY_AH=$min_cap
PRICE_ALERT_THRESHOLD=$threshold
EOL

# Set secure permissions
chmod 600 .env

echo ""
echo -e "${GREEN}[SUCCESS] Configuration saved to .env file!${NC}"
echo -e "Permissions set to 600 (read/write only for owner)."
echo ""
echo -e "You can now run the monitor:"
echo -e "  ${CYAN}python3 nkon_monitor.py --dry-run${NC}"
