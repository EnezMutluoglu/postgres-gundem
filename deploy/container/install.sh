#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
engine=${1:-docker}
[[ $engine == docker || $engine == podman ]] || { echo 'Kullanım: bash install.sh docker|podman'; exit 2; }
command -v "$engine" >/dev/null
command -v openssl >/dev/null
python3 -c 'import sys; assert sys.version_info >= (3,9), "Python 3.9+"'
rootless=false
uid=10001
gid=10001
base=${PG_ROOT:-/srv/postgres-gundem}
units=/etc/containers/systemd
system=(systemctl)
svc=/etc/systemd/system
if ((EUID!=0)); then
  [[ $engine == podman ]] || { echo 'Docker kurulumunu root olarak çalıştırın.'; exit 1; }
  rootless=true; uid=$(id -u); gid=$(id -g)
  base=${PG_ROOT:-$HOME/.local/share/postgres-gundem}
  units=${XDG_CONFIG_HOME:-$HOME/.config}/containers/systemd
  svc=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
  system=(systemctl --user)
  [[ $(loginctl show-user "$USER" -p Linger --value) == yes ]] || { echo "Önce yönetici olarak loginctl enable-linger $USER çalıştırın."; exit 1; }
fi
[[ $base =~ ^/[a-zA-Z0-9_./-]+$ && $base == "$(realpath -m "$base")" && $base != / ]] || { echo 'Geçersiz kurulum yolu.'; exit 1; }
export PG_ROOT=$base
mkdir -p "$base"/{models,data,arsiv,config,status,requests,manager,controller}
exec 9>"$base/manager/install.lock"
flock -n 9 || { echo 'Başka bir kurulum çalışıyor.'; exit 1; }
tag=v$(cat VERSION)
installed=false
if [[ -s $base/manager/active.json ]]; then
  python3 - "$base" "$engine" "$tag" <<'PY'
import json, pathlib, sys
base=pathlib.Path(sys.argv[1])
if json.loads((base/'settings.json').read_text())['engine'] != sys.argv[2] or json.loads((base/'manager/active.json').read_text())['tag'] != sys.argv[3]:
    sys.exit("Mevcut kurulum farklı. Yeni sürümlere Ayarlar üzerinden geçin.")
PY
  installed=true
fi
if [[ $engine == docker ]]; then
  docker compose version >/dev/null
  while read -r id; do
    [[ -z $id ]] && continue
    owner=$(docker inspect -f '{{ index .Config.Labels "com.docker.compose.project.working_dir" }}' "$id")
    [[ $owner == "$base" ]] || { echo "postgres-gundem Compose projesi başka bir dizinde çalışıyor: $owner"; exit 1; }
  done < <(docker ps -aq --filter label=com.docker.compose.project=postgres-gundem)
else
  "$engine" info >/dev/null
  [[ -x /usr/lib/systemd/system-generators/podman-system-generator || -x /usr/libexec/podman/quadlet || -x /usr/lib/podman/quadlet ]] || { echo 'Podman Quadlet desteği gerekli.'; exit 1; }
  mkdir -p "$units" "$svc"
  [[ ! -e $svc/postgres-gundem-model.service ]] || { echo 'Aynı adlı yerel model servisi var. Önce eski kurulumu kaldırın.'; exit 1; }
  for name in postgres-gundem-model postgres-gundem-web; do
    if podman container exists "$name"; then
      owner=$(podman inspect -f '{{ index .Config.Labels "net.postgres-gundem.root" }}' "$name")
      [[ $owner == "$base" ]] || { echo "$name başka bir kuruluma ait."; exit 1; }
    fi
  done
fi
test -f "$base/models/$(python3 -c 'import json; print(json.load(open("model.json"))["file"])')" || { echo 'Önce bash get-model.sh ile yerel modeli hazırlayın.'; exit 1; }
install -m 644 controller.py release.pub compose.yaml *.container "$base/controller/"
chmod 700 "$base/manager"; chmod 755 "$base" "$base/status"
chown "$uid:$gid" "$base/data" "$base/arsiv" "$base/requests"
chmod 700 "$base/data" "$base/arsiv" "$base/requests"
. /etc/os-release
python3 - "$base" "$engine" "$rootless" "$uid" "$gid" "$units" "$PRETTY_NAME" <<'PY'
import json, pathlib, sys, os
base,engine,less,uid,gid,units,system=sys.argv[1:]
p=pathlib.Path(base)
(p/'settings.json').write_text(json.dumps(dict(engine=engine,rootless=less=='true',uid=int(uid),gid=int(gid),quadlets=units,platform=system)))
PY
install -m 700 admin-password.py arsiv-tasi.py "$base/controller/"
if [[ ! -s $base/config/admin.json ]]; then python3 "$base/controller/admin-password.py"; fi
if ! "$engine" network inspect postgres-gundem-origin >/dev/null 2>&1; then "$engine" network create postgres-gundem-origin >/dev/null; fi
if [[ $engine == podman ]] && ! podman network exists postgres-gundem-private; then podman network create --internal postgres-gundem-private; fi
if [[ $installed == false ]]; then python3 "$base/controller/controller.py" install "$tag"; fi
if [[ $engine == docker ]]; then
  img=$(sed -n 's/^PG_IMAGE=//p' "$base/manager/runtime.env")
  if docker container inspect postgres-gundem-updater >/dev/null 2>&1; then
    owner=$(docker inspect -f '{{ index .Config.Labels "net.postgres-gundem.root" }}' postgres-gundem-updater)
    [[ $owner == "$base" ]] || { echo 'Güncelleyici adı başka kuruluma ait.'; exit 1; }
    docker start postgres-gundem-updater >/dev/null
  else
  docker run -d --name postgres-gundem-updater --restart unless-stopped --user 0:0 \
    --label "net.postgres-gundem.root=$base" \
    --read-only --tmpfs /tmp:rw,noexec,nosuid,size=32m --security-opt label=disable \
    -v /var/run/docker.sock:/var/run/docker.sock -v "$base:$base" -e PG_ROOT="$base" \
    --no-healthcheck "$img" python "$base/controller/controller.py" watch >/dev/null
  fi
else
  cat >"$svc/postgres-gundem-updater.service" <<EOF
[Unit]
Description=Postgres Gündem imzalı sürüm denetimi
After=network-online.target
[Service]
Environment=PG_ROOT=$base
ExecStart=/usr/bin/python3 $base/controller/controller.py watch
Restart=always
RestartSec=5
[Install]
WantedBy=default.target
EOF
  "${system[@]}" daemon-reload
  "${system[@]}" enable --now postgres-gundem-updater.service
fi
echo 'Panel ve yerel model hazır. Cloudflare hizmet adresi http://postgres-gundem:8080'

