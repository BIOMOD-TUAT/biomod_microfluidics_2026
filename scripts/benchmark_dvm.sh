#!/usr/bin/env bash
set -euo pipefail

case_path=$1
iterations=${2:-5}
uri_file=$(mktemp)
rm -f "$uri_file"

orterun \
    --allow-run-as-root \
    --dvm \
    --report-uri "$uri_file" \
    -np 1 \
    true \
    >/tmp/openfoam-dvm.log 2>&1 &
dvm_pid=$!

cleanup() {
    kill "$dvm_pid" 2>/dev/null || true
    wait "$dvm_pid" 2>/dev/null || true
    rm -f "$uri_file"
}
trap cleanup EXIT

for _ in {1..100}; do
    [[ -s $uri_file ]] && break
    sleep 0.02
done
[[ -s $uri_file ]]

for ((iteration = 1; iteration <= iterations; iteration++)); do
    started=$(date +%s%N)
    orterun \
        --allow-run-as-root \
        --hnp "file:$uri_file" \
        --bind-to hwthread \
        --map-by core \
        --mca pml ob1 \
        --mca btl self,vader \
        -np 24 \
        interFoam \
        -parallel \
        -fileHandler uncollated \
        -case "$case_path" \
        >"/tmp/openfoam-dvm-iteration-${iteration}.log" 2>&1
    ended=$(date +%s%N)
    awk \
        -v iteration="$iteration" \
        -v started="$started" \
        -v ended="$ended" \
        'BEGIN {
            printf "DVM_ITERATION %d %.6f\n",
                iteration, (ended - started) / 1000000000
        }'
done
