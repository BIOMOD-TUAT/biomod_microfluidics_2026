#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

project=/workspace
profiles=$project/pgo_profiles/PstreamNoInterpose
cd "$project"

bash scripts/build_pstream_pgo.sh generate
rm -f cases/pstream_pgo_training_1e6.db
python3 scripts/optimize_runtime.py \
    --trials 1 --end-time 1e-6 \
    --study-name pstream_pgo_training_1e6 \
    --storage-file /workspace/cases/pstream_pgo_training_1e6.db \
    --trial-root /dev/shm/pstream_pgo_training \
    --ranks 24 --placements sequential_hwthread_bind \
    --transports shared_memory_isolated --fpe-modes true \
    --runtime-modifiable-options true --allocators jemalloc_single_arena_thp \
    --numa-policies default --decomposition-methods scotch \
    --solvers interFoam --allreduce-algorithms default \
    --solver-performance-options true \
    --library-modes native_pstream_pgo_generate \
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
bash scripts/build_pstream_pgo.sh use
echo "Pstream PGO pipeline completed"
