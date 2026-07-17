#!/usr/bin/env python3
import subprocess, sys, shutil
from pathlib import Path

def run_cmd(cmd, cwd_path):
    print(f"========== 実行中: {cmd} ==========")
    if subprocess.run(cmd, shell=True, cwd=cwd_path).returncode != 0:
        print(f"\n[エラー] {cmd} が失敗しました。")
        print(f"ログファイル ({cwd_path}/log.コマンド名) を確認してください。")
        sys.exit(1)

def main():
    # スクリプトの親ディレクトリから mesh_base のパスを取得
    base_dir = Path(__file__).resolve().parent.parent
    mesh_base = base_dir / "cases" / "mesh_base"

    print("\n=== 1. 古いメッシュデータのクリーンアップ ===")
    shutil.rmtree(mesh_base / "constant" / "polyMesh", ignore_errors=True)
    shutil.rmtree(mesh_base / "constant" / "extendedFeatureEdgeMesh", ignore_errors=True)
    shutil.rmtree(mesh_base / "0", ignore_errors=True) 

    print("\n=== 2. STLファイルのスケール変換 ===")
    # CADから出力したSTLがmm単位の場合、OpenFOAM(m単位)に合わせるために0.001倍します。
    # ※不要な場合（すでにm単位の場合）や、二重変換を防ぐ場合はコメントアウトしてください。
    # run_cmd("surfaceTransformPoints -scale '(0.001 0.001 0.001)' constant/triSurface/flow_channel.stl constant/triSurface/flow_channel.stl", cwd_path=mesh_base)

    print("\n=== 3. メッシュとパッチの生成 ===")
    run_cmd("blockMesh > log.blockMesh 2>&1", cwd_path=mesh_base)
    run_cmd("surfaceFeatureExtract > log.surfaceFeatureExtract 2>&1", cwd_path=mesh_base)
    run_cmd("snappyHexMesh -overwrite > log.snappyHexMesh 2>&1", cwd_path=mesh_base)
    
    # フィルター修正済みのtopoSetで皮を捕らえ、createPatchで名前を書き換える
    run_cmd("topoSet > log.topoSet 2>&1", cwd_path=mesh_base)
    run_cmd("createPatch -overwrite > log.createPatch 2>&1", cwd_path=mesh_base)
    
    # メッシュ生成時に出る不要なディレクトリを削除
    shutil.rmtree(mesh_base / "0", ignore_errors=True) 

    print("\n=========================================================")
    print("メッシュ生成完了！")
    print(f"生成先: {mesh_base / 'constant' / 'polyMesh'}")
    print("=========================================================\n")

if __name__ == "__main__":
    main()