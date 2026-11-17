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

def test_journal_overview_and_reset(api):
    res = api.get("/api/journal")
    assert res.status_code == 200
    assert "trades" in res.json()["data"]
    assert "strategies" in res.json()["data"]
    assert "emotions" in res.json()["data"]

    res_reset = api.post("/api/journal/reset")
    assert res_reset.status_code == 200
    assert res_reset.json()["success"] is True


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
