#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

project=/workspace
output=$project/native_fv_nointerpose
cache=$project/build_cache/finiteVolumeNoInterpose
flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin -fno-semantic-interposition -fno-plt"

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
LD_LIBRARY_PATH="$output:${LD_LIBRARY_PATH:-}" interFoam -help >/dev/null
ls -lh "$output/libfiniteVolume.so"
echo "finiteVolume no-interposition build and load check completed"
