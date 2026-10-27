#!/usr/bin/env python3
"""Create and launch pressure-driven OpenFOAM interFoam cases."""

import argparse
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


REQUIRED_PATCHES = (
    "inlet_water",
    "inlet_oil",
    "outlet",
    "flow_channel",
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="圧力を指定して interFoam の計算ケースを作成・起動します。"
    )
    parser.add_argument(
        "--water-kpa",
        type=float,
        default=14.5,
        help="水入口圧力 [kPa]（既定値: 14.5）",
    )
    parser.add_argument(
        "--oil-kpa",
        type=float,
        nargs="+",
        default=[20.0, 30.0],
        help="油入口圧力 [kPa]。複数指定できます（既定値: 20 30）",
    )
    parser.add_argument(
        "--end-time",
        type=float,
        default=None,
        help="解析終了時刻 [s]。省略時はテンプレートの設定を使用",
    )
    parser.add_argument(
        "--write-interval",
        type=float,
        default=None,
        help="結果保存間隔 [s]。省略時はテンプレートの設定を使用",
    )
    parser.add_argument(
        "--prepare-only",
        action="store_true",
        help="ケースの準備だけ行い、ソルバーは起動しません",
    )
    args = parser.parse_args()

    pressures = [args.water_kpa, *args.oil_kpa]
    if not all(math.isfinite(p) and p > 0 for p in pressures):
        parser.error("入口圧力には正の有限値を指定してください。")

    if args.end_time is not None:
        if not math.isfinite(args.end_time) or args.end_time <= 0:
            parser.error("--end-time は正の有限値にしてください。")

    if args.write_interval is not None:
        if (
            not math.isfinite(args.write_interval)
            or args.write_interval <= 0
        ):
            parser.error(
                "--write-interval は正の有限値にしてください。"
            )

    return args


def number_label(value):
    """Convert 14.5 to '14p5' for directory names."""
    return format(value, "g").replace("-", "m").replace(".", "p")


def pressure_pa(value_kpa):
    """Convert kPa to Pa, rounded to the nearest whole Pa."""
    return round(value_kpa * 1000)


def patch_pattern(patch_name):
    return re.compile(
        rf"(?m)^[ \t]*{re.escape(patch_name)}[ \t]*"
        rf"(?:\r?\n[ \t]*)?\{{"
    )


