#!/usr/bin/env python3
"""Build the OpenFOAM mesh from an STL stored in millimetres."""

import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path


SCALE = "(0.001 0.001 0.001)"

# 今回の流路で使用する入口・出口は3つ
PATCH_NAMES = (
    "inlet_oil",
    "inlet_water",
    "outlet",
)


def stl_bounds(path: Path):
    """Return STL bounds as (minimums, maximums), without extra packages."""
    data = path.read_bytes()
    vertices = []

    # Binary STL: 80-byte header, 4-byte triangle count,
    # then 50 bytes per triangle.
    if len(data) >= 84:
        count = struct.unpack_from("<I", data, 80)[0]

        if 84 + count * 50 == len(data):
            for i in range(count):
                offset = 84 + i * 50 + 12
                for j in range(3):
                    vertices.append(
                        struct.unpack_from("<fff", data, offset + j * 12)
                    )
        else:
            data_text = data.decode("utf-8", errors="ignore")
            pattern = (
                r"\bvertex\s+"
                r"([-+0-9.eE]+)\s+"
                r"([-+0-9.eE]+)\s+"
                r"([-+0-9.eE]+)"
            )
            vertices = [
                tuple(map(float, match))
                for match in re.findall(pattern, data_text)
            ]

    if not vertices:
        raise RuntimeError(f"STLの頂点を読み取れません: {path}")

    mins = tuple(min(v[i] for v in vertices) for i in range(3))
    maxs = tuple(max(v[i] for v in vertices) for i in range(3))

    return mins, maxs


def validate_mm_stl(path: Path):
    """Reject files that appear to have already been scaled to metres."""
    mins, maxs = stl_bounds(path)
    spans = tuple(maxs[i] - mins[i] for i in range(3))

    print(f"STL: {path}")
    print(f"  Bounds: min={mins}, max={maxs}")
    print(f"  Extents: {spans}")

    # Expected approximate dimensions of this project in mm.
    if not (
        10.0 < spans[0] < 100.0
        and 5.0 < spans[1] < 50.0
        and 0.01 < spans[2] < 1.0
    ):
        raise RuntimeError(
            "STLの寸法が想定範囲から外れています。\n"
            "このプロジェクトではmm単位の元STLを使用してください。\n"
            "既にm単位へ変換されたSTLを元ファイルとして"
            "再利用しないでください。CADから元STLを再出力するか、"
            "正しいflow_channel_mm.stlを配置してください。"
        )


def run_logged(command, cwd: Path, log_name: str):
    """Run a command, save its output, and report failure immediately."""
    log_path = cwd / log_name

    print(f"\n========== {' '.join(command)} ==========")
    print(f"ログ: {log_path}")

    with log_path.open("w", encoding="utf-8") as log:
        result = subprocess.run(
            command,
            cwd=cwd,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )

    if result.returncode != 0:
        print(f"\n[ERROR] コマンドが失敗しました: {command[0]}")

        try:
            lines = log_path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()

            print("\n--- ログ末尾 ---")
            print("\n".join(lines[-40:]))

        except OSError:
            pass

        sys.exit(result.returncode)

    return log_path


def get_patch_face_count(boundary_text: str, patch_name: str):
    """Extract nFaces from a patch entry in constant/polyMesh/boundary."""
    pattern = (
        rf"(?ms)^\s*{re.escape(patch_name)}\s*\{{"
        rf"(.*?)^\s*\}}"
    )

    match = re.search(pattern, boundary_text)

    if not match:
        return None

    face_match = re.search(
        r"\bnFaces\s+(\d+)\s*;",
        match.group(1),
    )

    return int(face_match.group(1)) if face_match else None


