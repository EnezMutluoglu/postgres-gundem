#!/usr/bin/env python3
"""Verify stable releases, serialize updates and recover interrupted switches."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

REPO = "EnezMutluoglu/postgres-gundem"
REGISTRY = "ghcr.io/enezmutluoglu/postgres-gundem"
HERE = Path(__file__).resolve().parent
TAG = r"v(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)"
HEX = r"[0-9a-f]{64}"


def number(tag):
    if not isinstance(tag, str) or not re.fullmatch(TAG, tag):
        raise ValueError("Geçersiz sürüm etiketi")
    return tuple(map(int, tag[1:].split(".")))


def atomic(path, data, mode=0o644):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, path)
            fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        finally:
            tmp.unlink(missing_ok=True)


def save(path, obj):
    atomic(path, json.dumps(obj, ensure_ascii=False).encode())


def read(path, default=None):
    return json.loads(path.read_text()) if path.is_file() else default


def run(*args, timeout=900):
    return subprocess.run(
        [str(x) for x in args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    ).stdout.strip()


def open_url(url):
    return urlopen(
        Request(url, headers={"User-Agent": "postgres-gundem-updater/1"}), timeout=60
    )


def fetch(url, limit):
    with open_url(url) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Beklenenden büyük sürüm dosyası")
    return data


def file_hash(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def manifest(tag, arch):
    number(tag)
    base = f"https://github.com/{REPO}/releases/download/{tag}/"
    content = fetch(base + "release.json", 65536)
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "release"
        p.write_bytes(content)
        sig = Path(d) / "sig"
        sig.write_bytes(fetch(base + "release.sig", 128))
        run(
            "openssl",
            "pkeyutl",
            "-verify",
            "-pubin",
            "-inkey",
            HERE / "release.pub",
            "-rawin",
            "-in",
            p,
            "-sigfile",
            sig,
        )
    m = json.loads(content)
    if m["schema"] != 1 or m["tag"] != tag or m["controller_api"] != 1:
        raise ValueError("Sürüm biçimi veya güncelleyici uyumsuz.")
    a = m["images"][arch]
    if not all(
        re.fullmatch("sha256:" + HEX, a[k]) for k in ("digest", "id")
    ) or not re.fullmatch(HEX, a["sha256"]):
        raise ValueError("İmaj özeti geçersiz.")
    if not isinstance(a["bytes"], int) or not 0 < a["bytes"] < 2**31:
        raise ValueError("İmaj boyutu geçersiz.")
    model = m["model"]
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+\.gguf", model["file"])
        or model["type"] not in ("gemma", "riva")
        or not re.fullmatch(HEX, model["sha256"])
    ):
        raise ValueError("Model tanımı geçersiz.")
    return {"tag": tag, "image": a, "model": model, "notes": str(m["notes"])[:3000]}


class Manager:
    def __init__(self, base):
        self.base = Path(base).resolve()
        self.env = read(self.base / "settings.json")
        self.engine = self.env["engine"]
        self.system = ["systemctl"] + (["--user"] if self.env["rootless"] else [])
        self.arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64"}[
            platform.machine()
        ]
        self.private = self.base / "manager"
        self.active = self.private / "active.json"
        self.tx = self.private / "transaction.json"
        self.status = self.base / "status/status.json"
        self.db = self.base / "data/gundem.sqlite"

    def message(self, **values):
        current = read(self.status, {})
        current.update(
            values,
            platform=self.env["platform"] + " · " + self.arch + " · " + self.engine,
        )
        save(self.status, current)

    def check(self):
        release = json.loads(
            fetch(f"https://api.github.com/repos/{REPO}/releases/latest", 262144)
        )
        tag = release["tag_name"]
        if release["draft"] or release["prerelease"]:
            raise ValueError("Kararlı sürüm bekleniyor.")
        new = manifest(tag, self.arch)
        old = read(self.active)
        newer = not old or number(tag) > number(old["tag"])
        self.message(
            available=tag if newer else None,
            bytes=new["image"]["bytes"] if newer else 0,
            notes=new["notes"] if newer else "",
            checked=datetime.now(timezone.utc).isoformat(),
            busy=False,
            message="Yeni sürüm var." if newer else "Güncel.",
        )
        return new

    def local_tag(self, m):
        return "localhost/postgres-gundem:" + m["tag"] + "-" + m["image"]["id"][7:19]

    def stage(self, m):
        model = self.base / "models" / m["model"]["file"]
        if (
            not model.is_file()
            or model.is_symlink()
            or file_hash(model) != m["model"]["sha256"]
        ):
            raise ValueError("Gereken yerel modeli doğrulayın: " + model.name)
        a = m["image"]
        if (
            shutil.disk_usage(self.base).free
            < 3 * a["bytes"]
            + 2 * (self.db.stat().st_size if self.db.exists() else 0)
            + 128 * 2**20
        ):
            raise ValueError("Güncelleme için boş disk yetersiz.")
        local = self.local_tag(m)
        receipts = self.private / "image-receipts.json"
        known = read(receipts, {})

        def image_id(ref):
            return run(self.engine, "image", "inspect", "--format", "{{.Id}}", ref)

        try:
            reused = image_id(local) == known.get(a["digest"])
        except subprocess.CalledProcessError:
            reused = False
        if not reused:
            source = REGISTRY + "@" + a["digest"]
            try:
                run(self.engine, "pull", source)
            except subprocess.CalledProcessError:
                url = f"https://github.com/{REPO}/releases/download/{m['tag']}/image-{self.arch}.tar.gz"
                with (
                    tempfile.NamedTemporaryFile(dir=self.private) as f,
                    open_url(url) as response,
                ):
                    remaining = a["bytes"]
                    while remaining:
                        block = response.read(min(1024 * 1024, remaining))
                        if not block:
                            raise ValueError("İmaj dosyası eksik.")
                        f.write(block)
                        remaining -= len(block)
                    f.flush()
                    if response.read(1) or file_hash(Path(f.name)) != a["sha256"]:
                        raise ValueError("Arşiv doğrulanamadı.")
                    run(self.engine, "load", "-i", f.name)
                source = f"{REGISTRY}:{m['tag']}-{self.arch}"
            if (
                run(
                    self.engine,
                    "image",
                    "inspect",
                    "--format",
                    "{{.Os}}/{{.Architecture}}",
                    source,
                )
                != "linux/" + self.arch
            ):
                raise ValueError("İmaj mimarisi doğrulanamadı.")
            actual = image_id(source)
            run(self.engine, "tag", source, local)
            if image_id(local) != actual:
                raise ValueError("Yerel imaj kimliği doğrulanamadı.")
            known[a["digest"]] = actual
            save(receipts, known)

    def configure(self, m):
        cfg = dict(
            PG_IMAGE=self.local_tag(m),
            PG_ROOT=str(self.base),
            MODEL_TYPE=m["model"]["type"],
            MODEL_FILE=m["model"]["file"],
            RUN_UID=self.env["uid"],
            RUN_GID=self.env["gid"],
        )
        atomic(
            self.private / "runtime.env",
            "".join(f"{k}={v}\n" for k, v in cfg.items()).encode(),
        )
        if self.engine == "podman":
            for unit in ("web", "model"):
                template = (HERE / f"{unit}.container").read_text()
                for k, v in cfg.items():
                    template = template.replace("@" + k + "@", str(v))
                template = template.replace(
                    "@USERNS@", "UserNS=keep-id" if self.env["rootless"] else ""
                )
                units = Path(self.env["quadlets"])
                atomic(units / f"postgres-gundem-{unit}.container", template.encode())
            run(*self.system, "daemon-reload")

    def compose(self, *args):
        return run(
            "docker",
            "compose",
            "--project-directory",
            self.base,
            "--env-file",
            self.private / "runtime.env",
            "-f",
            HERE / "compose.yaml",
            *args,
        )

    def stop(self):
        if self.engine == "docker":
            self.compose("stop", "-t", "20")
        else:
            run(
                *self.system,
                "stop",
                "postgres-gundem-web.service",
                "postgres-gundem-model.service",
            )

    def start(self, m):
        self.configure(m)
        if self.engine == "docker":
            self.compose("up", "-d", "web", "model")
        else:
            run(
                *self.system,
                "start",
                "postgres-gundem-model.service",
                "postgres-gundem-web.service",
            )

    def verify(self, m):
        for _ in range(120):
            try:
                for unit in ("web", "model"):
                    probe = ["python", "/app/container/probe.py", unit]
                    if unit == "web":
                        probe.append(m["tag"][1:])
                    if self.engine == "docker":
                        self.compose("exec", "-T", unit, *probe)
                    else:
                        run("podman", "exec", "postgres-gundem-" + unit, *probe)
                return
            except (OSError, subprocess.SubprocessError):
                time.sleep(2)
        raise ValueError("Panel, SQLite veya model sağlık kontrolünü geçemedi.")

    def snapshot(self):
        if self.db.is_symlink() or not self.db.is_file():
            raise ValueError("SQLite dosyası doğrulanamadı.")
        dst = self.private / "switch.sqlite"
        dst.unlink(missing_ok=True)
        with (
            contextlib.closing(
                sqlite3.connect(self.db.as_uri() + "?mode=ro", uri=True)
            ) as src,
            contextlib.closing(sqlite3.connect(dst)) as out,
        ):
            src.backup(out)
            if out.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("Yedek doğrulanamadı.")
        with dst.open("rb") as f:
            os.fsync(f.fileno())

    def restore(self, snapshot):
        # Both services are stopped. Preserve the outgoing SQLite files even if a
        # failed candidate left an unreadable database that cannot be backed up.
        if self.db.is_file():
            shelf = self.private / "geri-donus"
            shelf.mkdir(mode=0o700, exist_ok=True)
            saved = Path(
                tempfile.mkdtemp(
                    prefix=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-"),
                    dir=shelf,
                )
            )
            for suffix in ("", "-wal", "-journal"):
                src = self.db.with_name(self.db.name + suffix)
                if src.is_file() and not src.is_symlink():
                    dst = saved / src.name
                    try:
                        os.link(src, dst)
                    except OSError:
                        shutil.copyfile(src, dst)
                    with dst.open("rb") as archive:
                        os.fsync(archive.fileno())
            for directory in (saved, shelf, self.private):
                fd = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
        with tempfile.NamedTemporaryFile(dir=self.db.parent, delete=False) as f:
            tmp = Path(f.name)
            try:
                with snapshot.open("rb") as src:
                    shutil.copyfileobj(src, f)
                f.flush()
                os.fsync(f.fileno())
                os.fchown(f.fileno(), self.env["uid"], self.env["gid"])
                for ext in ("-wal", "-shm", "-journal"):
                    Path(str(self.db) + ext).unlink(missing_ok=True)
                os.replace(tmp, self.db)
            finally:
                tmp.unlink(missing_ok=True)

    def recover(self):
        t = read(self.tx)
        if not t:
            return
        old = t["old"]
        if t["phase"] == "committed":
            self.finish(t)
            return
        if t["phase"] == "switch":
            self.stop()
            if old:
                self.restore(self.private / "switch.sqlite")
        if old:
            self.start(old)
            self.verify(old)
            self.discard(t["new"], [old, read(self.private / "previous.json")])
        self.tx.unlink()
        self.message(
            busy=False,
            message="Önceki sürüme dönüldü." if old else "İlk kurulum tamamlanamadı.",
        )

    def discard(self, unused, retained):
        if not unused or any(
            entry and entry["tag"] == unused["tag"] for entry in retained
        ):
            return
        refs = [self.local_tag(unused), f"{REGISTRY}:{unused['tag']}-{self.arch}"]
        if all(
            not entry or entry["image"].get("digest") != unused["image"].get("digest")
            for entry in retained
        ):
            if unused["image"].get("digest"):
                refs.append(REGISTRY + "@" + unused["image"]["digest"])
        for ref in refs:
            with contextlib.suppress(OSError, subprocess.SubprocessError):
                run(self.engine, "image", "rm", ref)

    def finish(self, t):
        save(self.active, t["new"])
        if t["old"]:
            older = read(self.private / "previous.json")
            previous_db = self.private / "switch.sqlite"
            if previous_db.exists():
                os.replace(previous_db, self.private / "previous.sqlite")
            save(self.private / "previous.json", t["old"])
            self.discard(older, [t["new"], t["old"]])
        self.message(
            available=None,
            notes="",
            busy=False,
            bytes=0,
            message="Sürüm çalışıyor: " + t["new"]["tag"],
        )
        self.tx.unlink(missing_ok=True)

    def apply(self, m, *, rollback=False):
        old = read(self.active)
        if old and not rollback and number(m["tag"]) <= number(old["tag"]):
            raise ValueError("Sürüm zaten güncel.")
        self.message(busy=True, message="İmaj ve yerel model doğrulanıyor.")
        self.stage(m)
        t = dict(phase="prepare", old=old, new=m)
        save(self.tx, t)
        try:
            if old:
                self.stop()
                self.snapshot()
            self.configure(m)
            t["phase"] = "switch"
            save(self.tx, t)
            if rollback:
                self.restore(self.private / "previous.sqlite")
            self.start(m)
            self.verify(m)
            t["phase"] = "committed"
            save(self.tx, t)
            self.finish(t)
        except BaseException:
            self.recover()
            raise

    def watch(self):
        next_check = 0
        while True:
            try:
                self.recover()
                queue = self.base / "requests"
                jobs = sorted(queue.iterdir(), key=lambda p: p.name)
                command = next(
                    (
                        p
                        for p in jobs
                        if p.name == "check" or re.fullmatch("apply-" + TAG, p.name)
                    ),
                    None,
                )
                if command:
                    if command.is_symlink() or not command.is_dir():
                        command.unlink()
                    else:
                        command.rmdir()
                if command or time.monotonic() >= next_check:
                    next_check = time.monotonic() + 3600
                    new = self.check()
                    if command and command.name == "apply-" + new["tag"]:
                        self.apply(new)
            except Exception as exc:
                logging.warning("Güncelleme: %s", exc)
                self.message(
                    busy=False, message="İşlem tamamlanamadı. " + str(exc)[:240]
                )
                time.sleep(5)
            time.sleep(3)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "operation", choices=("install", "watch", "rollback", "recover")
    )
    parser.add_argument("tag", nargs="?")
    args = parser.parse_args()
    manager = Manager(os.environ["PG_ROOT"])
    with (manager.private / "lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        manager.recover()
        if args.operation == "watch":
            manager.watch()
        elif args.operation == "install":
            manager.apply(manifest(args.tag, manager.arch))
        elif args.operation == "rollback":
            previous = read(manager.private / "previous.json")
            if not previous:
                sys.exit("Önceki sürüm yok.")
            manager.apply(previous, rollback=True)
