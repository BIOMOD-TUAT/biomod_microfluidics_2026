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
os_cache=$project/build_cache/OSspecificCorePGO
core_cache=$project/build_cache/OpenFOAMCorePGO
profiles=$project/pgo_profiles/OpenFOAMCoreNoInterpose
base_flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin -fno-semantic-interposition -fno-plt"

if [[ "$phase" == "generate" ]]; then
    output=$project/native_core_pgo_generate
    flags="$base_flags -fprofile-generate=$profiles/%p"
    rm -rf "$profiles"
    mkdir -p "$profiles"
else
    output=$project/native_core_pgo
    [[ -d "$profiles/merged" ]]
    flags="$base_flags -fprofile-use=$profiles/merged -fprofile-correction -fprofile-partial-training -Wno-missing-profile"
fi

rm -rf "$os_cache" "$core_cache" "$output"
cp -a /usr/lib/openfoam/openfoam2312/src/OSspecific/POSIX "$os_cache"
cp -a /usr/lib/openfoam/openfoam2312/src/OpenFOAM "$core_cache"
mkdir -p "$output/dummy"
cp -f "$project/native_fv_pgo_one_partition/"*.so "$output/"
ln -s /usr/lib/openfoam/openfoam2312/platforms/linux64GccDPInt32Opt/lib/dummy/libPstream.so \
    "$output/dummy/libPstream.so"

(
    cd "$os_cache"
    FOAM_LIBBIN="$output" \
    FOAM_EXTRA_CXXFLAGS="$flags" \
        wmake -j 24 libo
)
(
    cd "$core_cache"
    FOAM_LIBBIN="$output" \
    FOAM_EXTRA_CXXFLAGS="$flags" \
        wmake -j 24 libso
)

strip --strip-unneeded "$output/libOpenFOAM.so"
LD_LIBRARY_PATH="$output:${LD_LIBRARY_PATH:-}" interFoam -help >/dev/null
ls -lh "$output/libOpenFOAM.so" "$output/libfiniteVolume.so"
echo "OpenFOAM core PGO $phase build and load check completed"
