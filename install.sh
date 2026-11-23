#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID != 0 ]]; then echo 'Kurulum için sudo bash install.sh kullanın.' >&2; exit 1; fi
if [[ $# -gt 1 || (${1-} != '' && ${1-} != --paketten) ]]; then
  echo 'Kullanım: sudo bash install.sh [--paketten]' >&2; exit 2
fi
mode=${1-}
cd "$(dirname "$0")"
root=/opt/postgres-gundem
model=Riva-Translate-4B-Instruct-v2-Q4_K_M.gguf
revision=aa8cc2e72e2f97e07b021e4afbc612cff3bf9ae9
model_sha=90c2f48ff5549b770d9aaecb7eea603548bcca035a970a800d9c17781991804d
release=b12532
arch=$(uname -m)
bundled_engine=''
engine_program=llama-server
engine_id=$release
if [[ -f .runtime/MIMARI ]]; then
  target=$(<.runtime/MIMARI)
  host_arch=$(dpkg --print-architecture)
  if [[ $target != "$host_arch" || ( $target != amd64 && $target != arm64 ) ]]; then
    echo "Paket mimarisi $target, sistem mimarisi $host_arch. $host_arch paketini seçin." >&2
    exit 1
  fi
  bundled_engine="llama-$release-bin-debian12-$target.tar.gz"
  engine_sha=$(<".runtime/$bundled_engine.sha256")
  [[ $engine_sha =~ ^[0-9a-f]{64}$ && -f ".runtime/$bundled_engine" ]] || { echo 'Paketin çeviri motoru veya doğrulama özeti eksik.' >&2; exit 1; }
  if [[ $target == amd64 ]]; then
    cpu_flags=" $(awk -F ': ' '/^flags[[:space:]]*:/ {print $2; exit}' /proc/cpuinfo) "
    engine_program=llama-server-avx2
    for flag in sse4_2 avx avx2 f16c fma bmi2; do
      if [[ $cpu_flags != *" $flag "* ]]; then engine_program=llama-server; break; fi
    done
  fi
  engine_id="$release-$target-$engine_sha-$engine_program"
  mode=--paketten
fi
arm_asset="llama-$release-bin-ubuntu-arm64.tar.gz"
arm_sha=47650d39565de64a76aa78e54269b70f71bde1d5139f46b32f4eb5212da2a823
arm_url="https://github.com/ggml-org/llama.cpp/releases/download/$release/$arm_asset"
bookworm_asset="llama-$release-bin-debian12-arm64.tar.gz"
if [[ -f ".runtime/$bookworm_asset" ]]; then
  arm_asset=$bookworm_asset
  arm_sha=c917c6edecc7899ec8b9ac6cf024432cc73e15636a6fe0661cf3dbc6931c4e9a
  arm_url=''
elif [[ -z $bundled_engine && $arch == aarch64 ]] && ( . /etc/os-release && [[ $ID == debian && ${VERSION_ID:-} == 12 ]] ); then
  echo 'Debian 12 ARM64 için postgres-gundem-debian12-arm64-onarim.tar.gz paketindeki kurucuyu kullanın.' >&2
  exit 1
fi
if [[ -f ".runtime/$arm_asset" && ! -f ".runtime/llama-$release-source.tar.gz" && $arch != aarch64 ]]; then
  echo 'Bu paket 64 bit ARM içindir. Debian mimarisini dpkg --print-architecture ile kontrol edin.' >&2
  exit 1
fi
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
exec 9>/run/lock/postgres-gundem-kurulum.lock
flock 9

verify() { [[ -f "$2" ]] && printf '%s  %s\n' "$1" "$2" | sha256sum --check --status; }
stage_asset() {
  local name=$1 target=$2 url=$3
  if [[ -f ".runtime/$name" ]]; then
    echo "Paketten kopyalanıyor: $name"
    install -m 644 ".runtime/$name" "$target"
  elif [[ $mode == --paketten || -z $url ]]; then
    echo "Paket dosyası eksik: .runtime/$name. Arşivin SHA-256 özetini kontrol edip yeniden açın." >&2
    return 1
  else
    echo "İndiriliyor: $name"
    curl --fail --location --retry 3 --silent --show-error "$url" --output "$target"
  fi
}

apt-get update -qq
runtime_packages=(ca-certificates curl python3-venv libgomp1)
if [[ -n $bundled_engine ]]; then runtime_packages+=(iproute2 procps); fi
apt-get install -y --no-install-recommends "${runtime_packages[@]}"
install -d -m 755 "$root/models" "$root/llama"
if ! verify "$model_sha" "$root/models/$model"; then
  stage_asset "$model" "$root/models/$model.partial" "https://huggingface.co/liodon-ai/Riva-Translate-4B-Instruct-v2-imatrix-GGUF/resolve/$revision/$model"
  verify "$model_sha" "$root/models/$model.partial" || { echo 'Model dosyasının SHA-256 özeti eşleşmedi.' >&2; exit 1; }
  chmod 644 "$root/models/$model.partial"
  mv "$root/models/$model.partial" "$root/models/$model"
fi

if [[ -n $bundled_engine ]]; then
  verify "$engine_sha" ".runtime/$bundled_engine" || { echo 'Paketin motor özeti eşleşmedi.' >&2; exit 1; }
  if [[ "$(cat "$root/llama/release" 2>/dev/null || true)" != "$engine_id" ]] || ! "$root/llama/llama-server" --help >/dev/null 2>&1; then
    tar --no-same-owner --no-same-permissions -xzf ".runtime/$bundled_engine" -C "$scratch"
    "$scratch/llama-$release/$engine_program" --help >/dev/null
    install -m 755 "$scratch/llama-$release/$engine_program" "$root/llama/llama-server.new"
    mv -f "$root/llama/llama-server.new" "$root/llama/llama-server"
    install -m 644 "$scratch/llama-$release/LICENSE" "$root/llama/LICENSE"
    printf '%s\n' "$engine_id" > "$root/llama/release"
  fi
elif [[ "$(cat "$root/llama/release" 2>/dev/null || true)" != "$release" ]] || ! LD_LIBRARY_PATH="$root/llama" "$root/llama/llama-server" --help >/dev/null 2>&1; then
  mkdir "$scratch/llama"
  if [[ $arch == aarch64 ]]; then
    stage_asset "$arm_asset" "$scratch/bin.tgz" "$arm_url"
    verify "$arm_sha" "$scratch/bin.tgz" || { echo 'ARM64 motorunun SHA-256 özeti eşleşmedi.' >&2; exit 1; }
    tar --no-same-owner --no-same-permissions -xzf "$scratch/bin.tgz" -C "$scratch/llama" --strip-components=1
    LD_LIBRARY_PATH="$scratch/llama" "$scratch/llama/llama-server" --help >/dev/null
  elif [[ $arch == x86_64 ]]; then
    stage_asset "llama-$release-bin-ubuntu-x64.tar.gz" "$scratch/bin.tgz" "https://github.com/ggml-org/llama.cpp/releases/download/$release/llama-$release-bin-ubuntu-x64.tar.gz"
    verify 887205c688f0f1a8829d2b74be1a1c20978c2afe45201a2659a7bea213220d15 "$scratch/bin.tgz" || { echo 'llama.cpp paket özeti eşleşmedi.' >&2; exit 1; }
    tar --no-same-owner --no-same-permissions -xzf "$scratch/bin.tgz" -C "$scratch/llama" --strip-components=1
  fi
  if [[ $arch != aarch64 ]] && ! LD_LIBRARY_PATH="$scratch/llama" "$scratch/llama/llama-server" --help >/dev/null 2>&1; then
    apt-get install -y --no-install-recommends build-essential cmake libssl-dev
    stage_asset "llama-$release-source.tar.gz" "$scratch/src.tgz" "https://codeload.github.com/ggml-org/llama.cpp/tar.gz/refs/tags/$release"
    verify 78d5fbc0e769bcc571baa81638f0bb9ad92cc224fa8e77914d164a85f78a2c42 "$scratch/src.tgz" || { echo 'llama.cpp kaynak özeti eşleşmedi.' >&2; exit 1; }
    tar -xzf "$scratch/src.tgz" -C "$scratch"
    cmake -S "$scratch/llama.cpp-$release" -B "$scratch/build" -DCMAKE_BUILD_TYPE=Release -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF
    cmake --build "$scratch/build" --target llama-server --parallel 2
    cp -a "$scratch/build/bin/." "$scratch/llama/"
  fi
  cp -a "$scratch/llama/." "$root/llama/"
  LD_LIBRARY_PATH="$root/llama" "$root/llama/llama-server" --help >/dev/null
  printf '%s\n' "$release" >"$root/llama/release"
fi

install -m 644 app.py admin.py feeds.py community.py news_search.py archive.py turkish.json requirements.txt VERSION "$root/"
install -d -m 755 "$root/templates"
install -m 644 templates/*.html "$root/templates/"
if [[ -f deploy/tunel-koprusu.sh ]]; then install -m 755 deploy/tunel-koprusu.sh "$root/tunel-koprusu.sh"; fi
if [[ -d licenses ]]; then
  install -d -m 755 "$root/licenses"
  install -m 644 licenses/* "$root/licenses/"
fi
install -d -m 755 "$root/static/fonts"
install -m 644 static/*.{html,js,css,svg,png} "$root/static/"
install -m 644 static/fonts/* "$root/static/fonts/"
chown -R root:root "$root/static" "$root/llama"
chmod 755 "$root/static" "$root/static/fonts"
python3 -m venv "$root/venv"
pip_options=()
if [[ $arch == aarch64 || -n $bundled_engine ]]; then pip_options=(--only-binary=:all: --no-binary=langdetect --no-cache-dir); fi
"$root/venv/bin/python" -m pip --disable-pip-version-check install "${pip_options[@]}" -r "$root/requirements.txt"
install -m 644 deploy/*.service deploy/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable postgres-gundem-model.service postgres-gundem.service
systemctl restart postgres-gundem-model.service postgres-gundem.service
curl --fail --silent --show-error --retry 90 --retry-connrefused --retry-delay 1 http://127.0.0.1:8080/ -o /dev/null
if [[ -n $bundled_engine ]]; then
  systemctl enable --now postgres-gundem-arsiv.timer
  echo 'Panel HTTP 200. Yerel çeviri modeli yükleniyor...'
  curl -fs --retry 300 --retry-connrefused --retry-delay 2 --max-time 5 http://127.0.0.1:18081/health || {
    echo 'Model hazır olamadı. journalctl -u postgres-gundem-model -n 30 ile günlüğü kontrol edin.' >&2
    exit 1
  }
  printf '\n'
  systemctl start postgres-gundem-arsiv.service
fi
echo 'Postgres Gündem hazır. Panel adresi http://127.0.0.1:8080'
