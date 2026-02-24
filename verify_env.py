#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Utility to verify and fix .env configuration for NKON Monitor.
"""

import os
import json
import re
import sys
import argparse
from typing import Dict, List, Any, Optional

def mask_token(token: str) -> str:
    if len(token) > 8:
        return f"{token[:4]}***{token[-4:]}"
    return "***"

def parse_env_manually(filepath: str) -> Dict[str, str]:
    """Reads .env file and handles multiline quoted values correctly."""
    env_vars = {}
    if not os.path.exists(filepath):
        return env_vars

    # Try python-dotenv first (handles all edge cases)
    try:
        from dotenv import dotenv_values
        env_vars = {k: v for k, v in dotenv_values(filepath).items() if v is not None}
        return env_vars
    except ImportError:
        pass

    # Fallback: stateful line-based parser
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue

        key, _, val = line.partition('=')
        key = key.strip()

        # Check for quoted multiline values
        if val.startswith("'") or val.startswith('"'):
            quote = val[0]
            if val.endswith(quote) and len(val) > 1:
                # Single-line quoted value
                env_vars[key] = val[1:-1]
            else:
                # Multiline: collect until closing quote
                parts = [val[1:]]  # strip opening quote
                while i < len(lines):
                    next_line = lines[i].rstrip('\n').rstrip('\r')
                    i += 1
                    if next_line.rstrip().endswith(quote):
                        parts.append(next_line.rstrip()[:-1])  # strip closing quote
                        break
                    parts.append(next_line)
                env_vars[key] = '\n'.join(parts)
        else:
            # Unquoted value (strip inline comments)
            val = val.split('#')[0].strip()
            env_vars[key] = val

    return env_vars

def fix_json_syntax(raw_json: str) -> str:
    """Fixes common JS-style errors like unquoted keys (e.g., name: -> \"name\":)."""
    # Fix unquoted keys like name: or chat_id:
    # This regex looks for word characters followed by a colon that are NOT already in quotes
    # It's a heuristic but works for our expected structure
    fixed = re.sub(r'([{,]\s*)([a-zA-Z_][a-zA-Z0-9_]*)(\s*):', r'\1"\2"\3:', raw_json)
    return fixed

def verify(filepath: str, fix: bool = False, beautify: bool = False):
    if not os.path.exists(filepath):
        print(f"❌ File {filepath} not found!")
        return

    print(f"🔍 Verifying {filepath} config...\n")
    
    # We use a manual parser here because python-dotenv might strip too much or be unavailable
    # but we ALSO check what settings.py would see
    raw_env = parse_env_manually(filepath)
    
    errors = []
    
    # 1. Check TELEGRAM_BOT_TOKEN
    token = raw_env.get('TELEGRAM_BOT_TOKEN')
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN: MISSING")
        errors.append("token_missing")
    else:
        print(f"✅ TELEGRAM_BOT_TOKEN: present ({mask_token(token)})")

    # 2. Check TELEGRAM_CONFIG_JSON
    raw_config = raw_env.get('TELEGRAM_CONFIG_JSON', '[]')
    is_valid_json = False
    config_data = []
    
    try:
        config_data = json.loads(raw_config)
        is_valid_json = True
        print("✅ TELEGRAM_CONFIG_JSON: valid JSON")
    except json.JSONDecodeError as e:
        print(f"❌ TELEGRAM_CONFIG_JSON: invalid JSON")
        print(f"   Помилка: {e}")
        
        # Try to fix it
        fixed_json = fix_json_syntax(raw_config)
        try:
            config_data = json.loads(fixed_json)
            print("   💡 Підказка: Знайдено помилки синтаксису (наприклад, пропущені лапки).")
            if fix:
                is_valid_json = True
                print("   🛠️  Автовиправлення застосовано.")
                raw_config = fixed_json
            else:
                print("   👉 Запустіть з прапорцем --fix для автоматичного виправлення.")
        except:
            print("   ⚠️  Помилка занадто складна для автовиправлення.")

    # 3. Check recipients health
    if is_valid_json:
        if not isinstance(config_data, list):
            print("❌ TELEGRAM_CONFIG_JSON: має бути масивом []")
        else:
            print(f"ℹ️  Знайдено отримувачів: {len(config_data)}")
            for i, rec in enumerate(config_data):
                res = []
                if 'chat_id' not in rec: res.append("miss_id")
                if 'type' not in rec: res.append("miss_type")
                if 'name' not in rec:
                    if fix:
                        print(f"   🛠️  Додаю name для отримувача {rec.get('chat_id', i)}")
                        rec['name'] = input(f"      Введіть ім'я для отримувача {rec.get('url', rec.get('chat_id', i))}: ").strip() or "Unnamed"
                    else:
                        res.append("miss_name")
                
                if res:
                    print(f"   ⚠️  Отримувач #{i+1}: {', '.join(res)}")
                else:
                    print(f"   ✅ Отримувач #{i+1}: '{rec['name']}' ({rec['chat_id']})")
                    
    # 4. Global Settings
    for key in ['MIN_CAPACITY_AH', 'NKON_URL']:
        if key in raw_env:
            print(f"✅ {key}: {raw_env[key]}")
        else:
            print(f"⚠️  {key}: missing (using defaults)")

    # APPLY CHANGES
    if fix or beautify:
        if is_valid_json:
            # Reconstruct the string
            if beautify:
                new_config_val = json.dumps(config_data, indent=2, ensure_ascii=False)
            else:
                new_config_val = json.dumps(config_data, separators=(',', ':'), ensure_ascii=False)

            # Read entire file content
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

            # Replace TELEGRAM_CONFIG_JSON value (handles both single-line and multiline)
            # Pattern: TELEGRAM_CONFIG_JSON= followed by quoted or unquoted value
            pattern = re.compile(
                r"TELEGRAM_CONFIG_JSON\s*=\s*(?:"
                r"'[^']*(?:'|$)"
                r'|"[^"]*(?:"|$)'
                r"|[^\n]*)",
                re.DOTALL
            )

            replacement = f"TELEGRAM_CONFIG_JSON='{new_config_val}'"

            if pattern.search(content):
                new_content = pattern.sub(replacement, content, count=1)
            else:
                new_content = content.rstrip() + f"\n{replacement}\n"

            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(new_content)

            print(f"\n🚀 Зміни збережено у {filepath}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NKON .env Validator")
    parser.add_argument("--fix", action="store_true", help="Автоматично виправляти JSON та додавати імена")
    parser.add_argument("--beautify", action="store_true", help="Зробити JSON у .env красивим та багаторядковим")
    parser.add_argument("--file", default=".env", help="Шлях до файлу (за замовчуванням .env)")
    
    args = parser.parse_args()
    verify(args.file, args.fix, args.beautify)
