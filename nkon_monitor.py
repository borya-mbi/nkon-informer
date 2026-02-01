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
import argparse
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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('nkon_monitor.log', encoding='utf-8'),
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
        self.config = self._load_config(config_path)
        self.state_file = 'state.json'
        self.previous_state = self._load_state()
        
    def _load_config(self, config_path: str) -> Dict:
        """Завантаження конфігурації"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            logger.info(f"Конфігурацію завантажено з {config_path}")
            return config
        except FileNotFoundError:
            logger.error(f"Файл конфігурації {config_path} не знайдено!")
            sys.exit(1)
        except json.JSONDecodeError as e:
            logger.error(f"Помилка парсингу JSON: {e}")
            sys.exit(1)
            
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
    
    def extract_capacity(self, text: str) -> Optional[int]:
        """
        Витягування ємності батареї з тексту
        
        Args:
            text: Текст для пошуку
            
        Returns:
            Ємність в Ah або None
        """
        # Regex для пошуку ємності: 280Ah, 314 Ah, тощо
        pattern = r'(\d+)\s*Ah'
        match = re.search(pattern, text, re.IGNORECASE)
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
        
        # Ціна (.price-container .price)
        price_elem = item.find('span', class_='price')
        price = price_elem.get_text(strip=True) if price_elem else 'N/A'
        
        # Статус наявності
        stock_status = self._check_stock_status(item)
        
        if not stock_status:
            return None  # Тільки In Stock та Pre-order
        
        return {
            'name': name,
            'capacity': capacity,
            'price': price,
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
        Виявлення змін порівняно з попереднім станом
        
        Args:
            current_products: Поточний список товарів
            
        Returns:
            Словник зі статистикою змін
        """
        current_dict = {p['link']: p for p in current_products}
        previous_dict = self.previous_state
        
        current_links = set(current_dict.keys())
        previous_links = set(previous_dict.keys())
        
        # Нові товари
        new_links = current_links - previous_links
        new_products = [current_dict[link] for link in new_links]
        
        # Видалені товари
        removed_links = previous_links - current_links
        removed_products = [previous_dict[link] for link in removed_links]
        
        # Зміни цін та статусу
        price_changes = []
        status_changes = []
        
        for link in current_links & previous_links:
            current = current_dict[link]
            previous = previous_dict[link]
            
            if current['price'] != previous['price']:
                price_changes.append({
                    'product': current,
                    'old_price': previous['price'],
                    'new_price': current['price']
                })
            
            if current['stock_status'] != previous['stock_status']:
                status_changes.append({
                    'product': current,
                    'old_status': previous['stock_status'],
                    'new_status': current['stock_status']
                })
        
        return {
            'new': new_products,
            'removed': removed_products,
            'price_changes': price_changes,
            'status_changes': status_changes,
            'current': current_products
        }
    
    def format_telegram_message(self, changes: Dict) -> str:
        """
        Форматування Telegram повідомлення
        
        Args:
            changes: Словник зі змінами
            
        Returns:
            Форматований текст повідомлення
        """
        current = changes['current']
        new = changes['new']
        removed = changes['removed']
        price_changes = changes['price_changes']
        status_changes = changes['status_changes']
        
        # Підрахунок статистики
        in_stock_count = sum(1 for p in current if p['stock_status'] == 'in_stock')
        preorder_count = sum(1 for p in current if p['stock_status'] == 'preorder')
        
        # Заголовок
        message = "🔋 *NKON LiFePO4 Monitor Report*\n"
        message += f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        
        # Статистика
        message += "📊 *Статистика:*\n"
        message += f"✅ In Stock: {in_stock_count}\n"
        message += f"🔵 Pre-order: {preorder_count}\n"
        message += f"🆕 Нових: {len(new)}\n"
        message += f"❌ Видалено: {len(removed)}\n"
        
        # Якщо є зміни - показуємо їх
        if new or removed or price_changes or status_changes:
            message += f"\n🔄 *Зміни:*\n"
            
            # Нові товари
            for product in new[:5]:  # Обмежуємо до 5
                status_emoji = "✅" if product['stock_status'] == 'in_stock' else "🔵"
                message += f"🆕 {product['name'][:50]}... - {product['price']} ({status_emoji})\n"
            
            if len(new) > 5:
                message += f"... та ще {len(new) - 5} нових\n"
            
            # Видалені товари
            for product in removed[:3]:
                message += f"❌ {product['name'][:50]}... - зникла\n"
            
            if len(removed) > 3:
                message += f"... та ще {len(removed) - 3} видалених\n"
            
            # Зміни цін
            for change in price_changes[:3]:
                p = change['product']
                message += f"💰 {p['name'][:40]}... {change['old_price']} → {change['new_price']}\n"
            
            # Зміни статусу
            for change in status_changes[:3]:
                p = change['product']
                old_emoji = "✅" if change['old_status'] == 'in_stock' else "🔵"
                new_emoji = "✅" if change['new_status'] == 'in_stock' else "🔵"
                message += f"🔄 {p['name'][:40]}... {old_emoji} → {new_emoji}\n"
        
        # Повний список (обмежено)
        message += f"\n📋 *Повний список ({len(current)} товарів):*\n"
        for product in current[:10]:
            status_emoji = "✅" if product['stock_status'] == 'in_stock' else "🔵"
            message += f"{status_emoji} [{product['capacity']}Ah]({product['link']}) {product['name'][:40]}... - {product['price']}\n"
        
        if len(current) > 10:
            message += f"\n_... та ще {len(current) - 10} товарів_\n"
        
        message += f"\n🔗 [Переглянути всі]({self.config.get('url')})"
        
        return message
    
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
                response = requests.post(url, json=payload, timeout=10)
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
            logger.info(f"Нових: {len(changes['new'])}, Видалених: {len(changes['removed'])}")
            logger.info(f"Змін цін: {len(changes['price_changes'])}, Змін статусу: {len(changes['status_changes'])}")
            
            # Форматування та відправка повідомлення
            message = self.format_telegram_message(changes)
            self.send_telegram_message(message, dry_run=dry_run)
            
            # Збереження стану
            current_state = {p['link']: p for p in products}
            self._save_state(current_state)
            
            logger.info("=" * 60)
            logger.info("Моніторинг завершено успішно")
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"Критична помилка: {e}", exc_info=True)
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
