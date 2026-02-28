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
import requests
import argparse
import shutil
import copy
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Optional, Set
from datetime import datetime
from bs4 import BeautifulSoup

import settings
from db_manager import HistoryDB
from utils import clean_price, extract_capacity, shorten_name, mask_sensitive, extract_grade
from telegram_notifier import TelegramNotifier
try:
    from visualize_history import HistoryVisualizer
except ImportError:
    HistoryVisualizer = None
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
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
        self.quietly_removed = {} # Додаємо сховище для тихо видалених
        self.last_messages = {}
        self.stock_cumulative_diffs = {}
        self.last_notification_time = datetime.min
        
        # Завантаження стану
        loaded_state = self._load_state()
        
        # Обробка версій State
        if (loaded_state.get('version') or 0) >= 2:
            self.previous_state = loaded_state.get('products', {})
            self.quietly_removed = loaded_state.get('quietly_removed', {})
            self.last_messages = loaded_state.get('last_messages', {})
            self.stock_cumulative_diffs = loaded_state.get('stock_cumulative_diffs', {})
            nt_str = loaded_state.get('last_notification_time')
            self.last_notification_time = datetime.fromisoformat(nt_str) if nt_str else datetime.min
        else:
            # Legacy state
            self.previous_state = loaded_state
            self.quietly_removed = {}
            
        self.session = requests.Session()
        self.telegram = TelegramNotifier(self.config, self.session)
        

            
    def _save_history_to_db(self, products: List[Dict]):
        """Збереження інформації в історичну базу даних"""
        try:
            logger.info("Запис інформації до бази даних історії...")
            db = HistoryDB()
            try:
                db.sync_products(products)
                db.record_changes_bulk(products)
                logger.info("✅ Історія успішно збережена в БД.")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Помилка при збереженні історії в БД: {e}", exc_info=True)

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
            
            short = shorten_name(item.get('name', key))
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
    
    def _probe_qty(self, driver, qty: int) -> tuple:
        """
        Один пробний запит з qty.
        Повертає: ('error', int), ('success', None), або ('silence', None).
        """
        try:
            qty_input = driver.find_element(By.NAME, "qty")
            qty_input.clear()
            qty_input.send_keys(str(qty))
            # Пауза, щоб сайт "захопив" нове число перед кліком
            time.sleep(0.5)
            
            # Пошук кнопки Add to Cart / Pre Order
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
                return ('silence', None)
                
            # Видалення старих повідомлень із DOM перед кліком
            driver.execute_script("""
                document.querySelectorAll('.message-error, .mage-error, .message.error, .message-success, .message.success').forEach(el => el.remove());
            """)
                
            # Клікаємо JS-ом для надійності
            try:
                cart_button.click()
            except:
                driver.execute_script("arguments[0].click();", cart_button)

            # Очікування відповіді (error або success)
            response_selector = ".message-error, .mage-error, .message.error, .message-success"
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, response_selector))
                )
            except (TimeoutException, StaleElementReferenceException):
                return ('silence', None)

            # Аналіз результату за допомогою BeautifulSoup
            soup = BeautifulSoup(driver.page_source, 'html.parser')
            
            # 1. Пошук помилки (Error)
            error_selector = ".message-error, .mage-error, .message.error"
            error_elems = soup.select(error_selector)
            if error_elems:
                text = error_elems[-1].get_text(strip=True)
                patterns = [
                    r'only\s+(\d+)\s+left',
                    r'most\s+you\s+can\s+purchase\s+is\s+(\d+)',
                    r'максимальна\s+кількість\s+.*?\s+(\d+)',
                    r'залишилося\s+лише\s+(\d+)'
                ]
                for pattern in patterns:
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        return ('error', int(match.group(1)))
                
                # Специфічні фрази для нульового залишку (тільки явна відсутність)
                zero_stock_patterns = [
                    r'out of stock'
                ]
                if any(re.search(p, text, re.IGNORECASE) for p in zero_stock_patterns):
                    # "The requested qty is not available"
                    # означає "ви запитали більше ніж є", а НЕ "товар відсутній"
                    if "requested qty" not in text.lower():
                        return ('error', 0)
                
                # Помилка є, але кількість не розпізнана
                # Перевіряємо на відомі фрази "недоступної кількості"
                unavailable_patterns = [
                    r'запитаної кількості немає в наявності',
                    r'requested qty is not available',
                    r'requested quantity is not available'
                ]
                if any(re.search(p, text, re.IGNORECASE) for p in unavailable_patterns):
                    return ('silence', None)

                # Також перевіряємо на "Обов’язкове поле"
                if "обов’язкове поле" in text.lower() or "required field" in text.lower():
                    return ('reselect', None)

                logger.warning(f"  ⚠️ Нерозпізнана помилка (трактуємо як silence): '{text[:100]}'")
                return ('silence', None) 

            # 2. Пошук успіху (ТІЛЬКИ явне повідомлення про додавання до кошика)
            success_selector = ".message-success"
            success_elems = soup.select(success_selector)
            if success_elems:
                success_text = success_elems[-1].get_text(strip=True).lower()
                # Перевіряємо, що це саме повідомлення про додавання (відсіює застарілі повідомлення)
                add_keywords = ['added', 'додано', 'shopping cart', 'кошик']
                if any(kw in success_text for kw in add_keywords):
                    return ('success', None)
                else:
                    logger.debug(f"  🔍 Проігноровано нецільовий success: '{success_text[:80]}'")

            return ('silence', None)
            
        except (TimeoutException, StaleElementReferenceException):
            return ('silence', None)
        except Exception as e:
            msg = str(e).split('\n')[0]
            logger.warning(f"Помилка при пробному запиті qty={qty}: {msg}")
            return ('silence', None)

    def _fetch_real_stock(self, url: str, driver, prev_stock: int = None) -> Optional[int]:
        """
        Адаптивне отримання реальної кількості на складі через Selenium.
        Використовує метод дихотомії (бінарного пошуку) у зоні невідомості.
        """
        logger.info(f"Отримання реального залишку (Адаптивно): {url}")
        
        try:
            if driver.current_url != url:
                driver.get(url)
                
            def select_options():
                try:
                    selects = driver.find_elements(By.CSS_SELECTOR, "select.super-attribute-select, select.required-entry, select[id^='select_']")
                    for selector in selects:
                        if selector.is_displayed():
                            from selenium.webdriver.support.ui import Select
                            s = Select(selector)
                            if not s.first_selected_option or s.first_selected_option.get_attribute('value') == "":
                                priority_keywords = ['busbar', 'шини', 'шин', 'так', 'yes']
                                negative_patterns = [r'\bні\b', r'\bбез\b', r'\bno\b', r'\bnone\b', r'не потрібні']
                                target_idx = None
                                for i in range(1, len(s.options)):
                                    opt_text = s.options[i].text.lower()
                                    if any(kw in opt_text for kw in priority_keywords):
                                        if not any(re.search(pat, opt_text) for pat in negative_patterns):
                                            target_idx = i
                                            break
                                if target_idx is None:
                                    for i in range(1, len(s.options)):
                                        if s.options[i].get_attribute('value'):
                                            target_idx = i
                                            break
                                if target_idx is not None:
                                    s.select_by_index(target_idx)
                                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Помилка при спробі вибрати опції на {url}: {str(e).splitlines()[0]}")

            select_options()

            # 2. Очікування поля qty
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.NAME, "qty"))
                )
            except:
                logger.warning(f"Поле 'qty' не знайдено на {url}")
                return None

            # 3. Адаптивний пошук (Midpoint Search)
            INITIAL_PROBE = 30000
            MAX_ITERATIONS = 12
            
            # prev_stock — це лише підказка для першої проби, НЕ підтверджений успіх
            last_success = 0
            if prev_stock and prev_stock > 0:
                qty = prev_stock
            else:
                qty = INITIAL_PROBE
            
            last_silence = None
            
            for i in range(MAX_ITERATIONS):
                if qty < 1: qty = 1
                
                logger.info(f"  [iter {i+1}/{MAX_ITERATIONS}] qty={qty}, "
                             f"last_success={last_success}, last_silence={last_silence}")
                
                state, val = self._probe_qty(driver, qty)
                
                if state == 'error':
                    # Якщо ми розпізнали конкретне число - це і є залишок 
                    if last_success > 0 and val < last_success:
                        logger.info(f"  📌 ERROR '{val}' точніше за попередній SUCCESS '{last_success}'")
                    logger.info(f"  ✅ Знайдено реальний залишок (limit): {val}")
                    return val
                elif state == 'reselect':
                    logger.warning(f"  🔄 Скидання опцій! Пробую вибрати ще раз...")
                    select_options()
                    # Не зараховуємо як ітерацію або пробуємо ту саму кількість ще раз
                    state, val = self._probe_qty(driver, qty)
                    if state == 'success':
                        last_success = qty
                        if last_silence is not None:
                            qty = int((last_success + last_silence) / 2)
                        else:
                            qty = int(qty * 2)
                    elif state == 'error':
                        return val
                    else:
                        last_silence = qty
                        qty = int((last_success + last_silence) / 2)
                elif state == 'success':
                    last_success = qty
                    logger.info(f"  👍 {qty} доступно. Шукаємо БІЛЬШЕ...")
                    if last_silence is not None:
                        qty = int((last_success + last_silence) / 2)
                    else:
                        qty = int(qty * 2)
                else:  # silence
                    last_silence = qty
                    logger.info(f"  👎 {qty} забагато. Шукаємо МЕНШЕ...")
                    qty = int((last_success + last_silence) / 2)
                
                # Перевірка збіжності
                if last_silence is not None and (last_silence - last_success) < 10:
                    logger.info(f"  📊 Збіжність: [{last_success}, {last_silence}]")
                    break
                
                # Оптимізація: якщо вже маємо більше 30к і це 5-та ітерація без ERROR
                if i >= 4 and last_success >= 30000 and state == 'success':
                    logger.info(f"  🚀 Достатньо великий залишок (>30к), завершуємо ітерації")
                    break

                # Після SUCCESS — очистити кошик, щоб наступна проба була з чистого аркуша
                if state == 'success':
                    try:
                        logger.info(f"  🛒 Очищення кошика після успіху (видаляємо {last_success} шт.)...")
                        driver.get("https://www.nkon.nl/ua/checkout/cart/")
                        time.sleep(1)
                        # Видаляємо всі товари з кошика
                        delete_btns = driver.find_elements(By.CSS_SELECTOR, ".action.action-delete")
                        for btn in delete_btns:
                            try:
                                btn.click()
                                time.sleep(0.5)
                            except:
                                pass
                        # Повертаємося на сторінку товару
                        driver.get(url)
                        time.sleep(1)
                        select_options()
                    except Exception as e:
                        logger.warning(f"  Не вдалося очистити кошик: {str(e).splitlines()[0]}")
                        try:
                            driver.get(url)
                            time.sleep(1)
                        except:
                            pass

            if last_success > 0:
                logger.info(f"  📊 Наближений залишок (без ERROR): {last_success}")
                return last_success
                
            return None
            
        except Exception as e:
            logger.error(f"Помилка при адаптивному отриманні залишку для {url}: {e}")
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
        capacity = extract_capacity(name)
        
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
            
        price_float = clean_price(price_raw)
        
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
        # Пошук кнопки Add to Cart (більш гнучкий селектор)
        add_to_cart = item.find('button', class_=lambda c: c and ('btn--cart' in c or 'btn-cart' in c))
        
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
        
        # Ініціалізуємо список тихо видалених з поточного стану класу
        quietly_removed = self.quietly_removed.copy()
        
        for link, product in current_state.items():
            # Перевірка наявності в попередньому стані
            prev_products = self.previous_state
            if link not in prev_products:
                # is_first_run is not defined here, assuming it's meant to be `True` if previous_state is empty
                is_first_run = not bool(prev_products)
                if not is_first_run:
                    real_stock = product.get('real_stock')
                    # Перевіряємо, чи був він раніше тихо видалений
                    was_quietly_removed = link in quietly_removed
                    
                    if real_stock is not None and real_stock <= settings.SMALL_RESTOCK_THRESHOLD:
                        product['small_stock_notified'] = True
                        if was_quietly_removed:
                            logger.info(f"🔕 Ігноруємо ПОВТОРНУ появу товару після зникнення (залишок {real_stock} <= {settings.SMALL_RESTOCK_THRESHOLD} шт): {product['name']}")
                        else:
                            logger.info(f"🔔 Новий товар з малим залишком ({real_stock} <= {settings.SMALL_RESTOCK_THRESHOLD} шт): {product['name']}")
                            new_items.append(product)
                    else:
                        new_items.append(product)
                        # Якщо товару багато, він виходить з тихого режиму
                        if was_quietly_removed:
                            logger.info(f"📈 Товар {product['name']} повернувся з ВЕЛИКИМ залишком ({real_stock}), скидаємо тихий режим.")
                            quietly_removed.pop(link, None)
            else:
                old_product = prev_products[link]
                
                # Перенесення прапорця
                if 'small_stock_notified' in old_product:
                    product['small_stock_notified'] = old_product['small_stock_notified']
                
                # Скидання прапорця, якщо залишок перевищив поріг
                real_stock = product.get('real_stock')
                if real_stock is not None and real_stock > settings.SMALL_RESTOCK_THRESHOLD:
                    product.pop('small_stock_notified', None)
                    # Також про всяк випадок прибираємо з тихого списку
                    quietly_removed.pop(link, None)
                
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
                    real_stock = product.get('real_stock')
                    # Якщо статус змінився на in_stock або preorder і кількість <= порогу, ігноруємо цю подію
                    is_restock = status_changed and product['stock_status'] in ['in_stock', 'preorder']
                    
                    should_notify = True
                    if is_restock and real_stock is not None and real_stock <= settings.SMALL_RESTOCK_THRESHOLD:
                        if product.get('small_stock_notified'):
                            should_notify = False
                            logger.info(f"🔕 Ігноруємо ПОВТОРНУ появу товару ({product['stock_status']}, залишок {real_stock} <= {settings.SMALL_RESTOCK_THRESHOLD} шт): {product['name']}")
                        else:
                            product['small_stock_notified'] = True
                            logger.info(f"🔔 ПЕРША поява товару з малим залишком ({product['stock_status']}, залишок {real_stock} <= {settings.SMALL_RESTOCK_THRESHOLD} шт): {product['name']}")
                            
                    if should_notify:
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
        prev_products = self.previous_state
        for link, product in prev_products.items():
            if link not in current_state:
                # Якщо товар мав ознаку малого залишку, відмічаємо його як тихо видалений
                if product.get('small_stock_notified'):
                    logger.info(f"🔕 Тихо видаляємо товар, що мав малим залишок: {product['name']}")
                    quietly_removed[link] = True
                else:
                    removed_items.append(product)
                    # Якщо зникла велика партія - забуваємо про тихий режим для цього посилання
                    quietly_removed.pop(link, None)
                    
        return {
            'new': new_items,
            'removed': removed_items,
            'price_changes': price_changes,
            'status_changes': status_changes,
            'current': current_products,
            'quietly_removed': quietly_removed
        }
    

    def run(self, dry_run: bool = False, force_notify: bool = False, no_db: bool = False, no_fetch: bool = False):
        """
        Основний цикл моніторингу
        
        Args:
            dry_run: Якщо True, не відправляти Telegram повідомлення
            force_notify: Примусова нотифікація зі звуком
            no_db: Якщо True, не записувати в БД
            no_fetch: Якщо True, використовувати останній стан замість парсингу
        """
        logger.info("=" * 60)
        logger.info(f"Запуск моніторингу NKON (Фаза 5: {len(settings.RECIPIENTS)} отримувачів)")
        if no_fetch:
            logger.info("🟢 Режим BEЗ ПАРСИНГУ: використання останнього стану зі state.json")
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
        products = []
        try:
            if not no_fetch:
                # Ініціалізація драйвера
                driver = self._init_driver()
                
                # Завантаження сторінок з пагінацією
                url = settings.NKON_URL
                
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
                            
                            # 2. Реальний залишок — адаптивний пошук для preorder та in_stock товарів.
                            if effective_fetch_stock and p['stock_status'] in ('preorder', 'in_stock'):
                                key = f"{p['link']}_{p.get('capacity', '0')}"
                                old_p = self.previous_state.get(key)
                                prev_stock = old_p.get('real_stock') if old_p else None
                                
                                stock = self._fetch_real_stock(p['link'], driver=driver, prev_stock=prev_stock)
                                if stock is not None:
                                    p['real_stock'] = stock
                                    if stock == 0:
                                        logger.warning(f"  ⚠️ {p.get('capacity')}Ah: 0 шт на складі, статус -> out_of_stock")
                                        p['stock_status'] = 'out_of_stock'
                                else:
                                    # Якщо не вдалося отримати новий, зберігаємо старий (якщо був)
                                    if old_p and old_p.get('real_stock') is not None:
                                        p['real_stock'] = old_p['real_stock']
            else:
                # Режим використання стану без парсингу
                test_state_file = 'test_new_state.json'
                if os.path.exists(test_state_file):
                    try:
                        with open(test_state_file, 'r', encoding='utf-8') as f:
                            test_state = json.load(f)
                            products = copy.deepcopy(list(test_state.get('products', {}).values()))
                        logger.info(f"🟢 Використовуємо ТЕСТОВИЙ стан з {test_state_file}: завантажено {len(products)} товарів")
                    except Exception as e:
                        logger.error(f"❌ Помилка читання {test_state_file}: {e}")
                        products = []
                elif self.previous_state:
                    logger.info(f"📂 test_new_state.json не знайдено. Використовуємо поточний стан (Без змін)")
                    products = copy.deepcopy(list(self.previous_state.values()))
                else:
                    logger.warning("⚠️ Попередній стан порожній, нічого обробляти у режимі --no-fetch")
                    products = []
            
            # Остаточна фільтрація: видаляємо виявлені out_of_stock
            products = [p for p in products if p['stock_status'] in ['in_stock', 'preorder']]
            
            if not products:
                logger.warning("Не знайдено товарів після фільтрації")
                # Навіть якщо товарів немає, ми маємо зберегти стан (пустий)
            
            # --- Per-Recipient Notification Loop ---
            new_last_messages = {}
            active_no_changes = {}
            
            # Спочатку створюємо загальний список товарів для збереження в state
            current_state = {HistoryDB.generate_key(p): p for p in products}

            # Визначаємо URL головного каналу (з першого реципієнта)
            main_channel_url = settings.RECIPIENTS[0].get('url') if settings.RECIPIENTS else None
            # Збір всіх посилань для футера (всі, крім першого - головного каналу)
            all_footer_links = [
                {'url': r['url'], 'name': r.get('name', 'Чат')}
                for r in settings.RECIPIENTS[1:] if r.get('url')
            ]

            logger.info(f"Початок розсилки для {len(settings.RECIPIENTS)} отримувачів...")
            
            for i, recipient in enumerate(settings.RECIPIENTS):
                chat_id = str(recipient['chat_id'])
                thread_id = recipient.get('thread_id')
                rpt_type = recipient.get('type', 'changes')
                
                # Logic: Smart Header
                header_link = main_channel_url if i > 0 else None
                
                # Footer Links: посилання тільки для головного каналу (i == 0)
                footer_links = all_footer_links if i == 0 else None
                
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
                    msg_full = self.telegram.format_telegram_message(rec_changes, include_unchanged=True, is_update=False, msg_key=msg_key, header_link=header_link, footer_links=footer_links, stock_cumulative_diffs=self.stock_cumulative_diffs)
                    if msg_full:
                        sent = self.telegram.send_telegram_message(msg_full, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run)
                        if chat_id in sent:
                            new_last_messages[msg_key] = sent[chat_id]
                
                # 2. Звіти про зміни
                elif rpt_type == 'changes':
                    msg_ch = self.telegram.format_telegram_message(rec_changes, include_unchanged=False, is_update=False, msg_key=msg_key, header_link=header_link, footer_links=footer_links, stock_cumulative_diffs=self.stock_cumulative_diffs)
                    should_notify, reason = self.telegram._should_notify(recipient, bool(msg_ch), self.last_notification_time)
                    if force_notify:
                        should_notify, reason = True, "force-notify"
                    
                    old_nc_msgs = self.last_messages.get('_no_changes', {})
                    last_nc_id = old_nc_msgs.get(msg_key)

                    if msg_ch:
                        # Зафіксувати дельти у старому повідомленні
                        if last_nc_id and not dry_run:
                            msg_upd = self.telegram.format_telegram_message(rec_changes, include_unchanged=True, is_update=True, show_stock_diffs=True, msg_key=msg_key, header_link=header_link, footer_links=footer_links, stock_cumulative_diffs=self.stock_cumulative_diffs)
                            self.telegram.edit_telegram_message(chat_id, last_nc_id, msg_upd)
                        
                        # Скидаємо лічильники ТІЛЬКИ ПІСЛЯ оновлення старого (як контрольна точка)
                        self.stock_cumulative_diffs[msg_key] = {}

                        # Нове повідомлення про зміни
                        logger.info(f"📣 Зміни для {msg_key}: надсилаємо звіт")
                        self.telegram.send_telegram_message(msg_ch, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run)
                        self.last_notification_time = datetime.now()
                        
                        if not dry_run: time.sleep(2)
                        
                        # Новий стан (тихо)
                        no_changes_only = {'new': [], 'removed': [], 'price_changes': [], 'status_changes': [], 'current': rec_changes['current']}
                        msg_ns = self.telegram.format_telegram_message(no_changes_only, include_unchanged=True, is_update=False, show_stock_diffs=False, unchanged_header="Новий стан", msg_key=msg_key, header_link=header_link, footer_links=footer_links, stock_cumulative_diffs=self.stock_cumulative_diffs)
                        sent_st = self.telegram.send_telegram_message(msg_ns, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run, disable_notification=True)
                        if chat_id in sent_st:
                            active_no_changes[msg_key] = sent_st[chat_id]
                    
                    elif reason == "heartbeat" or reason == "force-notify":
                        logger.info(f"🔔 Heartbeat/Force для {msg_key}")
                        if last_nc_id and not dry_run:
                            msg_upd = self.telegram.format_telegram_message(rec_changes, include_unchanged=True, is_update=True, show_stock_diffs=True, msg_key=msg_key, header_link=header_link, footer_links=footer_links, stock_cumulative_diffs=self.stock_cumulative_diffs)
                            self.telegram.edit_telegram_message(chat_id, last_nc_id, msg_upd)
                        
                        self.stock_cumulative_diffs[msg_key] = {}
                        if not dry_run: time.sleep(2)
                        
                        no_changes_only = {'new': [], 'removed': [], 'price_changes': [], 'status_changes': [], 'current': rec_changes['current']}
                        msg_hb = self.telegram.format_telegram_message(no_changes_only, include_unchanged=True, is_update=False, show_stock_diffs=False, unchanged_header="Новий стан", msg_key=msg_key, header_link=header_link, footer_links=footer_links, stock_cumulative_diffs=self.stock_cumulative_diffs)
                        sent_hb = self.telegram.send_telegram_message(msg_hb, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run, disable_notification=False)
                        self.last_notification_time = datetime.now()
                        if chat_id in sent_hb:
                            active_no_changes[msg_key] = sent_hb[chat_id]
                    
                    else:
                        # Без змін - тихо редагувати
                        msg_upd = self.telegram.format_telegram_message(rec_changes, include_unchanged=True, is_update=True, show_stock_diffs=True, msg_key=msg_key, header_link=header_link, footer_links=footer_links, stock_cumulative_diffs=self.stock_cumulative_diffs)
                        if not msg_upd:
                            if header_link:
                                msg_upd = f"[🔋 NKON Monitor]({header_link})\n\n📋 Без змін\n\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                            else:
                                msg_upd = f"🔋 *NKON Monitor*\n\n📋 Без змін\n\n🕒 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
                            
                            if footer_links:
                                links_list = [
                                    f"[{link.get('name', 'Чат')}]({link['url']})"
                                    for link in footer_links if link.get('url')
                                ]
                                if links_list:
                                    msg_upd += f"\n\n💬 Обговорення: " + " | ".join(links_list)
                        
                        success = False
                        if last_nc_id and not dry_run:
                            success = self.telegram.edit_telegram_message(chat_id, last_nc_id, msg_upd)
                            if success:
                                active_no_changes[msg_key] = last_nc_id
                        
                        if not success:
                            sent_nc = self.telegram.send_telegram_message(msg_upd, chat_ids={chat_id}, thread_id=thread_id, dry_run=dry_run, disable_notification=True)
                            if chat_id in sent_nc:
                                active_no_changes[msg_key] = sent_nc[chat_id]
            
            new_last_messages['_no_changes'] = active_no_changes
            
            # Оновлюємо глобальний стан тихо видалених з результатів останньої перевірки
            if 'rec_changes' in locals() and 'quietly_removed' in rec_changes:
                self.quietly_removed = rec_changes['quietly_removed']

            # State V2
            state_to_save = {
                'products': current_state,
                'last_messages': new_last_messages,
                'stock_cumulative_diffs': self.stock_cumulative_diffs,
                'last_notification_time': self.last_notification_time.isoformat(),
                'quietly_removed': self.quietly_removed,
                'version': 2
            }
            
            if not dry_run:
                self._save_state(state_to_save)
            else:
                logger.info("🚫 Dry Run: State НЕ оновлено")
            
            # Запис в БД після розсилки (Фаза 5+)
            if not no_db:
                self._save_history_to_db(products)
                
                # Генерація та завантаження графіків історії
                if HistoryVisualizer and settings.FTP_HOST and settings.VISUALIZATION_BASE_URL:
                    try:
                        logger.info("Генерація та вивантаження графіків історії...")
                        visualizer = HistoryVisualizer()
                        files = visualizer.generate_htmls()
                        if files:
                            visualizer.upload_to_sftp(files)
                    except Exception as e:
                        logger.error(f"Помилка при обробці графіків візуалізації: {e}")
            else:
                logger.info("🚫 No-DB Run: Запис до БД пропущено")
            
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
                        self.telegram.send_telegram_message(error_msg, chat_ids=admin_chats)
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
    parser.add_argument('--no-db', action='store_true',
                        help='Не записувати дані в базу даних історії (nkon_history.db)')
    parser.add_argument('--no-fetch', action='store_true',
                        help='Запуск без фактичного парсингу веб-сторінки (використовується останній стан зі state.json)')
    
    args = parser.parse_args()
    
    monitor = NkonMonitor()
    monitor.run(dry_run=args.dry_run, force_notify=args.force_notify, no_db=args.no_db, no_fetch=args.no_fetch)


if __name__ == '__main__':
    main()
