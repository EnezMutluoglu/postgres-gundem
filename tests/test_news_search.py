from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from bs4 import BeautifulSoup
import app
import community
import news_search


class ArchiveSearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = patch.object(app, "DATA", Path(self.tmp.name))
        data.start()
        self.addCleanup(data.stop)
        app.initialize()
        self.client = app.app.test_client()

    def flush(self):
        while news_search.batch(app.db, app.EDITORIAL):
            pass

    def results(self, query, kind=""):
        self.flush()
        r = self.client.get("/arama", query_string={"q": query, "alan": kind})
        self.assertEqual(r.status_code, 200)
        return BeautifulSoup(r.data, "html.parser")

    def test_full_body_past_revision_turkish_folding_and_reader(self):
        body = (
            "Özet burada. "
            + "Satır başka bir konuyu anlatıyor. " * 40
            + " Sorgu planı bağlantı zaman aşımı içeriyor."
        )
        with app.db() as c:
            community.record_source(
                c, "foo.example", "Bülten", "https://foo.example", True, 1
            )
            for original in (body, "Haber yayıncı tarafından düzeltildi."):
                community.store(
                    c,
                    "https://foo.example/post",
                    "foo.example",
                    "tr",
                    "Arşivlenmiş haber",
                    "Kısa açıklama.",
                    original,
                    "2026-11-24",
                    "feed",
                    2,
                    1,
                )
        parsed = self.results("BAGLANTI zaman", "press")
        links = parsed.select("article h2 a")
        self.assertEqual(len(links), 1)
        self.assertEqual(parsed.select_one("article mark").get_text(), "bağlantı")
        reader = self.client.get(links[0]["href"])
        self.assertIn("bağlantı zaman aşımı", reader.get_data(as_text=True))
        self.assertEqual(
            len(self.results("bağlantı", "security").select("article h2")), 0
        )
        self.assertEqual(len(self.results("arşivlenmiş").select("article h2")), 1)

    def test_official_refresh_then_late_translation(self):
        source = "The planner selects an index."
        item = {
            "id": "CVE-2026-12345",
            "url": "https://www.postgresql.org/support/security/",
            "title": "Planner fix",
            "kind": "security",
            "summary": source,
        }
        app.save("security", [item])
        self.assertEqual(len(self.results("CVE-2026-12345").select("article h2")), 1)
        with app.db() as con:
            con.execute(
                "INSERT OR REPLACE INTO texts VALUES(?,?)",
                (source, "Sorgu planlayıcısı bir indeks seçer."),
            )
        self.assertEqual(len(self.results("planlayici").select("article h2")), 1)
        with app.db() as con:
            con.execute(
                "INSERT OR REPLACE INTO texts VALUES(?,?)",
                (source, "Sorgu planlayıcısı bir dizin seçer."),
            )
        self.assertEqual(len(self.results("dizin").select("article h2")), 1)
        self.assertFalse(self.results('x" OR 1=1--').select("article h2"))

    def test_body_translation_indexed_after_restart(self):
        with app.db() as c:
            community.record_source(c, "foo.example", "Foo", "feed", True, 1)
            community.store(
                c,
                "https://foo.example/t",
                "foo.example",
                "fr",
                "Une nouvelle",
                "Résumé",
                "Une information technique sur la restauration.",
                "2026-11-23",
                "feed",
                2,
                1,
            )
        self.flush()
        while community.translate_one(
            app.db,
            lambda text, language: (
                "Yedekten kurtarma işlemini anlatır."
                if "restauration" in text
                else "Başlık ve özet."
            ),
        ):
            pass
        app.initialize()
        self.assertEqual(len(self.results("kurtarma").select("article h2")), 1)
        self.assertEqual(len(self.results("restauration").select("article h2")), 1)

    def test_japanese_word_inside_sentence_and_exact_version(self):
        with app.db() as con:
            community.store(
                con,
                "https://foo.example/ja",
                "foo.example",
                "ja",
                "PostgreSQL 17.22",
                "",
                "これはデータベースの説明です。",
                "",
                "feed",
                2,
                1,
            )
        self.assertEqual(len(self.results("データベース").select("article h2")), 1)
        self.assertFalse(self.results("17.2").select("article h2"))
