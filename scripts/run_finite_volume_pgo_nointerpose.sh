#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

project=/workspace
profiles=$project/pgo_profiles/finiteVolumeNoInterpose
database=$project/cases/fv_pgo_nointerpose_training_1e6.db
trial_root=/dev/shm/fv_pgo_nointerpose_training

cd "$project"
bash scripts/build_finite_volume_pgo_nointerpose.sh generate

rm -f "$database"
rm -rf "$trial_root"
python3 scripts/optimize_runtime.py \
    --trials 1 --end-time 1e-6 \
    --study-name fv_pgo_nointerpose_training_1e6 \
    --storage-file "$database" --trial-root "$trial_root" \
    --ranks 24 --placements sequential_hwthread_bind \
    --transports shared_memory --fpe-modes true \
    --runtime-modifiable-options true --allocators jemalloc \
    --numa-policies default --decomposition-methods scotch \
    --solvers interFoam --allreduce-algorithms default \
    --solver-performance-options true \
    --library-modes native_fv_pgo_nointerpose_generate \
    --file-handlers uncollated --process-priorities default

merged=$profiles/merged
next=$profiles/.merged-next
mapfile -t inputs < <(find "$profiles" -mindepth 1 -maxdepth 1 -type d ! -name merged ! -name .merged-next | sort)
(( ${#inputs[@]} > 0 ))
rm -rf "$merged" "$next"
cp -a "${inputs[0]}" "$merged"
for input in "${inputs[@]:1}"; do
    rm -rf "$next"
    gcov-tool merge "$merged" "$input" -o "$next"
    rm -rf "$merged"
    mv "$next" "$merged"
done
count=$(find "$merged" -type f -name '*.gcda' | wc -l)
echo "merged ${#inputs[@]} process profiles: $count gcda files"
(( count > 0 ))

bash scripts/build_finite_volume_pgo_nointerpose.sh use
echo "finiteVolume PGO no-interposition pipeline completed"
