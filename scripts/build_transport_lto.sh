#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

project=/workspace
output=$project/native_transport_lto
cache=$project/build_cache/transportLTO
flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin"

rm -rf "$cache"
mkdir -p "$cache" "$output"
cp -f "$project/native_physics_lto/"*.so "$output/"

sources=(
    "TurbulenceModels/turbulenceModels"
    "TurbulenceModels/incompressible"
    "transportModels/twoPhaseProperties"
    "phaseSystemModels/twoPhaseInter/VoFphaseIncompressibleTurbulenceModels"
    "phaseSystemModels/twoPhaseInter/incompressibleInterPhaseTransportModel"
)

# Preserve the OpenFOAM source hierarchy. Several Make/options files use
# sibling-relative include paths (for example ../turbulenceModels/lnInclude).
for relative_source in "${sources[@]}"; do
    source_dir="/usr/lib/openfoam/openfoam2312/src/$relative_source"
    build_dir="$cache/src/$relative_source"
    mkdir -p "$(dirname "$build_dir")"
    cp -a "$source_dir" "$build_dir"
done

for relative_source in "${sources[@]}"; do
    build_dir="$cache/src/$relative_source"
    (
        cd "$build_dir"
        FOAM_LIBBIN="$output" \
        FOAM_EXTRA_CXXFLAGS="$flags" \
            wmake -j 24 libso
    )
done

strip --strip-unneeded "$output"/*.so
ls -lh "$output"/*.so
