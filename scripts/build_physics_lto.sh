#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

project=/workspace
output=$project/native_physics_lto
cache=$project/build_cache/physicsLTO
flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin"

rm -rf "$cache"
mkdir -p "$cache" "$output"
cp -f \
    "$project/native_full_lto/libOpenFOAM.so" \
    "$project/native_full_lto/libfiniteVolume.so" \
    "$output/"

libraries=(
    twoPhaseMixture
    incompressible
    interfaceProperties
    immiscibleIncompressibleTwoPhaseMixture
)

for library in "${libraries[@]}"; do
    source_dir="/usr/lib/openfoam/openfoam2312/src/transportModels/$library"
    build_dir="$cache/$library"
    cp -a "$source_dir" "$build_dir"
    (
        cd "$build_dir"
        FOAM_LIBBIN="$output" \
        FOAM_EXTRA_CXXFLAGS="$flags" \
            wmake -j 24 libso
    )
done

strip --strip-unneeded "$output"/*.so
ls -lh "$output"/*.so
