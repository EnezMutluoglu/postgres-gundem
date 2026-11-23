"""Move immutable monthly news archives after checking the copy on the destination disk."""

import argparse
import contextlib
import gzip
import hashlib
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def transfer(source, destination, move=False):
    source, destination = source.resolve(strict=True), destination.resolve(strict=True)
    if source == destination:
        raise ValueError("Hedef ve kaynak aynı dizin.")
    if move and source.stat().st_dev == destination.stat().st_dev:
        raise ValueError(
            "Taşıma için hedef diski bağlayın. Aynı dosya sisteminde ön kopya alabilirsiniz."
        )
    for src in sorted(source.glob("gundem-*.sqlite.gz")):
        match = re.fullmatch(r"gundem-(\d{4}-(?:0[1-9]|1[0-2]))\.sqlite\.gz", src.name)
        if not match or src.is_symlink() or not src.is_file():
            continue
        dest = destination / src.name
        if dest.is_symlink():
            raise ValueError("Hedef simgesel bağlantı: " + str(dest))
        sha = digest(src)
        # Keep temporary compressed and expanded copies on the destination device.
        with tempfile.TemporaryDirectory(dir=destination) as tmp:
            staged = Path(tmp) / "arsiv.gz"
            if not dest.exists():
                with src.open("rb") as inp, staged.open("xb") as out:
                    shutil.copyfileobj(inp, out)
                    out.flush()
                    os.fsync(out.fileno())
            checked = dest if dest.exists() else staged
            if digest(checked) != sha:
                raise ValueError("Hedef özeti uyuşmadı: " + str(dest))
            db = Path(tmp) / "kontrol.sqlite"
            with gzip.open(checked, "rb") as inp, db.open("wb") as out:
                shutil.copyfileobj(inp, out)
            with contextlib.closing(
                sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
            ) as con:
                if con.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("SQLite denetimi başarısız.")
                con.execute("SELECT 1 FROM items LIMIT 1")
            if checked == staged:
                os.link(staged, dest)
            sync_directory(destination)
            if move:
                if dest.is_symlink() or digest(dest) != sha or digest(src) != sha:
                    raise ValueError("Arşiv işlem sırasında değişti.")
                marker = source / (".tasindi-" + match[1])
                with marker.open("w") as note:
                    note.write(sha + "  " + str(dest) + "\n")
                    note.flush()
                    os.fsync(note.fileno())
                sync_directory(source)
                src.unlink()
                sync_directory(source)
        print("Taşındı" if move else "Kopya doğrulandı", dest, sha, flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Aylık haber arşivlerinin doğrulanmış kopyasını alın."
    )
    parser.add_argument("hedef", type=Path)
    parser.add_argument(
        "--kaynak", type=Path, default=Path("/srv/postgres-gundem/arsiv")
    )
    parser.add_argument(
        "--tasi",
        action="store_true",
        help="Hedefte SHA-256, gzip ve SQLite doğrulandıktan sonra yerel arşiv kopyasını kaldır.",
    )
    args = parser.parse_args()
    transfer(args.kaynak, args.hedef, args.tasi)
