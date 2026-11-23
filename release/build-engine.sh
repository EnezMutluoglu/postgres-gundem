#!/usr/bin/env bash
# Debian 12 build host: cmake, ninja-build, g++; arm64 cross-builds also use g++-aarch64-linux-gnu.
set -euo pipefail
if [[ $# != 3 ]]; then echo 'Kullanım: build-engine.sh amd64|arm64 kaynak.tar.gz çıktı-dizini' >&2; exit 2; fi
arch=$1
source_tar=$(realpath "$2")
mkdir -p "$3"
out=$(realpath "$3")
source_sha=78d5fbc0e769bcc571baa81638f0bb9ad92cc224fa8e77914d164a85f78a2c42
printf '%s  %s\n' "$source_sha" "$source_tar" | sha256sum -c -
. /etc/os-release
[[ $ID == debian && $VERSION_ID == 12 ]] || { echo 'Derleme ortamı Debian 12 olmalıdır.' >&2; exit 1; }
strip_tool=strip
case $arch in
  amd64)
    [[ $(dpkg --print-architecture) == amd64 ]] || { echo 'AMD64 derleme makinesi gerekli.' >&2; exit 1; }
    flags=(-DGGML_SSE42=OFF -DGGML_AVX=OFF -DGGML_AVX2=OFF -DGGML_FMA=OFF -DGGML_F16C=OFF -DGGML_BMI2=OFF)
    ;;
  arm64)
    flags=(-DGGML_CPU_ARM_ARCH=armv8-a)
    if [[ $(dpkg --print-architecture) != arm64 ]]; then
      flags+=(-DCMAKE_SYSTEM_NAME=Linux -DCMAKE_SYSTEM_PROCESSOR=aarch64
        -DCMAKE_C_COMPILER=aarch64-linux-gnu-gcc -DCMAKE_CXX_COMPILER=aarch64-linux-gnu-g++)
      strip_tool=aarch64-linux-gnu-strip
    fi
    ;;
  *) echo 'Desteklenen mimariler: amd64, arm64.' >&2; exit 2 ;;
esac
work=$(mktemp -d)
tmp=$(mktemp "$out/.llama-$arch.XXXXXXXX")
trap 'rm -rf -- "$work"; rm -f -- "$tmp"' EXIT
cd "$work"
mkdir -p src export/llama-b12532
tar -xzf "$source_tar" -C src --strip-components=1
cmake -S src -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  '-DCMAKE_C_FLAGS_RELEASE=-O2 -DNDEBUG' '-DCMAKE_CXX_FLAGS_RELEASE=-O2 -DNDEBUG' \
  -DBUILD_SHARED_LIBS=OFF -DGGML_BACKEND_DL=OFF -DGGML_NATIVE=OFF "${flags[@]}" \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_UI=OFF -DLLAMA_USE_PREBUILT_UI=OFF -DLLAMA_OPENSSL=OFF
cmake --build build --target llama-server --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-4}"
"$strip_tool" -o export/llama-b12532/llama-server build/bin/llama-server
chmod 755 export/llama-b12532/llama-server
if [[ $arch == amd64 ]]; then
  cmake -S src -B build -DGGML_SSE42=ON -DGGML_AVX=ON -DGGML_AVX2=ON -DGGML_FMA=ON -DGGML_F16C=ON -DGGML_BMI2=ON
  cmake --build build --target llama-server --parallel "${CMAKE_BUILD_PARALLEL_LEVEL:-4}"
  "$strip_tool" -o export/llama-b12532/llama-server-avx2 build/bin/llama-server
  chmod 755 export/llama-b12532/llama-server-avx2
fi
cp src/LICENSE export/llama-b12532/LICENSE
tar -C export --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner -cf - llama-b12532 | gzip -n -9 > "$tmp"
mv "$tmp" "$out/llama-b12532-bin-debian12-$arch.tar.gz"
