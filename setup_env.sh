#!/bin/bash

# Setup environment variables for NKON Monitor (Linux/Mac)
# This script interactively asks for configuration and saves it to a .env file.

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
GRAY='\033[0;90m'
NC='\033[0m' # No Color

# Function to read existing value
get_current_value() {
    local key=$1
    if [ -f ".env" ]; then
        # Use Python to reliably read .env (handles quoted values)
        local value=$(RKEY="$key" python3 -c "
import os
key = os.environ['RKEY']
try:
    from dotenv import dotenv_values
    vals = dotenv_values('.env')
    v = vals.get(key, '')
    if v:
        print(v)
except ImportError:
    # Fallback: simple line-based parsing
    with open('.env', 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line.startswith(key + '='):
                val = line.split('=', 1)[1]
                if (val.startswith(\"'\") and val.endswith(\"'\")) or (val.startswith('\"') and val.endswith('\"')):
                    print(val[1:-1])
                else:
                    print(val)
                break
" 2>/dev/null | tr -d '\r')
        if [ -n "$value" ]; then
            echo "$value"
            return
        fi
    fi
    printenv "$key"
}

# Function to ask for variable with "Keep Existing" logic
ask_variable() {
    local name=$1
    local prompt_text=$2
    local required=$3
    local default_value=$4
    
    local current=$(get_current_value "$name")
    local prompt="$prompt_text"
    
    if [ -n "$current" ]; then
        local display="$current"
        if [[ "$name" == *"TOKEN"* ]]; then
            if [ ${#current} -gt 8 ]; then
                display="${current:0:4}...${current: -4}"
            else
                display="***"
            fi
        fi
        prompt="$prompt [Current: $display]"
    elif [ -n "$default_value" ]; then
        prompt="$prompt [Default: $default_value]"
    fi
    
    echo "" >&2
    read -p "$prompt: " input_val >&2
    
    if [ -z "$input_val" ]; then
        if [ -n "$current" ]; then
            echo "$current"
            return
        fi
        if [ -n "$default_value" ]; then
            echo "$default_value"
            return
        fi
    else
        echo "$input_val"
        return
    fi
    
    if [ "$required" = "true" ]; then
        return 1
    fi
}

echo -e "${CYAN}--- NKON Monitor Setup (Linux) ---${NC}"

# Step 1: Choose storage method
echo -e "\n${YELLOW}Step 1: Choose storage method${NC}" >&2
echo "1) System (~/.bashrc) - Persistent across sessions" >&2
echo "2) .env file - Immediate and local to this folder (Recommended)" >&2
read -p "Your choice (1 or 2, default is 2): " storage_choice >&2
if [ -z "$storage_choice" ]; then storage_choice="2"; fi

# Step 2: Global Configuration
echo -e "\n${YELLOW}Step 2: Global Configuration${NC}" >&2

token=$(ask_variable "TELEGRAM_BOT_TOKEN" "Enter TELEGRAM_BOT_TOKEN" "true")
min_cap=$(ask_variable "MIN_CAPACITY_AH" "Enter Global MIN_CAPACITY_AH" "false" "200")
threshold=$(ask_variable "PRICE_ALERT_THRESHOLD" "Enter PRICE_ALERT_THRESHOLD" "false" "5")
fetch_dates=$(ask_variable "FETCH_DELIVERY_DATES" "Fetch Delivery Dates for Pre-orders? (true/false)" "false" "true")
fetch_stock=$(ask_variable "FETCH_REAL_STOCK" "Probe Real Stock Quantity? (true/false)" "false" "true")
fetch_delay=$(ask_variable "DETAIL_FETCH_DELAY" "Delay between detail requests (seconds)" "false" "2")
quiet_start=$(ask_variable "QUIET_HOURS_START" "Quiet hours START (hour 0-23)" "false" "21")
quiet_end=$(ask_variable "QUIET_HOURS_END" "Quiet hours END (hour 0-23)" "false" "8")
heartbeat=$(ask_variable "HEARTBEAT_TIMES" "Heartbeat times (e.g. 8:00,12:00)" "false" "8:00")

# Step 3: Granular Recipients Wizard
echo -e "\n${YELLOW}Step 3: Granular Recipients Wizard${NC}" >&2
current_json=$(get_current_value "TELEGRAM_CONFIG_JSON")
recipients_json="[]"

if [ -n "$current_json" ]; then
    recipients_json="$current_json"
    count=$(RJSON="$recipients_json" python3 -c "import json,os; print(len(json.loads(os.environ['RJSON'])))")
    echo -e "${GRAY}Found $count existing recipients.${NC}"
fi

read -p "Manage recipients? (y = start wizard, n/Enter = keep current): " manage
if [ "$manage" = "y" ]; then
    read -p "  (a) Append to existing or (r) Reset and start new? [default: a]: " mode
    if [ -z "$mode" ]; then mode="a"; fi
    
    if [ "$mode" = "r" ]; then
        recipients_json="[]"
    fi

    done=false
    while [ "$done" = "false" ]; do
        echo -e "\n${GRAY}--- Adding Recipient ---${NC}"
        read -p "  Chat ID (required, use -100xxx for channels/groups): " chatId
        if [ -z "$chatId" ]; then
            count=$(RJSON="$recipients_json" python3 -c "import json,os; print(len(json.loads(os.environ['RJSON'])))")
            if [ "$count" -eq 0 ]; then
                echo -e "${RED}Chat ID is required!${NC}"
                continue
            else
                break
            fi
        fi
        
        read -p "  Report Type (full/changes, default: changes): " type
        if [ -z "$type" ]; then type="changes"; fi
        
        read -p "  Thread ID (optional topic ID, Enter to skip): " thread
        read -p "  Custom Min Ah (default: $min_cap): " recMinAh
        if [ -z "$recMinAh" ]; then recMinAh=$min_cap; fi

        read -p "  Header Link URL (mandatory for first recipient, Enter to skip for others): " url
        count=$(RJSON="$recipients_json" python3 -c "import json,os; print(len(json.loads(os.environ['RJSON'])))")
        if [ -z "$url" ] && [ "$count" -eq 0 ]; then
            echo -e "${RED}Header Link URL is required for the first recipient!${NC}"
            continue
        fi

        read -p "  Name for footer (optional, e.g. Канал): " name

        # Use Python to safely update the JSON array
        recipients_json=$(
            RJSON="$recipients_json" \
            R_CHAT="$chatId" \
            R_TYPE="$type" \
            R_MIN="$recMinAh" \
            R_THREAD="$thread" \
            R_URL="$url" \
            R_NAME="$name" \
            python3 -c "
import json, os
data = json.loads(os.environ['RJSON'])
new_rec = {
    'chat_id': os.environ['R_CHAT'],
    'type': os.environ['R_TYPE'],
    'min_capacity_ah': int(os.environ['R_MIN'])
}
t = os.environ.get('R_THREAD', '')
if t:
    new_rec['thread_id'] = int(t)
u = os.environ.get('R_URL', '')
if u:
    new_rec['url'] = u
n = os.environ.get('R_NAME', '')
if n:
    new_rec['name'] = n
data.append(new_rec)
print(json.dumps(data, separators=(',', ':')))
")
        
        read -p "Add another recipient? (y/n, default: n): " another
        if [ "$another" != "y" ]; then done=true; fi
    done
fi

# Generate content
env_content="# Telegram Configuration
TELEGRAM_BOT_TOKEN=$token
TELEGRAM_CONFIG_JSON='$recipients_json'

# Scraper Thresholds
MIN_CAPACITY_AH=$min_cap
PRICE_ALERT_THRESHOLD=$threshold

# Quiet Mode
QUIET_HOURS_START=$quiet_start
QUIET_HOURS_END=$quiet_end

# Delivery Date & Stock Settings
FETCH_DELIVERY_DATES=$fetch_dates
FETCH_REAL_STOCK=$fetch_stock
DETAIL_FETCH_DELAY=$fetch_delay
HEARTBEAT_TIMES=$heartbeat

# Monitor URL
NKON_URL=https://www.nkon.nl/ua/rechargeable/lifepo4/prismatisch.html"

if [ "$storage_choice" = "1" ]; then
    # --- Option 1: ~/.bashrc ---
    BASHRC="$HOME/.bashrc"
    MARKER_START="# >>> NKON Monitor Config START >>>"
    MARKER_END="# <<< NKON Monitor Config END <<<"

    temp_bashrc=$(mktemp)
    if grep -q "$MARKER_START" "$BASHRC" 2>/dev/null; then
        sed "/$MARKER_START/,/$MARKER_END/d" "$BASHRC" > "$temp_bashrc"
    else
        cat "$BASHRC" > "$temp_bashrc"
    fi

    echo "$MARKER_START" >> "$temp_bashrc"
    echo "$env_content" | while read -r line; do
        if [[ $line == *"="* ]]; then
            echo "export $line" >> "$temp_bashrc"
        else
            echo "$line" >> "$temp_bashrc"
        fi
    done
    echo "$MARKER_END" >> "$temp_bashrc"

    mv "$temp_bashrc" "$BASHRC"
    echo -e "${GREEN}[SUCCESS] Configuration saved to ~/.bashrc!${NC}"
else
    # --- Option 2: .env ---
    echo "$env_content" > .env
    chmod 600 .env
    echo -e "${GREEN}[SUCCESS] Configuration saved to .env file!${NC}"
fi
