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
cache=$project/build_cache/finiteVolumePGO
profiles=$project/pgo_profiles/finiteVolume
base_flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin"

if [[ "$phase" == "generate" ]]; then
    output=$project/native_fv_pgo_generate
    flags="$base_flags -fprofile-generate=$profiles/%p"
    rm -rf "$profiles"
    mkdir -p "$profiles"
else
    output=$project/native_fv_pgo
    if [[ ! -d "$profiles/merged" ]]; then
        echo "missing merged profile: $profiles/merged" >&2
        exit 1
    fi
    flags="$base_flags -fprofile-use=$profiles/merged -fprofile-correction -fprofile-partial-training -Wno-missing-profile"
fi

# Keep the same build path for both phases: GCC derives the profile filename
# from the object path.
rm -rf "$cache" "$output"
cp -a /usr/lib/openfoam/openfoam2312/src/finiteVolume "$cache"
mkdir -p "$output"
cp -f "$project/native_physics_lto/"*.so "$output/"

(
    cd "$cache"
    FOAM_LIBBIN="$output" \
    FOAM_EXTRA_CXXFLAGS="$flags" \
        wmake -j 24 libso
)

strip --strip-unneeded "$output"/*.so
ls -lh "$output/libfiniteVolume.so"
