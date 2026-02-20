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
import shutil
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Optional, Set
from datetime import datetime

import settings

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
    
    # Константи для оформлення Telegram повідомлень
    LINE_PREFIX = "└──▷"  # Префікс для вкладених ліній. Варіанти: "└─►", "╰─►", "└─▷", "╰─▷", "└──▷", "╰──▷"
    
    def __init__(self):
        """Ініціалізація монітора"""
        # Convert settings to dict for compatibility
        self.config = {
            'url': settings.NKON_URL,
            'telegram_bot_token': settings.TELEGRAM_BOT_TOKEN,
            'min_capacity_ah': settings.MIN_CAPACITY_AH,
            'price_alert_threshold': settings.PRICE_ALERT_THRESHOLD,
            'fetch_delivery_dates': settings.FETCH_DELIVERY_DATES,
            'fetch_real_stock': settings.FETCH_REAL_STOCK,
            'restock_threshold': settings.RESTOCK_THRESHOLD,
            'detail_fetch_delay': settings.DETAIL_FETCH_DELAY,
            'heartbeat_times': settings.HEARTBEAT_TIMES,
            'quiet_hours_start': settings.QUIET_HOURS_START,
            'quiet_hours_end': settings.QUIET_HOURS_END
        }
        
        self.state_file = 'state.json'
        self.previous_state = {}
        self.last_messages = {}
        self.stock_cumulative_diffs = {}
        self.last_notification_time = datetime.min
        
        # Завантаження стану
        loaded_state = self._load_state()
        
        # Обробка версій State
        if (loaded_state.get('version') or 0) >= 2:
            self.previous_state = loaded_state.get('products', {})
            self.last_messages = loaded_state.get('last_messages', {})
            self.stock_cumulative_diffs = loaded_state.get('stock_cumulative_diffs', {})
            nt_str = loaded_state.get('last_notification_time')
            self.last_notification_time = datetime.fromisoformat(nt_str) if nt_str else datetime.min
        else:
            # Legacy state
            self.previous_state = loaded_state
            
        self.session = requests.Session()

            
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
        """Збереження поточного стану з бекапом попереднього"""
        try:
            # Ротація: зберігаємо попередній файл як .previous.json
            if os.path.exists(self.state_file):
                backup_file = self.state_file.replace('.json', '.previous.json')
                shutil.copy2(self.state_file, backup_file)
                # logger.debug(f"Створено бекап стейту: {backup_file}")
                
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
            
            # Логуємо кількість товарів, якщо це State v2 об'єкт
            product_count = len(items.get('products', {})) if isinstance(items, dict) and 'products' in items else len(items)
            logger.info(f"💾 State збережено до {self.state_file}: {product_count} товарів")
        except Exception as e:
            logger.error(f"Помилка збереження state: {e}")

    def _update_stock_counters(self, current_products: List[Dict], msg_key: str):
        """
        Оновлює лічильники змін залишків для конкретного отримувача.
        """
        restock_threshold = self.config.get('restock_threshold', 100)
        
        # Отримуємо дельти конкретно для цього отримувача
        rec_all_diffs = self.stock_cumulative_diffs.get(msg_key, {})
        
        # Визначаємо, чи потрібно логувати (тільки для першого отримувача в списку)
        # Це допомагає уникнути дублювання логів, якщо отримувачів багато
        should_log = False
        if settings.RECIPIENTS:
            first_chat = str(settings.RECIPIENTS[0]['chat_id'])
            first_thread = settings.RECIPIENTS[0].get('thread_id')
            first_key = f"{first_chat}_{first_thread}" if first_thread else first_chat
            if msg_key == first_key:
                should_log = True

        for item in current_products:
            if item.get('real_stock') is None:
                continue
                
            current_stock = item['real_stock']
            key = f"{item['link']}_{item.get('capacity', '0')}"
            
            # Обчислення дельти відносно ПОПЕРЕДНЬОГО запуску
            prev_stock = self.previous_state.get(key, {}).get('real_stock')
            
            if prev_stock is None or prev_stock == current_stock:
                continue
                
            delta = current_stock - prev_stock
            diffs = rec_all_diffs.get(key, {"decrease": 0, "increase": 0})
            
            short = self._shorten_name(item.get('name', key))
            if delta < 0:
                diffs["decrease"] += delta
                if should_log: logger.info(f"📉 {short}: {delta} (продаж)")
            elif delta <= restock_threshold:
                diffs["decrease"] += delta
                before_clamp = diffs["decrease"]
                diffs["decrease"] = min(diffs["decrease"], 0)
                
                if should_log:
                    if diffs["decrease"] != before_clamp:
                        logger.info(f"🔄 {short}: +{delta} (повернення, decrease обрізано до 0)")
                    else:
                        logger.info(f"🔄 {short}: +{delta} (повернення, decrease: {diffs['decrease']})")
            else:
                diffs["increase"] += delta
                if should_log: logger.info(f"🟢 {short}: +{delta} (поповнення складу)")
                
            rec_all_diffs[key] = diffs
            
        self.stock_cumulative_diffs[msg_key] = rec_all_diffs

    def _init_driver(self):
        """Ініціалізація Selenium Driver"""
        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        chrome_options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
        
        service = Service(ChromeDriverManager().install())
        return webdriver.Chrome(service=service, options=chrome_options)

    def fetch_page_with_selenium(self, url: str, driver=None) -> str:
        """
        Завантаження сторінки з використанням Selenium
        """
        logger.info(f"Завантаження сторінки: {url}")
        
        local_driver = False
        if driver is None:
            driver = self._init_driver()
            local_driver = True
            
        try:
            # Anti-ban delay
            delay = random.uniform(2, 5)
            logger.info(f"Anti-ban затримка: {delay:.2f} сек...")
            time.sleep(delay)
            
            driver.get(url)
            time.sleep(5) # JS Load delay
            
            try:
                WebDriverWait(driver, 15).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "product-item"))
                )
            except:
                pass
                
            html = driver.page_source
            return html
        finally:
            if local_driver and driver:
                driver.quit()
            
    def _fetch_delivery_date_details(self, url: str, driver) -> Optional[str]:
        """
        Отримання дати доставки через Selenium (бо requests блокує 403)
        """
        logger.info(f"Отримання детальної інформації про доставку (Selenium): {url}")
        
        delay = self.config.get('detail_fetch_delay', 2.0)
        logger.info(f"Затримка перед запитом до товару: {delay} сек...")
        time.sleep(delay)
        
        try:
            driver.get(url)
            # Очікування конкретного елемента
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "ampreorder-observed"))
                )
                time.sleep(0.3)  # Невелика пауза для стабілізації тексту
            except:
                logger.warning(f"Елемент .ampreorder-observed не з'явився на {url}")
            
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            date_elem = soup.select_one('.ampreorder-observed')
            if date_elem:
                match = re.search(r'(\d{1,2})-(\d{1,2})-(\d{4})', date_elem.get_text())
                if match:
                    # Regex шукає DD-MM-YYYY в тексті (працює і без пробілу: "доставки:27-03-2026")
                    # Нормалізація дати до DD-MM-YYYY (додавання нулів)
                    d, m, y = match.groups()
                    return f"{int(d):02d}-{int(m):02d}-{y}"
            return None
        except Exception as e:
            logger.warning(f"Не вдалося отримати дату доставки для {url}: {e}")
            return None
    
    def _fetch_real_stock(self, url: str, driver) -> Optional[int]:
        """
        Отримання реальної кількості на складі через Selenium 
        (шляхом введення 30000 в поле кількості)
        """
        logger.info(f"Отримання реального залишку (Selenium): {url}")
        
        try:
            # Ми вже на сторінці якщо викликано після _fetch_delivery_date_details, 
            # але для надійності перевіримо URL або просто завантажимо
            if driver.current_url != url:
                driver.get(url)
                
            # 1. Обробка обов'язкових випадаючих списків (dropdowns)
            # Деякі товари (наприклад, Eve MB31) вимагають вибору опцій (Busbars)
            try:
                # Шукаємо всі видимі select-елементи, які можуть бути обов'язковими
                selects = driver.find_elements(By.CSS_SELECTOR, "select.super-attribute-select, select.required-entry, select[id^='select_']")
                for selector in selects:
                    if selector.is_displayed():
                        from selenium.webdriver.support.ui import Select
                        s = Select(selector)
                        # Перевіряємо, чи вже вибрано щось (окрім дефолтного "Choose an Option")
                        if not s.first_selected_option or s.first_selected_option.get_attribute('value') == "":
                            # Логуємо всі доступні опції для діагностики
                            for idx, opt in enumerate(s.options):
                                logger.info(f"  Опція [{idx}]: '{opt.text}' (value='{opt.get_attribute('value')}')")
                            
                            # 1.1 Пошук пріоритетних опцій (із шинами/busbars)
                            # УВАГА: додаємо 'так'/'yes', бо іноді варіанти просто 'Ні' та 'Так'
                            priority_keywords = ['busbar', 'шини', 'шин', 'так', 'yes']
                            negative_patterns = [r'\bні\b', r'\bбез\b', r'\bno\b', r'\bnone\b', r'не потрібні']
                            
                            target_idx = None
                            
                            # Спроба знайти найкращий варіант (із шинами)
                            for i in range(1, len(s.options)):
                                opt_text = s.options[i].text.lower()
                                val = s.options[i].get_attribute('value')
                                if not val: continue
                                
                                # Якщо містить ключові слова І НЕ містить заперечень
                                if any(kw in opt_text for kw in priority_keywords):
                                    if not any(re.search(pat, opt_text) for pat in negative_patterns):
                                        logger.info(f"Знайдено пріоритетну опцію: {s.options[i].text}")
                                        target_idx = i
                                        break
                            
                            # Якщо пріоритет не знайдено, просто беремо першу доступну
                            if target_idx is None:
                                logger.info("Пріоритетну опцію не знайдено, обираємо першу доступну")
                                for i in range(1, len(s.options)):
                                    if s.options[i].get_attribute('value'):
                                        target_idx = i
                                        break
                            
                            if target_idx is not None:
                                logger.info(f"Вибір опції: {s.options[target_idx].text}")
                                s.select_by_index(target_idx)
                                time.sleep(0.5) # Пауза для оновлення ціни/стану

            except Exception as e:
                logger.warning(f"Помилка при спробі вибрати опції на {url}: {e}")

            # 2. Очікування та заповнення поля qty
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "qty"))
                )
            except:
                logger.warning(f"Поле 'qty' не знайдено на {url}")
                return None
            
            qty_input = driver.find_element(By.NAME, "qty")
            qty_input.clear()
            qty_input.send_keys("30000")
            time.sleep(1) # Пауза, щоб сайт "захопив" нове число
            
            # 3. Пошук кнопки Add to Cart / Pre Order
            button_selectors = ["button.tocart", "button.btn--cart", ".action.primary.tocart"]
            cart_button = None
            for selector in button_selectors:
                try:
                    btns = driver.find_elements(By.CSS_SELECTOR, selector)
                    for btn in btns:
                        if btn.is_displayed() and btn.is_enabled():
                            cart_button = btn
                            break
                    if cart_button:
                        break
                except:
                    continue
            
            if not cart_button:
                logger.warning(f"Не знайдено активну кнопку додавання в кошик на {url}")
                return None
                
            # Клікаємо JS-ом для надійності, якщо звичайний клік перекрито чимось
            try:
                cart_button.click()
            except:
                driver.execute_script("arguments[0].click();", cart_button)
            
            # 4. Очікування повідомлення помилки
            error_selector = ".message-error, .mage-error, .message.error, .message-success"
            
            # Спершу перевіримо, чи помилка ВЖЕ є (наприклад, від попереднього разу)
            def find_error():
                try:
                    return driver.find_elements(By.CSS_SELECTOR, error_selector)
                except:
                    return []

            # Якщо помилки нема, чекаємо
            if not find_error():
                try:
                    WebDriverWait(driver, 12).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, error_selector))
                    )
                except:
                    # Перевіримо, чи поле qty все ще 30000. Якщо воно скинулося в 1 - значить сайт щось зробив
                    current_qty = qty_input.get_attribute('value')
                    logger.warning(f"Повідомлення не з'явилося на {url}. Qty: {current_qty}")
                    if current_qty != "30000":
                        logger.info("Поле qty змінилося без повідомлення - вважаємо критичною помилкою наявності (0 шт)")
                        return 0
                    return None
            
            # 5. Парсинг тексту помилки
            # ВАЖЛИВО: беремо ОСТАННІЙ елемент помилки, бо на сторінці можуть 
            # залишатись повідомлення від попередніх товарів (Magento кешує)
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            error_elems = soup.select(error_selector)
            error_elem = error_elems[-1] if error_elems else None
            if error_elem:
                text = error_elem.get_text(strip=True)
                logger.info(f"Знайдено {len(error_elems)} помилок на сторінці, беремо останню: '{text[:80]}...'")
                # "The most you can purchase is 10928" або "only 10928 left"
                # Додаємо підтримку різних форматів повідомлень NKON
                patterns = [
                    r'only\s+(\d+)\s+left',
                    r'most\s+you\s+can\s+purchase\s+is\s+(\d+)',
                    r'максимальна\s+кількість\s+.*?\s+(\d+)',
                    r'залишилося\s+лише\s+(\d+)'
                ]
                
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        stock_val = int(match.group(1))
                        logger.info(f"✅ Знайдено реальний залишок: {stock_val}")
                        return stock_val
                
                # Специфічні фрази для нульового залишку
                zero_stock_patterns = [
                    r'немає в наявності',
                    r'not available',
                    r'not in stock',
                    r'out of stock'
                ]
                if any(re.search(p, text, re.IGNORECASE) for p in zero_stock_patterns):
                    logger.warning(f"Знайдено повідомлення про відсутність товару (0 шт): '{text}'")
                    return 0
                
                logger.warning(f"Помилка знайдена, але кількість не розпізнана: '{text}' (URL: {url})")
                return 0 # Вважаємо 0, якщо є помилка наявності, але нема числа
            else:
                logger.warning(f"Елемент помилки знайдено Selenium-ом, але BeautifulSoup його не бачить на {url}")
                
            return None
        except Exception as e:
            logger.error(f"Критична помилка при отриманні залишку для {url}: {e}", exc_info=True)
            return None
    

    def clean_price(self, price_text: str) -> Optional[float]:
        """
        Очищення та конвертація ціни в float
        
        Args:
            price_text: Текст ціни (наприклад, "€ 89.95" або "€89.95")
        
        Returns:
            Ціна як float або None
        """
        try:
            # Якщо є і кома, і крапка (наприклад, 1,234.50)
            if ',' in price_text and '.' in price_text:
                # Визначаємо, що є роздільником тисяч (той, що йде першим)
                if price_text.find(',') < price_text.find('.'):
                    price_text = price_text.replace(',', '') # Видаляємо кому
                else:
                    price_text = price_text.replace('.', '').replace(',', '.') # Видаляємо крапку, кому в крапку
            
            # Видаляємо всі символи крім цифр, крапки та коми
            cleaned = re.sub(r'[^\d.,]', '', price_text)
            # Замінюємо кому на крапку (якщо вона залишилась як єдиний роздільник)
            cleaned = cleaned.replace(',', '.')
            
            # Якщо після заміни залишилось більше однієї крапки (наприклад, 1.234.50)
            if cleaned.count('.') > 1:
                parts = cleaned.split('.')
                cleaned = "".join(parts[:-1]) + "." + parts[-1]
                
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
    
    def _get_next_page_url(self, html: str) -> Optional[str]:
        """
        Знаходить URL наступної сторінки в пагінації Magento 2
        """
        soup = BeautifulSoup(html, 'html.parser')
        next_item = soup.find('li', class_='pages-item-next')
        if next_item:
            next_link = next_item.find('a')
            if next_link and next_link.get('href'):
                return next_link.get('href')
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
        
        # Ціна (UA магазин завжди показує ціни без ПДВ)
        includes_tax = False
        
        # Беремо головну ціну
        price_elem = item.find('span', class_='price')
            
        price_raw = 'N/A'
        if price_elem:
            price_raw = price_elem.get_text(strip=True)
        else:
            logger.warning(f"Ціну не знайдено для {name}")
            
        price_float = self.clean_price(price_raw)
        
        # Нормалізація відображення ціни (завжди €52.95 замість 52,95 EUR)
        if price_float is not None:
            price_raw = f"€{price_float:.2f}"
            
        # Статус наявності
        stock_status = self._check_stock_status(item)
        
        if not stock_status:
            return None  # Тільки In Stock та Pre-order
        
        return {
            'name': name,
            'capacity': capacity,
            'price': price_raw,      # Оригінальний текст для відображення
            'price_value': price_float, # Числове значення для аналізу
            'includes_tax': includes_tax, # Boolean: True if VAT included
            'link': link,
            'stock_status': stock_status,  # 'in_stock' або 'preorder'
            'delivery_date': None,       # Буде заповнено пізніше в run() якщо preorder
            'real_stock': None,          # Реальний залишок
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
        current_state = {f"{p['link']}_{p.get('capacity', '0')}": p for p in current_products}
        
        new_items = []
        removed_items = []
        price_changes = []
        status_changes = []
        
        # Пошук нових товарів та змін
        is_first_run = not bool(self.previous_state)
        
        for link, product in current_state.items():
            if link not in self.previous_state:
                if not is_first_run:
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
                        'link': product['link'],
                        'old_price': old_product.get('price', 'N/A'),
                        'new_price': product.get('price', 'N/A'),
                        'old_price_value': old_price_val,
                        'new_price_value': new_price_val
                    })
                
                # Зміни статусу або дати доставки
                status_changed = product['stock_status'] != old_product['stock_status']
                date_changed = product.get('delivery_date') != old_product.get('delivery_date')
                
                if status_changed or date_changed:
                    status_changes.append({
                        'name': product['name'],
                        'capacity': product['capacity'],
                        'link': product['link'],
                        'price': product['price'],
                        'old_status': old_product['stock_status'],
                        'new_status': product['stock_status'],
                        'old_date': old_product.get('delivery_date'),
                        'new_date': product.get('delivery_date')
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
    
    def _extract_grade(self, text: str) -> str:
        """
        Витягування грейду (Grade A/B) з назви
        Підтримує англійську (Grade) та українську (Клас) версії
        """
        # Grade A, Grade A-, Клас A, Група A, B-Grade тощо
        match = re.search(r'(?i)(?:(?:Grade|Клас|Група)\s*[A-B][-+]?|[A-B]-Grade)', text)
        if match:
            grade = match.group(0)
            # Нормалізація: B-Grade -> Grade B
            if len(grade) > 1 and grade[1] == '-': 
                return f"Grade {grade[0]}"
            # Клас A -> Grade A, Група A -> Grade A
            grade = re.sub(r'(?i)(Клас|Група)', 'Grade', grade)
            grade = grade.title()  # grade a -> Grade A
            return grade
        return "?"

    def _shorten_name(self, text: str) -> str:
        """
        Скорочення назви товару для компактності
        Підтримує англійську та українську версії
        """
        # 1. Видаляємо грейд (бо ми його показуємо окремо)
        # Підтримка Grade/Клас/Група
        text = re.sub(r'(?i)(?:(?:Grade|Клас|Група)\s*[A-B][-+]?|[A-B]-Grade)', '', text)
        
        # 2. Видаляємо технічні характеристики (бо вони зрозумілі з контексту)
        remove_words = [
            r'LiFePO4', r'3\.2V', r'Prismatic', r'Rechargeable', 
            r'Battery', r'Cell', r'\d+\s*Ah',  # Ємність вже є на початку
            r'Призматичний'  # Українська "Prismatic"
        ]
        
        for word in remove_words:
            text = re.sub(f'(?i){word}', '', text)
            
        # 3. Видаляємо зайві символи та пробіли
        text = text.replace(' - ', ' ').replace(' , ', ' ')
        
        # Видаляємо дублікати пробілів
        text = ' '.join(text.split())
        
        # Видаляємо зайві символи в кінці та на початку (тире, коми, крапки)
        text = text.strip(" -.,|")
        
        # Максимальна довжина (обрізаємо якщо задовга)
        if len(text) > 30:
            text = text[:28] + ".."
            
        return text.strip()

    def _mask_sensitive(self, text: str) -> str:
        """Маскування чутливих даних в логах"""
        if not text: return ""
        text_str = str(text)
        if len(text_str) <= 12:
            return "***"
        return f"{text_str[:4]}***{text_str[-4:]}"

    def _format_stock_display(self, item, show_diffs: bool = True, msg_key: str = None) -> str:
        """Формує рядок залишку. Чисте читання - можна викликати багато разів."""
        if item.get('real_stock') is None:
            return ""
            
        current = item['real_stock']
        
        if not show_diffs or not msg_key:
            return f" `[{current} шт]`"
        
        key = f"{item['link']}_{item.get('capacity', '0')}"
        
        # Отримуємо дельти для конкретного отримувача (msg_key)
        rec_diffs = self.stock_cumulative_diffs.get(msg_key, {})
        diffs = rec_diffs.get(key, {"decrease": 0, "increase": 0})
        
        dec = diffs["decrease"]  # завжди <= 0
        inc = diffs["increase"]  # завжди >= 0
        
        if dec != 0 or inc != 0:
            diff_str = ""
            if dec != 0: diff_str += str(dec)       # "-128"
            if inc != 0: diff_str += f"+{inc}"      # "+2000"
            return f" `[{current}({diff_str}) шт]`"
            
        return f" `[{current} шт]`"

    def format_telegram_message(self, changes: Dict, include_unchanged: bool = True, is_update: bool = False, show_stock_diffs: bool = False, unchanged_header: str = "Без змін", msg_key: str = None) -> Optional[str]:
        """
        Форматування повідомлення для Telegram
        """
        msg = f"[🔋 NKON LiFePO4 Monitor]({settings.MAIN_CHANNEL_URL})\n\n"
        
        has_changes = False
        threshold = self.config.get('price_alert_threshold', 5)
        
        def get_grade_display(grade_str: str) -> str:
            """Формує рядок грейду з відповідним емодзі та іконкою мінуса"""
            if grade_str == "?":
                return ""
            
            # Вибір основної іконки
            emoji = "🅰️" if "Grade A" in grade_str else "🅱️" if "Grade B" in grade_str else "❓"
            
            # Додаємо іконку мінуса, якщо він є в грейді
            if "-" in grade_str:
                emoji += "➖"
                
            return f"{emoji} {grade_str} | "

        def format_line(item, prefix_emoji="", show_status=False):
            """Helper для форматування одного рядка товару"""
            grade = self._extract_grade(item['name'])
            short_name = self._shorten_name(item['name'])
            price = item.get('price', 'N/A')
            grade_msg = get_grade_display(grade)
            
            # 1. Підготовка повідомлення про залишок
            stock_msg = self._format_stock_display(item, show_diffs=show_stock_diffs, msg_key=msg_key)
            
            # 2. Статус (Pre-order/In Stock) + Дата доставки
            status_ico = ""
            delivery_msg = ""
            
            if item.get('stock_status') == 'preorder':
                status_ico = f" [📦Pre]({item['link']})"
                if item.get('delivery_date'):
                    # Для Pre-order залишок йде після дати (зовні лінка, щоб не зламати Markdown)
                    delivery_msg = f"\n  [{self.LINE_PREFIX} {item['delivery_date']}]({item['link']}){stock_msg}"
                else:
                    # Якщо раптом дати немає, але є залишок
                    status_ico += stock_msg
            elif item.get('stock_status') == 'in_stock':
                status_ico = f" [✅In]({item['link']}){stock_msg}"
            elif item.get('stock_status') == 'out_of_stock':
                status_ico = f" ❌Out{stock_msg}"
                
            link_text = f"[{item['capacity']}Ah]({item['link']})"
            
            return f"{prefix_emoji} {link_text} {grade_msg}{short_name} | {price}{status_ico}{delivery_msg}"

        # Нові товари
        if changes.get('new'):
            has_changes = True
            msg += f"✨ *Нові товари ({len(changes['new'])}):*\n"
            for item in changes['new']:
                msg += format_line(item, "•") + "\n"
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
                
                grade = self._extract_grade(item['name'])
                grade_msg = get_grade_display(grade)
                short_name = self._shorten_name(item['name'])
                
                msg += f"• [{item['capacity']}Ah]({item['link']}) {grade_msg}{short_name} | {change_str}\n"
            msg += "\n"
        
        # Зміни статусу або дати
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
                
                if old_status != new_status:
                    status_info = f" | {old_str} → {new_str}"
                else:
                    status_info = "" # Статус не змінився, значить змінилася тільки дата
                
                # Показ дати
                date_msg = ""
                old_date = item.get('old_date')
                new_date = item.get('new_date')
                if new_date:
                    if old_date and old_date != new_date:
                        date_msg = f"\n  {self.LINE_PREFIX} {old_date} → {new_date}"
                    else:
                        date_msg = f"\n  {self.LINE_PREFIX} {new_date}"
                
                grade_raw = self._extract_grade(item['name'])
                grade_msg = get_grade_display(grade_raw)
                short_name = self._shorten_name(item['name'])
                
                msg += f"• {status_emoji} [{item['capacity']}Ah]({item['link']}) {grade_msg}{short_name}{status_info}{date_msg} | {price}\n"
            msg += "\n"
        
        # Видалені товари
        if changes.get('removed'):
            has_changes = True
            msg += f"❌ *Видалені ({len(changes['removed'])}):*\n"
            for item in changes['removed']:
                link_text = f"[{item['capacity']}Ah]({item['link']})"
                msg += f"• {link_text} {self._shorten_name(item['name'])}\n"
            msg += "\n"
            
        # Якщо змін немає, чи показувати повний список?
        if not has_changes and not include_unchanged:
            return None
        
        # Збираємо лінки товарів, що змінилися
        changed_links = set()
        for item in changes.get('new', []): changed_links.add(item['link'])
        for item in changes.get('price_changes', []): changed_links.add(item['link'])
        for item in changes.get('status_changes', []): changed_links.add(item['link'])
        
        # Включаємо блок "Без змін" тільки якщо просили
        if include_unchanged:
            current = changes.get('current', [])
            unchanged = [p for p in current if p['link'] not in changed_links]
            
            if unchanged:
                msg += f"📋 *{unchanged_header} ({len(unchanged)}):*\n"
                for item in unchanged:
                    msg += format_line(item, "•") + "\n"
        
        # Видаляємо всі зайві пробіли/переноси в кінці та додаємо час одним пустим рядком
        msg = msg.strip()
        status_emoji = "🆕" if not is_update else "🔄"
        msg += f"\n\n{status_emoji} {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
        return msg

    
    def edit_telegram_message(self, chat_id: str, message_id: int, text: str) -> bool:
        """
        Редагування існуючого повідомлення
        """
        bot_token = self.config.get('telegram_bot_token')
        if not bot_token: return False
        
        # Перетворюємо в int якщо це числовий ID (для стабільності API)
        target_chat = chat_id
        if isinstance(chat_id, str):
            if (chat_id.startswith('-') and chat_id[1:].isdigit()) or chat_id.isdigit():
                target_chat = int(chat_id)
        
        url = f"https://api.telegram.org/bot{bot_token}/editMessageText"
        payload = {
            'chat_id': target_chat,
            'message_id': message_id,
            'text': text,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        masked_chat = self._mask_sensitive(chat_id)
        
        try:
            response = self.session.post(url, json=payload, timeout=10)
            if not response.ok:
                logger.warning(f"Не вдалося відредагувати повідомлення {masked_chat}/{message_id}: {response.text}")
                return False
            logger.info(f"✏️ Повідомлення {message_id} у чаті {masked_chat} оновлено")
            return True
        except Exception as e:
            logger.warning(f"Помилка редагування в {masked_chat}: {e}")
            return False

    def send_telegram_message(self, message: str, chat_ids: Set[str] = None, thread_id: Optional[int] = None, dry_run: bool = False, disable_notification: bool = False) -> Dict[str, int]:
        """
        Відправка повідомлення в Telegram
        Returns: Dict {chat_id: message_id}
        """
        sent_messages = {}
        if not chat_ids:
            return sent_messages

        # --- Quiet Mode Logic ---
        now_hour = datetime.now().hour
        q_start = self.config.get('quiet_hours_start', 21)
        q_end = self.config.get('quiet_hours_end', 8)
        
        is_quiet = False
        if q_start > q_end:  # e.g. 21:00 to 08:00
            if now_hour >= q_start or now_hour < q_end:
                is_quiet = True
        else:  # e.g. 00:00 to 08:00
            if q_start <= now_hour < q_end:
                is_quiet = True
        
        if is_quiet and not disable_notification:
            logger.info(f"🌙 Quiet Mode ({q_start}-{q_end}): вимикаємо звук для повідомлення")
            disable_notification = True

        if dry_run:
            logger.info(f"[DRY RUN] Telegram повідомлення для {[self._mask_sensitive(c) for c in chat_ids]}:\n{message}")
            return sent_messages

        bot_token = self.config.get('telegram_bot_token')
        if not bot_token:
            logger.error("Telegram credentials не налаштовані")
            return sent_messages
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        success_count = 0
        
        for chat_id in chat_ids:
            masked_chat = self._mask_sensitive(chat_id)
            
            # Перетворюємо в int якщо це числовий ID
            target_chat = chat_id
            if isinstance(chat_id, str):
                if (chat_id.startswith('-') and chat_id[1:].isdigit()) or chat_id.isdigit():
                    target_chat = int(chat_id)
            
            payload = {
                'chat_id': target_chat,
                'text': message,
                'parse_mode': 'Markdown',
                'disable_web_page_preview': True,
                'disable_notification': disable_notification
            }
            
            # Пріоритет: аргумент thread_id > налаштування в config (якщо вони залишились)
            target_thread = thread_id or self.config.get('telegram_thread_id')
            if target_thread:
                payload['message_thread_id'] = target_thread
            
            try:
                response = self.session.post(url, json=payload, timeout=10)
                if not response.ok:
                    logger.error(f"❌ Помилка Telegram API для {masked_chat}: {response.status_code} {response.text}")
                response.raise_for_status()
                
                data = response.json()
                if data.get('ok'):
                    msg_id = data['result']['message_id']
                    sent_messages[chat_id] = msg_id
                
                success_count += 1
                logger.info(f"✅ Повідомлення відправлено до чату {masked_chat}")
            except Exception as e:
                if not isinstance(e, requests.exceptions.HTTPError):
                    logger.error(f"❌ Помилка відправки до чату {masked_chat}: {e}")
        
        if success_count > 0:
            logger.info(f"📊 Відправлено {success_count}/{len(chat_ids)} повідомлень")
            
        return sent_messages
    
    def _should_notify(self, has_changes: bool) -> tuple:
        """
        Визначає, чи потрібно надсилати повідомлення зі звуком.
        
        Returns: (should_notify: bool, reason: str)
        """
        if has_changes:
            return True, "changes"
        
        now = datetime.now()
        last = self.last_notification_time
        # Cooldown за замовчуванням 24h (буде автоматично перевизначено при завантаженні конфігу)
        cooldown_hours = self.config.get('heartbeat_cooldown', 24.0)
        
        # 1. Перевірка Cooldown (найвищий пріоритет для тиші)
        if (now - last).total_seconds() < (cooldown_hours * 3600):
            logger.info(f"🔕 Heartbeat пропущено: cooldown (остання {last.strftime('%H:%M')})")
            return False, "cooldown"
        
        # 2. Перевірка Heartbeat слотів
        heartbeat_times = self.config.get('heartbeat_times', [])
        for hb_time in heartbeat_times:
            # Чи зараз >= цей слот?
            if now.time() >= hb_time:
                # Чи вже була нотифікація ПІСЛЯ цього слоту сьогодні?
                slot_dt = datetime.combine(now.date(), hb_time)
                if last < slot_dt:
                    logger.info(f"🔔 Heartbeat: слот {hb_time.strftime('%H:%M')}")
                    return True, "heartbeat"
        
        return False, "silent"

    def run(self, dry_run: bool = False, force_notify: bool = False):
        """
        Основний цикл моніторингу
        
        Args:
            dry_run: Якщо True, не відправляти Telegram повідомлення
            force_notify: Примусова нотифікація зі звуком
        """
        logger.info("=" * 60)
        logger.info(f"Запуск моніторингу NKON (Фаза 4: {len(settings.RECIPIENTS)} отримувачів)")
        logger.info("=" * 60)
        
        # --- Aggregation Logic (Розрахунок мінімальних вимог для скрапера) ---
        effective_min_ah = settings.MIN_CAPACITY_AH
        effective_fetch_dates = settings.FETCH_DELIVERY_DATES
        effective_fetch_stock = settings.FETCH_REAL_STOCK
        
        if settings.RECIPIENTS:
            # Скрапер бере найменшу ємність серед усіх отримувачів, щоб зібрати всі потрібні дані
            effective_min_ah = min([r.get('min_capacity_ah', settings.MIN_CAPACITY_AH) for r in settings.RECIPIENTS])
            # Глибокий збір (дати/залишки) запускається, якщо хоча б один отримувач його потребує
            effective_fetch_dates = any([r.get('fetch_delivery_dates', settings.FETCH_DELIVERY_DATES) for r in settings.RECIPIENTS])
            effective_fetch_stock = any([r.get('fetch_real_stock', settings.FETCH_REAL_STOCK) for r in settings.RECIPIENTS])

        driver = None
        try:
            # Ініціалізація драйвера
            driver = self._init_driver()
            
            # Завантаження сторінок з пагінацією
            url = settings.NKON_URL
            
            products = []
            current_url = url
            page_num = 1
            max_pages = 5
            
            while current_url and page_num <= max_pages:
                if page_num > 1:
                    logger.info(f"Перехід до сторінки {page_num}: {current_url}")
                
                html = self.fetch_page_with_selenium(current_url, driver=driver)
                
                # Парсинг товарів з поточної сторінки
                page_products = self.parse_products(html)
                
                # Попередня фільтрація за ефективною мінімальною ємністю
                page_products = [p for p in page_products if p['capacity'] >= effective_min_ah]
                products.extend(page_products)
                
                # Пошук наступної сторінки
                current_url = self._get_next_page_url(html)
                if current_url:
                    page_num += 1
                else:
                    break
            
            if page_num > 1:
                logger.info(f"Загалом знайдено {len(products)} товарів (>={effective_min_ah}Ah) на {page_num} сторінках")
            
            # Додатково: отримання деталей
            if effective_fetch_dates or effective_fetch_stock:
                target_items = [p for p in products if p['stock_status'] in ['in_stock', 'preorder']]
                
                if target_items:
                    logger.info(f"Збір деталей для {len(target_items)} товарів (Dates={effective_fetch_dates}, Stock={effective_fetch_stock})...")
                    for p in target_items:
                        # 1. Дата доставки
                        if effective_fetch_dates:
                            date = self._fetch_delivery_date_details(p['link'], driver=driver)
                            if date:
                                p['delivery_date'] = date
                                if p['stock_status'] == 'in_stock':
                                    logger.info(f"  Каталог вказав in_stock, але знайдено дату передзамовлення -> preorder")
                                    p['stock_status'] = 'preorder'
                            else:
                                key = f"{p['link']}_{p.get('capacity', '0')}"
                                old_p = self.previous_state.get(key)
                                if old_p and old_p.get('stock_status') == 'preorder' and old_p.get('delivery_date'):
                                    p['delivery_date'] = old_p['delivery_date']
                        
                        # 2. Реальний залишок
                        if effective_fetch_stock:
                            stock = self._fetch_real_stock(p['link'], driver=driver)
                            if stock is not None:
                                p['real_stock'] = stock
                                if stock == 0:
                                    logger.warning(f"  ⚠️ {p.get('capacity')}Ah: 0 шт на складі, статус -> out_of_stock")
                                    p['stock_status'] = 'out_of_stock'
                            else:
                                key = f"{p['link']}_{p.get('capacity', '0')}"
                                old_p = self.previous_state.get(key)
                                if old_p and old_p.get('real_stock') is not None:
                                    p['real_stock'] = old_p['real_stock']
            
            # Остаточна фільтрація: видаляємо виявлені out_of_stock
            products = [p for p in products if p['stock_status'] in ['in_stock', 'preorder']]
            
            if not products:
                logger.warning("Не знайдено товарів після фільтрації")
                # Навіть якщо товарів немає, ми маємо зберегти стан (пустий)
            
            # --- Per-Recipient Notification Loop ---
            new_last_messages = {}
            active_no_changes = {}
            
            # Спочатку створюємо загальний список товарів для збереження в state
            current_state = {f"{p['link']}_{p.get('capacity', '0')}": p for p in products}

            logger.info(f"Початок розсилки для {len(settings.RECIPIENTS)} отримувачів...")
            
            for recipient in settings.RECIPIENTS:
                chat_id = str(recipient['chat_id'])
                thread_id = recipient.get('thread_id')
                rpt_type = recipient.get('type', 'changes')
                # Ключ для відстеження повідомлень: chat_id_threadID щоб уникнути конфліктів у топіках
                msg_key = f"{chat_id}_{thread_id}" if thread_id else chat_id
                
                # Фільтрація товарів конкретно для цього отримувача
                rec_min_ah = recipient.get('min_capacity_ah', settings.MIN_CAPACITY_AH)
                rec_products = [p for p in products if p['capacity'] >= rec_min_ah]
                
                # Оновлюємо лічильники залишків та виявляємо зміни для цього отримувача
                self._update_stock_counters(rec_products, msg_key)
                rec_changes = self.detect_changes(rec_products)
                
                # 1. Повні звіти
                if rpt_type == 'full':
                    msg_full = self.format_telegram_message(rec_changes, include_unchanged=True, is_update=False, msg_key=msg_key)
                    if msg_full:
                        sent = self.send_telegram_message(msg_full, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run)
                        if chat_id in sent:
                            new_last_messages[msg_key] = sent[chat_id]
                
                # 2. Звіти про зміни
                elif rpt_type == 'changes':
                    msg_ch = self.format_telegram_message(rec_changes, include_unchanged=False, is_update=False, msg_key=msg_key)
                    should_notify, reason = self._should_notify(bool(msg_ch))
                    if force_notify:
                        should_notify, reason = True, "force-notify"
                    
                    old_nc_msgs = self.last_messages.get('_no_changes', {})
                    last_nc_id = old_nc_msgs.get(msg_key)

                    if msg_ch:
                        # Зафіксувати дельти у старому повідомленні
                        if last_nc_id and not dry_run:
                            msg_upd = self.format_telegram_message(rec_changes, include_unchanged=True, is_update=True, show_stock_diffs=True, msg_key=msg_key)
                            self.edit_telegram_message(chat_id, last_nc_id, msg_upd)
                        
                        # Скидаємо лічильники ТІЛЬКИ ПІСЛЯ оновлення старого (як контрольна точка)
                        self.stock_cumulative_diffs[msg_key] = {}

                        # Нове повідомлення про зміни
                        logger.info(f"📣 Зміни для {msg_key}: надсилаємо звіт")
                        self.send_telegram_message(msg_ch, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run)
                        self.last_notification_time = datetime.now()
                        
                        if not dry_run: time.sleep(2)
                        
                        # Новий стан (тихо)
                        no_changes_only = {'new': [], 'removed': [], 'price_changes': [], 'status_changes': [], 'current': rec_changes['current']}
                        msg_ns = self.format_telegram_message(no_changes_only, include_unchanged=True, is_update=False, show_stock_diffs=False, unchanged_header="Новий стан", msg_key=msg_key)
                        sent_st = self.send_telegram_message(msg_ns, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run, disable_notification=True)
                        if chat_id in sent_st:
                            active_no_changes[msg_key] = sent_st[chat_id]
                    
                    elif reason == "heartbeat" or reason == "force-notify":
                        logger.info(f"🔔 Heartbeat/Force для {msg_key}")
                        if last_nc_id and not dry_run:
                            msg_upd = self.format_telegram_message(rec_changes, include_unchanged=True, is_update=True, show_stock_diffs=True, msg_key=msg_key)
                            self.edit_telegram_message(chat_id, last_nc_id, msg_upd)
                        
                        self.stock_cumulative_diffs[msg_key] = {}
                        if not dry_run: time.sleep(2)
                        
                        no_changes_only = {'new': [], 'removed': [], 'price_changes': [], 'status_changes': [], 'current': rec_changes['current']}
                        msg_hb = self.format_telegram_message(no_changes_only, include_unchanged=True, is_update=False, show_stock_diffs=False, unchanged_header="Новий стан", msg_key=msg_key)
                        sent_hb = self.send_telegram_message(msg_hb, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run, disable_notification=False)
                        self.last_notification_time = datetime.now()
                        if chat_id in sent_hb:
                            active_no_changes[msg_key] = sent_hb[chat_id]
                    
                    else:
                        # Без змін - тихо редагувати
                        msg_upd = self.format_telegram_message(rec_changes, include_unchanged=True, is_update=True, show_stock_diffs=True, msg_key=msg_key)
                        if not msg_upd:
                            msg_upd = f"[🔋 NKON Monitor]({settings.MAIN_CHANNEL_URL})\n\n📋 Без змін\n\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                        
                        success = False
                        if last_nc_id and not dry_run:
                            success = self.edit_telegram_message(chat_id, last_nc_id, msg_upd)
                            if success:
                                active_no_changes[msg_key] = last_nc_id
                        
                        if not success:
                            sent_nc = self.send_telegram_message(msg_upd, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run, disable_notification=True)
                            if chat_id in sent_nc:
                                active_no_changes[msg_key] = sent_nc[chat_id]
            
            new_last_messages['_no_changes'] = active_no_changes
            
            # State V2
            state_to_save = {
                'products': current_state,
                'last_messages': new_last_messages,
                'stock_cumulative_diffs': self.stock_cumulative_diffs,
                'last_notification_time': self.last_notification_time.isoformat(),
                'version': 2
            }
            
            if not dry_run:
                self._save_state(state_to_save)
            else:
                logger.info("🚫 Dry Run: State НЕ оновлено")
            
            logger.info("=" * 60)
            logger.info("Моніторинг завершено успішно")
            logger.info("=" * 60)

        except Exception as e:
            error_msg = f"❌ *КРИТИЧНА ПОМИЛКА МОНІТОРИНГУ*\n\n"
            error_msg += f"Тип: `{type(e).__name__}`\n"
            error_msg += f"Помилка: `{str(e)}`\n"
            error_msg += f"Час: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            
            logger.error(f"Критична помилка: {e}", exc_info=True)
            
            # Спроба відправити помилку в Telegram (тільки адмінам з типом 'full')
            if not dry_run:
                try:
                    admin_chats = {str(r['chat_id']) for r in settings.RECIPIENTS if r.get('type') == 'full'}
                    if admin_chats:
                        self.send_telegram_message(error_msg, chat_ids=admin_chats)
                except Exception as send_err:
                    logger.error(f"Не вдалося відправити помилку в Telegram: {send_err}")
            
            raise
        finally:
            if driver:
                logger.info("Закриття Selenium драйвера...")
                driver.quit()


def main():
    """Точка входу"""
    parser = argparse.ArgumentParser(description='NKON LiFePO4 Battery Monitor')
    parser.add_argument('--dry-run', action='store_true', 
                        help='Запуск без відправки Telegram повідомлень (для тестування)')
    parser.add_argument('--force-notify', action='store_true',
                        help='Примусова нотифікація зі звуком (для тестування)')
    
    args = parser.parse_args()
    
    monitor = NkonMonitor()
    monitor.run(dry_run=args.dry_run, force_notify=args.force_notify)


if __name__ == '__main__':
    main()
