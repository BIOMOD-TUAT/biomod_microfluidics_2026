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
cache=$project/build_cache/physicsPGO
profiles=$project/pgo_profiles/physicsNoInterpose
base_flags="-march=broadwell -mtune=broadwell -ffp-contract=off -flto=24 -fuse-linker-plugin -fno-semantic-interposition -fno-plt"

if [[ "$phase" == "generate" ]]; then
    output=$project/native_physics_pgo_generate
    flags="$base_flags -fprofile-generate=$profiles/%p"
    rm -rf "$profiles"
    mkdir -p "$profiles"
else
    output=$project/native_physics_pgo
    [[ -d "$profiles/merged" ]]
    flags="$base_flags -fprofile-use=$profiles/merged -fprofile-correction -fprofile-partial-training -Wno-missing-profile"
fi

rm -rf "$cache" "$output"
mkdir -p "$cache" "$output"
cp -f "$project/native_core_pgo/"*.so "$output/"

libraries=(
    twoPhaseMixture
    incompressible
    interfaceProperties
    immiscibleIncompressibleTwoPhaseMixture
)
for library in "${libraries[@]}"; do
    build_dir=$cache/$library
    cp -a "/usr/lib/openfoam/openfoam2312/src/transportModels/$library" "$build_dir"
    (
        cd "$build_dir"
        FOAM_LIBBIN="$output" \
        FOAM_EXTRA_CXXFLAGS="$flags" \
            wmake -j 24 libso
    )
done

strip --strip-unneeded "$output"/*.so
LD_LIBRARY_PATH="$output:${LD_LIBRARY_PATH:-}" interFoam -help >/dev/null
ls -lh "$output"/*.so
echo "physics PGO $phase build and load check completed"
