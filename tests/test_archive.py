import gzip
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from archive import archive


class ArchiveTests(unittest.TestCase):
    def test_live_wal_restore_permanent_retention_and_failed_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            output = data / "arsiv"
            with closing(sqlite3.connect(data / "gundem.sqlite")) as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.execute("CREATE TABLE items(id INTEGER)")
                archive(data, "2026-01")
                self.assertFalse(list(output.glob("*.gz")))
                for month in range(1, 5):
                    db.execute("INSERT INTO items VALUES (?)", (month,))
                    db.commit()
                    archive(data, f"2026-{month:02d}")
                files = sorted(output.glob("*.gz"))
                self.assertEqual(
                    [p.name for p in files],
                    [f"gundem-2026-{month}.sqlite.gz" for month in ("01", "02", "03", "04")],
                )
                restored = data / "restored.sqlite"
                restored.write_bytes(gzip.decompress(files[-1].read_bytes()))
                with closing(sqlite3.connect(restored)) as copy:
                    self.assertEqual(
                        copy.execute("PRAGMA integrity_check").fetchall(), [("ok",)]
                    )
                    self.assertEqual(
                        copy.execute("SELECT id FROM items ORDER BY id").fetchall(),
                        [(1,), (2,), (3,), (4,)],
                    )
                previous = files[-1].read_bytes()
                with (
                    patch(
                        "archive.shutil.copyfileobj", side_effect=OSError("disk full")
                    ),
                    self.assertRaises(OSError),
                ):
                    archive(data, "2026-05")
                self.assertEqual(files[-1].read_bytes(), previous)
                self.assertEqual(sorted(output.iterdir()), files)
