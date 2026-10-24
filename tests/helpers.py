STATE = {"unread": set(), "drafts": [], "ai": None}


def sync_all(c, **body):
    out = {"remaining": 1}
    first = True
    while out["remaining"]:
        r = c.post("/api/sync", json=body if first else {})
        first = False
        assert r.status_code == 200, r.get_json()
        out = r.get_json()
    return out
