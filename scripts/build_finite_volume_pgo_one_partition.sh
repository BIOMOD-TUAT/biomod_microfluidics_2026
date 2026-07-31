#!/usr/bin/env bash
set -o pipefail

source /usr/lib/openfoam/openfoam2312/etc/bashrc
set -euo pipefail

project=/workspace
output=$project/native_fv_pgo_one_partition
cache=$project/build_cache/finiteVolumePGONoInterpose
profiles=$project/pgo_profiles/finiteVolumeNoInterpose
[[ -d "$profiles/merged" ]]

flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -flto-partition=one -fuse-linker-plugin -fipa-pta -fdevirtualize-at-ltrans -fno-semantic-interposition -fno-plt -fprofile-use=$profiles/merged -fprofile-correction -fprofile-partial-training -Wno-missing-profile"

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
echo "finiteVolume PGO one-partition build and load check completed"
