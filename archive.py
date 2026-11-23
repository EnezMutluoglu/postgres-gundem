"""Monthly gzip snapshot of the live SQLite bulletin. Run via the archive service."""

import gzip
import os
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
    if final.exists() or (output / f".tasindi-{month}").exists():
        return
    with tempfile.TemporaryDirectory(dir=output, prefix=".snapshot-") as work:
        snapshot = Path(work) / "snapshot.sqlite"
        partial = Path(work) / "snapshot.gz"
        uri = (data / "gundem.sqlite").resolve().as_uri() + "?mode=ro"
        with (
            closing(sqlite3.connect(uri, uri=True)) as live,
            closing(sqlite3.connect(snapshot)) as copy,
        ):
            live.backup(copy, pages=128)
            has_press = copy.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='press_articles'"
            ).fetchone()
            if not copy.execute("SELECT 1 FROM items LIMIT 1").fetchone() and not (
                has_press
                and copy.execute("SELECT 1 FROM press_articles LIMIT 1").fetchone()
            ):
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
            try:
                os.link(partial, final)
            except FileExistsError:
                return
            if os.name == "posix":
                directory = os.open(output, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            partial.unlink(missing_ok=True)


if __name__ == "__main__":
    archive(
        Path("/var/lib/postgres-gundem"), datetime.now(timezone.utc).strftime("%Y-%m")
    )
