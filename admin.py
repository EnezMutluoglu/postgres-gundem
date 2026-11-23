"""Local administrator session and fixed commands for the isolated release worker."""

import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
from collections import deque
from datetime import timedelta
from pathlib import Path
from urllib.request import urlopen

from flask import abort, jsonify, request, session
from werkzeug.security import check_password_hash


def register(web, data, model, database, pending_count):
    version_file = Path(__file__).with_name("VERSION")
    version = version_file.read_text().strip() if version_file.exists() else "legacy"
    control = Path(os.getenv("GUNDEM_CONTROL", "/control"))
    config = Path(os.getenv("GUNDEM_ADMIN", "/config/admin.json"))
    enabled = config.is_file()
    password = ""
    if enabled:
        auth = json.loads(config.read_text())
        web.secret_key = auth["secret"]
        password = auth["password"]
    web.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_REFRESH_EACH_REQUEST=False,
        PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        MAX_CONTENT_LENGTH=16384,
    )
    attempts = deque()
    lock = threading.Lock()

    @web.get("/health/live")
    def live():
        return jsonify(status="ok", version=version)

    @web.get("/health/ready")
    def ready():
        try:
            with database() as con:
                con.execute("SELECT id FROM items LIMIT 1").fetchall()
            return jsonify(status="ok", version=version)
        except Exception:
            return jsonify(status="unavailable", version=version), 503

    @web.get("/ayarlar")
    def settings():
        return web.send_static_file("settings.html")

    @web.get("/api/admin/session")
    def who():
        if not enabled:
            return jsonify(error="Konteyner yönetimi kurulmamış."), 503
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return jsonify(authenticated=bool(session.get("admin")), csrf=session["csrf"])

    def verify(admin=True):
        if not enabled:
            abort(503)
        if admin and not session.get("admin"):
            abort(401)
        if request.method == "POST" and (
            not request.is_json
            or not session.get("csrf")
            or not hmac.compare_digest(
                request.headers.get("X-CSRF-Token", "").encode(),
                session["csrf"].encode(),
            )
        ):
            abort(403)

    @web.post("/api/admin/login")
    def login():
        verify(False)
        supplied = (
            request.json.get("password") if isinstance(request.json, dict) else None
        )
        if not isinstance(supplied, str) or len(supplied) > 512:
            abort(400)
        with lock:
            now = time.monotonic()
            while attempts and attempts[0] <= now - 60:
                attempts.popleft()
            if len(attempts) >= 8:
                abort(429)
            attempts.append(now)
        if not check_password_hash(password, supplied):
            abort(401)
        session.clear()
        session.update(admin=True, csrf=secrets.token_urlsafe(32))
        session.permanent = True
        return jsonify(csrf=session["csrf"])

    @web.post("/api/admin/logout")
    def logout():
        verify()
        session.clear()
        return jsonify(ok=True)

    def release_status():
        try:
            return json.loads((control / "status/status.json").read_text())
        except (OSError, ValueError):
            return dict(message="Sürüm bilgisi için Şimdi denetle’ye basın.")

    @web.get("/api/admin/status")
    def status():
        verify()
        try:
            with urlopen(model + "/health", timeout=2) as r:
                model_ok = json.load(r).get("status") == "ok"
        except (OSError, ValueError):
            model_ok = False
        database_ok = True
        try:
            with database() as con:
                last = con.execute("SELECT MAX(success) FROM sources").fetchone()[0]
                err = con.execute(
                    "SELECT value FROM state WHERE key='translation_error'"
                ).fetchone()
                queue = pending_count(con)
                memory_entries = con.execute(
                    "SELECT count(*) FROM translation_memory"
                ).fetchone()[0]
                fallback, next_retry = con.execute(
                    "SELECT count(*),min(due) FROM translation_tasks WHERE status='failed'"
                ).fetchone()
        except (OSError, sqlite3.Error, ValueError):
            database_ok = False
            last = err = queue = fallback = next_retry = memory_entries = None
        archives = sorted((data / "arsiv").glob("gundem-????-??.sqlite.gz"))
        return jsonify(
            version=version,
            model=model_ok,
            database=database_ok,
            last_scan=last,
            pending=queue,
            original_only=fallback,
            next_retry=next_retry,
            memory_entries=memory_entries,
            translation_error=json.loads(err[0]) if err else None,
            archive=archives[-1].name if archives else None,
            free=shutil.disk_usage(data).free,
            release=release_status(),
        )

    @web.post("/api/admin/retry-translations")
    def retry_translations():
        verify()
        with database() as con:
            count = con.execute(
                "UPDATE translation_tasks SET due=0 WHERE status='failed' AND due<>0"
            ).rowcount
        return jsonify(requeued=count)

    @web.post("/api/admin/<command>")
    def update(command):
        verify()
        if command not in ("check", "apply"):
            abort(404)
        name = command
        if command == "apply":
            tag = (
                request.json.get("version") if isinstance(request.json, dict) else None
            )
            if (
                not isinstance(tag, str)
                or not re.fullmatch(r"v\d+\.\d+\.\d+", tag)
                or tag != release_status().get("available")
            ):
                abort(409)
            name += "-" + tag
        try:
            (control / "requests" / name).mkdir(exist_ok=True)
        except OSError:
            return jsonify(error="Güncelleme hizmetine ulaşılamadı."), 503
        return jsonify(ok=True), 202
