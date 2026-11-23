import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

import app
import community
import feeds
import news_search


class HistoryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        data = patch.object(app, "DATA", Path(folder.name))
        data.start()
        self.addCleanup(data.stop)
        app.initialize()
        self.client = app.app.test_client()

    def test_backfill_resume_new_minor_and_saved_translation(self):
        base = feeds.PG + "/docs/15/"
        template = """<div id="docContent"><div class="sect1"><h2>E.1. Release VERSION <a class="id_link">#</a></h2>
        <p>Release date: 2023-01-01</p><div class="sect2"><h3>Migration to Version VERSION</h3><p>Read the notes.</p>
        <pre>SELECT  1;</pre></div><div class="sect2"><h3>Changes</h3><ul><li><p>Fix an error. <a class="ulink">§</a></p>
        <p>More details.</p></li></ul></div></div></div>"""
        versions = {
            "14": {"latest": "14.7"},
            "15": {"latest": "15.2"},
            "19": {"latest": "19.0"},
        }
        entries = ["15-2", "15-1"]
        fetched = []

        def page(url):
            if url == base + "release.html":
                html = (
                    '<div id="docContent"><div class="toc">'
                    + "".join(
                        f'<a href="release-{v}.html">Release</a><a href="release-{v}.html#changes">Changes</a>'
                        for v in entries
                    )
                    + "</div></div>"
                )
            else:
                v = (
                    url.removeprefix(base + "release-")
                    .removesuffix(".html")
                    .replace("-", ".")
                )
                fetched.append(v)
                html = template.replace("VERSION", v)
                if fetched == ["15.2"]:
                    html = html.replace("Changes", "Offline")
            return BeautifulSoup(html, "html.parser")

        with (
            patch.object(feeds, "versions", return_value=versions),
            patch.object(feeds, "page", side_effect=page),
        ):
            with self.assertLogs(level="ERROR"), self.assertRaises(ValueError):
                app.collect("maintenance")
            app.initialize()
            app.collect("maintenance")
            with patch.object(
                app, "translate", return_value="Bir hata düzeltildi."
            ) as model:
                app.work.clear()
                app.translate_round()
                calls = model.call_count
                versions["15"]["latest"] = "15.3"
                entries.insert(0, "15-3")
                app.collect("maintenance")
                app.work.clear()
                app.translate_round()
                self.assertEqual(model.call_count, calls)
        self.assertEqual(fetched, ["15.2", "15.1", "15.2", "15.3"])
        self.assertEqual(self.client.get("/bakim/14.7").status_code, 404)
        self.assertIn(b"15.3", self.client.get("/bakim").data)
        note = self.client.get("/bakim/15.3").get_data(as_text=True)
        for s in (
            "Bir hata düzeltildi.",
            "More details.",
            "SELECT  1;",
            "Bu sürüme geçiş",
        ):
            self.assertIn(s, note)
        self.assertFalse(self.client.get("/api/bulletin").json["items"])
        news_search.batch(app.db, {})
        self.assertIn(
            "3 haber bulundu",
            self.client.get("/arama?q=hata&alan=maintenance").get_data(as_text=True),
        )

    def test_search_windows_cover_year_and_filter_provider_dates(self):
        today = date(2026, 1, 2)
        searches = [
            (key, parse_qs(urlsplit(url).query)["q"][0], parse)
            for key, url, parse in community.jobs(today)
            if key.startswith("search/") and key.endswith("/tr")
        ]
        self.assertEqual(len(searches), 13)
        self.assertIn("after:2025-01-01", searches[-1][1])
        self.assertIn("before:2026-01-03", searches[0][1])
        xml = """<rss><channel><item><title>PostGIS güncellemesi</title><link>https://news.google.com/rss/articles/1</link>
        <source url="https://postgis.net">PostGIS</source><pubDate>2025-01-02</pubDate></item></channel></rss>"""
        with app.db() as con:
            searches[0][2](con, xml.encode(), 10)
            self.assertEqual(
                con.execute("SELECT count(*) FROM press_articles").fetchone()[0], 0
            )
            searches[-1][2](con, xml.encode(), 10)
            self.assertEqual(
                con.execute("SELECT count(*) FROM press_articles").fetchone()[0], 1
            )

    def test_project_page_verification_retry_and_revision(self):
        origin = "https://postgis.net/sitemap.xml"
        url = "https://postgis.net/2026/10/postgis-release/"
        other = "https://another.example/2026/10/postgis-release/"
        ts = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp())
        xml = (
            f"<urlset><url><loc>{url}</loc></url><url><loc>{other}</loc></url></urlset>"
        )
        page = f"""<html><head><link rel="canonical" href="{url}"><meta property="article:published_time" content="2026-10-01"></head>
        <body><h1>PostGIS</h1><section class="gdoc-markdown"><p>First edition.</p></section></body></html>""".encode()
        with app.db() as con:
            community.project_index(con, xml.encode(), origin, ts)
        responses = iter(
            [
                page.replace(url.encode(), other.encode()),
                page,
                page,
                OSError("offline"),
                page.replace(b"First", b"Second"),
            ]
        )

        def fetch(target, project):
            self.assertEqual((target, project), (url, origin))
            reply = next(responses)
            if isinstance(reply, Exception):
                raise reply
            return reply

        def read():
            return self.client.get("/api/dis-basin?konu=teknoloji").json

        with self.assertLogs(level="WARNING"):
            community.check_project_pages(app.db, fetch, lambda: ts)
        self.assertEqual(read()["total"], 0)
        ts += 3601
        community.check_project_pages(app.db, fetch, lambda: ts)
        app.initialize()
        community.check_project_pages(app.db, fetch, lambda: ts)
        ts += community.WEEK
        community.check_project_pages(app.db, fetch, lambda: ts)
        self.assertEqual(read()["items"][0]["versions"], 1)
        self.assertEqual(self.client.get("/api/bulletin").json["project_news"][0]["name"], "PostGIS")
        ts += community.WEEK
        with self.assertLogs(level="WARNING"):
            community.check_project_pages(app.db, fetch, lambda: ts)
        self.assertTrue(read()["items"][0]["link_failed"])
        ts += 3601
        community.check_project_pages(app.db, fetch, lambda: ts)
        self.assertEqual(read()["items"][0]["versions"], 2)
