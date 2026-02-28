import sqlite3
from datetime import datetime

def format_timestamp(ts):
    try:
        dt = datetime.fromisoformat(ts.replace(' ', 'T'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return ts

def read_last_records(db_path="nkon_history.db"):
    print(f"--- Аналіз бази даних: {db_path} ---")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 1. Останні 10 продуктів
        print("\n[Продукти] Останні 10 зареєстрованих:")
        cursor.execute("SELECT id, product_key, name, capacity_ah FROM products ORDER BY id DESC LIMIT 10")
        products = cursor.fetchall()
        print(f"{'ID':<4} | {'Ємність':<7} | {'Назва'}")
        print("-" * 50)
        for p in products:
            print(f"{p[0]:<4} | {p[3]:<7} | {p[2][:60]}")

        # 2. Останні 10 записів історії залишків
        print("\n[Історія залишків] Останні 10 змін:")
        query = """
            SELECT sh.timestamp, p.name, sh.in_stock_qty, sh.preorder_qty, sh.status
            FROM stock_history sh
            JOIN products p ON sh.product_id = p.id
            ORDER BY sh.timestamp DESC LIMIT 10
        """
        cursor.execute(query)
        stocks = cursor.fetchall()
        print(f"{'Час':<20} | {'В наявності':<12} | {'Pre-order':<10} | {'Статус':<10} | {'Товар'}")
        print("-" * 100)
        for s in stocks:
            print(f"{s[0]:<20} | {s[2]:<12} | {s[3]:<10} | {s[4]:<10} | {s[1][:40]}")

        # 3. Останні 10 записів історії цін
        print("\n[Історія цін] Останні 10 змін:")
        query = """
            SELECT ph.timestamp, p.name, ph.price 
            FROM price_history ph
            JOIN products p ON ph.product_id = p.id
            ORDER BY ph.timestamp DESC LIMIT 10
        """
        cursor.execute(query)
        prices = cursor.fetchall()
        print(f"{'Час':<20} | {'Ціна':<8} | {'Товар'}")
        print("-" * 60)
        for pr in prices:
            print(f"{pr[0]:<20} | €{pr[2]:<7.2f} | {pr[1][:40]}")

        conn.close()
    except sqlite3.OperationalError as e:
        print(f"Помилка: База даних ще не створена або таблиці відсутні. ({e})")
    except Exception as e:
        print(f"Виникла помилка: {e}")

if __name__ == "__main__":
    read_last_records()
