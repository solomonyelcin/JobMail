from app.sync import reclassify_all, ensure_classifier_current
from helpers import sync_all


def test_application_detail_sort_and_csv(auth_client):
    sync_all(auth_client)
    items = auth_client.get("/api/applications?sort=company").get_json()["items"]
    assert [a["company"] for a in items] == ["Acme", "Globex"]
    by_status = auth_client.get("/api/applications?sort=status").get_json()["items"]
    assert by_status[0]["status"] == "interview"  # interview ranks above rejected

    detail = auth_client.get(f"/api/applications/{items[0]['id']}").get_json()
    assert detail["company"] == "Acme" and len(detail["emails"]) == 2
    assert auth_client.get("/api/applications/9999").status_code == 404

    csv_resp = auth_client.get("/api/export.csv")
    assert csv_resp.mimetype == "text/csv"
    text = csv_resp.get_data(as_text=True)
    assert text.splitlines()[0].startswith("Company,Role,Status")
    assert "Acme" in text and "Globex" in text


def test_csv_neutralises_formulas(auth_client):
    auth_client.post("/api/applications", json={"company": "=HYPERLINK(\"x\")", "role": "Dev"})
    assert "'=HYPERLINK" in auth_client.get("/api/export.csv").get_data(as_text=True)


def test_delete_email_is_not_reimported(auth_client):
    sync_all(auth_client)
    emails = auth_client.get("/api/emails").get_json()["items"]
    assert auth_client.delete(f"/api/emails/{emails[0]['id']}").status_code == 200
    assert auth_client.get("/api/emails").get_json()["total"] == 3
    sync_all(auth_client)
    assert auth_client.get("/api/emails").get_json()["total"] == 3


def test_stats_include_weekly_and_stale(auth_client):
    sync_all(auth_client)
    s = auth_client.get("/api/stats").get_json()
    assert len(s["weekly"]) == 8
    assert s["stale"] >= 1  # sample emails are old, so open applications count as stale


def test_reclassify_fixes_old_rows_and_keeps_manual_changes(app, auth_client):
    sync_all(auth_client)
    acme = next(a for a in auth_client.get("/api/applications").get_json()["items"] if a["company"] == "Acme")
    auth_client.patch(f"/api/applications/{acme['id']}", json={"status": "offer"})
    auth_client.post("/api/applications", json={"company": "Manual Co", "role": "Dev"})

    db = app.extensions["jobmail_db"]
    c = db.connect()  # simulate an old, wrong classification
    c.execute("UPDATE emails SET category='interview', company='Zach at Acme'")
    c.commit(); c.close()

    reclassify_all(db)
    emails = auth_client.get("/api/emails").get_json()["items"]
    assert {e["company"] for e in emails if e["category"] != "opening"} == {"Acme", "Globex"}
    apps = {a["company"]: a for a in auth_client.get("/api/applications").get_json()["items"]}
    assert apps["Acme"]["status"] == "offer"          # manual status survived
    assert "Manual Co" in apps                         # manual application survived
    assert apps["Globex"]["status"] == "rejected"


def test_ensure_classifier_current_runs_once(app):
    db = app.extensions["jobmail_db"]
    ensure_classifier_current(db)
    c = db.connect()
    assert c.one("SELECT value FROM meta WHERE key='classifier_version'")["value"]
    c.close()
