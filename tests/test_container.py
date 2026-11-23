import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from werkzeug.security import generate_password_hash

from admin import register
import app


def load_controller():
    file = Path(__file__).resolve().parents[1] / "deploy/container/controller.py"
    spec = importlib.util.spec_from_file_location("controller", file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuthTests(unittest.TestCase):
    def test_readers_cannot_dispatch_and_admin_is_bound_to_session_csrf_and_release(
        self,
    ):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "requests").mkdir()
            (base / "status").mkdir()
            (base / "status/status.json").write_text('{"available":"v1.2.0"}')
            (base / "auth").write_text(
                json.dumps(
                    {
                        "secret": "test-only-secret",
                        "password": generate_password_hash("test-password"),
                    }
                )
            )
            web = Flask("test")
            with patch.dict(
                os.environ, {"GUNDEM_CONTROL": temp, "GUNDEM_ADMIN": str(base / "auth")}
            ):
                with patch.object(app, "DATA", base):
                    app.initialize()
                register(web, base, "http://127.0.0.1", app.db, app.pending_count)
            client = web.test_client()

            def post(path, body, token=""):
                return client.post(
                    "/api/admin/" + path,
                    json=body,
                    headers={"X-CSRF-Token": token},
                    base_url="https://localhost",
                )

            self.assertEqual(post("retry-translations", {}).status_code, 401)
            self.assertEqual(post("apply", {}).status_code, 401)
            token = client.get("/api/admin/session", base_url="https://localhost").json[
                "csrf"
            ]
            self.assertEqual(
                post("login", {"password": "test-password"}).status_code, 403
            )
            self.assertEqual(post("login", {"password": "bad"}, token).status_code, 401)
            token = post("login", {"password": "test-password"}, token).json["csrf"]
            self.assertEqual(post("apply", {"version": "v1.2.0"}).status_code, 403)
            self.assertEqual(
                post("apply", {"version": "v9.9.9"}, token).status_code, 409
            )
            self.assertEqual(post("retry-translations", {}).status_code, 403)
            with patch.object(app, "DATA", base):
                with app.db() as con:
                    con.execute(
                        "INSERT INTO translation_tasks VALUES('press','1',0,3,'failed',100,'',1)"
                    )
                    con.execute(
                        "INSERT INTO translation_tasks VALUES('press','1',1,1,'working',9999999999,'',1)"
                    )
                self.assertEqual(
                    post("retry-translations", {}, token).json, {"requeued": 1}
                )
                with app.db() as con:
                    self.assertEqual(
                        [
                            tuple(row)
                            for row in con.execute(
                                "SELECT status,due FROM translation_tasks ORDER BY part"
                            )
                        ],
                        [("failed", 0), ("working", 9999999999)],
                    )
            for _ in range(2):
                self.assertEqual(
                    post("apply", {"version": "v1.2.0"}, token).status_code, 202
                )
            self.assertEqual(
                [p.name for p in (base / "requests").iterdir()], ["apply-v1.2.0"]
            )


class QualityTests(unittest.TestCase):
    def test_version_direction_and_database_meaning(self):
        self.assertTrue(
            app.safe_instruction(
                "Versions before 15.7 are affected.",
                "15.7 öncesi sürümler etkilenmektedir.",
            )
        )
        self.assertFalse(
            app.safe_instruction("The system is unaffected.", "Sistem etkilenmektedir.")
        )
        for source, target in [
            ("Upgrade from 16.2 to 16.3.", "16.3 sürümünden 16.2 sürümüne yükseltin."),
            (
                "Versions from 15.7 onward are unaffected.",
                "15.7'den sonraki sürümler etkilenmez.",
            ),
            ("Do not restart the server.", "Sunucuyu yeniden başlatın."),
            ("The table is dropped at commit.", "Tablo taahhütte düşürülür."),
        ]:
            self.assertFalse(app.safe_instruction(source, target))
        self.assertEqual(
            app.translate("Upgrade from 16.2 to 16.3."),
            "16.2 sürümünden 16.3 sürümüne yükseltin.",
        )


