#!/usr/bin/env python3
import subprocess, sys, shutil
from pathlib import Path

def run_cmd(cmd, cwd_path):
    print(f"========== 実行中: {cmd} ==========")
    if subprocess.run(cmd, shell=True, cwd=cwd_path).returncode != 0:
        print(f"\n[エラー] {cmd} が失敗しました。")
        print(f"ログファイル ({cwd_path}/log.コマンド名) を確認してください。")
        sys.exit(1)

def get_next_run_dir(cases_dir):
    """既存の run_XXX ディレクトリを探索し、次の連番ディレクトリパスを返す"""
    max_num = 0
    # cases/ 内の run_ で始まるディレクトリを検索
    for p in cases_dir.glob("run_*"):
        if p.is_dir():
            try:
                num = int(p.name.split("_")[1])
                if num > max_num:
                    max_num = num
            except ValueError:
                continue
    next_num = max_num + 1
    return cases_dir / f"run_{next_num:03d}" # 3桁ゼロ埋め (例: run_001)

def main():
    base_dir = Path(__file__).resolve().parent.parent
    cases_dir = base_dir / "cases"
    calc_base = cases_dir / "calc_base"
    mesh_base = cases_dir / "mesh_base"
    mesh_source = mesh_base / "constant" / "polyMesh"

    # メッシュが事前に作られているかチェック
    if not mesh_source.exists():
        print("[エラー] メッシュが存在しません。先に scripts/make_mesh.py を実行してください。")
        sys.exit(1)

    print("\n=== 1. 新しい計算用ディレクトリの作成 ===")
    run_dir = get_next_run_dir(cases_dir)
    print(f"作業ディレクトリを作成します: {run_dir.name}")
    
    # calc_baseを丸ごとコピー
    shutil.copytree(calc_base, run_dir)

    print("\n=== 2. メッシュの適用 ===")
    # mesh_base から polyMesh を run_XXX/constant/ 内にコピー
    shutil.copytree(mesh_source, run_dir / "constant" / "polyMesh")

    print("\n=== 3. 物理条件・初期状態のセット ===")
    # 0.orig を 0 にコピー
    shutil.copytree(run_dir / "0.orig", run_dir / "0")
    
    # setFieldsの実行 (計算ディレクトリ内)
    run_cmd("setFields > log.setFields 2>&1", cwd_path=run_dir)

    print("\n=== 4. シミュレーション(interFoam)の実行 ===")
    # バックグラウンドで実行開始
    run_cmd("interFoam > log.interFoam &", cwd_path=run_dir)

    print("\n=========================================================")
    print(f"全プロセス成功！ {run_dir.name} でシミュレーションを開始しました。")
    print("進捗を確認するには以下のコマンドを実行してください：")
    print(f"tail -f cases/{run_dir.name}/log.interFoam")
    print("=========================================================\n")

if __name__ == "__main__":
    main()