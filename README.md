# OpenFOAM InterFoam Workflow for Pressure-Driven Water/Oil Inlet Cases

This repository provides a reproducible workflow for:

- building a mesh from an STL geometry,
- generating pressure-driven `interFoam` cases from a template,
- running single-core or MPI-parallel simulations,
- post-processing multiple runs into CSV summary tables.

The project is designed to run inside a Docker/devcontainer environment with OpenFOAM preinstalled.

## What This Repository Contains

- `cases/mesh_base/`: mesh generation base case and generated mesh artifacts
- `cases/calc_base/`: simulation template case used to create new runs
- `cases/run_*`: generated simulation cases (created by automation script)
- `cases/test_*`: experimental/test case variants
- `scripts/make_mesh.py`: mesh build pipeline from STL (mm -> m + OpenFOAM meshing)
- `scripts/allrun.py`: run-case generator + launcher (`interFoam`)
- `scripts/data_analysis.py`: post-processing for `S` metric and summary CSVs
- `docker/`: Docker image definition and Python dependencies
- `.devcontainer/`: VS Code devcontainer configuration

## Prerequisites

## 1) Recommended: Docker + VS Code Dev Containers

- Docker Engine + Docker Compose
- VS Code with Dev Containers extension

The repository includes:

- `docker/Dockerfile` with OpenFOAM `v2312` (ESI)
- Python packages for analysis (`numpy`, `pandas`, `scipy`, etc.)

## 2) Alternative: Native Linux Setup

You can run natively if your environment already has:

- OpenFOAM tools (`blockMesh`, `snappyHexMesh`, `setFields`, `interFoam`, etc.)
- Python 3 with dependencies from `docker/requirements.txt`

## Quick Start (Docker)

Build and enter the container:

```bash
docker compose up -d --build
docker compose exec openfoam-env bash
```

Inside the container, run the standard workflow:

```bash
# 1) Build mesh from STL
python3 scripts/make_mesh.py

# 2) Prepare and run cases (example: parallel)
python3 scripts/allrun.py --water-kpa 14.5 --oil-kpa 20 30 --parallel --n-procs 8 --wait

# 3) Analyze all runs under /workspace/cases
python3 scripts/data_analysis.py
```

## Standard Workflow

## Step 1. Prepare Geometry and Build Mesh

Input geometry location:

- `cases/mesh_base/constant/triSurface/flow_channel_mm.stl` (millimeters)

Run:

```bash
python3 scripts/make_mesh.py
```

What it does:

1. Validates STL dimensions are in expected mm range.
2. Converts STL from mm to m (`surfaceTransformPoints`).
3. Executes mesh pipeline:
   - `surfaceCheck`
   - `blockMesh`
   - `surfaceFeatureExtract`
   - `snappyHexMesh -overwrite`
   - `topoSet`
   - `createPatch -overwrite`
   - `checkMesh`
4. Verifies required boundary patches exist and are non-empty:
   - `inlet_oil`
   - `inlet_water`
   - `outlet`

Primary output:

- `cases/mesh_base/constant/polyMesh/`

## Step 2. Generate and Launch Simulation Cases

Run case generation/launch script:

```bash
python3 scripts/allrun.py [options]
```

Main options:

- `--water-kpa <value>`: water inlet pressure in kPa (default: `14.5`)
- `--oil-kpa <v1> <v2> ...`: one or more oil inlet pressures in kPa (default: `20 30`)
- `--end-time <seconds>`: override `system/controlDict` end time
- `--write-interval <seconds>`: override write interval
- `--parallel`: run with MPI (`interFoam -parallel`)
- `--n-procs <N>`: MPI process count (default: `8`)
- `--prepare-only`: create cases but do not launch solver
- `--wait`: block until all launched jobs complete

Example commands:

```bash
# Serial runs for 3 oil pressures
python3 scripts/allrun.py --water-kpa 14.5 --oil-kpa 20 25 30 --wait

# Parallel runs with 4 MPI ranks
python3 scripts/allrun.py --water-kpa 14.5 --oil-kpa 45 --parallel --n-procs 4 --wait

# Prepare only (no solver launch)
python3 scripts/allrun.py --oil-kpa 22 28 35 --prepare-only
```

What the script creates per run:

- New directory: `cases/run_XXX_water..._oil.../`
- Mesh copy from `cases/mesh_base/constant/polyMesh`
- Pressure updates in `0.orig/p_rgh`:
  - `inlet_water` = water pressure [Pa]
  - `inlet_oil` = oil pressure [Pa]
  - `outlet` must remain `0 Pa`
- `0/` initialized from `0.orig/`
- `setFields` execution log: `log.setFields`
- Solver log:
  - serial: `log.interFoam`
  - parallel: `log.interFoam.parallel`

For parallel mode, it also updates `numberOfSubdomains` and runs `decomposePar -force`.

## Step 3. Analyze Results

Run:

```bash
python3 scripts/data_analysis.py
```

The analysis script scans `cases/` for folders matching `oilXXkPa` naming and computes an `S` metric from `alpha.water` fields over time.

Generated outputs at repository root:

- `simulation_summary_by_folder.csv`
- `simulation_summary_by_O.csv`

It also prints mesh-related summary values (`Nz`, `dx`, `dy`, `dz`) for each case in the terminal.

## Repository Structure (High Level)

```text
.
├── cases/
│   ├── calc_base/                  # Template simulation case
│   ├── mesh_base/                  # Mesh-generation base case
│   ├── run_*/                      # Generated run cases
│   └── test_*/                     # Experimental/test cases
├── scripts/
│   ├── make_mesh.py                # Build and validate mesh
│   ├── allrun.py                   # Create/launch runs
│   └── data_analysis.py            # Aggregate results
├── docker/
│   ├── Dockerfile                  # OpenFOAM + Python environment
│   └── requirements.txt
├── docker-compose.yml
└── .devcontainer/
```

## Logs and Troubleshooting

Typical logs:

- Mesh pipeline logs in `cases/mesh_base/`:
  - `log.surfaceTransformPoints`, `log.blockMesh`, `log.snappyHexMesh`, etc.
- Case logs in each `cases/run_*/` folder:
  - `log.setFields`, `log.interFoam` or `log.interFoam.parallel`

If a step fails:

1. Check the corresponding `log.*` tail first.
2. Verify STL is the original millimeter geometry (`flow_channel_mm.stl`).
3. Confirm patch names in fields include:
   - `inlet_water`, `inlet_oil`, `outlet`, `flow_channel`
4. Ensure `cases/mesh_base/constant/polyMesh/boundary` exists before `allrun.py`.

## Notes

- Existing `cases/run_*` and `cases/test_*` directories include prior runs and experiments.
- `.gitignore` is configured to ignore generated `run_*` cases and common mesh/result artifacts.

## License

No license file is currently included in this repository. Add one if you plan to redistribute or publish this project.
