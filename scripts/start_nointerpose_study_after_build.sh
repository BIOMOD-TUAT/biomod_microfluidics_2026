#!/usr/bin/env bash
set -euo pipefail

project=/home/komori_24266040/biomod_microfluidics_2026
upstream=optuna_fv_pgo_compare
build=finite_volume_nointerpose
study=optuna_fv_nointerpose_compare
build_log=$project/cases/finite_volume_nointerpose.log
study_log=$project/cases/fv_nointerpose_compare_v1_1e6.log

docker wait "$upstream" >/dev/null
for _ in $(seq 1 60); do
    if docker inspect "$build" >/dev/null 2>&1; then
        break
    fi
    sleep 2
done
if ! docker inspect "$build" >/dev/null 2>&1; then
    echo "no-interposition build container was not created" >&2
    exit 1
fi

docker wait "$build" >/dev/null
exit_code=$(docker inspect -f '{{.State.ExitCode}}' "$build")
if [[ "$exit_code" != 0 ]] || \
   ! grep -q 'finiteVolume no-interposition build and load check completed' "$build_log"; then
    echo "no-interposition study not started because build verification failed" >&2
    exit 1
fi

cd "$project"
docker rm -f "$study" >/dev/null 2>&1 || true
rm -f cases/fv_nointerpose_compare_v1_1e6.db
: > "$study_log"
docker run \
    --name "$study" \
    --shm-size=32g \
    -v "$project:/workspace" \
    -w /workspace \
    biomod_microfluidics_2026-openfoam-env \
    bash -lc '
        source /usr/lib/openfoam/openfoam2312/etc/bashrc >/dev/null 2>&1
        python3 scripts/optimize_runtime.py \
            --trials 64 \
            --end-time 1e-6 \
            --study-name fv_nointerpose_compare_v1_1e6 \
            --storage-file /workspace/cases/fv_nointerpose_compare_v1_1e6.db \
            --trial-root /dev/shm/fv_nointerpose_compare \
            --ranks 24 \
            --placements sequential_hwthread_bind \
            --transports shared_memory \
            --fpe-modes true \
            --runtime-modifiable-options true \
            --allocators jemalloc \
            --numa-policies default \
            --decomposition-methods scotch \
            --solvers interFoam \
            --allreduce-algorithms default \
            --solver-performance-options true \
            --library-modes native_full_lto,native_physics_lto,native_fv_nointerpose \
            --enqueue-library-rounds 8 \
            --file-handlers uncollated \
            --process-priorities default
    ' >>"$study_log" 2>&1
