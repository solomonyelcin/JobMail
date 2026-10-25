"""SmartMail: personal Gmail job-application tracker."""
import logging

from flask import Flask, jsonify, send_from_directory
from werkzeug.middleware.proxy_fix import ProxyFix

from .api import bp
from . import api_extra  # noqa: F401  (registers more routes on the same blueprint)
from . import api_ws  # noqa: F401
from .config import load_config
from .crypto import TokenCipher
from .db import Database
from .sync import ensure_classifier_current
from . import gmail as gmail_mod


def default_gmail_factory(cfg, refresh_token):
    token = gmail_mod.refresh_access_token(cfg("GOOGLE_CLIENT_ID"), cfg("GOOGLE_CLIENT_SECRET"), refresh_token)
    return gmail_mod.GmailClient(token)


def create_app(overrides=None):
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config.update(load_config(overrides))
    if not app.config["SECRET_KEY"]:
        raise RuntimeError("SECRET_KEY is not set (see .env.example)")
    logging.basicConfig(level=logging.INFO)

    # Render / most hosts terminate TLS in front of the app
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db = Database(app.config["DATABASE_URL"])
    db.init_schema()
    ensure_classifier_current(db)
    app.extensions["jobmail_db"] = db
    app.extensions["jobmail_cipher"] = TokenCipher(app.config["TOKEN_ENCRYPTION_KEY"])
    app.extensions["gmail_factory"] = default_gmail_factory
    app.register_blueprint(bp)

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/healthz")
    def healthz():
        conn = db.connect()
        try:
            conn.execute("SELECT 1")
        finally:
            conn.close()
        return jsonify(status="ok")

    @app.after_request
    def security_headers(resp):
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        )
        if app.config["SESSION_COOKIE_SECURE"]:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if resp.mimetype == "application/json":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    return app
