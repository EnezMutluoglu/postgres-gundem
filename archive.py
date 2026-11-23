"""Monthly gzip snapshot of the live SQLite bulletin. Run via the archive service."""

import gzip
import os
import re
import shutil
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def archive(data, month):
    output = data / "arsiv"
    output.mkdir(mode=0o700, exist_ok=True)
    final = output / f"gundem-{month}.sqlite.gz"
    partial = final.with_suffix(".gz.partial")
    # systemd serializes service starts and removes its private /var/tmp after a crash.
    with tempfile.TemporaryDirectory() as work:
        snapshot = Path(work) / "snapshot.sqlite"
        uri = (data / "gundem.sqlite").resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(uri, uri=True)) as live,
            closing(sqlite3.connect(snapshot)) as copy,
        ):
            live.backup(copy, pages=128)
            if not copy.execute("SELECT 1 FROM items LIMIT 1").fetchone():
                return
            if copy.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("SQLite arşivi doğrulanamadı")
        try:
            with snapshot.open("rb") as source, partial.open("wb") as raw:
                with gzip.GzipFile(
                    filename="", fileobj=raw, mode="wb", mtime=0
                ) as compressed:
                    shutil.copyfileobj(source, compressed)
                raw.flush()
                os.fsync(raw.fileno())
            os.replace(partial, final)
        finally:
            partial.unlink(missing_ok=True)
    completed = sorted(
        p
        for p in output.iterdir()
        if re.fullmatch(r"gundem-\d{4}-(?:0[1-9]|1[0-2])\.sqlite\.gz", p.name)
    )
    for old in completed[:-3]:
        old.unlink()


if __name__ == "__main__":
    archive(
        Path("/var/lib/postgres-gundem"), datetime.now(timezone.utc).strftime("%Y-%m")
    )
