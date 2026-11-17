from app.streaming.price_cache import price_cache
from app.streaming.upstox_streamer import UpstoxMarketStreamer


def test_extract_ltp_from_ltpc():
    assert UpstoxMarketStreamer._extract_ltp({"ltpc": {"ltp": 650.5}}) == 650.5


def test_extract_ltp_from_full_feed_market():
    feed = {"fullFeed": {"marketFF": {"ltpc": {"ltp": 3510.25}}}}
    assert UpstoxMarketStreamer._extract_ltp(feed) == 3510.25


def test_extract_ltp_from_full_feed_index():
    feed = {"fullFeed": {"indexFF": {"ltpc": {"ltp": 22150.75}}}}
    assert UpstoxMarketStreamer._extract_ltp(feed) == 22150.75


def test_extract_ltp_from_first_level_with_greeks():
    feed = {"firstLevelWithGreeks": {"ltpc": {"ltp": 1500.0}}}
    assert UpstoxMarketStreamer._extract_ltp(feed) == 1500.0


def test_extract_ltp_returns_none_when_absent():
    assert UpstoxMarketStreamer._extract_ltp({}) is None
    assert UpstoxMarketStreamer._extract_ltp({"ltpc": {}}) is None
    assert UpstoxMarketStreamer._extract_ltp({"ltpc": {"ltp": None}}) is None


def test_live_feed_message_updates_price_cache():
    streamer = UpstoxMarketStreamer("dummy-token")
    token = "NSE_EQ|TEST_FEED_TICK"

    streamer.on_message_received(
        {"type": "live_feed", "feeds": {token: {"ltpc": {"ltp": 651.2}}}}
    )

    assert price_cache.get_price(token) == 651.2


def test_market_info_message_is_ignored():
    streamer = UpstoxMarketStreamer("dummy-token")
    token = "NSE_EQ|TEST_MARKET_INFO"

    streamer.on_message_received({"type": "market_info", "marketInfo": {token: {}}})
    streamer.on_message_received({"type": "live_feed", "feeds": "not-a-dict"})

    assert price_cache.get_price(token) == 100.0


def test_authenticate_requires_token():
    assert UpstoxMarketStreamer("token").authenticate() is True
    assert UpstoxMarketStreamer("").authenticate() is False