def extract_braced_block(text, patch_name):
    match = patch_pattern(patch_name).search(text)
    if not match:
        raise RuntimeError(
            f"境界条件ファイルにパッチ '{patch_name}' がありません。"
        )

    opening = text.find("{", match.start())
    depth = 0

    for index in range(opening, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return match.start(), index + 1, text[match.start():index + 1]

    raise RuntimeError(f"パッチ '{patch_name}' の括弧が閉じていません。")


def replace_entry(path, key, value):
    """Replace a top-level dictionary entry such as endTime."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"(?m)^([ \t]*{re.escape(key)}[ \t]+)[^;\n]*;"
    )
    updated, count = pattern.subn(
        lambda match: match.group(1) + f"{value};",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(
            f"{path} の '{key}' を更新できませんでした。"
        )
    path.write_text(updated, encoding="utf-8")


def set_patch_pressure(path, patch_name, value_pa):
    text = path.read_text(encoding="utf-8")
    start, end, block = extract_braced_block(text, patch_name)

    if not re.search(r"\btype\s+fixedValue\s*;", block):
        raise RuntimeError(
            f"{path}: {patch_name} が fixedValue ではありません。"
        )

    updated_block, count = re.subn(
        r"(\bvalue\s+uniform\s+)[^;]+;",
        lambda match: match.group(1) + f"{value_pa};",
        block,
        count=1,
    )
    if count != 1:
        raise RuntimeError(
            f"{path}: {patch_name} の圧力値を更新できませんでした。"
        )

    path.write_text(
        text[:start] + updated_block + text[end:],
        encoding="utf-8",
    )


def run_logged(command, cwd, log_name):
    log_path = cwd / log_name
    print(f"  実行: {' '.join(command)}")
    print(f"  ログ: {log_path}")

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
        lines = log_path.read_text(
            encoding="utf-8", errors="replace"
        ).splitlines()
        print("\n--- ログ末尾 ---")
        print("\n".join(lines[-40:]))
        raise RuntimeError(
            f"{command[0]} が終了コード {result.returncode} "
            "で失敗しました。"
        )


def next_run_number(cases_dir):
    pattern = re.compile(r"^run_(\d+)(?:_|$)")
    numbers = []

    for path in cases_dir.glob("run_*"):
        if path.is_dir():
            match = pattern.match(path.name)
            if match:
                numbers.append(int(match.group(1)))

    return max(numbers, default=0) + 1


def validate_field_patches(case_dir):
    for field_name in ("U", "p_rgh", "alpha.water"):
        field_path = case_dir / "0.orig" / field_name
        if not field_path.is_file():
            raise FileNotFoundError(f"必要なファイルがありません: {field_path}")

        text = field_path.read_text(encoding="utf-8")
        for patch in REQUIRED_PATCHES:
            if not patch_pattern(patch).search(text):
                raise RuntimeError(
                    f"{field_path} にパッチ '{patch}' がありません。"
                )


def validate_outlet_pressure(path):
    text = path.read_text(encoding="utf-8")
    _, _, block = extract_braced_block(text, "outlet")

    if not re.search(r"\btype\s+fixedValue\s*;", block):
        raise RuntimeError("p_rgh の outlet は fixedValue ではありません。")

    if not re.search(
        r"\bvalue\s+uniform\s+0(?:\.0*)?\s*;", block
    ):
        raise RuntimeError("p_rgh の outlet 圧力は 0 Pa にしてください。")


def prepare_case(
    calc_base,
    mesh_source,
    run_dir,
    water_kpa,
    oil_kpa,
    end_time,
    write_interval,
):
    if run_dir.exists():
        raise FileExistsError(
            f"ケースが既に存在するため上書きしません: {run_dir}"
        )

    water_pa = pressure_pa(water_kpa)
    oil_pa = pressure_pa(oil_kpa)

    print("\n" + "=" * 60)
    print(f"ケース: {run_dir.name}")
    print(f"水入口: {water_kpa:g} kPa ({water_pa} Pa)")
    print(f"油入口: {oil_kpa:g} kPa ({oil_pa} Pa)")
    print("出口: 0 Pa")
    print("=" * 60)

    shutil.copytree(calc_base, run_dir)

    target_mesh = run_dir / "constant" / "polyMesh"
    target_mesh.parent.mkdir(parents=True, exist_ok=True)
    if target_mesh.exists():
        shutil.rmtree(target_mesh)
    shutil.copytree(mesh_source, target_mesh)

    validate_field_patches(run_dir)

    p_rgh = run_dir / "0.orig" / "p_rgh"
    set_patch_pressure(p_rgh, "inlet_water", water_pa)
    set_patch_pressure(p_rgh, "inlet_oil", oil_pa)
    validate_outlet_pressure(p_rgh)

    control_dict = run_dir / "system" / "controlDict"
    if end_time is not None:
        replace_entry(control_dict, "endTime", format(end_time, ".12g"))
    if write_interval is not None:
        replace_entry(
            control_dict,
            "writeInterval",
            format(write_interval, ".12g"),
        )

    time_zero = run_dir / "0"
    if time_zero.exists():
        shutil.rmtree(time_zero)
    shutil.copytree(run_dir / "0.orig", time_zero)

    run_logged(["setFields"], run_dir, "log.setFields")

    print(f"[OK] 準備完了: {run_dir}")


def launch_solver(run_dir):
    log_path = run_dir / "log.interFoam"
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            ["interFoam"],
            cwd=run_dir,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    (run_dir / "interFoam.pid").write_text(
        f"{process.pid}\n", encoding="utf-8"
    )
    print(f"[起動] {run_dir.name}: PID={process.pid}")
    print(f"       ログ: {log_path}")


def main():
    args = parse_args()

    project_root = Path(__file__).resolve().parent.parent
    cases_dir = project_root / "cases"
    calc_base = cases_dir / "calc_base"
    mesh_source = cases_dir / "mesh_base" / "constant" / "polyMesh"

    if not calc_base.is_dir():
        raise FileNotFoundError(f"テンプレートがありません: {calc_base}")
    if not (mesh_source / "boundary").is_file():
        raise FileNotFoundError(f"メッシュがありません: {mesh_source}")

    # Ensure the reusable template includes the seeded initial water region.
    set_fields_dict = calc_base / "system" / "setFieldsDict"
    seed_text = set_fields_dict.read_text(encoding="utf-8")
    if seed_text.count("boxToCell") < 2:
        raise RuntimeError(
            f"{set_fields_dict} に水相の初期領域が2つありません。"
            "テンプレート修正コマンドを先に実行してください。"
        )

    first_number = next_run_number(cases_dir)
    run_dirs = []

    print("\n指定された圧力")
    print(f"  水入口: {args.water_kpa:g} kPa")
    print(f"  油入口: {', '.join(format(p, 'g') for p in args.oil_kpa)} kPa")
    print("  出口: 0 Pa")

    if args.end_time is not None:
        print(f"  今回の endTime: {args.end_time:g} s")
    else:
        print("  endTime: calc_base/system/controlDict の設定を使用")

    # Prepare all requested cases before launching any solver.
    for offset, oil_kpa in enumerate(args.oil_kpa):
        label = (
            f"water{number_label(args.water_kpa)}kPa_"
            f"oil{number_label(oil_kpa)}kPa"
        )
        run_dir = cases_dir / f"run_{first_number + offset:03d}_{label}"

        prepare_case(
            calc_base=calc_base,
            mesh_source=mesh_source,
            run_dir=run_dir,
            water_kpa=args.water_kpa,
            oil_kpa=oil_kpa,
            end_time=args.end_time,
            write_interval=args.write_interval,
        )
        run_dirs.append(run_dir)

    if args.prepare_only:
        print("\n準備のみ完了しました。ソルバーは起動していません。")
        return

    print("\nケースをバックグラウンドで起動します。")
    for run_dir in run_dirs:
        launch_solver(run_dir)

    print("\n起動したケース:")
    for run_dir in run_dirs:
        print(f"  {run_dir}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"\n[FATAL] {exc}", file=sys.stderr)
        sys.exit(1)