def main():
    project_root = Path(__file__).resolve().parent.parent
    mesh_base = project_root / "cases" / "mesh_base"
    tri_dir = mesh_base / "constant" / "triSurface"

    source_stl = tri_dir / "flow_channel_mm.stl"
    output_stl = tri_dir / "flow_channel.stl"

    # Required configuration files.
    required_files = (
        mesh_base / "system" / "blockMeshDict",
        mesh_base / "system" / "surfaceFeatureExtractDict",
        mesh_base / "system" / "snappyHexMeshDict",
        mesh_base / "system" / "topoSetDict",
        mesh_base / "system" / "createPatchDict",
    )

    for path in required_files:
        if not path.is_file():
            raise FileNotFoundError(
                f"必要な設定ファイルがありません: {path}"
            )

    tri_dir.mkdir(parents=True, exist_ok=True)

    # One-time migration from the old STL filename.
    # Preserve the original mm geometry from this point onward.
    if not source_stl.exists():
        if not output_stl.exists():
            raise FileNotFoundError(
                f"元STLがありません: {source_stl}\n"
                "mm単位のSTLをflow_channel_mm.stlとして配置してください。"
            )

        print(
            "flow_channel_mm.stlがないため、既存STLの寸法を確認します。"
        )

        validate_mm_stl(output_stl)
        shutil.copy2(output_stl, source_stl)

        print(f"元STLを保存しました: {source_stl}")

    validate_mm_stl(source_stl)

    print("\n=== 1. 古い生成物を削除 ===")

    cleanup_paths = (
        mesh_base / "constant" / "polyMesh",
        mesh_base / "constant" / "extendedFeatureEdgeMesh",
        mesh_base / "0",
        tri_dir / "flow_channel.eMesh",
        tri_dir / "flow_channel.obj",
    )

    for path in cleanup_paths:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    # Remove only the generated metre-scale file,
    # never the original STL.
    output_stl.unlink(missing_ok=True)

    print("\n=== 2. mmからmへ変換 ===")

    run_logged(
        [
            "surfaceTransformPoints",
            "-scale",
            SCALE,
            "constant/triSurface/flow_channel_mm.stl",
            "constant/triSurface/flow_channel.stl",
        ],
        mesh_base,
        "log.surfaceTransformPoints",
    )

    # Check the transformed geometry.
    run_logged(
        ["surfaceCheck", "constant/triSurface/flow_channel.stl"],
        mesh_base,
        "log.surfaceCheck",
    )

    print("\n=== 3. 背景メッシュを生成 ===")

    run_logged(
        ["blockMesh"],
        mesh_base,
        "log.blockMesh",
    )

    print("\n=== 4. STL特徴エッジを抽出 ===")

    run_logged(
        ["surfaceFeatureExtract"],
        mesh_base,
        "log.surfaceFeatureExtract",
    )

    print("\n=== 5. STLに追従するメッシュを生成 ===")

    run_logged(
        ["snappyHexMesh", "-overwrite"],
        mesh_base,
        "log.snappyHexMesh",
    )

    print("\n=== 6. 境界候補面を抽出 ===")

    run_logged(
        ["topoSet"],
        mesh_base,
        "log.topoSet",
    )

    print("\n=== 7. 入口・出口パッチを作成 ===")

    run_logged(
        ["createPatch", "-overwrite"],
        mesh_base,
        "log.createPatch",
    )

    print("\n=== 8. 最終メッシュを検査 ===")

    run_logged(
        ["checkMesh"],
        mesh_base,
        "log.checkMesh",
    )

    boundary_path = (
        mesh_base / "constant" / "polyMesh" / "boundary"
    )

    if not boundary_path.is_file():
        raise RuntimeError(
            f"boundaryファイルがありません: {boundary_path}"
        )

    boundary_text = boundary_path.read_text(
        encoding="utf-8",
        errors="replace",
    )

    has_error = False

    print("\n=== 9. 入口・出口パッチの検査 ===")

    for name in PATCH_NAMES:
        count = get_patch_face_count(boundary_text, name)

        if count is None:
            print(f"[ERROR] パッチがありません: {name}")
            has_error = True
        elif count == 0:
            print(f"[ERROR] パッチの面数が0です: {name}")
            has_error = True
        else:
            print(f"[OK] {name}: {count} faces")

    if has_error:
        raise RuntimeError(
            "入口・出口パッチの検査に失敗しました。\n"
            "log.topoSet、log.createPatch、STLの開口位置を確認してください。"
        )

    print("\n=================================================")
    print("メッシュ生成処理が完了しました。")
    print(f"STL: {output_stl}")
    print(f"メッシュ: {mesh_base / 'constant' / 'polyMesh'}")
    print("注意: パッチの面数が正しくても、位置や向きが")
    print("物理的に正しいことまでは保証されません。")
    print("ParaView等で各パッチを色分けして確認してください。")
    print("=================================================")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[FATAL] {exc}", file=sys.stderr)
        sys.exit(1)