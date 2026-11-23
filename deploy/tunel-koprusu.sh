#!/usr/bin/env bash
set -euo pipefail

fail() { echo "$*" >&2; exit 1; }
[[ $EUID == 0 ]] || fail 'Sunucuda root olarak çalıştırın.'
http_code() { "$@" --noproxy '*' -sS -o /dev/null --max-time 5 -w '%{http_code}'; }
origin=http://127.0.0.1:8080/
[[ $(http_code curl "$origin") == 200 ]] || fail "Panel $origin adresinde HTTP 200 vermedi."

mapfile -t pids < <(pgrep -x cloudflared || true)
if [[ $# == 1 ]]; then
  pid=$1
  [[ $pid =~ ^[0-9]+$ && $(cat "/proc/$pid/comm") == cloudflared ]] || fail 'Geçerli bir cloudflared PID değeri girin.'
elif [[ $# == 0 && ${#pids[@]} == 1 ]]; then
  pid=${pids[0]}
else
  fail "cloudflared işlemleri: ${pids[*]:-yok}. Tünelin PID değeriyle çalıştırın: bash $0 PID"
fi
net=(nsenter -t "$pid" -n)
if [[ $(readlink "/proc/$pid/ns/net") == "$(readlink /proc/self/ns/net)" ]]; then
  echo "Tünel sunucuyla aynı ağı kullanıyor. Service URL: ${origin%/}"
  exit 0
fi

gw=$("${net[@]}" ip -4 route show default | awk '$2=="via" && !found {print $3; found=1}')
bridge=$(ip -o -4 addr show | awk -v gw="$gw" '{split($4, a, "/"); if (a[1]==gw) print $2}')
[[ $gw =~ ^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.) && $bridge =~ ^[a-zA-Z0-9_.-]+$ && -d /sys/class/net/$bridge/bridge ]] ||
  fail "Özel ağ geçidi yerel bir Linux köprüsüyle eşleşmedi. Ağ geçidi: ${gw:-yok}, arayüz: ${bridge:-yok}. Ayar yapılmadı."
proxy=/lib/systemd/systemd-socket-proxyd
[[ -x $proxy ]] || fail "Debian'ın $proxy dosyası bulunamadı."

# The bridge device triggers the socket when Docker creates it, including after a reboot.
unit=postgres-gundem-tunel
device=$(systemd-escape --path --suffix=device "/sys/subsystem/net/devices/$bridge")
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
cat >"$work/$unit.socket" <<EOF
[Socket]
ListenStream=$gw:18080
BindToDevice=$bridge
FreeBind=yes

[Install]
WantedBy=$device
EOF
cat >"$work/$unit.service" <<EOF
[Unit]
PartOf=$unit.socket

[Service]
ExecStart=$proxy 127.0.0.1:8080
DynamicUser=yes
NoNewPrivileges=yes
EOF
dir=/etc/systemd/system
if ! cmp -s "$work/$unit.socket" "$dir/$unit.socket" || ! cmp -s "$work/$unit.service" "$dir/$unit.service"; then
  if [[ -f $dir/$unit.socket ]]; then
    systemctl disable --now "$unit.socket"
  fi
  install -m 644 "$work/$unit.socket" "$work/$unit.service" "$dir/"
  systemctl daemon-reload
fi
systemctl start "$unit.socket"
url=http://$gw:18080
if [[ $(http_code "${net[@]}" curl "$url/") != 200 ]]; then
  systemctl disable --now "$unit.socket"
  fail "Tünel $url adresinden HTTP 200 alamadı. Köprü dinleyicisi durduruldu."
fi
systemctl --quiet enable "$unit.socket"
printf 'Tünelden panele: HTTP 200\nCloudflare Type: HTTP\nCloudflare URL: %s:18080\nService URL: %s\n' "$gw" "$url"
