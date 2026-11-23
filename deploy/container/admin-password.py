"""Reset the local admin password from the host, invalidating existing sessions."""

import getpass
import hashlib
import json
import os
import secrets
import tempfile
from pathlib import Path

base = Path(os.environ.get("PG_ROOT") or Path(__file__).resolve().parents[1])
cfg = json.loads((base / "settings.json").read_text())
min_length = 6
pw = getpass.getpass(f"Yeni yönetici parolası (en az {min_length} karakter): ")
if not min_length <= len(pw) <= 512:
    raise SystemExit(
        f"Yönetici parolası {min_length} ile 512 karakter arasında olmalı."
    )
if pw != getpass.getpass("Parolayı tekrar girin: "):
    raise SystemExit("Girilen parolalar eşleşmiyor.")
salt = secrets.token_hex(16)
value = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 1000000).hex()
auth = {
    "secret": secrets.token_hex(32),
    "password": f"pbkdf2:sha256:1000000${salt}${value}",
}
with tempfile.NamedTemporaryFile(mode="w", dir=base / "config", delete=False) as out:
    json.dump(auth, out)
    out.flush()
    os.fsync(out.fileno())
    os.chown(out.name, cfg["uid"], cfg["gid"])
    os.replace(out.name, base / "config/admin.json")
print("Parola kaydedildi. Çalışan paneli yeniden başlattığınızda etkinleşir.")
