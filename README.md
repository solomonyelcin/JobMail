# JobMail

A personal web app that reads your Gmail (read-only), keeps **only job-related emails**, classifies them, and tracks each application from "applied" to "offer" or "rejected". Works on laptop and phone.

## Features

- **Gmail sign-in** with Google OAuth. Only the one account in `ALLOWED_EMAIL` can log in.
- **Automatic sync**: runs when you open the app, when you return to the tab, and every 5 minutes while it is open. After the first full sync, later syncs only look back to just before the previous one, and messages are fetched in parallel, so they are quick. A manual **Sync** button is still there.
- **Classification**: `applied`, `assessment`, `interview`, `offer`, `rejected`, `opening` (rule based, see `app/classify.py`). Newsletters and course promotions that merely mention interviews are filtered out. When the rules change, stored emails are re-classified automatically on the next start.
- **Application tracking**: company and role are extracted automatically; status follows the latest email. Manual status edits are never overwritten by later syncs.
- **Kanban board** with drag and drop, plus a list view, a detail drawer with notes and an email timeline, and a "needs follow-up" nudge for applications quiet for 14+ days.
- **Search and filters**: highlighted free-text search, category chips, application status, date range, sorting.
- **Insights**: pipeline funnel, response rate, weekly email activity.
- **Tools**: CSV export, "Not job-related" to remove a wrongly captured email, dark mode, keyboard shortcut `/` to search, works on phones.
- **Security**: refresh token encrypted at rest (Fernet), signed session cookies, HTTPS-only cookies in production, strict CSP, CSRF header on all writes, no CORS (frontend and API share one origin).

## Architecture

| Part | Technology | Production host |
|------|-----------|-----------------|
| Backend + API | Python 3.12, Flask, gunicorn | Render (Docker, free plan) |
| Frontend | Plain HTML/CSS/JS served by the backend | same service |
| Database | PostgreSQL (SQLite for local dev/tests) | Neon (free) |
| CI/CD | GitHub Actions | GitHub |

The frontend is served by the same service as the API, so there is one HTTPS URL, no CORS configuration, and nothing separate to keep in sync. GitHub Pages is intentionally not used because it can only host static files and would add cross-origin cookie problems for no benefit.

```
app/            Flask application (api.py, sync.py, classify.py, gmail.py, db.py, crypto.py)
app/static/     Frontend (index.html, app.js, style.css)
tests/          Automated tests
docs/DEPLOYMENT.md   Step-by-step deployment guide
.github/workflows/ci.yml   Test, build, deploy pipeline
Dockerfile, render.yaml    Container and Render blueprint
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env        # then fill in the values (see below)
set -a; source .env; set +a
flask --app wsgi run --port 8000
```

Open http://localhost:8000. For Google sign-in locally, add `http://localhost:8000/auth/callback` as an authorized redirect URI (see the deployment guide, section 5).

Run the tests: `python -m pytest -q`. To test against PostgreSQL, set `TEST_DATABASE_URL=postgresql://user:pass@localhost/dbname`.

## Deploying

Follow [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Privacy

JobMail requests the `gmail.readonly` scope. It cannot send, delete or modify mail. Only emails matching job-related rules are saved (subject, sender, snippet, first 4,000 characters of text). Message ids of non-job emails are remembered so they are not re-fetched.

## Known limitations

- Classification and company/role extraction are heuristics; use the edit button to correct them.
- On Render's free plan the service sleeps after ~15 minutes idle, so the first request takes up to a minute.
- Single-user by design.
