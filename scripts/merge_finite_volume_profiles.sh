#!/usr/bin/env bash
set -euo pipefail

profiles=/workspace/pgo_profiles/finiteVolume
merged=$profiles/merged
next=$profiles/.merged-next

mapfile -t inputs < <(
    find "$profiles" -mindepth 1 -maxdepth 1 -type d \
        ! -name merged ! -name .merged-next | sort
)
if (( ${#inputs[@]} == 0 )); then
    echo "no finiteVolume profiles found under $profiles" >&2
    exit 1
fi

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
if (( count == 0 )); then
    exit 1
fi
