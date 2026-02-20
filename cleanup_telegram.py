import requests
import settings
import json
import os
import sys

def delete_messages(chat_id, message_ids):
    """Видаляє список ID повідомлень."""
    token = settings.TELEGRAM_BOT_TOKEN
    base_url = f"https://api.telegram.org/bot{token}/deleteMessage"
    
    print(f"🧹 Починаю видалення {len(message_ids)} повідомлень...")
    
    success_count = 0
    for mid in message_ids:
        params = {"chat_id": chat_id, "message_id": mid}
        try:
            resp = requests.post(base_url, data=params)
            result = resp.json()
            if result.get("ok"):
                print(f"  ✅ Видалено ID: {mid}")
                success_count += 1
            else:
                print(f"  ❌ Не вдалося видалити {mid}: {result.get('description', 'Unknown error')}")
        except Exception as e:
            print(f"  ❌ Помилка для ID {mid}: {e}")
            
    print(f"\n✨ Готово! Успішно видалено: {success_count}")

if __name__ == "__main__":
    if not settings.RECIPIENTS:
        print("❌ Не знайдено отримувачів.")
        sys.exit(1)

    chat_id = settings.RECIPIENTS[0]['chat_id']
    state_file = 'state.json'
    current_ids = []

    # Спробуємо знайти актуальне ID зі state.json
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                last_msgs = state.get('last_messages', {}).get('_no_changes', {})
                for key, mid in last_msgs.items():
                    current_ids.append(mid)
        except: pass

    print(f"--- Telegram Cleanup Tool ---")
    print(f"Чат: {chat_id}")
    if current_ids:
        print(f"Знайдено в state.json (останні базові повідомлення): {current_ids}")
    
    print("\nВаріанти введення:")
    print("1. Список через кому (наприклад: 83158, 83159, 83160)")
    print("2. Діапазон через тире (наприклад: 83150-83165)")
    
    user_input = input("\nВведіть ID для видалення: ").strip()
    if not user_input:
        print("Нічого не введено.")
        sys.exit(0)

    target_ids = []
    try:
        if '-' in user_input:
            start, end = map(int, user_input.split('-'))
            target_ids = list(range(start, end + 1))
        else:
            target_ids = [int(i.strip()) for i in user_input.split(',')]
            
        confirm = input(f"⚠️ Видалити {len(target_ids)} повідомлень? (y/n): ")
        if confirm.lower() == 'y':
            delete_messages(chat_id, target_ids)
    except ValueError:
        print("❌ Помилка: введіть коректні числа.")
