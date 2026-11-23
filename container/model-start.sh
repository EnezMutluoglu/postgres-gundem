#!/bin/sh
set -eu
exe=/engine/llama-server
if [ -x /engine/llama-server-avx2 ]; then
  flags=$(awk -F': ' '/^flags[[:space:]]*:/ { print $2; exit }' /proc/cpuinfo)
  accelerated=yes
  for f in sse4_2 avx avx2 fma f16c bmi2; do
    case " $flags " in *" $f "*) ;; *) accelerated=no ;; esac
  done
  if [ "$accelerated" = yes ]; then exe=/engine/llama-server-avx2; fi
fi
exec "$exe" -m "/models/$MODEL_FILE" --host 0.0.0.0 --port 18081 -c 2048 -np 1 -t 2 -tb 2 -b 96 -ub 48 --load-mode mmap --no-repack --cache-ram 0 --no-warmup --no-ui --jinja

