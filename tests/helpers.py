def sync_all(c):
    out = {"remaining": 1}
    while out["remaining"]:
        r = c.post("/api/sync", json={})
        assert r.status_code == 200, r.get_json()
        out = r.get_json()
    return out
