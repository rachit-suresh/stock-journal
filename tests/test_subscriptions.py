from app.streaming.subscriptions import SubscriptionRegistry, diff_subscriptions


def test_diff_reports_both_directions():
    added, removed = diff_subscriptions(
        ["NSE_EQ|A", "NSE_EQ|B"],
        ["NSE_EQ|B", "NSE_EQ|C"],
    )

    assert added == ["NSE_EQ|C"]
    assert removed == ["NSE_EQ|A"]


def test_diff_is_empty_when_unchanged():
    assert diff_subscriptions(["A", "B"], ["B", "A"]) == ([], [])


def test_registry_merges_defaults_and_every_user():
    registry = SubscriptionRegistry(["NSE_EQ|DEFAULT"], ttl_seconds=3600)
    registry.set_user_keys("u1", ["NSE_EQ|ONE"])
    registry.set_user_keys("u2", ["NSE_EQ|TWO", "NSE_EQ|ONE"])

    assert registry.snapshot() == ["NSE_EQ|DEFAULT", "NSE_EQ|ONE", "NSE_EQ|TWO"]


def test_registry_drops_users_after_the_ttl():
    registry = SubscriptionRegistry([], ttl_seconds=0.01)
    registry.set_user_keys("stale", ["NSE_EQ|OLD"])

    assert registry.snapshot() == ["NSE_EQ|OLD"]

    import time
    time.sleep(0.02)
    assert registry.snapshot() == []


def test_registry_drop_user_removes_its_keys():
    registry = SubscriptionRegistry([])
    registry.set_user_keys("u1", ["NSE_EQ|ONE"])

    registry.drop_user("u1")

    assert registry.snapshot() == []
