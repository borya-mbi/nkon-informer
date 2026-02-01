import re
import sys
from nkon_monitor import NkonMonitor

# Mock monitor to test methods without initializing Selenium or Config
class MockMonitor(NkonMonitor):
    def __init__(self):
        self.config = {}

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

if __name__ == "__main__":
    run_tests()
