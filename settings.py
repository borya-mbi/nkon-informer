import os
import json
from datetime import time
from typing import List, Dict, Any

# Force reload of .env to ensure fresh data
try:
    from dotenv import load_dotenv
    load_dotenv(override=True)
except ImportError:
    pass

# --- Global Settings ---
NKON_URL = os.getenv('NKON_URL', 'https://www.nkon.nl/ua/rechargeable/lifepo4/prismatisch.html')
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
MIN_CAPACITY_AH = int(os.getenv('MIN_CAPACITY_AH', 200))
PRICE_ALERT_THRESHOLD = int(os.getenv('PRICE_ALERT_THRESHOLD', 5))
FETCH_DELIVERY_DATES = os.getenv('FETCH_DELIVERY_DATES', 'true').lower() == 'true'
FETCH_REAL_STOCK = os.getenv('FETCH_REAL_STOCK', 'true').lower() == 'true'
RESTOCK_THRESHOLD = int(os.getenv('RESTOCK_THRESHOLD', 100))
DETAIL_FETCH_DELAY = float(os.getenv('DETAIL_FETCH_DELAY', 2.0))

# --- Quiet Mode (Global Defaults) ---
QUIET_HOURS_START = int(os.getenv('QUIET_HOURS_START', 21))
QUIET_HOURS_END = int(os.getenv('QUIET_HOURS_END', 8))

# --- Recipients Configuration ---
raw_config = os.getenv('TELEGRAM_CONFIG_JSON', '[]')
RECIPIENTS: List[Dict[str, Any]] = []

try:
    RECIPIENTS = json.loads(raw_config)
except json.JSONDecodeError:
    # Use empty list if JSON is invalid to prevent crash
    print(f"❌ Error parsing TELEGRAM_CONFIG_JSON: {raw_config}")
    RECIPIENTS = []

# --- Smart Heartbeat ---
_hb_times = os.getenv('HEARTBEAT_TIMES', '8:00').split(',')
HEARTBEAT_TIMES = []
for t in _hb_times:
    try:
        # Support both 8:00 and 08:00
        parts = t.strip().split(':')
        if len(parts) == 2:
            H, M = map(int, parts)
            HEARTBEAT_TIMES.append(time(hour=H, minute=M))
    except (ValueError, TypeError):
        pass
