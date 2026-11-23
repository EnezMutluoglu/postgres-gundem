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
RECHECK = 7 * 24 * 3600
LOCAL = threading.local()
# The official and press workers may request exactly the same text concurrently.
TEXT_LOCKS = tuple(threading.Lock() for _ in range(32))
SCHEMA = """
CREATE TABLE IF NOT EXISTS translation_tasks(
 kind TEXT,ref TEXT,part INTEGER,attempts INTEGER NOT NULL,status TEXT NOT NULL,due INTEGER NOT NULL,detail TEXT NOT NULL,checked_at INTEGER,
 PRIMARY KEY(kind,ref,part));
CREATE TABLE IF NOT EXISTS translation_memory(
 language TEXT NOT NULL, original TEXT NOT NULL, translation TEXT NOT NULL, saved_at INTEGER,
 PRIMARY KEY(language,original)) WITHOUT ROWID;
"""


def setup(con):
    con.executescript(SCHEMA)
    if "checked_at" not in {
        row[1] for row in con.execute("PRAGMA table_info(translation_tasks)")
    }:
        con.execute("ALTER TABLE translation_tasks ADD COLUMN checked_at INTEGER")
    con.execute(
        "UPDATE translation_tasks SET status='failed',due=0 WHERE status='original'"
    )
    # One application process owns this SQLite database. An interrupted inference can be retried.
    con.execute(
        """UPDATE translation_tasks SET status=CASE WHEN attempts-1>=? THEN 'failed' ELSE 'retry' END, attempts=max(attempts-1,0),
        due=0,detail='Önceki çeviri kesildi.' WHERE status='working'""",
        (LIMIT,),
    )


def source_language(lang):
    return (lang or "und").lower().split("-")[0]


def import_existing(con, editorial):
    marker = "translation_memory_imported"
    if con.execute("SELECT 1 FROM state WHERE key=?", (marker,)).fetchone():
        return False
    # Imported rows have no known translation date. Keep their original article associations.
    con.create_function("source_language", 1, source_language)
    con.create_function("strip_source", 1, str.strip)
    insert = "INSERT OR IGNORE INTO translation_memory(language,original,translation) "
    con.executemany(insert + "VALUES('en',?,?)", editorial.items())
    con.execute(
        insert + "SELECT 'en',original,translation FROM texts WHERE translation<>''"
    )
    for field in ("title", "excerpt"):
        con.execute(
            insert
            + f"SELECT source_language(lang),{field},{field}_tr FROM press_revisions WHERE {field}_tr<>'' AND source_language(lang)<>'tr' ORDER BY id DESC"
        )
    con.execute(
        insert
        + """SELECT source_language(r.lang),strip_source(substr(r.original,p.pos+1,p.length)),p.translation
        FROM press_parts p JOIN press_revisions r ON r.id=p.revision WHERE p.translation<>'' ORDER BY p.revision DESC"""
    )
    con.execute("INSERT INTO state VALUES(?, 'true')", (marker,))
    return True


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


def run(
    db, kind, ref, part, source, language, produce, commit, *, health=None, seconds=3600
):
    memory_key = (source_language(language), source)
    key = (kind, str(ref), part)
    with TEXT_LOCKS[hash(memory_key) % len(TEXT_LOCKS)]:
        return translate_field(db, key, memory_key, produce, commit, health, seconds)


def translate_field(db, key, memory_key, produce, commit, health, seconds):
    now = int(time.time())
    with db() as con:
        con.execute("BEGIN IMMEDIATE")
        cached = con.execute(
            "SELECT translation FROM translation_memory WHERE language=? AND original=?",
            memory_key,
        ).fetchone()
        if cached:
            commit(con, cached[0])
            con.execute(
                "DELETE FROM translation_tasks WHERE kind=? AND ref=? AND part=?", key
            )
            return "done"
        prev = con.execute(
            "SELECT attempts,due FROM translation_tasks WHERE kind=? AND ref=? AND part=?",
            key,
        ).fetchone()
        if prev and prev[1] > now:
            return "skip"
        attempt = 1 + (prev[0] if prev else 0)
        con.execute(
            """INSERT INTO translation_tasks(kind,ref,part,attempts,status,due,detail,checked_at) VALUES(?,?,?,?,'working',?,'',?)
            ON CONFLICT(kind,ref,part) DO UPDATE SET attempts=excluded.attempts,status='working',due=excluded.due,checked_at=excluded.checked_at""",
            (*key, attempt, now + seconds + 10, now),
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
            if attempt >= LIMIT:
                status = "failed"
        else:
            status = "failed" if attempt >= LIMIT else "retry"
            delay = RECHECK if status == "failed" else RETRY_DELAYS[attempt - 1]
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
        logging.info("Çeviri %s (%s, deneme %s): %s", status, key[0], attempt, reason)
        return "offline" if offline else status
    with db() as con:
        if result:
            con.execute(
                "INSERT INTO translation_memory(language,original,translation,saved_at) VALUES(?,?,?,?)",
                (*memory_key, result, int(time.time())),
            )
        commit(con, result)
        con.execute(
            "DELETE FROM translation_tasks WHERE kind=? AND ref=? AND part=?", key
        )
    return "done"
