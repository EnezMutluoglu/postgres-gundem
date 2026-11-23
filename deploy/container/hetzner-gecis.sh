#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
[[ $EUID == 0 ]] || { echo 'Root olarak çalıştırın.'; exit 1; }
export PG_ROOT=/srv/postgres-gundem
legacy=/var/lib/postgres-gundem
[[ -f $legacy/gundem.sqlite ]] || { echo 'Eski veritabanı bulunamadı. Temiz kurulum için install.sh docker kullanın.'; exit 1; }
docker compose version >/dev/null
mkdir -p "$PG_ROOT"/{data,arsiv,manager}
exec 8>"$PG_ROOT/manager/gecis.lock"
flock -n 8 || { echo 'Başka bir geçiş çalışıyor.'; exit 1; }
[[ ! -e $PG_ROOT/data/gundem.sqlite && ! -e $PG_ROOT/manager/active.json ]] || {
  echo 'Hedefte veritabanı veya etkin kurulum var. Mevcut dosyalar korundu.'; exit 1; }
bash get-model.sh "$@"
units=(postgres-gundem-arsiv.timer postgres-gundem.service postgres-gundem-model.service)
active=()
for unit in "${units[@]}"; do
  if systemctl is-active --quiet "$unit"; then active+=("$unit"); fi
done
recover(){
  rc=$?
  if ((rc)); then
    if [[ -s $PG_ROOT/manager/runtime.env ]]; then
      docker compose --project-directory "$PG_ROOT" --env-file "$PG_ROOT/manager/runtime.env" -f "$PG_ROOT/controller/compose.yaml" stop || true
    fi
    if ((${#active[@]})); then systemctl start "${active[@]}" || true; fi
    echo 'Geçiş tamamlanamadı. Eski birimlerin ilk çalışma durumu geri yüklenmeye çalışıldı. Ayrıntılar için systemctl status postgres-gundem kullanın.' >&2
  fi
}
trap recover EXIT
if ((${#active[@]})); then systemctl stop "${active[@]}"; fi
python3 - "$legacy/gundem.sqlite" "$PG_ROOT/data" <<'PY'
import os, pathlib, sqlite3, sys, tempfile
from contextlib import closing
src, dest = map(pathlib.Path, sys.argv[1:])
with tempfile.NamedTemporaryFile(dir=dest) as tmp:
    with closing(sqlite3.connect(src.as_uri()+"?mode=ro", uri=True)) as old, closing(sqlite3.connect(tmp.name)) as new:
        old.backup(new)
        if new.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise SystemExit("SQLite kopyası doğrulanamadı.")
    os.chown(tmp.name, 10001, 10001)
    os.link(tmp.name, dest/"gundem.sqlite")
PY
shopt -s nullglob
for f in "$legacy"/arsiv/gundem-????-??.sqlite.gz; do
  if [[ -e $PG_ROOT/arsiv/${f##*/} ]]; then
    cmp -- "$f" "$PG_ROOT/arsiv/${f##*/}" || { echo 'Aynı aya ait iki farklı arşiv var. İki kopya da korundu.'; exit 1; }
    continue
  fi
  install -o 10001 -g 10001 -m 600 "$f" "$PG_ROOT/arsiv/"
done
bash install.sh docker
trap - EXIT
for unit in "${units[@]}"; do
  if systemctl is-enabled --quiet "$unit"; then systemctl disable "$unit"; fi
done
echo 'Eski dosyalar yerinde. Cloudflare bağlayıcısını postgres-gundem-origin ağına ekleyip rotayı http://postgres-gundem:8080 olarak değiştirin.'
