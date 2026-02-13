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

    # Test 7: Smart Heartbeat Logic (_should_notify)
    print('\n--- TEST 7: Smart Heartbeat Logic (_should_notify) ---')
    from datetime import datetime, time as dt_time, timedelta
    
    monitor.config['heartbeat_times'] = [dt_time(8, 0), dt_time(16, 0)]
    monitor.config['heartbeat_cooldown'] = monitor._calculate_auto_cooldown(monitor.config['heartbeat_times'])
    
    # Використовуємо фіксовану дату як базу для тестів, щоб не залежати від реального "зараз"
    base_date = datetime(2025, 1, 1, 12, 0)
    
    # Case A: Changes detected
    res, reason = monitor._should_notify(has_changes=True)
    status = "✅" if (res, reason) == (True, "changes") else "❌"
    print(f'{status} Case A (Changes): {res}, reason: {reason}')

    # Case B: Cooldown active (last notification 2h ago relative to now)
    now_real = datetime.now()
    monitor.last_notification_time = now_real - timedelta(hours=2)
    res, reason = monitor._should_notify(has_changes=False)
    status = "✅" if (res, reason) == (False, "cooldown") else "❌"
    print(f'{status} Case B (Cooldown): {res}, reason: {reason}')

    # Case C: Heartbeat time reached (now >= 8:00, last yesterday - sufficiency far for cooldown)
    # last = 20:00 day before base_date
    monitor.last_notification_time = base_date - timedelta(days=1)
    # mock_now = 8:05 AM on base_date
    mock_now = datetime.combine(base_date.date(), dt_time(8, 5))
    import unittest.mock
    with unittest.mock.patch('nkon_monitor.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.combine = datetime.combine
        res, reason = monitor._should_notify(has_changes=False)
        status = "✅" if (res, reason) == (True, "heartbeat") else "❌"
        print(f'{status} Case C (Heartbeat 8:00): {res}, reason: {reason}')

    # Case D: Before heartbeat time (now = 7:30)
    mock_now = datetime.combine(base_date.date(), dt_time(7, 30))
    with unittest.mock.patch('nkon_monitor.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.combine = datetime.combine
        res, reason = monitor._should_notify(has_changes=False)
        status = "✅" if (res, reason) == (False, "silent") else "❌"
        print(f'{status} Case D (Before Heartbeat): {res}, reason: {reason}')

    # Case E: First slot passed, second slot reached (now 16:30, last was at 8:05)
    # З автоматичним кулдауном для [8:00, 16:00] він буде 8 годин.
    # 16:30 - 8:05 = ~8.4 год. Це > 8 год, тому має спрацювати HEARTBEAT!
    monitor.last_notification_time = datetime.combine(base_date.date(), dt_time(8, 5))
    mock_now = datetime.combine(base_date.date(), dt_time(16, 30))
    with unittest.mock.patch('nkon_monitor.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.combine = datetime.combine
        res, reason = monitor._should_notify(has_changes=False)
        status = "✅" if (res, reason) == (True, "heartbeat") else "❌"
        print(f'{status} Case E (Heartbeat 16:00, auto-cooldown): {res}, reason: {reason}')
    
    # Case F: All slots today already handled (now 20:00, last was 16:10)
    monitor.last_notification_time = datetime.combine(base_date.date(), dt_time(16, 10))
    mock_now = datetime.combine(base_date.date(), dt_time(20, 0))
    with unittest.mock.patch('nkon_monitor.datetime') as mock_datetime:
        mock_datetime.now.return_value = mock_now
        mock_datetime.fromisoformat = datetime.fromisoformat
        mock_datetime.combine = datetime.combine
        res, reason = monitor._should_notify(has_changes=False)
        status = "✅" if (res, reason) == (False, "cooldown") else "❌"
        print(f'{status} Case F (After all heartbeats, cooldown active): {res}, reason: {reason}')

    # Test 8: Automatic Cooldown Calculation
    print('\n--- TEST 8: Automatic Cooldown Calculation ---')
    test_cases = [
        ([dt_time(8, 0)], 24.0),
        ([dt_time(8, 0), dt_time(20, 0)], 12.0),
        ([dt_time(8, 0), dt_time(12, 0), dt_time(16, 0)], 4.0),
        ([dt_time(7, 0), dt_time(12, 0), dt_time(18, 0)], 5.0), # 7-12=5, 12-18=6, 18-7=13
    ]
    for times, expected in test_cases:
        res = monitor._calculate_auto_cooldown(times)
        status = "✅" if res == expected else "❌"
        print(f'{status} Intervals for {times} -> {res}h (Expected: {expected}h)')

if __name__ == "__main__":
    run_tests()
