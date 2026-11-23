"""Assemble a signed multi-architecture release after native CI builds."""
import json
import sys
from pathlib import Path

out=Path(sys.argv[1])
tag=sys.argv[2]
if tag!="v"+Path("VERSION").read_text().strip():
    raise SystemExit("Sürüm etiketi VERSION ile uyuşmuyor.")
model=json.loads(Path("deploy/container/model.json").read_text())
notes=Path("release/notes.txt").read_text().strip()
images={arch:json.loads((out/f"image-{arch}.json").read_text()) for arch in ("amd64","arm64")}
(out/"release.json").write_text(json.dumps(dict(schema=1,controller_api=1,tag=tag,model=model,
                                               images=images,notes=notes),ensure_ascii=False,indent=2)+"\n")

