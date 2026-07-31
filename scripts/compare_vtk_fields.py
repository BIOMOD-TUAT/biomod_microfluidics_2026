#!/usr/bin/env python3
"""Compare cell and point arrays in two OpenFOAM-generated VTU files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import vtk
from vtk.util.numpy_support import vtk_to_numpy


def read_vtu(path: Path) -> vtk.vtkUnstructuredGrid:
    reader = vtk.vtkXMLUnstructuredGridReader()
    reader.SetFileName(str(path))
    reader.Update()
    grid = reader.GetOutput()
    if grid is None or grid.GetNumberOfCells() == 0:
        raise RuntimeError(f"no cells read from {path}")
    return grid


def arrays(attributes: vtk.vtkDataSetAttributes) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for index in range(attributes.GetNumberOfArrays()):
        vtk_array = attributes.GetArray(index)
        if vtk_array is not None and vtk_array.GetName():
            result[vtk_array.GetName()] = vtk_to_numpy(vtk_array)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--rtol", type=float, default=1e-12)
    parser.add_argument("--atol", type=float, default=1e-14)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    reference = read_vtu(args.reference)
    candidate = read_vtu(args.candidate)
    if (
        reference.GetNumberOfCells() != candidate.GetNumberOfCells()
        or reference.GetNumberOfPoints() != candidate.GetNumberOfPoints()
    ):
        raise SystemExit("mesh size differs")

    report: dict[str, object] = {
        "reference": str(args.reference),
        "candidate": str(args.candidate),
        "rtol": args.rtol,
        "atol": args.atol,
        "arrays": {},
    }
    failed = False
    for location, reference_attributes, candidate_attributes in (
        ("cell", reference.GetCellData(), candidate.GetCellData()),
        ("point", reference.GetPointData(), candidate.GetPointData()),
    ):
        reference_arrays = arrays(reference_attributes)
        candidate_arrays = arrays(candidate_attributes)
        if reference_arrays.keys() != candidate_arrays.keys():
            missing = sorted(reference_arrays.keys() - candidate_arrays.keys())
            extra = sorted(candidate_arrays.keys() - reference_arrays.keys())
            raise SystemExit(
                f"{location} array names differ: missing={missing}, extra={extra}"
            )
        for name in sorted(reference_arrays):
            left = reference_arrays[name]
            right = candidate_arrays[name]
            if left.shape != right.shape:
                raise SystemExit(
                    f"{location}/{name} shape differs: {left.shape} != {right.shape}"
                )
            delta = np.abs(left - right)
            scale = np.maximum(np.abs(left), np.abs(right))
            max_abs = float(delta.max(initial=0.0))
            relative = np.divide(
                delta,
                scale,
                out=np.zeros_like(delta, dtype=float),
                where=scale != 0,
            )
            max_rel = float(relative.max(initial=0.0))
            passed = bool(
                np.allclose(
                    left,
                    right,
                    rtol=args.rtol,
                    atol=args.atol,
                    equal_nan=True,
                )
            )
            report["arrays"][f"{location}/{name}"] = {
                "shape": left.shape,
                "max_abs": max_abs,
                "max_rel": max_rel,
                "passed": passed,
            }
            failed |= not passed
            print(
                f"{location}/{name}: max_abs={max_abs:.6e} "
                f"max_rel={max_rel:.6e} passed={passed}"
            )

    if args.json:
        args.json.write_text(json.dumps(report, indent=2) + "\n")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
