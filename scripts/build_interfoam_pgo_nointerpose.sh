#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

phase=${1:-}
if [[ "$phase" != "generate" && "$phase" != "use" ]]; then
    echo "usage: $0 generate|use" >&2
    exit 2
fi

project=/workspace
cache=$project/build_cache/interFoamPGONoInterpose
profiles=$project/pgo_profiles/interFoamNoInterpose
base_flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin -fno-semantic-interposition -fno-plt"

if [[ "$phase" == "generate" ]]; then
    output=$project/native_bin_pgo_nointerpose_generate
    flags="$base_flags -fprofile-generate=$profiles/%p"
    rm -rf "$profiles"
    mkdir -p "$profiles"
else
    output=$project/native_bin_pgo_nointerpose
    [[ -d "$profiles/merged" ]]
    flags="$base_flags -fprofile-use=$profiles/merged -fprofile-correction -fprofile-partial-training -Wno-missing-profile"
fi

rm -rf "$cache" "$output"
cp -a /usr/lib/openfoam/openfoam2312/applications/solvers/multiphase/interFoam "$cache"
mkdir -p "$output"
(
    cd "$cache"
    FOAM_APPBIN="$output" \
    FOAM_EXTRA_CXXFLAGS="$flags" \
    FOAM_EXTRA_LDFLAGS="$flags" \
        wmake -j 24
)
strip --strip-unneeded "$output/interFoam"
LD_LIBRARY_PATH="$project/native_fv_pgo_nointerpose:${LD_LIBRARY_PATH:-}" \
    "$output/interFoam" -help >/dev/null
ls -lh "$output/interFoam"
echo "interFoam PGO no-interposition $phase build and load check completed"
