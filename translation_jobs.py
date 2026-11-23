"""Persist per-field translation attempts. A failed input never blocks the next one."""

import time
from urllib.error import HTTPError
from urllib.request import urlopen
import json
import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

RETRY_DELAYS = (120, 900)
LIMIT = len(RETRY_DELAYS) + 1
LOCAL = threading.local()
SCHEMA = """
CREATE TABLE IF NOT EXISTS translation_tasks(
 kind TEXT,ref TEXT,part INTEGER,attempts INTEGER NOT NULL,status TEXT NOT NULL,due INTEGER NOT NULL,detail TEXT NOT NULL,
 PRIMARY KEY(kind,ref,part));
"""


def setup(con):
    con.executescript(SCHEMA)
    # One application process owns this SQLite database. An interrupted inference can be retried.
    con.execute("""UPDATE translation_tasks SET status='retry', attempts=max(attempts-1,0),
        due=0,detail='Önceki çeviri kesildi.' WHERE status='working'""")


def available(url):
    try:
        with urlopen(url + "/health", timeout=3) as r:
            return json.load(r).get("status") == "ok"
    except (OSError, ValueError):
        return False


@contextmanager
def deadline(seconds):
    LOCAL.until = time.monotonic() + seconds
    try:
        yield
    finally:
        del LOCAL.until


def timeout(default):
    remaining = getattr(LOCAL, "until", float("inf")) - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Çeviri süresi doldu")
    return min(default, remaining)


def run(db, kind, ref, part, produce, commit, *, health=None, seconds=3600):
    key = (kind, str(ref), part)
    now = int(time.time())
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        prev = con.execute(
            "SELECT attempts,status,due FROM translation_tasks WHERE kind=? AND ref=? AND part=?",
            key,
        ).fetchone()
        if prev and (prev[1] == "original" or prev[2] > now):
            return "skip"
        attempt = 1 + (prev[0] if prev else 0)
        con.execute(
            "INSERT OR REPLACE INTO translation_tasks VALUES(?,?,?,?,?,?,?)",
            (*key, attempt, "working", now + seconds + 10, ""),
        )
    try:
        with deadline(seconds):
            result = produce(attempt)
    except Exception as exc:
        transport = isinstance(exc, OSError) and not (
            isinstance(exc, HTTPError) and 400 <= exc.code < 500 and exc.code != 429
        )
        offline = transport and health is not None and not health()
        if offline:
            status, delay, reason = "offline", 60, "Yerel model yanıt vermedi."
            attempt -= 1
        else:
            status = "original" if attempt >= LIMIT else "retry"
            delay = 0 if status == "original" else RETRY_DELAYS[attempt - 1]
            reason = (
                str(exc)[:160]
                if isinstance(exc, ValueError)
                else "Yerel çeviri isteği tamamlanamadı."
            )
        with db() as con:
            con.execute(
                "UPDATE translation_tasks SET attempts=?,status=?,due=?,detail=? WHERE kind=? AND ref=? AND part=?",
                (attempt, status, int(time.time()) + delay, reason, *key),
            )
            con.execute(
                "INSERT OR REPLACE INTO state VALUES('translation_error',?)",
                (
                    json.dumps(
                        {
                            "time": datetime.now(timezone.utc).isoformat(
                                timespec="seconds"
                            ),
                            "message": reason,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        logging.info("Çeviri %s (%s, deneme %s): %s", status, kind, attempt, reason)
        return status
    with db() as con:
        commit(con, result)
        con.execute(
            "DELETE FROM translation_tasks WHERE kind=? AND ref=? AND part=?", key
        )
    return "done"
