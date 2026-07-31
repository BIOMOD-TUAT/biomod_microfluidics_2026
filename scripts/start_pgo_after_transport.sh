#!/usr/bin/env bash
set -euo pipefail

project=/home/komori_24266040/biomod_microfluidics_2026
upstream=optuna_transport_lto
pipeline=finite_volume_pgo
upstream_log=$project/cases/transport_lto_v1_1e6.log
pipeline_log=$project/cases/finite_volume_pgo.log

docker wait "$upstream"
exit_code=$(docker inspect -f '{{.State.ExitCode}}' "$upstream")
finished=$(grep -c 'Trial .* finished' "$upstream_log" || true)
failed=$(grep -c 'Trial .* failed' "$upstream_log" || true)
echo "transport study: exit=$exit_code finished=$finished failed=$failed"

if [[ "$exit_code" != 0 || "$finished" -lt 64 || "$failed" != 0 ]]; then
    echo "PGO not started because the transport study did not pass its gate" >&2
    exit 1
fi

docker rm -f "$pipeline" >/dev/null 2>&1 || true
: > "$pipeline_log"
docker run \
    --name "$pipeline" \
    --shm-size=32g \
    -v "$project:/workspace" \
    -w /workspace \
    biomod_microfluidics_2026-openfoam-env \
    bash scripts/run_finite_volume_pgo.sh \
    >>"$pipeline_log" 2>&1
