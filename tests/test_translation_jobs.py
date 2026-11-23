from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
import community
import translation_jobs as tasks


class TranslationQueueTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data = patch.object(app, "DATA", Path(directory.name))
        data.start()
        self.addCleanup(data.stop)
        app.initialize()

    def test_legacy_empty_translation_bad_input_and_restart(self):
        bad, good = "First sample.", "Next sample."
        app.save("notes", [dict(id="x", kind="dev", title=bad, summary=good)])
        with app.db() as con:
            con.execute("INSERT INTO texts VALUES(?, '')", (bad,))

        def translate(text, *, guided):
            if text == bad:
                raise ValueError("Çeviri doğrulanamadı")
            return "Sonraki örnek."

        with patch.object(app, "translate", side_effect=translate) as model:
            for _ in range(3):
                app.initialize()
                with app.db() as con:
                    con.execute("UPDATE translation_tasks SET due=0")
                app.work.clear()
                app.translate_round()
            app.translate_round()
            self.assertEqual(model.call_count, 4)
            self.assertTrue(model.call_args.kwargs["guided"])
        result = app.app.test_client().get("/api/bulletin").json["items"][0]
        self.assertEqual(result["original_only"], [bad])
        self.assertEqual(result["tr"][good], "Sonraki örnek.")
        with app.db() as con:
            self.assertEqual(app.pending_count(con), 0)
            self.assertEqual(
                tuple(
                    con.execute(
                        "SELECT attempts,status FROM translation_tasks"
                    ).fetchone()
                ),
                (3, "failed"),
            )

    def test_model_outage_and_interrupted_last_attempt(self):
        key = (app.db, "official", "Metin", 0, "Metin", "en")
        commit = Mock()
        fail = Mock(side_effect=ConnectionRefusedError())
        for _ in range(4):
            self.assertEqual(
                tasks.run(*key, fail, commit, health=lambda: False), "offline"
            )
            with app.db() as con:
                self.assertEqual(
                    con.execute("SELECT attempts FROM translation_tasks").fetchone()[0],
                    0,
                )
                con.execute("UPDATE translation_tasks SET due=0")
        with app.db() as con:
            con.execute(
                "UPDATE translation_tasks SET attempts=3,status='working',due=9999999999"
            )
        app.initialize()
        self.assertEqual(
            tasks.run(*key, lambda attempt: f"Sonuç {attempt}", commit), "done"
        )
        self.assertEqual(commit.call_args.args[1], "Sonuç 3")
        with app.db() as con:
            self.assertIsNone(con.execute("SELECT 1 FROM translation_tasks").fetchone())

    def test_external_fields_recover_independently_and_body_keeps_advancing(self):
        with app.db() as con:
            community.store(
                con,
                "https://example.org/pg",
                "example.org",
                "en",
                "Database news",
                "Short summary",
                "A " * 310 + "End of article.",
                "",
                "feed",
                1,
                1,
            )
            con.execute("UPDATE press_revisions SET retry=9999999999, error='legacy'")

        def translate(text, language):
            if text.startswith(("Short", "A A")):
                raise ValueError("Doğrulanamadı")
            return "Veritabanı haberi" if text.startswith("Database") else "Son bölüm"

        for _ in range(3):
            with app.db() as con:
                con.execute("UPDATE translation_tasks SET due=0")
            while community.translate_one(app.db, translate):
                pass
        with app.db() as con:
            entry = con.execute(
                "SELECT title_tr,excerpt_tr FROM press_revisions"
            ).fetchone()
            self.assertEqual(tuple(entry), ("Veritabanı haberi", None))
            self.assertEqual(
                {r[0] for r in con.execute("SELECT status FROM translation_tasks")},
                {"failed"},
            )
            self.assertTrue(
                con.execute(
                    "SELECT 1 FROM press_parts WHERE translation='Son bölüm'"
                ).fetchone()
            )
        client = app.app.test_client()
        article = client.get("/api/dis-basin").json["items"][0]
        self.assertEqual(
            (article["original_only"], article["excerpt"]), (1, "Short summary")
        )
        self.assertIn(b"End of article", client.get("/arsiv/oku/-1").data)

    def test_weekly_retry_only_when_due_and_success_survives_restart(self):
        source = "News item for the weekly check."
        app.save("notes", [dict(kind="dev", title=source, id="weekly")])
        app.work.clear()
        ts = 1700000000
        with patch.object(
            app, "translate", side_effect=ValueError("Terim doğrulanamadı")
        ) as model:
            for delay in (0, *tasks.RETRY_DELAYS):
                ts += delay
                with patch("time.time", return_value=ts):
                    app.translate_round()
            due = ts + tasks.RECHECK
            with app.db() as con:
                row = con.execute(
                    "SELECT status,attempts,checked_at,due,detail FROM translation_tasks"
                ).fetchone()
                self.assertEqual(
                    tuple(row), ("failed", 3, ts, due, "Terim doğrulanamadı")
                )
            app.initialize()
            with patch("time.time", return_value=due - 1):
                app.translate_round()
            self.assertEqual(model.call_count, 3)
        with (
            patch("time.time", return_value=due),
            patch.object(app, "translate", return_value="Haftalık haber.") as model,
        ):
            app.translate_round()
            app.initialize()
            app.translate_round()
            model.assert_called_once_with(source, guided=True)
        with app.db() as con:
            self.assertFalse(con.execute("SELECT 1 FROM translation_tasks").fetchone())
            self.assertEqual(
                tuple(
                    con.execute(
                        "SELECT translation,saved_at FROM translation_memory WHERE original=?",
                        (source,),
                    ).fetchone()
                ),
                ("Haftalık haber.", due),
            )

    def test_existing_translations_reused_across_articles_and_revisions(self):
        def put(url, lang, title, summary):
            with app.db() as con:
                community.store(
                    con,
                    url,
                    "example.org",
                    lang,
                    title,
                    summary,
                    summary,
                    "",
                    "feed",
                    1,
                    1,
                )

        put("https://example.org/a", "fr", "Titre", "Résumé")
        with app.db() as con:
            # Mimic data written before the translation memory existed.
            con.execute(
                "UPDATE press_revisions SET title_tr='Başlık', excerpt_tr='Özet'"
            )
            con.execute("INSERT INTO texts VALUES('First announcement','İlk duyuru')")
            con.execute("DELETE FROM state WHERE key='translation_memory_imported'")
        app.initialize()
        put("https://example.org/a", "fr", "Titre", "Changement")
        put("https://example.org/b", "fr", "Titre", "Résumé")
        put("https://example.org/c", "en-US", "First announcement", "")
        put("https://example.org/d", "de", "Titre", "")
        model = Mock(
            side_effect=lambda source, lang: {
                ("Changement", "fr"): "Değişiklik",
                ("Titre", "de"): "Almanca başlık",
            }[(source, lang)]
        )
        while community.translate_one(app.db, model):
            pass
        self.assertCountEqual(
            [c.args for c in model.call_args_list],
            [("Changement", "fr"), ("Titre", "de")],
        )
        app.initialize()
        self.assertFalse(community.translate_one(app.db, model))
        with app.db() as con:
            rows = con.execute(
                "SELECT title_tr,excerpt_tr FROM press_revisions ORDER BY id"
            ).fetchall()
            self.assertEqual(
                [tuple(r) for r in rows],
                [
                    ("Başlık", "Özet"),
                    ("Başlık", "Değişiklik"),
                    ("Başlık", "Özet"),
                    ("İlk duyuru", None),
                    ("Almanca başlık", None),
                ],
            )

    def test_concurrent_identical_text_has_one_model_request(self):
        start = Barrier(2)
        model = Mock(return_value="Kalıcı çeviri")
        commit = Mock()

        def translate(ref):
            start.wait(timeout=3)
            return tasks.run(
                app.db, "press", ref, 0, "Shared text", "en", model, commit
            )

        with ThreadPoolExecutor(2) as pool:
            self.assertEqual(list(pool.map(translate, (1, 2))), ["done", "done"])
        model.assert_called_once_with(1)
        self.assertEqual(commit.call_count, 2)

    def test_superseded_official_revision_retains_its_translation_job(self):
        app.save("notes", [dict(kind="dev", id="revised", title="Previous title")])
        app.save("notes", [dict(kind="dev", id="revised", title="Updated title")])
        app.initialize()
        app.work.clear()
        with patch.object(
            app,
            "translate",
            side_effect=lambda source, guided: {
                "Previous title": "Önceki başlık",
                "Updated title": "Yeni başlık",
            }[source],
        ) as model:
            app.translate_round()
            app.translate_round()
            self.assertEqual(model.call_count, 2)
        with app.db() as con:
            self.assertEqual(
                dict(con.execute("SELECT original,translation FROM texts")),
                {"Previous title": "Önceki başlık", "Updated title": "Yeni başlık"},
            )
