import sqlite3
import logging
from datetime import datetime
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class HistoryDB:
    def __init__(self, db_path: str = "nkon_history.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path)
        # Увімкнення підтримки зовнішніх ключів
        self.conn.execute("PRAGMA foreign_keys = ON")
        self._init_db()

    def _init_db(self):
        """Ініціалізація таблиць БД, якщо вони не існують"""
        cursor = self.conn.cursor()
        
        # Таблиця продуктів
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_key TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                name TEXT NOT NULL,
                capacity_ah INTEGER
            )
        ''')
        
        # Таблиця історії залишків
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                in_stock_qty INTEGER,
                preorder_qty INTEGER,
                status TEXT,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        
        # Таблиця історії цін
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                timestamp DATETIME NOT NULL,
                price REAL NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products (id)
            )
        ''')
        self.conn.commit()
        logger.info(f"База даних {self.db_path} ініціалізована та готова до роботи.")

    @staticmethod
    def generate_key(product: Dict) -> str:
        """Уніфікована генерація ключа продукту"""
        return f"{product['link']}_{product.get('capacity', 0)}"

    def close(self):
        """Закриття з'єднання з БД"""
        if self.conn:
            self.conn.close()
            logger.info("З'єднання з базою даних закрите.")

    def sync_products(self, current_products: List[Dict]):
        """Синхронізація списку товарів з таблицею products"""
        cursor = self.conn.cursor()
        for product in current_products:
            product_key = self.generate_key(product)
            cursor.execute('''
                INSERT INTO products (product_key, url, name, capacity_ah)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(product_key) DO UPDATE SET
                    url = excluded.url,
                    name = excluded.name,
                    capacity_ah = excluded.capacity_ah
            ''', (
                product_key,
                product['link'],
                product['name'],
                product.get('capacity', 0)
            ))
        self.conn.commit()

    def get_product_id(self, product_key: str) -> Optional[int]:
        """Отримання внутрішнього id за ключем продукту"""
        cursor = self.conn.cursor()
        cursor.execute('SELECT id FROM products WHERE product_key = ?', (product_key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def record_changes_bulk(self, products: List[Dict]):
        """Масовий запис змін залишків та цін.
        Отримує всі останні стани одним запитом і порівнює в пам'яті.
        """
        if not products:
            return

        cursor = self.conn.cursor()
        
        # 1. Отримуємо id для всіх переданих ключів
        keys = [self.generate_key(p) for p in products]
        placeholders = ','.join('?' * len(keys))
        cursor.execute(f'SELECT product_key, id FROM products WHERE product_key IN ({placeholders})', keys)
        key_to_id = {row[0]: row[1] for row in cursor.fetchall()}

        # Збираємо всі ідентифікатори товарів
        product_ids = list(key_to_id.values())
        if not product_ids:
            return

        id_placeholders = ','.join('?' * len(product_ids))

        # 2. Отримуємо останні залишки для всіх товарів (використовуючи групування для швидкості)
        # Субзапит потрібен для знаходження максимального часу для кожного товару
        cursor.execute(f'''
            SELECT sh.product_id, sh.in_stock_qty, sh.preorder_qty, sh.status
            FROM stock_history sh
            INNER JOIN (
                SELECT product_id, MAX(timestamp) as max_ts
                FROM stock_history
                WHERE product_id IN ({id_placeholders})
                GROUP BY product_id
            ) max_sh ON sh.product_id = max_sh.product_id AND sh.timestamp = max_sh.max_ts
        ''', product_ids)
        last_stocks = {row[0]: (row[1], row[2], row[3]) for row in cursor.fetchall()}

        # 3. Отримуємо останні ціни для всіх товарів
        cursor.execute(f'''
            SELECT ph.product_id, ph.price
            FROM price_history ph
            INNER JOIN (
                SELECT product_id, MAX(timestamp) as max_ts
                FROM price_history
                WHERE product_id IN ({id_placeholders})
                GROUP BY product_id
            ) max_ph ON ph.product_id = max_ph.product_id AND ph.timestamp = max_ph.max_ts
        ''', product_ids)
        last_prices = {row[0]: row[1] for row in cursor.fetchall()}

        # 4. Формуємо списки для масового запису
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        new_stocks = []
        new_prices = []

        for p in products:
            key = self.generate_key(p)
            pid = key_to_id.get(key)
            if not pid:
                continue

            # Обробка залишків
            real_qty = p.get('real_stock', 0)
            in_stock = real_qty if p['stock_status'] == 'in_stock' else 0
            preorder = real_qty if p['stock_status'] == 'preorder' else 0
            status = p['stock_status']

            last_s = last_stocks.get(pid)
            if not last_s or last_s[0] != in_stock or last_s[1] != preorder or last_s[2] != status:
                new_stocks.append((pid, in_stock, preorder, status, now))

            # Обробка ціни
            price = p.get('price_value')
            if price is not None:
                last_p = last_prices.get(pid)
                if last_p is None or abs(last_p - price) > 0.001:
                    new_prices.append((pid, price, now))

        # 5. Масовий запис до БД
        if new_stocks:
            cursor.executemany('''
                INSERT INTO stock_history (product_id, in_stock_qty, preorder_qty, status, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', new_stocks)
            
        if new_prices:
            cursor.executemany('''
                INSERT INTO price_history (product_id, price, timestamp)
                VALUES (?, ?, ?)
            ''', new_prices)

        if new_stocks or new_prices:
            self.conn.commit()
            logger.info(f"Оновлено історію: {len(new_stocks)} залишків, {len(new_prices)} цін.")
