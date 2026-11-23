import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bs4 import BeautifulSoup

import app
import feeds


class SecurityTests(unittest.TestCase):
    info = {
        "url": feeds.PG + "/support/security/CVE-2024-4317/",
        "title": "Restrict visibility of statistics",
        "cve": "CVE-2024-4317",
        "bulletin": "",
        "score": 3.1,
        "component": "core server",
    }
    # Version Information from the PostgreSQL 2024-05-09 bulletin, in non-numeric order.
    html = """<div id="pgContentWrap"><h3>Restrict visibility of statistics</h3>
        <p>Existing installations remain vulnerable until they follow the instructions in the release notes.
        Within major versions 14-16, minor versions before PostgreSQL 16.3, 15.7, and 14.12 are affected.</p>
        <ol><li>Apply the fix in each database.</li></ol><h2>Version Information</h2><table><tbody>
        <tr><td>16</td><td>16.3</td><td>2024-05-09</td></tr>
        <tr><td>14</td><td>14.12</td><td>2024-05-09</td></tr>
        <tr><td>15</td><td>15.7</td><td>2024-05-09</td></tr></tbody></table></div>"""

    def read(self, html):
        with patch.object(
            feeds, "page", return_value=BeautifulSoup(html, "html.parser")
        ):
            return feeds.advisory(self.info)

    def test_version_pairs_and_operational_revision(self):
        row = self.read(self.html)
        self.assertEqual(
            {r["major"]: r["fixed"] for r in row["matrix"]},
            {"16": "16.3", "15": "15.7", "14": "14.12"},
        )
        self.assertEqual(row["date"], "2024-05-09")
        self.assertTrue(row["extra"])
        self.assertNotEqual(
            row["guidance_revision"],
            self.read(
                self.html.replace("each database", "each database including template0")
            )["guidance_revision"],
        )

    def test_unrecognized_table_does_not_replace_cached_advisory(self):
        with self.assertRaises(ValueError):
            self.read(self.html.replace("Version Information", ""))

    def test_eol_overrides_stale_supported_flag(self):
        with patch.object(
            feeds,
            "fetch",
            return_value=b'[{"major":"14","latestMinor":"25","supported":true,"eolDate":"2001-01-01","relDate":"2000-01-01"}]',
        ):
            self.assertEqual(
                feeds.versions()["14"],
                dict(
                    latest="14.25", supported=False, eol="2001-01-01", date="2000-01-01"
                ),
            )

    def test_model_must_preserve_patch_number_and_identifier(self):
        with patch.object(
            app,
            "model_text",
            side_effect=["18.2 düzeltildi.", "[[T0]] sürümünde [[T1]] düzeltildi."],
        ):
            self.assertEqual(
                app.translate("18.7 fixes pg_trgm."),
                "18.7 sürümünde pg_trgm düzeltildi.",
            )
        with patch.object(app, "model_text", return_value="18.2"):
            with self.assertRaises(ValueError):
                app.translate("Upgrade to 18.7")


