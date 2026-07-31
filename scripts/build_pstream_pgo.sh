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
cache=$project/build_cache/PstreamMpiPGO
profiles=$project/pgo_profiles/PstreamNoInterpose
base_flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin -fno-semantic-interposition -fno-plt"

if [[ "$phase" == "generate" ]]; then
    output=$project/native_pstream_pgo_generate
    flags="$base_flags -fprofile-generate=$profiles/%p"
    rm -rf "$profiles"
    mkdir -p "$profiles"
else
    output=$project/native_pstream_pgo
    [[ -d "$profiles/merged" ]]
    flags="$base_flags -fprofile-use=$profiles/merged -fprofile-correction -fprofile-partial-training -Wno-missing-profile"
fi

rm -rf "$cache" "$output"
cp -a /usr/lib/openfoam/openfoam2312/src/Pstream/mpi "$cache"
mkdir -p "$output"
cp -f "$project/native_core_pgo/"*.so "$output/"
(
    cd "$cache"
    FOAM_LIBBIN="$output" \
    FOAM_MPI_LIBBIN="$output" \
    FOAM_EXTRA_CXXFLAGS="$flags" \
        wmake -j 24 libso
)
strip --strip-unneeded "$output"/*.so
LD_LIBRARY_PATH="$output:${LD_LIBRARY_PATH:-}" interFoam -help >/dev/null
ls -lh "$output/libPstream.so"
echo "Pstream PGO $phase build and load check completed"
