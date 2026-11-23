#!/bin/bash
set -euo pipefail
image=$1
work=$(mktemp -d)
network="pg-ci-private-${GITHUB_RUN_ID:-local}-$$"
name="pg-ci-model-$$"
cleanup(){ docker rm -f "$name" >/dev/null 2>&1 || true; docker network rm "$network" >/dev/null 2>&1 || true; rm -rf -- "$work"; }
trap cleanup EXIT
PG_ROOT=$work bash deploy/container/get-model.sh
model=$(python3 -c 'import json; print(json.load(open("deploy/container/model.json"))["file"])')
kind=$(python3 -c 'import json; print(json.load(open("deploy/container/model.json"))["type"])')
docker network create --internal "$network" >/dev/null
docker run -d --name "$name" --network "$network" --memory=2880m --memory-swap=2880m --cpus=2 \
  --read-only --tmpfs /tmp -e MODEL_FILE="$model" -v "$work/models:/models:ro" "$image" /bin/sh /app/container/model-start.sh >/dev/null
for _ in {1..120}; do
  if docker exec "$name" python /app/container/probe.py model >/dev/null 2>&1; then break; fi
  if [[ $(docker inspect -f '{{.State.Running}}' "$name") != true ]]; then docker logs "$name"; exit 1; fi
  sleep 2
done
docker exec "$name" python /app/container/probe.py model
docker exec -i -e GUNDEM_TRANSLATOR="$kind" -e GUNDEM_MODEL_URL=http://127.0.0.1:18081 "$name" python - <<'PY'
import app
samples=[
 ("Take a full backup before applying the maintenance update.", ("bakım güncelleme","yedek")),
 ("Do not restart the primary server.", ("birincil sunucu","başlatma")),
]
for en,words in samples:
    tr=app.translate(en)
    assert all(word in tr.lower() for word in words) and app.safe_instruction(en,tr),tr
    assert app.reasons_supported(en,tr) and "güvenlik" not in tr.lower(),tr
    print(en, "=>", tr)
PY
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' "$name"

