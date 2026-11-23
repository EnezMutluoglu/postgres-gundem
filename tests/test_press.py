import gzip
import importlib.util
from pathlib import Path
import sqlite3
import os
import tempfile
import unittest
from unittest.mock import patch
from contextlib import closing

import app
import community as press
from archive import archive

spec = importlib.util.spec_from_file_location(
    "transfer", Path(__file__).resolve().parents[1] / "deploy/container/arsiv-tasi.py"
)
mover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mover)


class PressTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        p = patch.object(app, "DATA", self.base)
        p.start()
        self.addCleanup(p.stop)
        app.initialize()

    def put(self, body, ts=10):
        raw = f"""<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>PostgreSQL 19 est sorti</title><link href="https://blog.dalibo.com/p?utm_source=rss"/><published>2026-11-19T08:00:00Z</published><summary>{body}</summary></entry></feed>""".encode()
        with app.db() as c:
            press.parse_feed(
                c,
                raw,
                "fr",
                "Dalibo",
                "blog.dalibo.com",
                "https://blog.dalibo.com/feed.xml",
                ts,
            )

    def test_append_only_history_pagination_translation_and_backup(self):
        self.put("Premier texte.")
        self.put("Premier texte.")
        self.put("Deuxième texte.", 20)
        self.assertTrue(
            press.translate_one(
                app.db,
                lambda t, language: "Yeni başlık" if "PostgreSQL" in t else "Yeni özet",
            )
        )
        client = app.app.test_client()
        data = client.get("/api/dis-basin?dil=fr").json
        self.assertEqual(
            (data["total"], data["items"][0]["versions"], data["items"][0]["title_tr"]),
            (1, 2, "Yeni başlık"),
        )
        old = client.get("/api/dis-basin/1/gecmis").json
        self.assertEqual(old[0]["excerpt"], "Premier texte.")
        self.assertEqual(client.get("/api/dis-basin?kaynak=yok").json["total"], 0)
        with app.db() as c:
            press.parse_feed(
                c,
                b"<rss><channel/></rss>",
                "fr",
                "Dalibo",
                "blog.dalibo.com",
                "feed",
                30,
            )
        archive(self.base, "2026-11")
        restored = self.base / "restored.sqlite"
        restored.write_bytes(
            gzip.decompress((self.base / "arsiv/gundem-2026-11.sqlite.gz").read_bytes())
        )
        with closing(sqlite3.connect(restored)) as c:
            self.assertEqual(
                c.execute("select count(*) from press_revisions").fetchone()[0], 2
            )
        with app.db() as c:
            self.assertEqual(
                c.execute("select url from press_articles").fetchone()[0],
                "https://blog.dalibo.com/p",
            )

    def test_discovery_requires_independent_provenance_and_keeps_unknown_candidates(
        self,
    ):
        raw = b'<rss><channel><item><title>Postgres 19 - Foo</title><link>https://news.google.com/rss/articles/123</link><source url="https://foo.example">Foo</source></item></channel></rss>'
        with app.db() as c:
            press.parse_feed(c, raw, "en", "", "", press.SEARCH, 5, True)
            self.assertEqual(
                c.execute("select count(*) from press_articles").fetchone()[0], 0
            )
            press.directory(
                c,
                press.INTL,
                b'<div id="pgContentWrap"><table><tr><td><a href="https://foo.example">Foo</a></td></tr></table></div>',
                6,
            )
            press.parse_feed(c, raw, "en", "", "", press.SEARCH, 7, True)
            self.assertEqual(
                c.execute("select count(*) from press_articles").fetchone()[0], 1
            )
        with self.assertRaises(ValueError):
            press.network_url("https://foo.example/rss")

    def test_weekly_restart_and_failure_retry(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if url == "b" and calls.count(url) == 1:
                raise OSError("offline")
            return b"ok"

        tasks = [(u, u, lambda c, b, t: None) for u in ("a", "b")]
        with patch.object(press, "jobs", return_value=tasks):
            for t in (5, 10, 3606, press.WEEK + 6):
                press.scan(app.db, fetch, lambda: t)
        self.assertEqual(calls, ["a", "b", "b", "a"])

    def test_official_revisions_are_archived(self):
        app.save("notes", [{"id": "n", "kind": "dev", "title": "First"}])
        app.save("notes", [{"id": "n", "kind": "dev", "title": "Next"}])
        app.initialize()
        with app.db() as c:
            self.assertEqual(
                c.execute("select count(*) from item_history").fetchone()[0], 2
            )

    def test_multilingual_version_check(self):
        with patch.object(
            app, "model_text", return_value="PostgreSQL 17.2 yayımlandı."
        ):
            with self.assertRaises(ValueError):
                app.press_translation("PostgreSQL 17.1 est disponible.", "fr")
        self.assertEqual(
            app.press_translation("Bakım sürümü yayımlandı.", "tr"),
            "Bakım sürümü yayımlandı.",
        )

    @unittest.skipUnless(os.name == "posix", "Linux disk aracı")
    def test_archive_transfer_respects_existing_copy(self):
        self.put("Premier texte.")
        archive(self.base, "2026-11")
        target = self.base / "hedef"
        target.mkdir()
        source = self.base / "arsiv"
        mover.transfer(source, target)
        name = "gundem-2026-11.sqlite.gz"
        self.assertEqual(mover.digest(source / name), mover.digest(target / name))
        (target / name).write_bytes(b"incorrect")
        with self.assertRaises(ValueError):
            mover.transfer(source, target)
        self.assertTrue((source / name).exists())
        other = Path("/dev/shm")
        if other.is_dir() and other.stat().st_dev != source.stat().st_dev:
            with tempfile.TemporaryDirectory(dir=other) as disk:
                mover.transfer(source, Path(disk), move=True)
                self.assertFalse((source / name).exists())
                self.assertTrue((Path(disk) / name).exists())
                archive(self.base, "2026-11")
                self.assertFalse((source / name).exists())
