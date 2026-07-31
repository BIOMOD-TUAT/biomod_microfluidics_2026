#!/usr/bin/env bash
set -euo pipefail

case_path=$1
iterations=${2:-3}
log_dir=${3:-}

for ((iteration = 1; iteration <= iterations; iteration++)); do
    if [[ ${OMPI_COMM_WORLD_RANK:-} == 0 ]]; then
        started=$(date +%s%N)
    fi

    if [[ -n $log_dir ]]; then
        interFoam \
            -parallel \
            -fileHandler uncollated \
            -case "$case_path" \
            >"$log_dir/rank_${OMPI_COMM_WORLD_RANK}_iteration_${iteration}.log" \
            2>&1
    else
        interFoam \
            -parallel \
            -fileHandler uncollated \
            -case "$case_path" \
            >/dev/null 2>&1
    fi

    if [[ ${OMPI_COMM_WORLD_RANK:-} == 0 ]]; then
        ended=$(date +%s%N)
        awk \
            -v iteration="$iteration" \
            -v started="$started" \
            -v ended="$ended" \
            'BEGIN {
                printf "PERSISTENT_ITERATION %d %.6f\n",
                    iteration, (ended - started) / 1000000000
            }'
    fi
done
