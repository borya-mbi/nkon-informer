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

def delete_message(chat_id, mid, token):
    """Видаляє одне повідомлення."""
    base_url = f"https://api.telegram.org/bot{token}/deleteMessage"
    params = {"chat_id": chat_id, "message_id": mid}
    try:
        resp = requests.post(base_url, data=params, timeout=10)
        return resp.json().get("ok", False), resp.json().get("description", "Error")
    except Exception as e:
        return False, str(e)

if __name__ == "__main__":
    if not settings.RECIPIENTS:
        print("❌ Не знайдено отримувачів у конфігурації.")
        sys.exit(1)

    token = settings.TELEGRAM_BOT_TOKEN
    all_chats = [r['chat_id'] for r in settings.RECIPIENTS]
    state_file = 'state.json'
    
    # Мапа id -> chat_id для точного видалення
    id_to_chat = {}
    
    if os.path.exists(state_file):
        try:
            with open(state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                # Перевіряємо різні типи повідомлень у state
                for msg_type in ['_no_changes', '_last_alert']:
                    msgs = state.get('last_messages', {}).get(msg_type, {})
                    for rec_key, mid in msgs.items():
                        # rec_key зазвичай містить chat_id як префікс (e.g. "-100..._83042")
                        # або це просто chat_id
                        cid = rec_key.split('_')[0]
                        id_to_chat[int(mid)] = cid
        except Exception as e:
            print(f"⚠️ Попередження: не вдалося повністю розпарсити state.json: {e}")

    print(f"--- Telegram Cleanup Tool (Multi-Chat Support) ---")
    print(f"Отримувачі: {', '.join(all_chats)}")
    
    found_ids = sorted(list(id_to_chat.keys()))
    if found_ids:
        print(f"Знайдено в state.json: {found_ids}")
    
    print("\nВаріанти введення:")
    print("1. Список через кому (наприклад: 83158, 83159)")
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
            
        confirm = input(f"⚠️ Видалити {len(target_ids)} повідомлень у всіх доступних чатах? (y/n): ")
        if confirm.lower() != 'y':
            print("Скасовано.")
            sys.exit(0)

        print(f"\n🧹 Починаю видалення...")
        total_success = 0
        
        for mid in target_ids:
            success = False
            # 1. Спробуємо точний чат зі state.json
            if mid in id_to_chat:
                cid = id_to_chat[mid]
                ok, err = delete_message(cid, mid, token)
                if ok:
                    print(f"  ✅ ID {mid} видалено з чату {cid} (зі state.json)")
                    success = True
                else:
                    print(f"  ❌ ID {mid} (чат {cid}): {err}")
            
            # 2. Якщо не вийшло або ID не в мапі — пробуємо всі чати
            if not success:
                for cid in all_chats:
                    if mid in id_to_chat and cid == id_to_chat[mid]: continue # Вже пробували
                    
                    ok, err = delete_message(cid, mid, token)
                    if ok:
                        print(f"  ✅ ID {mid} видалено з чату {cid} (broadcast)")
                        success = True
                        break
                
                if not success and mid not in id_to_chat:
                    print(f"  ❌ ID {mid} не знайдено в жодному з {len(all_chats)} чатів")

            if success: total_success += 1

        print(f"\n✨ Готово! Успішно видалено повідомлень: {total_success}")

    except ValueError:
        print("❌ Помилка: введіть коректні числа (наприклад 83161 або 83160-83165).")
