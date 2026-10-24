# Deploying JobMail

Result: JobMail at a public HTTPS URL (for example `https://jobmail.onrender.com`) that works from your laptop and phone, with code in your private GitHub repo `JobMail` and automatic deploys on every push to `main` once tests pass.

Total cost: free (Render free web service + Neon free Postgres). Time: about 30 minutes.

> Throughout this guide, `<your-url>` means your Render URL, e.g. `https://jobmail.onrender.com`. Render shows the real one after you create the service (step 4). You can create the service first, then come back to Google (step 5).

---

## 1. Create the GitHub repository

1. Go to https://github.com/new
2. Owner: your personal account. Repository name: `JobMail`. Visibility: **Private**.
3. Do **not** add a README, .gitignore or license (the project already has them).
4. Click **Create repository**.

## 2. Push the project

In the project folder (already a git repo with branch `main`):

```bash
git remote add origin https://github.com/<your-github-username>/JobMail.git
git push -u origin main
```

If prompted for a password, use a Personal Access Token (GitHub > Settings > Developer settings > Tokens, scope `repo`) or sign in through GitHub CLI (`gh auth login`).

Check that `.env` is not in the repository (only `.env.example` should be).

## 3. Create the database (Neon, free PostgreSQL)

1. Sign up at https://neon.tech (GitHub login works).
2. Create a project named `jobmail`, choose a region near you.
3. Copy the **connection string** (it looks like `postgresql://user:password@ep-xxxx.neon.tech/neondb?sslmode=require`). Keep it secret. This is your `DATABASE_URL`.

JobMail creates its tables automatically on first start.

## 4. Create the backend (Render)

1. Sign up at https://render.com with GitHub.
2. **New > Blueprint**, pick your `JobMail` repo (grant Render access to it). Render reads `render.yaml` and proposes a web service called `jobmail` on the free plan.
3. Fill in the prompted environment variables:

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | Neon connection string from step 3 |
| `BASE_URL` | `<your-url>` with no trailing slash. If you do not know it yet, use `https://jobmail.onrender.com`; if Render gives a different name, change this later (step 8) |
| `ALLOWED_EMAIL` | your Gmail address |
| `TOKEN_ENCRYPTION_KEY` | any random string of 24+ characters (e.g. from a password manager), or a Fernet key from `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | from step 5 (enter placeholders now, update after) |
| `SECRET_KEY` | generated automatically |

4. Create the service. The first build takes a few minutes. When live, open `<your-url>/healthz`; it should show `{"status":"ok"}`.

> **Keep `TOKEN_ENCRYPTION_KEY` safe.** If you lose or change it, the stored Gmail token cannot be read and you just sign in again.

## 5. Configure Gmail OAuth (Google Cloud)

1. Go to https://console.cloud.google.com, create a project named `JobMail`.
2. **APIs & Services > Library**: search **Gmail API** and click **Enable**.
3. **APIs & Services > OAuth consent screen** (or "Google Auth platform"):
   - User type: **External**. App name `JobMail`. Support and developer email: yours.
   - **Data access / Scopes**: add `.../auth/gmail.readonly` (plus `openid` and `email`).
   - **Test users**: add your Gmail address.
4. **Publish the app** (set publishing status to **In production**).
   - Important: while the status is **Testing**, Google expires the refresh token after **7 days**, and you would have to sign in weekly.
   - Because `gmail.readonly` is a restricted scope and you are not going through Google's verification, sign-in shows "Google hasn't verified this app". For your own account click **Advanced > Go to JobMail (unsafe)**. This is expected for a personal app. Unverified apps are limited to 100 users, which is irrelevant here.
5. **Credentials > Create credentials > OAuth client ID**:
   - Application type: **Web application**, name `JobMail web`.
   - **Authorized redirect URIs** (exact match, no trailing slash):
     - `<your-url>/auth/callback`
     - `http://localhost:8000/auth/callback` (only if you want to run locally)
   - Authorized JavaScript origins are not needed.
6. Copy the **Client ID** and **Client secret**.
7. In Render > your service > **Environment**, set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET`, then save (the service restarts).

Google's policies and screen names change from time to time; if a menu differs, the settings above are what matter.

## 6. GitHub Actions (CI/CD)

The pipeline in `.github/workflows/ci.yml` runs automatically on every push and pull request:

1. **Tests** against SQLite and a real PostgreSQL service container.
2. **Docker image build** check.
3. On pushes to `main` only, if both pass: **deploy** to Render, then poll `/healthz` until the new version is healthy (the job fails if it never becomes healthy).

Any failure shows as a red cross on the commit and the Actions tab, and nothing is deployed.

To enable the deploy step, add these in GitHub (repo > **Settings > Secrets and variables > Actions**):

| Type | Name | Value |
|------|------|-------|
| Secret | `RENDER_DEPLOY_HOOK_URL` | Render service > **Settings > Deploy Hook** URL |
| Variable | `APP_URL` | `<your-url>` (no trailing slash) |

Without the secret the deploy job just prints a warning and skips. Render's own auto-deploy is turned off in `render.yaml` so that only tested commits are deployed.

## 7. Deploy

Push a commit to `main` (or re-run the workflow from the Actions tab). Watch **Actions > CI/CD** go green, then open `<your-url>`.

## 8. Use it

1. Open `<your-url>` on your laptop or phone (on a phone, "Add to Home Screen" for an app-like icon).
2. **Sign in with Google**, accept the unverified-app warning once, grant read-only Gmail access.
3. Tap **Sync Gmail**. The first sync can take a minute or two; it fetches in batches and shows progress.
4. Browse **Applications** and **Emails**, search, filter, and edit statuses.

The first request after idle takes up to ~1 minute on Render's free plan while the service wakes up.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Google error `redirect_uri_mismatch` | The redirect URI in Google must equal `BASE_URL` + `/auth/callback` exactly (https, no trailing slash). |
| "That Google account is not allowed" | `ALLOWED_EMAIL` must match the Google account you sign in with. |
| "Google did not return offline access" | Remove JobMail at https://myaccount.google.com/permissions and sign in again. |
| Asked to sign in again every week | Publishing status is still **Testing**; set it to **In production** (step 5.4). |
| `/healthz` returns 500 | Check `DATABASE_URL` and that Neon is reachable; see Render logs. |
| Deploy job skipped | `RENDER_DEPLOY_HOOK_URL` secret is not set (step 6). |
| Login loop on phone | `BASE_URL` must be the exact `https://` URL you open, not `http://`. |

## Rotating secrets

- Google client secret: create a new secret in Google Console, update `GOOGLE_CLIENT_SECRET` in Render.
- Session key: change `SECRET_KEY` in Render (signs you out).
- Never commit `.env`; `.gitignore` excludes it.