@unittest.skipUnless(os.name == "posix", "Linux sürüm hizmeti")
class SwitchTests(unittest.TestCase):
    def setUp(self):
        self.module = load_controller()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        for name in ("manager", "data", "status", "models"):
            (self.base / name).mkdir()
        (self.base / "settings.json").write_text(
            json.dumps(
                dict(
                    engine="docker",
                    uid=os.getuid(),
                    gid=os.getgid(),
                    platform="Linux",
                    rootless=False,
                )
            )
        )
        self.m = self.module.Manager(self.base)
        self.old = dict(tag="v1.0.0", image={"id": "sha256:" + "1" * 64})
        self.new = dict(tag="v1.1.0", image={"id": "sha256:" + "2" * 64})
        self.module.save(self.m.active, self.old)
        with sqlite3.connect(self.m.db) as db:
            db.execute("CREATE TABLE items(id TEXT)")
            db.execute("INSERT INTO items VALUES ('old')")
        for name in ("configure", "stage", "stop", "start", "discard"):
            p = patch.object(self.m, name)
            p.start()
            self.addCleanup(p.stop)

    def test_failed_switch_restores_sqlite_and_previous_version(self):
        def verify(manifest):
            if manifest == self.new:
                with sqlite3.connect(self.m.db) as db:
                    db.execute("DROP TABLE items")
                raise ValueError("Sağlık hatası")

        with (
            patch.object(self.m, "verify", side_effect=verify),
            self.assertRaises(ValueError),
        ):
            self.m.apply(self.new)
        self.assertEqual(self.module.read(self.m.active), self.old)
        with sqlite3.connect(self.m.db) as db:
            self.assertEqual(db.execute("select id from items").fetchone(), ("old",))
        self.assertFalse(self.m.tx.exists())

    def test_watch_stays_offline_until_an_admin_requests_a_release_check(self):
        queue = self.base / "requests"
        queue.mkdir()
        (
            queue / "check"
        ).touch()  # Only directory requests created by the admin endpoint are valid.
        with (
            patch.object(self.m, "check", return_value=self.new) as check,
            patch.object(self.m, "apply") as apply,
            patch.object(
                self.module.time, "monotonic", side_effect=range(0, 86400, 7200)
            ),
            patch.object(
                self.module.time, "sleep", side_effect=[None, None, KeyboardInterrupt]
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.m.watch()
        check.assert_not_called()
        apply.assert_not_called()

        for name in ("check", "apply-" + self.new["tag"]):
            (queue / name).mkdir()
            with (
                patch.object(self.m, "check", return_value=self.new) as check,
                patch.object(self.m, "apply") as apply,
                patch.object(self.module.time, "sleep", side_effect=KeyboardInterrupt),
                self.assertRaises(KeyboardInterrupt),
            ):
                self.m.watch()
            check.assert_called_once_with()
            if name == "check":
                apply.assert_not_called()
            else:
                apply.assert_called_once_with(self.new)
            self.assertFalse((queue / name).exists())

    def test_interrupted_switch_recovers_twice(self):
        self.m.snapshot()
        self.module.save(self.m.tx, dict(phase="switch", old=self.old, new=self.new))
        self.m.db.unlink()
        with patch.object(self.m, "verify"):
            self.m.recover()
            self.m.recover()
        self.assertTrue(self.m.db.is_file())
        self.assertFalse(self.m.tx.exists())

    def test_semver_and_failed_preflight_leave_live_data(self):
        self.assertGreater(self.module.number("v1.10.0"), self.module.number("v1.9.9"))
        for tag in ("main", "../v1.0.0", "v1.0.0-rc1"):
            with self.assertRaises(ValueError):
                self.module.number(tag)
        self.m.stage.side_effect = ValueError("Yetersiz alan")
        with self.assertRaises(ValueError):
            self.m.apply(self.new)
        self.m.stop.assert_not_called()
        self.assertEqual(self.module.read(self.m.active), self.old)

    def test_unsigned_manifest_rejected_before_inspecting_images(self):
        with patch.object(
            self.module, "fetch", side_effect=[b'{"tag":"v1.0.1"}', b"x" * 64]
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                self.module.manifest("v1.0.1", "amd64")

    def test_wrong_model_and_low_disk_rejected_before_engine_access(self):
        import hashlib

        model = {
            "file": "local.gguf",
            "sha256": hashlib.sha256(b"expected").hexdigest(),
        }
        candidate = dict(self.new, model=model, image={"bytes": 100})
        local = self.base / "models/local.gguf"
        local.write_bytes(b"corrupt")
        with patch.object(self.module, "run") as engine:
            with self.assertRaisesRegex(ValueError, "modeli"):
                self.module.Manager.stage(self.m, candidate)
            local.write_bytes(b"expected")
            with patch.object(self.module.shutil, "disk_usage") as disk:
                disk.return_value.free = 0
                with self.assertRaisesRegex(ValueError, "disk"):
                    self.module.Manager.stage(self.m, candidate)
            engine.assert_not_called()
