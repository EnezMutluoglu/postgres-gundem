#!/usr/bin/env bash
# Hetzner'deki mevcut Docker ve Cloudflare Tunnel ile temiz kurulum.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Root oturumunda çalıştırın.' >&2; exit 1; }
docker info >/dev/null
docker compose version >/dev/null

tag=v1.1.3
export PG_ROOT=/srv/postgres-gundem
install_panel() {
  local dir=/root/postgres-gundem-kurulum/$tag
  local model file unit digest
  local -a args=() legacy=() active=()
  mkdir -p "$dir"
  cd "$dir"
  curl --fail --location --retry 3 --proto '=https' \
    "https://github.com/EnezMutluoglu/postgres-gundem/releases/download/$tag/kurulum.tar.gz" -o kurulum.tar.gz
  echo '4287553a9a8569093776716223a5a99252e9cd9c3d8b658e475d648f9c4f0c13  kurulum.tar.gz' | sha256sum -c -
  tar -xzf kurulum.tar.gz
  cd container

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
  docker start postgres-gundem-model-1 postgres-gundem-web-1 postgres-gundem-updater >/dev/null
else
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
