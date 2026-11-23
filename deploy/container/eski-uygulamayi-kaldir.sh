#!/bin/bash
# Eski systemd kurulumunu kaldırır. Docker'a geçişten önce veya sonra çalıştırılabilir.
set -euo pipefail
legacy=/opt/postgres-gundem
data=/var/lib/postgres-gundem
[[ $EUID == 0 ]] || { echo 'Root olarak çalıştırın.' >&2; exit 1; }
[[ -e $legacy ]] || { echo 'Eski uygulama dizini zaten kaldırılmış.'; exit 0; }
[[ $(systemctl show -p WorkingDirectory --value postgres-gundem.service) == "$legacy" &&
   $(realpath "$legacy") == "$legacy" && -f $legacy/app.py && -s $data/gundem.sqlite ]] ||
  { echo 'Eski systemd kurulumunu ve ayrı haber veritabanını doğrulayamadım.' >&2; exit 1; }
inside=$(find "$legacy" -type f \( -iname '*.sqlite*' -o -iname '*.db' -o -iname '*.db.gz' \) -print -quit)
[[ -z $inside ]] || { echo "Uygulama dizininde veri bulundu, işlem durdu: $inside" >&2; exit 1; }
python3 - "$data/gundem.sqlite" <<'PY'
import sqlite3, sys
from pathlib import Path
from contextlib import closing
with closing(sqlite3.connect(Path(sys.argv[1]).as_uri() + "?mode=ro", uri=True)) as con:
    if con.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
        raise SystemExit("Haber veritabanının bütünlük denetimi başarısız.")
    print("Korunan bülten kaydı:", con.execute("SELECT count(*) FROM items").fetchone()[0])
PY
du -sh -- "$legacy" "$data"
echo "Silinecek uygulama: $legacy"
echo "Haberler ve aylık arşivler: $data"
read -r -p 'Eski paneli durdurup uygulama dizinini kaldırmak için KALDIR yazın: ' answer
[[ $answer == KALDIR ]] || { echo 'İşlem iptal edildi.'; exit 0; }
for unit in postgres-gundem-arsiv.timer postgres-gundem-tunel.socket postgres-gundem.service postgres-gundem-model.service; do
  if systemctl cat "$unit" >/dev/null 2>&1; then systemctl disable --now "$unit"; fi
done
for unit in postgres-gundem-arsiv.service postgres-gundem-tunel.service; do
  if systemctl is-active --quiet "$unit"; then systemctl stop "$unit"; fi
done
rm -r --one-file-system -- "$legacy"
echo "Geçiş için hazır. Haber veritabanı: $data/gundem.sqlite"
