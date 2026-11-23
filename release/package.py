"""Build and verify a model-inclusive Debian archive. Requires Python 3.11+."""

import argparse
import hashlib
import io
import os
import struct
import tarfile
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL = "Riva-Translate-4B-Instruct-v2-Q4_K_M.gguf"
MODEL_SHA = "90c2f48ff5549b770d9aaecb7eea603548bcca035a970a800d9c17781991804d"
ENGINE_PREFIX = "llama-b12532"
ELF_MACHINE = {"amd64": 62, "arm64": 183}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def publish(source, destination):
    # On Windows a virus scanner can still be reading a just-closed, multi-GB tar.
    for attempt in range(31):
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == 30:
                raise
            time.sleep(1)


def package(arch, engine, model, output):
    engine_name = f"{ENGINE_PREFIX}-bin-debian12-{arch}.tar.gz"
    with tarfile.open(engine, "r:gz") as nested:
        programs = ("llama-server", "llama-server-avx2") if arch == "amd64" else ("llama-server",)
        for program in programs:
            executable = nested.getmember(f"{ENGINE_PREFIX}/{program}")
            if not executable.isfile() or not executable.mode & 0o111:
                raise ValueError(f"Çalıştırılabilir dosya bulunamadı: {program}")
            with nested.extractfile(executable) as binary:
                header = binary.read(20)
            if len(header) != 20 or header[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", header, 18)[0] != ELF_MACHINE[arch]:
                raise ValueError(f"Motorun ELF mimarisi uyuşmuyor: {arch}")
        nested.getmember(f"{ENGINE_PREFIX}/LICENSE")

    required = (
        "README.md", "install.sh", "app.py", "admin.py", "VERSION", "feeds.py", "community.py", "translation_jobs.py", "news_search.py", "templates/archive-search.html", "templates/maintenance.html", "archive.py", "turkish.json",
        "requirements.txt", "static/index.html", "deploy/tunel-koprusu.sh",
        "deploy/postgres-gundem.service", "deploy/postgres-gundem-model.service",
        "deploy/postgres-gundem-arsiv.service", "deploy/postgres-gundem-arsiv.timer",
        "licenses/NVIDIA-Open-Model-License.txt", "release/build-engine.sh", "release/package.py",
    )
    paths = {name: ROOT / name for name in required}
    for directory, pattern in (("licenses", "*"), ("static", "**/*"), ("tests", "test_*.py")):
        for path in (ROOT / directory).glob(pattern):
            if path.is_file():
                paths[path.relative_to(ROOT).as_posix()] = path
    paths[f".runtime/{MODEL}"] = model
    paths[f".runtime/{engine_name}"] = engine
    expected = {name: MODEL_SHA if name == f".runtime/{MODEL}" else digest(path) for name, path in paths.items()}
    metadata = {".runtime/MIMARI": f"{arch}\n".encode(), f".runtime/{engine_name}.sha256": (expected[f".runtime/{engine_name}"] + "\n").encode()}
    expected.update({name: hashlib.sha256(raw).hexdigest() for name, raw in metadata.items()})

    output.mkdir(parents=True, exist_ok=True)
    name = f"postgres-gundem-debian12-13-{arch}.tar"
    with tempfile.TemporaryDirectory(dir=output) as work:
        staged = Path(work) / name
        with tarfile.open(staged, "w:") as archive:
            for member in sorted(expected):
                info = tarfile.TarInfo("postgres-gundem/" + member)
                info.mode = 0o755 if member.endswith(".sh") else 0o644
                if member in metadata:
                    info.size = len(metadata[member])
                    archive.addfile(info, io.BytesIO(metadata[member]))
                else:
                    info.size = paths[member].stat().st_size
                    with paths[member].open("rb") as stream:
                        archive.addfile(info, stream)
        with tarfile.open(staged, "r:") as archive:
            if archive.getnames() != ["postgres-gundem/" + n for n in sorted(expected)]:
                raise ValueError("Arşiv içeriği uyuşmuyor.")
            for member, want in expected.items():
                with archive.extractfile("postgres-gundem/" + member) as stream:
                    if hashlib.file_digest(stream, "sha256").hexdigest() != want:
                        raise ValueError(f"SHA-256 uyuşmuyor: {member}")
        sha = digest(staged)
        sidecar = Path(work) / (name + ".sha256")
        sidecar.write_bytes(f"{sha}  {name}\n".encode("ascii"))
        publish(staged, output / name)
        publish(sidecar, output / sidecar.name)
    print(f"{name}: {(output / name).stat().st_size} bytes, SHA-256 {sha}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arch", choices=("amd64", "arm64"))
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--model", type=Path, default=ROOT / ".runtime" / MODEL)
    parser.add_argument("--output", type=Path, default=ROOT / "paket")
    args = parser.parse_args()
    package(args.arch, args.engine, args.model, args.output)
