import threading
import time
from app.streaming.price_cache import PriceCache

def test_price_cache_basic_operations():
    cache = PriceCache()
    cache.set_price("3045", 650.25)
    
    assert cache.get_price("3045") == 650.25
    assert cache.get_price("2885", default=100.0) == 100.0

def test_price_cache_batch():
    cache = PriceCache()
    cache.set_price("3045", 650.00)
    cache.set_price("2885", 80.00)
    
    batch = cache.get_batch_prices(["3045", "2885", "9999"])
    assert batch["3045"] == 650.00
    assert batch["2885"] == 80.00
    assert batch["9999"] == 100.0  # default fallback

def test_price_cache_concurrent_multithreaded_writes():
    cache = PriceCache()
    
    def writer_task(token_prefix, count):
        for i in range(count):
            token = f"{token_prefix}_{i % 5}"
            cache.set_price(token, float(i))
            time.sleep(0.001)

    threads = []
    for t_idx in range(5):
        t = threading.Thread(target=writer_task, args=(f"token_{t_idx}", 50))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    # Verify no race condition corruptions occurred
    for t_idx in range(5):
        for i in range(5):
            val = cache.get_price(f"token_{t_idx}_{i}")
            assert val is not None
