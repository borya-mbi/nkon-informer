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

# Function to read existing value (check .env first, then system environment)
get_current_value() {
    local key=$1
    if [ -f ".env" ]; then
        local value=$(grep "^${key}=" .env | cut -d '=' -f2- | tr -d '\r')
        if [ -n "$value" ]; then
            echo "$value"
            return
        fi
    fi
    # Check system environment
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
    
    # Display current value mask/hint
    if [ -n "$current" ]; then
        local display="$current"
        # Mask sensitive data
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
    
    echo "" >&2
}

echo -e "${CYAN}--- NKON Monitor Setup (Linux) ---${NC}"

# Step 0: Choose storage method
echo -e "\n${YELLOW}Step 0: Choose storage method${NC}" >&2
echo "1) System (~/.bashrc) - Persistent across sessions" >&2
echo "2) .env file - Immediate and local to this folder (Recommended for testing)" >&2
read -p "Your choice (1 or 2, default is 2): " storage_choice >&2

if [ -z "$storage_choice" ]; then storage_choice="2"; fi

if [ "$storage_choice" = "1" ]; then
    echo -e "${YELLOW}Saving to ~/.bashrc. You may need to restart your shell later.${NC}" >&2
else
    if [ -f ".env" ]; then
        echo -e "${YELLOW}Found existing .env file. Press Enter to keep current values.${NC}" >&2
    fi
fi

# 1. Telegram Token (Required)
while true; do
    token=$(ask_variable "TELEGRAM_BOT_TOKEN" "Enter TELEGRAM_BOT_TOKEN" "true")
    if [ $? -eq 0 ] && [ -n "$token" ]; then
        break
    else
        echo -e "${RED}Token cannot be empty!${NC}"
    fi
done

# 2. Granular Chat IDs
echo -e "\n${YELLOW}Configuration for Notifications:${NC}"
chat_ids_full=$(ask_variable "TELEGRAM_CHAT_IDS_FULL" "Enter Chat IDs for FULL Reports (comma separated)" "false")
chat_ids_changes=$(ask_variable "TELEGRAM_CHAT_IDS_CHANGES_ONLY" "Enter Chat IDs for CHANGES ONLY (comma separated)" "false")

# Logic: Remove Changes IDs from Full IDs to avoid duplicates
if [ -n "$chat_ids_full" ] && [ -n "$chat_ids_changes" ]; then
    # Convert changes to array
    IFS=',' read -r -a changes_array <<< "$chat_ids_changes"
    
    # Clean full list
    cleaned_full=""
    IFS=',' read -r -a full_array <<< "$chat_ids_full"
    
    for id in "${full_array[@]}"; do
        # Trim whitespace
        id=$(echo "$id" | xargs)
        
        is_duplicate=false
        for change_id in "${changes_array[@]}"; do
             change_id=$(echo "$change_id" | xargs)
             if [ "$id" == "$change_id" ]; then
                 is_duplicate=true
                 break
             fi
        done
        
        if [ "$is_duplicate" == "false" ] && [ -n "$id" ]; then
            if [ -n "$cleaned_full" ]; then
                cleaned_full="$cleaned_full,$id"
            else
                cleaned_full="$id"
            fi
        elif [ "$is_duplicate" == "true" ]; then
            echo -e "${GRAY}Notice: ID $id removed from FULL list because it is in CHANGES ONLY list.${NC}"
        fi
    done
    
    chat_ids_full="$cleaned_full"
fi

# 4. Settings
min_cap=$(ask_variable "MIN_CAPACITY_AH" "Enter MIN_CAPACITY_AH" "false" "200")
threshold=$(ask_variable "PRICE_ALERT_THRESHOLD" "Enter PRICE_ALERT_THRESHOLD" "false" "5")
fetch_dates=$(ask_variable "FETCH_DELIVERY_DATES" "Fetch Delivery Dates for Pre-orders? (true/false)" "false" "true")
fetch_stock=$(ask_variable "FETCH_REAL_STOCK" "Probe Real Stock Quantity? (true/false)" "false" "true")
fetch_delay=$(ask_variable "DETAIL_FETCH_DELAY" "Delay between detail requests (seconds)" "false" "2")

# Generate content
env_content="# Telegram Configuration
TELEGRAM_BOT_TOKEN=$token

# Notification Groups (Comma separated IDs)
# Recipients for ALL reports (every run)
TELEGRAM_CHAT_IDS_FULL=$chat_ids_full

# Recipients for CHANGES ONLY (no spam if no changes)
TELEGRAM_CHAT_IDS_CHANGES_ONLY=$chat_ids_changes

# Thresholds
MIN_CAPACITY_AH=$min_cap
PRICE_ALERT_THRESHOLD=$threshold

# Delivery Date & Stock Settings
FETCH_DELIVERY_DATES=$fetch_dates
FETCH_REAL_STOCK=$fetch_stock
DETAIL_FETCH_DELAY=$fetch_delay

# Monitor URL
NKON_URL=https://www.nkon.nl/ua/rechargeable/lifepo4/prismatisch.html"

if [ "$storage_choice" = "1" ]; then
    # --- Option 1: ~/.bashrc ---
    BASHRC="$HOME/.bashrc"
    MARKER_START="# >>> NKON Monitor Config START >>>"
    MARKER_END="# <<< NKON Monitor Config END <<<"

    # Create a temporary file for the new bashrc content
    temp_bashrc=$(mktemp)
    
    # Remove existing block if present
    if grep -q "$MARKER_START" "$BASHRC" 2>/dev/null; then
        sed "/$MARKER_START/,/$MARKER_END/d" "$BASHRC" > "$temp_bashrc"
    else
        cat "$BASHRC" > "$temp_bashrc"
    fi

    # Append new block
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
    echo -e "${YELLOW}IMPORTANT: Run 'source ~/.bashrc' or restart shell to apply.${NC}"
else
    # --- Option 2: .env ---
    temp_env=$(mktemp)
    echo "$env_content" > "$temp_env"
    mv "$temp_env" .env
    chmod 600 .env
    echo -e "${GREEN}[SUCCESS] Configuration saved to .env file!${NC}"
fi

echo ""
