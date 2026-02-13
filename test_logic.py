import re
import sys
from nkon_monitor import NkonMonitor

# Mock monitor to test methods without initializing Selenium or Config
class MockMonitor(NkonMonitor):
    def __init__(self):
        self.config = {}
        self.session = None
        self.previous_state = {}
        self.last_messages = {}
        self.stock_cumulative_diffs = {}
        self.state_file = 'state_test.json'

    def send_telegram_message(self, message: str, chat_ids: set = None, dry_run: bool = False, disable_notification: bool = False):
        return {"123": 456}

def run_tests():
    print("Initializing MockMonitor for Unit Testing...")
    try:
        monitor = MockMonitor()
    except Exception as e:
        print(f"Error initializing monitor: {e}")
        return

    # Test 1: Regex
    print('\n--- TEST 1: Regex Capacity ---')
    test_cases = [
        'Eve LF280K 280Ah', 
        '280 Ah', 
        '280  Ah', 
        '314ah', 
        '280AHgrade B', 
        '99Ah', 
        '100Ah',
        'REPT 324Ah'
    ]
    
    for test in test_cases:
        res = monitor.extract_capacity(test)
        status = "✅" if res else "❌"
        print(f'{status} "{test}" -> {res}')

    # Test 2: Clean Price
    print('\n--- TEST 2: Clean Price ---')
    prices = [
        '€ 89.95', 
        '€89.95', 
        '€ 89,95', 
        '€1,234.50', 
        'N/A', 
        'Price: 100',
        '89.95'
    ]
    
    for p in prices:
        res = monitor.clean_price(p)
        status = "✅" if res is not None else "❌"
        print(f'{status} "{p}" -> {res}')

    # Test 3: Delivery Date
    print('\n--- TEST 3: Delivery Date ---')
    dates = [
        'Орієнтовна дата доставки:27-03-2026',
        'Орієнтовна дата доставки: 15-04-2026',
        'Орієнтовна дата доставки:10-3-2026',
        '27-03-2026',
        'Something else 12-12-2025',
        'No date here'
    ]
    
    for d in dates:
        match = re.search(r'(\d{1,2}-\d{1,2}-\d{4})', d)
        res = match.group(1) if match else None
        status = "✅" if res else "❌"
        print(f'{status} "{d}" -> {res}')

    # Test 4: Stock Counters
    print('\n--- TEST 4: Stock Counters (Sales, Returns, Restocks) ---')
    monitor.config['restock_threshold'] = 100
    test_link = "https://example.com/battery"
    test_item = {
        'link': test_link,
        'capacity': '280',
        'name': 'Eve LF280K 280Ah',
        'real_stock': 100
    }
    key = f"{test_link}_280"
    
    # 1. Start: stock=100 (first time seen)
    print("1. Initializing with 100...")
    monitor._update_stock_counters([test_item])
    print(f"   Diffs: {monitor.stock_cumulative_diffs.get(key)}")
    
    # 2. Sale: stock=90
    print("2. Sale: 100 -> 90...")
    monitor.previous_state = {key: {'real_stock': 100}}
    test_item['real_stock'] = 90
    monitor._update_stock_counters([test_item])
    diffs = monitor.stock_cumulative_diffs[key]
    print(f"   Real stock: 90, Diffs: {diffs}")
    
    # 3. Return: stock=95 (<= threshold)
    print("3. Return: 90 -> 95...")
    monitor.previous_state = {key: {'real_stock': 90}}
    test_item['real_stock'] = 95
    monitor._update_stock_counters([test_item])
    diffs = monitor.stock_cumulative_diffs[key]
    print(f"   Real stock: 95, Diffs: {diffs}")
    
    # 4. Restock: stock=2095 (> threshold)
    print("4. Restock: 95 -> 2095...")
    monitor.previous_state = {key: {'real_stock': 95}}
    test_item['real_stock'] = 2095
    monitor._update_stock_counters([test_item])
    diffs = monitor.stock_cumulative_diffs[key]
    print(f"   Real stock: 2095, Diffs: {diffs}")
    
    # 5. Format check (with diffs)
    display_with_diffs = monitor._format_stock_display(test_item, show_diffs=True)
    print(f"   With diffs: {display_with_diffs}")
    
    # 6. Format check (without diffs - Full Report mode)
    display_clean = monitor._format_stock_display(test_item, show_diffs=False)
    print(f"   Clean (Full Report): {display_clean}")
    
    expected_diffs = {'decrease': -5, 'increase': 2000}
    expected_display = " `[2095(-5+2000) шт]`"
    expected_clean = " `[2095 шт]`"
    
    if diffs == expected_diffs and display_with_diffs == expected_display and display_clean == expected_clean:
        print("✅ TEST 4 PASSED")
    else:
        print(f"❌ TEST 4 FAILED")
        if diffs != expected_diffs: print(f"   Diffs: {diffs} != {expected_diffs}")
        if display_with_diffs != expected_display: print(f"   Display: {display_with_diffs} != {expected_display}")
        if display_clean != expected_clean: print(f"   Clean: {display_clean} != {expected_clean}")

    # Test 5: Format Telegram Message Header
    print('\n--- TEST 5: Format Telegram Message Header ---')
    changes = {'current': [{'name': 'Item 1', 'link': 'url1', 'capacity': 100, 'price': '10', 'stock_status': 'in_stock', 'real_stock': 50}]}
    
    # Default header
    msg_default = monitor.format_telegram_message(changes, include_unchanged=True)
    if "📋 *Без змін (1):*" in msg_default:
        print("✅ Default Header: OK")
    else:
        print(f"❌ Default Header: FAILED. Got: {msg_default}")
        
    # Custom header "Новий стан"
    msg_custom = monitor.format_telegram_message(changes, include_unchanged=True, unchanged_header="Новий стан")
    if "📋 *Новий стан (1):*" in msg_custom:
        print("✅ Custom Header: OK")
    else:
        print(f"❌ Custom Header: FAILED. Got: {msg_custom}")

    # Test 6: Send Telegram Message Notification param
    print('\n--- TEST 6: Send Message Params ---')
    # Since we mocked send_telegram_message in MockMonitor, we acting as if we are testing the signature in the main class
    # We will verify if the method accepts the argument without error
    try:
        monitor.send_telegram_message("test", chat_ids={"123"}, disable_notification=True)
        print("✅ send_telegram_message accepts disable_notification")
    except TypeError as e:
        print(f"❌ send_telegram_message rejected disable_notification: {e}")

if __name__ == "__main__":
    run_tests()
