#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NKON LiFePO4 Battery Monitor
Моніторинг батарей LiFePO4 ємністю >=200Ah на nkon.nl з відправкою сповіщень в Telegram
"""

import json
import logging
import os
import re
import sys
import time
import random
import argparse
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Optional, Set
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# Налаштування логування
handler = RotatingFileHandler(
    'nkon_monitor.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,
    encoding='utf-8'
)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        handler,
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class NkonMonitor:
    """Клас для моніторингу батарей LiFePO4 на сайті NKON"""
    
    def __init__(self, config_path: str = 'config.json'):
        """
        Ініціалізація монітора
        
        Args:
            config_path: Шлях до файлу конфігурації
        """
        self.config = self._load_config_with_env(config_path)
        self.state_file = 'state.json'
        self.previous_state = self._load_state()
        self.session = requests.Session()  # Для anti-ban (Telegram API)

    def _load_config_with_env(self, config_path: str) -> Dict:
        """Завантаження конфігурації з .env або config.json"""
        config = {}
        
        # Спроба завантажити з .env
        from dotenv import load_dotenv
        env_loaded = load_dotenv()
        
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_ids_str = os.getenv('TELEGRAM_CHAT_IDS')
        
        if bot_token:
            if env_loaded:
                logger.info("Використовується .env файл для конфігурації")
            else:
                logger.info("Використовуються змінні середовища для конфігурації")
                
            config['telegram_bot_token'] = bot_token
            # Парсинг чатів з рядка "id1,id2"
            if chat_ids_str:
                config['telegram_chat_ids'] = [cid.strip() for cid in chat_ids_str.split(',') if cid.strip()]
            
            config['min_capacity_ah'] = int(os.getenv('MIN_CAPACITY_AH', 200))
            config['price_alert_threshold'] = int(os.getenv('PRICE_ALERT_THRESHOLD', 5))
            config['url'] = os.getenv('NKON_URL', 'https://www.nkon.nl/rechargeable/lifepo4/prismatisch.html?___store=en')
            return config
        
        # Fallback до config.json
        if missing_env:
            logger.warning(f"⚠️  Змінні середовища не знайдено: {', '.join(missing_env)}")
            logger.info("Спроба завантажити config.json...")
            
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                    config.update(file_config)
                    logger.info("✅ Конфігурацію завантажено з config.json")
            except FileNotFoundError:
                logger.error("❌ ПОМИЛКА: Не знайдено налаштувань!")
                logger.error("1. Або встановіть змінні середовища (TELEGRAM_BOT_TOKEN, etc)")
                logger.error("2. Або створіть config.json / .env файл")
                sys.exit(1)
            except json.JSONDecodeError as e:
                logger.error(f"Помилка парсингу JSON: {e}")
                sys.exit(1)
        return config
            
    def _load_state(self) -> Dict:
        """Завантаження попереднього стану (для відстеження змін)"""
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.warning(f"Не вдалося завантажити state: {e}")
        return {}
    
    def _save_state(self, items: Dict):
        """Збереження поточного стану"""
        try:
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            logger.info(f"State збережено: {len(items)} товарів")
        except Exception as e:
            logger.error(f"Помилка збереження state: {e}")
    
    def fetch_page_with_selenium(self, url: str) -> str:
        """
        Завантаження сторінки з використанням Selenium (для JS контенту)
        
        Args:
            url: URL сторінки
            
        Returns:
            HTML контент сторінки
        """
        logger.info(f"Завантаження сторінки: {url}")
        
        # Налаштування Chrome
        chrome_options = Options()
        chrome_options.add_argument('--headless')  # Безголовий режим
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        try:
            # Автоматичне керування ChromeDriver
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # Anti-ban: Випадкова затримка перед запитом
            delay = random.uniform(2, 5)
            logger.info(f"Anti-ban затримка: {delay:.2f} сек...")
            time.sleep(delay)
            
            driver.get(url)
            
            # Очікування завантаження контенту (JavaScript)
            logger.info("Очікування завантаження JavaScript контенту...")
            time.sleep(5)  # Базова затримка
            
            # Спроба дочекатися появи товарів
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "product-item"))
                )
                logger.info("Товари завантажено")
            except:
                logger.warning("Час очікування товарів минув, продовжуємо...")
            
            html = driver.page_source
            driver.quit()
            
            logger.info(f"Сторінку завантажено ({len(html)} символів)")
            return html
            
        except Exception as e:
            logger.error(f"Помилка при завантаженні сторінки: {e}")
            if 'driver' in locals():
                driver.quit()
            raise
    

    def clean_price(self, price_text: str) -> Optional[float]:
        """
        Очищення та конвертація ціни в float
        
        Args:
            price_text: Текст ціни (наприклад, "€ 89.95" або "€89.95")
        
        Returns:
            Ціна як float або None
        """
        try:
            # Видаляємо всі символи крім цифр, крапки та коми
            cleaned = re.sub(r'[^\d.,]', '', price_text)
            # Замінюємо кому на крапку (європейський формат)
            cleaned = cleaned.replace(',', '.')
            return float(cleaned)
        except (ValueError, AttributeError):
            return None

    def extract_capacity(self, text: str) -> Optional[int]:
        """
        Витягування ємності батареї з тексту
        
        Args:
            text: Текст для пошуку
            
        Returns:
            Ємність в Ah або None
        """
        # Гнучкий regex для різних форматів: 280Ah, 280 Ah, 280  Ah, 280ah, 280AH
        # \d{3,} - мінімум 3 цифри (автоматично фільтрує <100Ah)
        # \s* - будь-яка кількість пробілів
        # (?:...) - non-capturing group для всіх варіантів написання
        pattern = r'(\d{3,})\s*(?:Ah|ah|AH|aH)'
        match = re.search(pattern, text)
        if match:
            return int(match.group(1))
        return None
    
    def parse_products(self, html: str) -> List[Dict]:
        """
        Парсинг товарів зі сторінки
        
        Args:
            html: HTML контент сторінки
            
        Returns:
            Список товарів
        """
        soup = BeautifulSoup(html, 'html.parser')
        products = []
        
        # Magento 2 StructurE: li.product-item
        product_items = soup.find_all('li', class_='product-item')
        
        logger.info(f"Знайдено {len(product_items)} товарів на сторінці")
        
        for item in product_items:
            try:
                product = self._parse_single_product(item)
                if product:
                    products.append(product)
            except Exception as e:
                logger.warning(f"Помилка парсингу товару: {e}")
                continue
        
        logger.info(f"Успішно розпарсено {len(products)} товарів (>=200Ah, In Stock/Pre-order)")
        return products
    
    def _parse_single_product(self, item) -> Optional[Dict]:
        """Парсинг одного товару"""
        # Назва товару (a.product-item-link)
        name_elem = item.find('a', class_='product-item-link')
        if not name_elem:
            return None
        
        name = name_elem.get_text(strip=True)
        
        # Витягування ємності
        capacity = self.extract_capacity(name)
        
        # Фільтрація: тільки >= min_capacity_ah
        min_capacity = self.config.get('min_capacity_ah', 200)
        if not capacity or capacity < min_capacity:
            return None
        
        # Посилання
        link = name_elem.get('href', '')
        if link and not link.startswith('http'):
            link = 'https://www.nkon.nl' + link
        
        price_elem = item.find('span', class_='price')
        price_raw = price_elem.get_text(strip=True) if price_elem else 'N/A'
        price_float = self.clean_price(price_raw)
        
        # Статус наявності
        stock_status = self._check_stock_status(item)
        
        if not stock_status:
            return None  # Тільки In Stock та Pre-order
        
        return {
            'name': name,
            'capacity': capacity,
            'price': price_raw,      # Оригінальний текст для відображення
            'price_value': price_float, # Числове значення для аналізу
            'link': link,
            'stock_status': stock_status,  # 'in_stock' або 'preorder'
            'timestamp': datetime.now().isoformat()
        }
    
    def _check_stock_status(self, item) -> Optional[str]:
        """
        Перевірка статусу наявності товару
        
        Args:
            item: BeautifulSoup елемент товару
            
        Returns:
            'in_stock', 'preorder' або None (якщо out of stock)
        """
        # Пошук кнопки Add to Cart
        add_to_cart = item.find('button', class_='btn--cart')
        
        if not add_to_cart:
            return None  # Немає кнопки = out of stock
        
        # Перевірка на pre-order (синя кнопка)
        classes = ' '.join(add_to_cart.get('class', []))
        if 'btn--cart--preorder' in classes or 'preorder' in classes.lower():
            return 'preorder'
        
        # Інакше - in stock (зелена кнопка)
        return 'in_stock'
    
    def detect_changes(self, current_products: List[Dict]) -> Dict:
        """
        Виявлення змін між поточним та попереднім станом
        
        Args:
            current_products: Список поточних товарів
            
        Returns:
            Словник зі змінами
        """
        current_state = {p['link']: p for p in current_products}
        
        new_items = []
        removed_items = []
        price_changes = []
        status_changes = []
        
        # Пошук нових товарів та змін
        for link, product in current_state.items():
            if link not in self.previous_state:
                new_items.append(product)
            else:
                old_product = self.previous_state[link]
                
                # Зміни цін
                old_price_val = old_product.get('price_value')
                new_price_val = product.get('price_value')
                
                # Порівнюємо number values якщо є, інакше рядки
                changed = False
                if old_price_val is not None and new_price_val is not None:
                    if old_price_val != new_price_val:
                        changed = True
                elif product['price'] != old_product['price']:
                    changed = True
                    
                if changed:
                    price_changes.append({
                        'name': product['name'],
                        'capacity': product['capacity'],
                        'link': link,
                        'old_price': old_product.get('price', 'N/A'),
                        'new_price': product.get('price', 'N/A'),
                        'old_price_value': old_price_val,
                        'new_price_value': new_price_val
                    })
                
                # Зміни статусу
                if product['stock_status'] != old_product['stock_status']:
                    status_changes.append({
                        'name': product['name'],
                        'capacity': product['capacity'],
                        'link': link,
                        'price': product['price'],
                        'old_status': old_product['stock_status'],
                        'new_status': product['stock_status']
                    })
        
        # Пошук видалених товарів
        for link, product in self.previous_state.items():
            if link not in current_state:
                removed_items.append(product)
                
        return {
            'new': new_items,
            'removed': removed_items,
            'price_changes': price_changes,
            'status_changes': status_changes,
            'current': current_products  # Додаємо поточні товари для відображення "без змін"
        }
    
    def format_telegram_message(self, changes: Dict) -> str:
        """Форматування повідомлення для Telegram"""
        msg = "🔋 *NKON LiFePO4 Monitor*\n\n"
        
        has_changes = False
        threshold = self.config.get('price_alert_threshold', 5)
        
        # Нові товари
        if changes.get('new'):
            has_changes = True
            msg += f"✨ *Нові товари ({len(changes['new'])}):*\n"
            for item in changes['new']:
                price = item.get('price', 'N/A')
                msg += f"• [{item['capacity']}Ah]({item['link']}) - {price}"
                if item.get('stock_status') == 'preorder':
                    msg += " 📦 Pre-order"
                msg += "\n"
            msg += "\n"
        
        # Зміни цін
        if changes.get('price_changes'):
            has_changes = True
            msg += f"💰 *Зміни цін ({len(changes['price_changes'])}):*\n"
            for item in changes['price_changes']:
                old_price = item.get('old_price', 'N/A')
                new_price = item.get('new_price', 'N/A')
                change_str = f"{old_price} → {new_price}"
                
                # Розрахунок відсотку
                old_val = item.get('old_price_value')
                new_val = item.get('new_price_value')
                
                if old_val and new_val:
                    try:
                        change_percent = ((new_val - old_val) / old_val) * 100
                        # Показуємо відсоток тільки якщо зміни значні
                        if abs(change_percent) >= threshold:
                            emoji = "🔴" if change_percent > 0 else "🟢"
                            sign = "+" if change_percent > 0 else ""
                            change_str += f" ({emoji}{sign}{change_percent:.1f}%)"
                    except ZeroDivisionError:
                        pass
                
                msg += f"• [{item['capacity']}Ah]({item['link']}) - {change_str}\n"
            msg += "\n"
        
        # Зміни статусу
        if changes.get('status_changes'):
            has_changes = True
            msg += f"📦 *Зміни статусу ({len(changes['status_changes'])}):*\n"
            for item in changes['status_changes']:
                new_status = item.get('new_status')
                old_status = item.get('old_status')
                price = item.get('price', 'N/A')
                
                status_emoji = "✅" if new_status == 'in_stock' else "📦"
                old_status_str = "Pre-order" if old_status == 'preorder' else "In Stock"
                new_status_str = "Pre-order" if new_status == 'preorder' else "In Stock"
                
                msg += f"• {status_emoji} [{item['capacity']}Ah]({item['link']}) - {price}\n"
                msg += f"   Status: {old_status_str} → {new_status_str}\n"
            msg += "\n"
        
        # Видалені товари
        if changes.get('removed'):
            has_changes = True
            msg += f"❌ *Видалені ({len(changes['removed'])}):*\n"
            for item in changes['removed']:
                msg += f"• [{item['capacity']}Ah] {item['name']}\n"
            msg += "\n"
        
            msg += "\n"
        
        # Товари без змін (для повної картини)
        # Збираємо лінки товарів, що змінилися
        changed_links = set()
        for item in changes.get('new', []): changed_links.add(item['link'])
        for item in changes.get('price_changes', []): changed_links.add(item['link'])
        for item in changes.get('status_changes', []): changed_links.add(item['link'])
        
        # Знаходимо незмінені
        current = changes.get('current', [])
        unchanged = [p for p in current if p['link'] not in changed_links]
        
        if unchanged:
            msg += f"📋 *Без змін ({len(unchanged)}):*\n"
            for item in unchanged:
                price = item.get('price', 'N/A')
                status_emoji = "✅" if item.get('stock_status') == 'in_stock' else "📦"
                msg += f"• {status_emoji} [{item['capacity']}Ah]({item['link']}) - {price}\n"
        
        msg += f"\n🕒 _{datetime.now().strftime('%d.%m.%Y %H:%M:%S')}_"
        return msg    
    def send_telegram_message(self, message: str, dry_run: bool = False):
        """
        Відправка повідомлення в Telegram (підтримує декілька чатів)
        
        Args:
            message: Текст повідомлення
            dry_run: Якщо True, не відправляти реально
        """
        if dry_run:
            logger.info(f"[DRY RUN] Telegram повідомлення:\n{message}")
            return
        
        bot_token = self.config.get('telegram_bot_token')
        
        # Підтримка нового формату (список) та старого формату (рядок)
        chat_ids = self.config.get('telegram_chat_ids')
        if not chat_ids:
            # Зворотна сумісність зі старим форматом
            chat_id = self.config.get('telegram_chat_id')
            if chat_id:
                chat_ids = [chat_id]
        
        if not bot_token or not chat_ids:
            logger.error("Telegram credentials не налаштовані в config.json")
            return
        
        # Перетворюємо на список, якщо це рядок
        if isinstance(chat_ids, str):
            chat_ids = [chat_ids]
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        
        # Відправка повідомлення кожному чату
        success_count = 0
        total_count = len(chat_ids)
        
        for chat_id in chat_ids:
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': False
            }
            
            try:
                response = self.session.post(url, json=payload, timeout=10)
                response.raise_for_status()
                success_count += 1
                logger.info(f"✅ Повідомлення відправлено до чату {chat_id}")
            except Exception as e:
                logger.error(f"❌ Помилка відправки до чату {chat_id}: {e}")
        
        logger.info(f"📊 Відправлено {success_count}/{total_count} повідомлень")
    
    def run(self, dry_run: bool = False):
        """
        Основний цикл моніторингу
        
        Args:
            dry_run: Якщо True, не відправляти Telegram повідомлення
        """
        logger.info("=" * 60)
        logger.info("Запуск моніторингу NKON LiFePO4")
        logger.info("=" * 60)
        
        try:
            # Завантаження сторінки
            url = self.config.get('url', 'https://www.nkon.nl/rechargeable/lifepo4/prismatisch.html?___store=en')
            html = self.fetch_page_with_selenium(url)
            
            # Парсинг товарів
            products = self.parse_products(html)
            
            if not products:
                logger.warning("Не знайдено товарів, що відповідають критеріям")
                return
            
            # Виявлення змін
            changes = self.detect_changes(products)
            
            # Логування змін
            logger.info(f"Нових: {len(changes['new'])}, Видалених: {len(changes['removed'])}, "
                        f"Змін цін: {len(changes['price_changes'])}, Змін статусу: {len(changes['status_changes'])}")
            
            # Форматування та відправка повідомлення
            message = self.format_telegram_message(changes)
            if message:
                self.send_telegram_message(message, dry_run=dry_run)
            else:
                logger.info("Змін не виявлено, повідомлення не відправлено")
            
            # Збереження стану
            current_state = {p['link']: p for p in products}
            self._save_state(current_state)
            
            logger.info("=" * 60)
            logger.info("Моніторинг завершено успішно")
            logger.info("=" * 60)
            
        except Exception as e:
            error_msg = f"❌ *КРИТИЧНА ПОМИЛКА МНІТОРИНГУ*\n\n"
            error_msg += f"Тип: `{type(e).__name__}`\n"
            error_msg += f"Помилка: `{str(e)}`\n"
            error_msg += f"Час: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            logger.error(f"Критична помилка: {e}", exc_info=True)
            
            # Спроба відправити помилку в Telegram (тільки якщо не dry_run)
            if not dry_run:
                try:
                    self.send_telegram_message(error_msg)
                except Exception as send_err:
                    logger.error(f"Не вдалося відправити помилку в Telegram: {send_err}")
            
            raise


def main():
    """Точка входу"""
    parser = argparse.ArgumentParser(description='NKON LiFePO4 Battery Monitor')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Запуск без відправки Telegram повідомлень (для тестування)')
    parser.add_argument('--config', default='config.json',
                        help='Шлях до файлу конфігурації (за замовчуванням: config.json)')
    
    args = parser.parse_args()
    
    monitor = NkonMonitor(config_path=args.config)
    monitor.run(dry_run=args.dry_run)


if __name__ == '__main__':
    main()
