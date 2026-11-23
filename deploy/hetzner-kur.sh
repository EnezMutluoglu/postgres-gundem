#!/usr/bin/env bash
# Hetzner'deki mevcut Docker ve Cloudflare Tunnel ile temiz kurulum.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Root oturumunda çalıştırın.' >&2; exit 1; }
docker info >/dev/null
docker compose version >/dev/null

tag=v1.2.0
bundle=kurulum.tar.gz
package_sha=3c6e3d2205e6fae4acb2c9462000387502605ff4f4248ac133795140a16ed4db
export PG_ROOT=/srv/postgres-gundem
mode=${1:-kur}
[[ $mode == kur || $mode == --sadece-guncelleyici ]] || { echo 'Kullanım: bash postgres-gundem-kur.sh [--sadece-guncelleyici]' >&2; exit 1; }
dir=/root/postgres-gundem-kurulum/$tag/manuel
mkdir -p "$dir"
cd "$dir"
curl --fail --location --retry 3 --proto '=https' \
  "https://github.com/EnezMutluoglu/postgres-gundem/releases/download/$tag/$bundle" -o kurulum.tar.gz
printf '%s  kurulum.tar.gz\n' "$package_sha" | sha256sum -c -
tar -xzf kurulum.tar.gz
cd container

install_panel() {
  local model file unit digest
  local -a args=() legacy=() active=()

  model=$(python3 -c 'import json; print(json.load(open("model.json"))["file"])')
  digest=$(python3 -c 'import json; print(json.load(open("model.json"))["sha256"])')
  for file in /root/"$model" /root/docker-v*/"$model" /opt/postgres-gundem/models/"$model"; do
    if [[ -f $file ]] && printf '%s  %s\n' "$digest" "$file" | sha256sum -c --status; then
      args=("$file")
      break
    fi
  done
  bash get-model.sh "${args[@]}"

  for unit in postgres-gundem.service postgres-gundem-model.service; do
    if [[ $(systemctl show -p WorkingDirectory --value "$unit" 2>/dev/null) == /opt/postgres-gundem ]]; then legacy+=("$unit"); fi
  done
  if ((${#legacy[@]})) && systemctl cat postgres-gundem-arsiv.timer >/dev/null 2>&1; then
    legacy+=(postgres-gundem-arsiv.timer)
  fi
  for unit in "${legacy[@]}"; do
    if systemctl is-active --quiet "$unit"; then active+=("$unit"); fi
  done
  if ((${#active[@]})); then systemctl stop "${active[@]}"; fi
  if ! bash install.sh docker; then
    if ((${#active[@]})); then systemctl start "${active[@]}"; fi
    return 1
  fi
  if ((${#legacy[@]})); then systemctl disable "${legacy[@]}"; fi
}

if [[ -s $PG_ROOT/manager/active.json ]] &&
   [[ $(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' postgres-gundem-web-1 2>/dev/null) == "$PG_ROOT" ]]; then
  updater=postgres-gundem-updater
  target=$PG_ROOT/controller/controller.py
  [[ $(docker inspect -f '{{index .Config.Labels "net.postgres-gundem.root"}}' "$updater") == "$PG_ROOT" ]]
  if ! cmp -s controller.py "$target" || [[ $mode == --sadece-guncelleyici ]]; then
    current=$(sha256sum "$target")
    case "${current%% *}" in
      ec3066fef8dffe275a71ed54c55a407515f6493c249c2dd15cbb261c58381c1a|a281874372c0304d1f49465d0c1f7d26ff1376fd5ac5f3173fdd2aeaacde1334) ;;
      *) cmp -s controller.py "$target" || { echo 'Kurulu güncelleyici farklı bir sürüme ait.' >&2; exit 1; } ;;
    esac
    python3 - "$PG_ROOT" <<'PY'
import json, sys
from pathlib import Path
base = Path(sys.argv[1])
status = base / "status/status.json"
if (base / "manager/transaction.json").exists() or (status.is_file() and json.loads(status.read_text()).get("busy")):
    raise SystemExit("Devam eden sürüm işlemi bittiğinde komutu yeniden çalıştırın.")
PY
    tmp=$(mktemp "$PG_ROOT/controller/.controller.XXXXXXXX")
    trap 'rm -f -- "$tmp"' EXIT
    install -m 644 controller.py "$tmp"
    mv -fT -- "$tmp" "$target"
    docker restart "$updater" >/dev/null
  fi
  echo 'Panel sürümü artık yönetici isteğiyle denetlenir.'
  if [[ $mode == --sadece-guncelleyici ]]; then exit 0; fi
  helper=$PG_ROOT/controller/admin-password.py
  if printf '%s  %s\n' 2cc374024ddcbe2a41c620aa180e253ac2705838f554dd69e61b882faa75ab8a "$helper" | sha256sum -c --status; then
    install -m 700 admin-password.py "$helper"
  fi
  docker start postgres-gundem-model-1 postgres-gundem-web-1 postgres-gundem-updater >/dev/null
else
  if [[ $mode == --sadece-guncelleyici ]]; then echo 'Kurulu Docker paneli bulunamadı. İlk kurulum için betiği parametresiz çalıştırın.' >&2; exit 1; fi
  install_panel
fi

if [[ -n ${CLOUDFLARED_CONTAINER:-} ]]; then
  tunnel=$CLOUDFLARED_CONTAINER
else
  running=$(docker ps --format '{{.Names}} {{.Image}}')
  mapfile -t tunnels < <(awk '$2 ~ /(^|\/)cloudflare\/cloudflared([:@]|$)/ {print $1}' <<<"$running")
  if ((${#tunnels[@]} != 1)); then
    echo 'Panel kuruldu. Mevcut tünelin konteynerini aşağıdaki listeden seçin.'
    echo "$running"
    echo 'Ardından CLOUDFLARED_CONTAINER=KONTEYNER_ADI bash /root/postgres-gundem-kur.sh çalıştırın.'
    exit 1
  fi
  tunnel=${tunnels[0]}
fi
owner=$tunnel
while :; do
  mode=$(docker inspect --type container -f '{{.HostConfig.NetworkMode}}' "$owner")
  case "$mode" in
    container:*) owner=${mode#container:} ;;
    host|none) echo "$tunnel konteynerinin ağ modu $mode. Tüneli postgres-gundem-origin adlı Docker ağına bağlanabilen bir konteynerde çalıştırın." >&2; exit 1 ;;
    *) break ;;
  esac
done
network=postgres-gundem-origin
connected=$(docker inspect -f '{{if index .NetworkSettings.Networks "postgres-gundem-origin"}}yes{{end}}' "$owner")
if [[ $connected != yes ]]; then
  priority=()
  if docker network connect --help | grep -q -- '--gw-priority'; then priority=(--gw-priority=-1); fi
  docker network connect "${priority[@]}" "$network" "$owner"
fi
image=$(docker inspect --type container -f '{{.Image}}' postgres-gundem-web-1)
docker run --rm --network "container:$tunnel" "$image" python -c '
import json, time
from urllib.request import urlopen
for attempt in range(10):
    try:
        with urlopen("http://postgres-gundem:8080/health/ready", timeout=4) as response:
            if json.load(response).get("status") == "ok":
                print("Tünelden panele HTTP 200")
                break
    except OSError:
        pass
    time.sleep(1)
else:
    raise SystemExit("Tünel konteynerinden panelin sağlık adresine ulaşılamadı.")
'
echo 'Cloudflare rotası: posthaber.bspteam.net | Type: HTTP | URL: postgres-gundem:8080'
