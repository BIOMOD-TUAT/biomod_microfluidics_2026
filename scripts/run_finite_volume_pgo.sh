#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

project=/workspace
study=fv_pgo_training_1e6
database=$project/cases/fv_pgo_training_1e6.db
trial_root=/dev/shm/fv_pgo_training

cd "$project"
bash scripts/build_finite_volume_pgo.sh generate

rm -f "$database"
rm -rf "$trial_root"
python3 scripts/optimize_runtime.py \
    --trials 1 \
    --end-time 1e-6 \
    --study-name "$study" \
    --storage-file "$database" \
    --trial-root "$trial_root" \
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
    --library-modes native_fv_pgo_generate \
    --file-handlers uncollated \
    --process-priorities default

bash scripts/merge_finite_volume_profiles.sh
bash scripts/build_finite_volume_pgo.sh use

LD_LIBRARY_PATH="$project/native_fv_pgo:${LD_LIBRARY_PATH:-}" \
    interFoam -help >/dev/null
echo "finiteVolume PGO build and load check completed"
