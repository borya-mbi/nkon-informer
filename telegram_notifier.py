#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Notification Manager for NKON Monitor
"""

import logging
import time
import hashlib
import requests
from datetime import datetime
from typing import List, Dict, Optional, Set

import settings
from utils import extract_grade, shorten_name, mask_sensitive

logger = logging.getLogger(__name__)

class TelegramNotifier:
    LINE_PREFIX = "└──▷"

    def __init__(self, config: Dict, session: requests.Session = None):
        self.config = config
        self.session = session or requests.Session()

    def is_quiet_hours(self) -> bool:
        """Перевіряє, чи активний зараз тихий час (за замовчуванням 21:00 - 08:00)"""
        now = datetime.now()
        start = self.config.get('quiet_hours_start', settings.QUIET_HOURS_START)
        end = self.config.get('quiet_hours_end', settings.QUIET_HOURS_END)
        
        if start > end: # Перехід через північ (напр. 21 - 8)
            return now.hour >= start or now.hour < end
        else: # В межах однієї доби
            return start <= now.hour < end

    def _format_stock_display(self, item: Dict, show_diffs: bool = True, msg_key: str = None, stock_cumulative_diffs: Dict = None) -> str:
        """Формує рядок залишку."""
        if item.get('real_stock') is None:
            if item.get('stock_status') == 'in_stock':
                return " `[В\u00a0наявності]`"
            return ""
            
        current = item['real_stock']
        
        if not show_diffs or not msg_key or not stock_cumulative_diffs:
            return f" `[{current} шт]`"
        
        key = f"{item['link']}_{item.get('capacity', '0')}"
        rec_diffs = stock_cumulative_diffs.get(msg_key, {})
        diffs = rec_diffs.get(key, {"decrease": 0, "increase": 0})
        
        dec = diffs["decrease"]
        inc = diffs["increase"]
        
        if dec != 0 or inc != 0:
            diff_str = ""
            if dec != 0: diff_str += str(dec)
            if inc != 0: diff_str += f"+{inc}"
            return f" `[{current}({diff_str}) шт]`"
            
        return f" `[{current} шт]`"

    def format_telegram_message(self, changes: Dict, include_unchanged: bool = True, is_update: bool = False, 
                               show_stock_diffs: bool = False, unchanged_header: str = "Без змін", 
                               msg_key: str = None, header_link: str = None, footer_links: list = None,
                               stock_cumulative_diffs: Dict = None) -> Optional[str]:
        """
        Форматування повідомлення для Telegram
        """
        if header_link:
            msg = f"[🔋 NKON LiFePO4 Monitor]({header_link})\n\n"
        else:
            msg = f"🔋 *NKON LiFePO4 Monitor*\n\n"
        
        has_changes = False
        threshold = self.config.get('price_alert_threshold', 5)
        
        def get_grade_display(grade_str: str) -> str:
            if grade_str == "?":
                return ""
            emoji = "🅰️" if "Grade A" in grade_str else "🅱️" if "Grade B" in grade_str else "❓"
            if "-" in grade_str:
                emoji += "➖"
            return f"{emoji} {grade_str} | "

        def get_graph_link(item: Dict) -> str:
            if settings.VISUALIZATION_BASE_URL:
                p_key = f"{item['link']}_{item.get('capacity', '0')}"
                graph_id = hashlib.md5(p_key.encode()).hexdigest()[:8]
                graph_url = f"{settings.VISUALIZATION_BASE_URL.rstrip('/')}/graph_{graph_id}.html"
                return f" [📈Stat]({graph_url})"
            return ""

        def format_line(item, prefix_emoji="", show_status=False):
            grade = extract_grade(item['name'])
            short_name = shorten_name(item['name'])
            price = item.get('price', 'N/A')
            grade_msg = get_grade_display(grade)
            
            stock_msg = self._format_stock_display(item, show_diffs=show_stock_diffs, msg_key=msg_key, stock_cumulative_diffs=stock_cumulative_diffs)
            
            status_ico = ""
            delivery_msg = ""
            
            if item.get('stock_status') == 'preorder':
                status_ico = f" [📦Pre]({item['link']})"
                if item.get('delivery_date'):
                    delivery_msg = f"\n  [{self.LINE_PREFIX} {item['delivery_date']}]({item['link']}){stock_msg}"
                else:
                    status_ico += stock_msg
            elif item.get('stock_status') == 'in_stock':
                status_ico = f" [✅In]({item['link']})"
                if stock_msg:
                    delivery_msg = f"\n  [{self.LINE_PREFIX} В\u00a0наявності]({item['link']}){stock_msg}"
                else:
                    status_ico += stock_msg
            elif item.get('stock_status') == 'out_of_stock':
                status_ico = f" ❌Out{stock_msg}"
                
            link_text = f"[{item['capacity']}Ah]({item['link']})"
            graph_icon = get_graph_link(item)
            return f"{prefix_emoji} {link_text} {grade_msg}{short_name} | {price}{status_ico}{delivery_msg}{graph_icon}"

        if changes.get('new'):
            has_changes = True
            msg += f"✨ *Нові товари ({len(changes['new'])}):*\n"
            for item in changes['new']:
                msg += format_line(item, "•") + "\n"
            msg += "\n"
        
        if changes.get('price_changes'):
            has_changes = True
            msg += f"💰 *Зміни цін ({len(changes['price_changes'])}):*\n"
            for item in changes['price_changes']:
                old_price = item.get('old_price', 'N/A')
                new_price = item.get('new_price', 'N/A')
                change_str = f"{old_price} → {new_price}"
                old_val = item.get('old_price_value')
                new_val = item.get('new_price_value')
                
                if old_val and new_val:
                    try:
                        change_percent = ((new_val - old_val) / old_val) * 100
                        if abs(change_percent) >= threshold:
                            emoji = "🔴" if change_percent > 0 else "🟢"
                            sign = "+" if change_percent > 0 else ""
                            change_str += f" ({emoji}{sign}{change_percent:.1f}%)"
                    except ZeroDivisionError:
                        pass
                
                grade = extract_grade(item['name'])
                grade_msg = get_grade_display(grade)
                short_name = shorten_name(item['name'])
                link_text = f"[{item['capacity']}Ah]({item['link']})"
                graph_icon = get_graph_link(item)
                msg += f"• {link_text} {grade_msg}{short_name} | {change_str}{graph_icon}\n"
            msg += "\n"
        
        if changes.get('status_changes'):
            has_changes = True
            msg += f"📦 *Зміни статусу({len(changes['status_changes'])}):*\n"
            for item in changes['status_changes']:
                new_status = item.get('new_status')
                old_status = item.get('old_status')
                price = item.get('price', 'N/A')
                status_map = {'preorder': 'Pre', 'in_stock': 'In', 'out_of_stock': 'Out'}
                status_emoji = "✅" if new_status == 'in_stock' else "📦"
                old_str = status_map.get(old_status, 'Out')
                new_str = status_map.get(new_status, 'Out')
                
                status_info = f" | {old_str} → {new_str}" if old_status != new_status else ""
                
                date_msg = ""
                old_date = item.get('old_date')
                new_date = item.get('new_date')
                if new_date:
                    if old_date and old_date != new_date:
                        date_msg = f"\n  {self.LINE_PREFIX} {old_date} → {new_date}"
                    else:
                        date_msg = f"\n  {self.LINE_PREFIX} {new_date}"
                
                grade_raw = extract_grade(item['name'])
                grade_msg = get_grade_display(grade_raw)
                short_name = shorten_name(item['name'])
                link_text = f"[{item['capacity']}Ah]({item['link']})"
                graph_icon = get_graph_link(item)
                msg += f"• {status_emoji} {link_text} {grade_msg}{short_name}{status_info}{date_msg} | {price}{graph_icon}\n"
            msg += "\n"
        
        if changes.get('removed'):
            has_changes = True
            msg += f"❌ *Видалені ({len(changes['removed'])}):*\n"
            for item in changes['removed']:
                link_text = f"[{item['capacity']}Ah]({item['link']})"
                graph_icon = get_graph_link(item)
                msg += f"• {link_text} {shorten_name(item['name'])}{graph_icon}\n"
            msg += "\n"
            
        if not has_changes and not include_unchanged:
            return None
        
        changed_links = set()
        for item in changes.get('new', []): changed_links.add(item['link'])
        for item in changes.get('price_changes', []): changed_links.add(item['link'])
        for item in changes.get('status_changes', []): changed_links.add(item['link'])
        
        if include_unchanged:
            current = changes.get('current', [])
            unchanged = [p for p in current if p['link'] not in changed_links]
            if unchanged:
                msg += f"📋 *{unchanged_header} ({len(unchanged)}):*\n"
                for item in unchanged:
                    msg += format_line(item, "•") + "\n"
        
        msg = msg.strip()
        status_emoji = "🆕" if not is_update else "🔄"
        msg += f"\n\n{status_emoji} {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
        
        if footer_links:
            links_list = [f"[{link.get('name', 'Чат')}]({link['url']})" for link in footer_links if link.get('url')]
            if links_list:
                msg += f"\n\n💬 Обговорення: " + " | ".join(links_list)
        return msg

    def send_telegram_message(self, text: str, chat_ids: Set[str] = None, thread_id: int = None, 
                              dry_run: bool = False, disable_notification: bool = False) -> Dict[str, int]:
        """Відправлення повідомлення в Telegram групі отримувачів"""
        sent_messages = {}
        bot_token = self.config.get('telegram_bot_token')
        if not bot_token or not chat_ids: 
            if not bot_token: logger.error("Telegram bot token не налаштований")
            return sent_messages
        
        if dry_run:
            logger.info(f"[DRY RUN] Telegram повідомлення для {[mask_sensitive(c) for c in chat_ids]} (silent={disable_notification or self.is_quiet_hours()}):\n{text}")
            return sent_messages

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        for chat_id in chat_ids:
            masked_chat = mask_sensitive(chat_id)
            target_chat = chat_id
            if isinstance(chat_id, str):
                if (chat_id.startswith('-') and chat_id[1:].isdigit()) or chat_id.isdigit():
                    target_chat = int(chat_id)
            
            # Примусово вимикаємо звук, якщо зараз тихий час
            is_silent = disable_notification or self.is_quiet_hours()
            
            payload = {
                "chat_id": target_chat,
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
                "disable_notification": is_silent
            }
            if thread_id:
                payload["message_thread_id"] = thread_id
                
            try:
                response = self.session.post(url, json=payload, timeout=15)
                result = response.json()
                if result.get("ok"):
                    msg_id = result["result"]["message_id"]
                    sent_messages[chat_id] = msg_id
                    logger.info(f"✅ Повідомлення відправлено до чату {masked_chat}")
                else:
                    logger.error(f"❌ Помилка Telegram для {masked_chat}: {result.get('description')}")
            except Exception as e:
                logger.error(f"❌ Помилка при відправці до чату {masked_chat}: {e}")
        
        return sent_messages

    def edit_telegram_message(self, chat_id: str, message_id: int, text: str) -> bool:
        """Редагування повідомлення в Telegram"""
        bot_token = self.config.get('telegram_bot_token')
        if not bot_token: return False
        
        target_chat = chat_id
        if isinstance(chat_id, str):
            if (chat_id.startswith('-') and chat_id[1:].isdigit()) or chat_id.isdigit():
                target_chat = int(chat_id)
        
        url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
        payload = {
            "chat_id": target_chat,
            "message_id": message_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        try:
            response = self.session.post(url, json=payload, timeout=15)
            result = response.json()
            return result.get("ok", False)
        except Exception as e:
            logger.error(f"❌ Помилка при редагуванні в Telegram: {e}")
        return False

    def _should_notify(self, recipient_config: Dict, has_changes: bool, last_notification_time: Optional[float]) -> tuple:
        """
        Перевірка, чи потрібно відправляти повідомлення згідно з логікою Heartbeat/Quiet mode
        Повертає: (should_notify: bool, reason: str)
        """
        if has_changes:
            return True, "changes"
            
        quiet_mode = recipient_config.get('quiet_mode', False)
        if not quiet_mode:
            return True, "no_quiet"
            
        # Якщо Quiet mode включений, перевіряємо кулдаун для Heartbeat
        heartbeat_hours = recipient_config.get('heartbeat_interval_hours', settings.DEFAULT_HEARTBEAT_INTERVAL)
        
        if last_notification_time is None:
            return True, "first_run"
            
        # Якщо last_notification_time це datetime
        if isinstance(last_notification_time, datetime):
            last_ts = last_notification_time.timestamp()
        else:
            last_ts = float(last_notification_time) if last_notification_time else 0
            
        elapsed_hours = (time.time() - last_ts) / 3600
        if elapsed_hours >= heartbeat_hours:
            return True, "heartbeat"
            
        return False, "cooldown"

