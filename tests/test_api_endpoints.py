def test_get_prices_endpoint(api):
    res = api.get("/api/prices?tokens=3045,2885")
    assert res.status_code == 200
    body = res.json()
    assert "data" in body
    assert "3045" in body["data"]
    assert "2885" in body["data"]

def test_strategies_api(api):
    # GET
    res = api.get("/api/strategies")
    assert res.status_code == 200
    assert "Breakout" in res.json()["data"]

    # POST (Add)
    res_add = api.post("/api/strategies", json={"name": "Gap Fill"})
    assert res_add.status_code == 200
    assert res_add.json()["success"] is True

    # Duplicate Add -> 400
    res_dup = api.post("/api/strategies", json={"name": "Gap Fill"})
    assert res_dup.status_code == 400

    # DELETE
    res_del = api.delete("/api/strategies/Gap Fill")
    assert res_del.status_code == 200
    assert res_del.json()["success"] is True

def test_emotions_api(api):
    # GET
    res = api.get("/api/emotions")
    assert res.status_code == 200
    assert "Disciplined" in res.json()["data"]

    # POST (Add)
    res_add = api.post("/api/emotions", json={"name": "FOMO"})
    assert res_add.status_code == 200

    # DELETE
    res_del = api.delete("/api/emotions/FOMO")
    assert res_del.status_code == 200

def test_trades_api_crud(api):
    trade_payload = {
        "symbol": "RELIANCE",
        "side": "BUY",
        "price": 2800.0,
        "shares": 15,
        "strategy": "Breakout",
        "emotion": "Confident",
        "notes": "Testing trade creation"
    }
    res_create = api.post("/api/trades", json=trade_payload)
    assert res_create.status_code == 200
    created = res_create.json()["data"]
    trade_id = created["id"]
    assert created["symbol"] == "RELIANCE"

    res_get_all = api.get("/api/trades")
    assert res_get_all.status_code == 200
    trades_list = res_get_all.json()["data"]
    assert any(t["id"] == trade_id for t in trades_list)

    res_single = api.get(f"/api/trades/{trade_id}")
    assert res_single.status_code == 200
    assert res_single.json()["data"]["price"] == 2800.0

    res_update = api.put(f"/api/trades/{trade_id}", json={"price": 2850.0})
    assert res_update.status_code == 200
    assert res_update.json()["data"]["price"] == 2850.0

    res_delete = api.delete(f"/api/trades/{trade_id}")
    assert res_delete.status_code == 200
    assert api.get(f"/api/trades/{trade_id}").status_code == 404

def test_journal_overview_starts_empty(api):
    res = api.get("/api/journal")
    assert res.status_code == 200
    data = res.json()["data"]

    # No preloaded stocks: a brand-new account opens an empty journal.
    assert data["trades"] == []
    # The tag library is still usable on day one.
    assert "Breakout" in data["strategies"]
    assert "Disciplined" in data["emotions"]

    # The demo reset route is gone: nothing serves it any more (404, or 405
    # when the router matches the prefix but not the method).
    assert api.post("/api/journal/reset").status_code in (404, 405)


def test_trade_instrument_key_is_validated_and_kept(api):
    payload = {
        "symbol": "sbin",
        "instrumentKey": " nse_eq|ine002a01018 ",
        "side": "BUY",
        "price": 650.0,
        "shares": 5,
    }
    created = api.post("/api/trades", json=payload)
    assert created.status_code == 200
    assert created.json()["data"]["instrumentKey"] == "NSE_EQ|INE002A01018"

    # Without a key the trade is still valid, just not linked to a live price.
    plain = api.post("/api/trades", json={**payload, "instrumentKey": ""})
    assert plain.status_code == 200
    assert plain.json()["data"]["instrumentKey"] is None

    # A bare symbol is not an instrument key.
    assert api.post("/api/trades", json={**payload, "instrumentKey": "SBIN"}).status_code == 422


def test_prices_endpoint_reports_freshness_metadata(api):
    res = api.get("/api/prices?tokens=UNSEENKEY")
    body = res.json()

    assert body["data"]["UNSEENKEY"] == 100.0
    assert body["meta"]["UNSEENKEY"] == {"as_of": None, "stale": True}
    assert isinstance(body["timestamp"], int)


def test_update_trade_clears_optional_fields(api):
    created = api.post("/api/trades", json={
        "symbol": "WIPRO",
        "side": "BUY",
        "price": 450.0,
        "shares": 10,
        "stopLoss": 440.0,
    }).json()["data"]

    res = api.put(f"/api/trades/{created['id']}", json={"stopLoss": None})

    assert res.status_code == 200
    assert res.json()["data"]["stopLoss"] is None


def test_legacy_journal_compat_routes_removed(api):
    assert api.post("/api/journal?action=reset").status_code == 405
    assert api.put("/api/journal?id=trade_1").status_code == 405
    assert api.delete("/api/journal?id=trade_1").status_code == 405
