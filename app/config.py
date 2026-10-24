"""Runtime configuration, read from environment variables (see .env.example)."""
import os


def load_config(overrides=None):
    base_url = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
    cfg = {
        "SECRET_KEY": os.environ.get("SECRET_KEY", ""),
        "TOKEN_ENCRYPTION_KEY": os.environ.get("TOKEN_ENCRYPTION_KEY", ""),
        "DATABASE_URL": os.environ.get("DATABASE_URL", "sqlite:///jobmail.db"),
        "BASE_URL": base_url,
        "GOOGLE_CLIENT_ID": os.environ.get("GOOGLE_CLIENT_ID", ""),
        "GOOGLE_CLIENT_SECRET": os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        # Only this Google account may sign in (JobMail is a personal app).
        "ALLOWED_EMAIL": os.environ.get("ALLOWED_EMAIL", "").strip().lower(),
        # optional: enables AI categorisation, job-fit scoring and reply drafting
        "ANTHROPIC_API_KEY": os.environ.get("ANTHROPIC_API_KEY", "").strip(),
        "AI_MODEL": os.environ.get("AI_MODEL", "claude-haiku-5-5"),
        "AI_COMPOSE_MODEL": os.environ.get("AI_COMPOSE_MODEL", "claude-sonnet-5-5"),
        "AI_BATCH": int(os.environ.get("AI_BATCH", "20")),
        "SYNC_DAYS": int(os.environ.get("SYNC_DAYS", "90")),
        "SYNC_BATCH": int(os.environ.get("SYNC_BATCH", "100")),
        "SESSION_COOKIE_SECURE": base_url.startswith("https://"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "PERMANENT_SESSION_LIFETIME": 60 * 60 * 24 * 30,
        "MAX_CONTENT_LENGTH": 3 * 1024 * 1024,
    }
    if overrides:
        cfg.update(overrides)
    return cfg