class PersistenceTests(unittest.TestCase):
    def test_old_term_errors_requeued_without_losing_other_translations(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DATA", Path(tmp)):
            app.initialize()
            with app.db() as con:
                con.executemany(
                    "INSERT INTO texts VALUES(?,?)",
                    [
                        ("Maintenance updates", "Yedekleme güncellemeleri"),
                        ("After maintenance updates", "Bakım güncellemelerinden sonra"),
                        ("Create a backup", "Bir yedek oluşturun"),
                    ],
                )
            app.initialize()
            app.initialize()
            with app.db() as con:
                self.assertEqual(
                    dict(con.execute("SELECT * FROM texts")),
                    {
                        "Maintenance updates": "",
                        "After maintenance updates": "Bakım güncellemelerinden sonra",
                        "Create a backup": "Bir yedek oluşturun",
                    },
                )

    def test_restarts_partial_outage_and_revision(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DATA", Path(tmp)):
            app.initialize()
            item = feeds.record(
                "release",
                feeds.PG + "/about/news/example/",
                "PostgreSQL 18.7",
                date="2026-11-12",
                notes=[],
            )

            def view():
                return app.app.test_client().get("/api/bulletin").get_json()

            app.save("releases", [item])
            app.source_status("releases")
            first = view()["items"][0]["seq"]
            app.initialize()
            app.save("releases", [item])
            app.source_status("releases", "upstream timeout")
            self.assertEqual(view()["items"][0]["seq"], first)
            src = next(s for s in view()["sources"] if s["key"] == "releases")
            self.assertTrue(src["error"])
            self.assertIsNotNone(src["success"])
            app.save("releases", [dict(item, notes=["Changed update instruction."])])
            self.assertGreater(view()["items"][0]["seq"], first)
            self.assertEqual(len(view()["items"]), 1)
            app.source_status("releases")
            self.assertFalse(
                next(s for s in view()["sources"] if s["key"] == "releases")["error"]
            )


class TerminologyTests(unittest.TestCase):
    def test_security_measure_prefix_follows_the_source(self):
        source = "Take a full backup before applying the maintenance update."
        action = "Bakım güncellemesini uygulama öncesinde tam bir yedek alın."
        for prefix in (
            "Güvenlik önlemleri olarak",
            "Güvenlik tedbirleri olarak",
            "Bir güvenlik önlemi olarak",
        ):
            raw = f"{prefix}, {action[0].lower()}{action[1:]}"
            with (
                self.subTest(prefix=prefix),
                patch.object(app, "model_text", return_value=raw),
            ):
                self.assertFalse(app.reasons_supported(source, raw))
                self.assertEqual(app.translate(source), action)
                explicit = "As a security measure, " + source.lower()
                self.assertEqual(app.translate(explicit), raw)

    def test_known_mistranslation_preserves_suffixes_and_distinct_backup_updates(self):
        with patch.object(
            app,
            "model_text",
            return_value="Yedekleme güncellemesinden sonra ana sunucuda çalışır.",
        ) as model:
            self.assertEqual(
                app.translate(
                    "It runs on the primary server after the maintenance update."
                ),
                "Bakım güncellemesinden sonra birincil sunucuda çalışır.",
            )
            model.assert_called_once()
        other = "Yedekleme güncellemesi ana sunucuda çalışır."
        with patch.object(app, "model_text", return_value=other):
            self.assertEqual(
                app.translate("The backup update runs on the main server."), other
            )

    def test_glossary_retry_keeps_real_backup_and_inflected_terms(self):
        source = "The primary server needs a backup before maintenance updates."
        good = (
            "Birincil sunucunun bakım güncellemelerinden önce bir yedeğe ihtiyacı var."
        )
        with patch.object(
            app,
            "model_text",
            side_effect=[
                "Birincil sunucunun yedekleme güncellemelerinden önce bir yedeğe ihtiyacı var.",
                good,
            ],
        ) as model:
            self.assertEqual(app.translate(source), good)
            model.assert_called_with(source, explicit_terms=True)
        with (
            patch.object(app, "model_text", return_value="Yedekleme güncellemesi"),
            self.assertRaisesRegex(ValueError, "sözlük"),
        ):
            app.translate(source)

    def test_maintenance_correction_also_preserves_wal_and_version_on_retry(self):
        with patch.object(
            app,
            "model_text",
            side_effect=[
                "Yedekleme güncellemesi gerekli.",
                "Bakım güncellemesi [[T0]] sürümünde [[T1]] kayıtlarını etkiler.",
            ],
        ):
            self.assertEqual(
                app.translate("The maintenance update in 18.7 affects WAL records."),
                "Bakım güncellemesi 18.7 sürümünde WAL kayıtlarını etkiler.",
            )


class RationaleTests(unittest.TestCase):
    instruction = "Take a full backup before applying the maintenance update."
    action = "Bakım güncellemesini uygulamadan önce tam yedek alın."
    extra = "Güvenlik amaçlı, bakım güncellemesini uygulamadan önce tam yedek alın."

    def test_detached_motive_removed_only_when_unsupported(self):
        with patch.object(app, "model_text", return_value=self.extra):
            self.assertEqual(app.translate(self.instruction), self.action)
            self.assertEqual(
                app.translate(
                    "For security reasons, take a full backup before applying the maintenance update."
                ),
                self.extra,
            )
        with patch.object(
            app, "model_text", return_value="Güvenlik amaçlı, pg_upgrade çalıştırın."
        ):
            self.assertEqual(app.translate("Run pg_upgrade."), "pg_upgrade çalıştırın.")

    def test_security_update_and_another_reason_do_not_authorize_a_security_motive(
        self,
    ):
        en = "Apply the security update to improve performance."
        bad = "Güvenlik güncellemesini güvenlik gerekçesiyle uygulayın."
        good = "Performansı iyileştirmek için güvenlik güncellemesini uygulayın."
        with patch.object(app, "model_text", side_effect=[bad, good]):
            self.assertEqual(app.translate(en), good)
        with (
            patch.object(app, "model_text", return_value=bad),
            self.assertRaisesRegex(ValueError, "gerekçe"),
        ):
            app.translate(en)
        self.assertFalse(
            app.reasons_supported(
                en, "Veri kaybını önlemek için güvenlik güncellemesini uygulayın."
            )
        )
        self.assertFalse(
            app.reasons_supported(
                "Restart the service. For security reasons, stop the backup.",
                "Güvenlik nedeniyle hizmeti yeniden başlatın. Yedeklemeyi durdurun.",
            )
        )

    def test_retry_without_glossary_preserves_true_reason(self):
        en = "For security reasons, restart the service."
        good = "Güvenlik nedeniyle hizmeti yeniden başlatın."
        with patch.object(
            app, "model_text", side_effect=["Hizmeti yeniden başlatın.", good]
        ):
            self.assertEqual(app.translate(en), good)
        with (
            patch.object(
                app,
                "model_text",
                return_value="Veri kaybını önlemek için hizmeti yeniden başlatın.",
            ),
            self.assertRaises(ValueError),
        ):
            app.translate("Restart the service.")

    def test_upgrade_requeues_existing_unsupported_motive(self):
        explained = "For security reasons, take a full backup before applying the maintenance update."
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "DATA", Path(tmp)):
            app.initialize()
            with app.db() as con:
                con.executemany(
                    "INSERT INTO texts VALUES(?,?)",
                    [
                        (self.instruction, self.extra),
                        (explained, self.extra),
                    ],
                )
            app.initialize()
            with app.db() as con:
                self.assertEqual(
                    dict(con.execute("SELECT * FROM texts")),
                    {
                        self.instruction: "",
                        explained: self.extra,
                    },
                )

    def test_extra_explanatory_sentence_and_negated_reason(self):
        self.assertFalse(
            app.reasons_supported(
                "Take a full backup.", "Tam yedek alın. Bu işlem verilerinizi korur."
            )
        )
        self.assertTrue(
            app.reasons_supported(
                "To avoid data loss, take a full backup.",
                "Veri kaybını önlemek için tam yedek alın.",
            )
        )
        self.assertFalse(
            app.reasons_supported(
                "Restart for compatibility, not for security reasons.",
                "Güvenlik nedeniyle yeniden başlatın.",
            )
        )


if __name__ == "__main__":
    unittest.main()
