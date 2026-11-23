#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
base=${PG_ROOT:-/srv/postgres-gundem}
if ((EUID!=0)); then base=${PG_ROOT:-$HOME/.local/share/postgres-gundem}; fi
mkdir -p "$base/models"
readarray -t fields < <(python3 -c 'import json; m=json.load(open("model.json")); print(m["file"],m["sha256"],m["url"],m["license"],sep="\n")')
dest="$base/models/${fields[0]}"
verify(){ printf '%s  %s\n' "${fields[1]}" "$1" | sha256sum -c --status; }
if [[ -f $dest ]] && verify "$dest"; then echo 'Yerel model doğrulandı.'; exit; fi
echo "Model lisansı: ${fields[3]}"
tmp=$(mktemp "$base/models/.indir.XXXXXXXX")
trap 'rm -f -- "$tmp"' EXIT
if [[ $# -eq 1 ]]; then cp -- "$1" "$tmp"
else curl -fL --retry 3 --proto '=https' "${fields[2]}" -o "$tmp"; fi
verify "$tmp" || { echo 'Model özeti uyuşmadı.' >&2; exit 1; }
chmod 644 "$tmp"
mv -f -- "$tmp" "$dest"
echo "Model hazır: $dest"

