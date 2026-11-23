from pathlib import Path
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
                (3, "original"),
            )

    def test_model_outage_and_interrupted_last_attempt(self):
        key = (app.db, "official", "Metin", 0)
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
                {"original"},
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
