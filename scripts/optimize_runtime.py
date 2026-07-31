#!/usr/bin/env python3
"""Benchmark OpenFOAM MPI layouts with an Optuna study.

Run this script inside the project's OpenFOAM container.  Each trial solves the
same short transient case, so the objective changes execution strategy without
changing the production case's physical model.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

import optuna


RANKS = [8, 12, 16, 20, 24, 32, 48]
EXECUTION_TIME_RE = re.compile(r"ExecutionTime = ([0-9.eE+-]+) s")
ALPHA_RE = re.compile(
    r"Min\(alpha\.water\) = ([0-9.eE+-]+)\s+Max\(alpha\.water\) = ([0-9.eE+-]+)"
)


def run(command: list[str], *, cwd: Path, log: Path | None = None) -> None:
    if log is None:
        subprocess.run(command, cwd=cwd, check=True)
        return
    with log.open("w") as stream:
        subprocess.run(
            command,
            cwd=cwd,
            check=True,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )


def set_dictionary(case: Path, dictionary: str, entry: str, value: str) -> None:
    subprocess.run(
        [
            "foamDictionary",
            str(case / "system" / dictionary),
            "-entry",
            entry,
            "-set",
            value,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
    )


def objective_factory(
    project: Path,
    end_time: float,
    rank_options: list[int],
    placement_options: list[str],
    transport_options: list[str],
    fpe_options: list[str],
    runtime_modifiable_options: list[str],
    allocator_options: list[str],
    numa_options: list[str],
    decomposition_options: list[str],
    solver_options: list[str],
    allreduce_options: list[str],
    solver_performance_options: list[str],
    library_options: list[str],
    file_handler_options: list[str],
    priority_options: list[str],
    trial_root: Path | None,
):
    cases = project / "cases"
    calc_base = cases / "calc_base"
    mesh = cases / "mesh_base" / "constant" / "polyMesh"
    artifacts = cases / "optuna_runtime"
    artifacts.mkdir(exist_ok=True)
    case_root = trial_root or artifacts
    case_root.mkdir(parents=True, exist_ok=True)

    def objective(trial: optuna.Trial) -> float:
        ranks = trial.suggest_categorical("mpi_ranks", rank_options)
        placement_mode = trial.suggest_categorical("placement", placement_options)
        transport_mode = trial.suggest_categorical(
            "mpi_transport", transport_options
        )
        fpe_mode = trial.suggest_categorical("fpe_trap", fpe_options)
        runtime_modifiable = trial.suggest_categorical(
            "runtime_modifiable", runtime_modifiable_options
        )
        allocator = trial.suggest_categorical("allocator", allocator_options)
        numa_policy = trial.suggest_categorical("numa_policy", numa_options)
        decomposition = trial.suggest_categorical(
            "decomposition", decomposition_options
        )
        solver_binary = trial.suggest_categorical("solver_binary", solver_options)
        allreduce_algorithm = trial.suggest_categorical(
            "allreduce_algorithm", allreduce_options
        )
        solver_performance = trial.suggest_categorical(
            "solver_performance_log", solver_performance_options
        )
        library_mode = trial.suggest_categorical("library_mode", library_options)
        file_handler = trial.suggest_categorical(
            "file_handler", file_handler_options
        )
        priority_mode = trial.suggest_categorical(
            "process_priority", priority_options
        )
        # Numerical algorithms stay identical to calc_base.  The optimizer may
        # tune execution layout only; it must not change the solution method.
        p_preconditioner = "DIC"
        u_smoother = "symGaussSeidel"
        case = case_root / f"trial_{trial.number:03d}"
        shutil.rmtree(case, ignore_errors=True)
        shutil.copytree(calc_base, case)
        shutil.copytree(mesh, case / "constant" / "polyMesh")
        shutil.copytree(case / "0.orig", case / "0")

        set_dictionary(case, "controlDict", "endTime", str(end_time))
        set_dictionary(case, "controlDict", "writeInterval", "1")
        set_dictionary(case, "controlDict", "writeFormat", "binary")
        set_dictionary(
            case, "controlDict", "runTimeModifiable", runtime_modifiable
        )
        set_dictionary(
            case, "decomposeParDict", "numberOfSubdomains", str(ranks)
        )
        set_dictionary(case, "decomposeParDict", "method", decomposition)
        run(["setFields", "-case", str(case)], cwd=project)
        run(
            ["decomposePar", "-case", str(case), "-force"],
            cwd=project,
            log=case / "log.decomposePar",
        )

        if placement_mode == "unbound":
            placement = []
        elif ranks <= 24 and placement_mode == "balanced_sockets":
            placement = [
                "--bind-to",
                "core",
                "--map-by",
                f"ppr:{ranks // 2}:socket",
            ]
        elif ranks <= 24 and placement_mode == "sequential_hwthread_bind":
            placement = ["--bind-to", "hwthread", "--map-by", "core"]
        elif ranks <= 24:
            placement = ["--bind-to", "core", "--map-by", "core"]
        else:
            placement = [
                "--use-hwthread-cpus",
                "--bind-to",
                "hwthread",
                "--map-by",
                "hwthread",
            ]
        if transport_mode in {
            "shared_memory",
            "shared_memory_shm_tmp",
            "shared_memory_isolated",
        }:
            transport = ["--mca", "pml", "ob1", "--mca", "btl", "self,vader"]
            if transport_mode == "shared_memory_shm_tmp":
                transport += ["--mca", "orte_tmpdir_base", "/dev/shm"]
            elif transport_mode == "shared_memory_isolated":
                transport += ["--mca", "plm", "isolated"]
        else:
            transport = []
        if allreduce_algorithm != "default":
            transport += [
                "--mca",
                "coll_tuned_use_dynamic_rules",
                "1",
                "--mca",
                "coll_tuned_allreduce_algorithm",
                allreduce_algorithm,
            ]

        solver_log = case / "log.interFoam"
        environment = ["env", f"FOAM_SIGFPE={fpe_mode}"]
        native_library_directories = {
            "native_finite_volume": "/workspace/native_fv_only",
            "native_core": "/workspace/native_core_only",
            "native_stack": "/workspace/native_lib",
            "native_core_lto": "/workspace/native_core_lto",
            "native_stack_lto": "/workspace/native_stack_lto",
            "native_full_lto": "/workspace/native_full_lto",
            "native_full_lto_pstream": "/workspace/native_full_lto_pstream",
            "native_physics_lto": "/workspace/native_physics_lto",
            "native_transport_lto": "/workspace/native_transport_lto",
            "native_fv_pgo_generate": "/workspace/native_fv_pgo_generate",
            "native_fv_pgo": "/workspace/native_fv_pgo",
            "native_fv_pgo_nointerpose_generate": "/workspace/native_fv_pgo_nointerpose_generate",
            "native_fv_pgo_nointerpose": "/workspace/native_fv_pgo_nointerpose",
            "native_fv_pgo_one_partition": "/workspace/native_fv_pgo_one_partition",
            "native_fv_nointerpose": "/workspace/native_fv_nointerpose",
        }
        if library_mode in native_library_directories:
            environment.append(
                f"LD_LIBRARY_PATH={native_library_directories[library_mode]}:"
                "/root/OpenFOAM/user-v2312/platforms/"
                "linux64GccDPInt32Opt/lib:"
                "/usr/lib/openfoam/openfoam2312/site/2312/platforms/"
                "linux64GccDPInt32Opt/lib:"
                "/usr/lib/openfoam/openfoam2312/platforms/"
                "linux64GccDPInt32Opt/lib/sys-openmpi:"
                "/usr/lib/openfoam/openfoam2312/platforms/"
                "linux64GccDPInt32Opt/lib:"
                "/usr/lib/x86_64-linux-gnu/openmpi/lib:"
                "/usr/lib/openfoam/openfoam2312/platforms/"
                "linux64GccDPInt32Opt/lib/dummy"
            )
        if allocator.startswith("jemalloc"):
            environment.append(
                "LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2"
            )
        if allocator == "jemalloc_single_arena":
            environment.append(
                "MALLOC_CONF=narenas:1,background_thread:false,"
                "dirty_decay_ms:-1,muzzy_decay_ms:-1"
            )
        elif allocator == "jemalloc_four_arenas":
            environment.append(
                "MALLOC_CONF=narenas:4,background_thread:false,"
                "dirty_decay_ms:-1,muzzy_decay_ms:-1"
            )
        elif allocator == "jemalloc_thp":
            environment.append(
                "MALLOC_CONF=background_thread:false,dirty_decay_ms:-1,"
                "muzzy_decay_ms:-1,thp:always,metadata_thp:always"
            )
        elif allocator == "jemalloc_single_arena_thp":
            environment.append(
                "MALLOC_CONF=narenas:1,background_thread:false,"
                "dirty_decay_ms:-1,muzzy_decay_ms:-1,"
                "thp:always,metadata_thp:always"
            )
        elif allocator == "tcmalloc":
            environment.append(
                "LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libtcmalloc_minimal.so.4"
            )
        if numa_policy == "localalloc":
            numa_prefix = ["numactl", "--localalloc"]
        elif numa_policy == "interleave":
            numa_prefix = ["numactl", "--interleave=all"]
        else:
            numa_prefix = []
        priority_prefix = ["nice", "-n", "-20"] if priority_mode == "high" else []
        started = time.perf_counter()
        solver_arguments = []
        if solver_performance == "false":
            solver_arguments = ["-info-switch", "SolverPerformance=0"]
        try:
            run(
                [
                    *numa_prefix,
                    *priority_prefix,
                    *environment,
                    "mpirun",
                    "--allow-run-as-root",
                    *placement,
                    *transport,
                    "-np",
                    str(ranks),
                    solver_binary,
                    *solver_arguments,
                    "-parallel",
                    "-fileHandler",
                    file_handler,
                    "-case",
                    str(case),
                ],
                cwd=project,
                log=solver_log,
            )
        except subprocess.CalledProcessError:
            trial.set_user_attr("failed_log", str(solver_log))
            raise
        wall_seconds = time.perf_counter() - started

        log_text = solver_log.read_text(errors="replace")
        matches = EXECUTION_TIME_RE.findall(log_text)
        foam_seconds = float(matches[-1]) if matches else None
        alpha_matches = ALPHA_RE.findall(log_text)
        if not alpha_matches:
            raise optuna.TrialPruned("alpha.water bounds were not reported")
        alpha_min, alpha_max = map(float, alpha_matches[-1])
        trial.set_user_attr("alpha_min", alpha_min)
        trial.set_user_attr("alpha_max", alpha_max)
        if alpha_min < -1e-6 or alpha_max > 1.0001:
            raise optuna.TrialPruned(
                f"unstable alpha.water bounds: [{alpha_min}, {alpha_max}]"
            )
        trial.set_user_attr("openfoam_execution_seconds", foam_seconds)
        trial.set_user_attr("wall_seconds", wall_seconds)

        summary = {
            "trial": trial.number,
            "mpi_ranks": ranks,
            "placement": placement_mode,
            "mpi_transport": transport_mode,
            "fpe_trap": fpe_mode,
            "runtime_modifiable": runtime_modifiable,
            "allocator": allocator,
            "numa_policy": numa_policy,
            "decomposition": decomposition,
            "solver_binary": solver_binary,
            "allreduce_algorithm": allreduce_algorithm,
            "solver_performance_log": solver_performance,
            "library_mode": library_mode,
            "file_handler": file_handler,
            "process_priority": priority_mode,
            "p_preconditioner": p_preconditioner,
            "u_smoother": u_smoother,
            "file_handler": file_handler,
            "wall_seconds": wall_seconds,
            "openfoam_execution_seconds": foam_seconds,
            "alpha_min": alpha_min,
            "alpha_max": alpha_max,
        }
        (artifacts / f"trial_{trial.number:03d}.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
        shutil.rmtree(case)
        return wall_seconds

    return objective


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trials", type=int, default=48)
    parser.add_argument("--end-time", type=float, default=5e-6)
    parser.add_argument("--study-name")
    parser.add_argument("--storage-file", type=Path)
    parser.add_argument(
        "--trial-root",
        type=Path,
        help="Optional fast local filesystem for temporary trial cases",
    )
    parser.add_argument(
        "--ranks",
        default=",".join(map(str, RANKS)),
        help="Comma-separated MPI rank choices",
    )
    parser.add_argument(
        "--placements",
        default="sequential_cores,balanced_sockets",
        help="Comma-separated MPI placement choices",
    )
    parser.add_argument(
        "--transports",
        default="default",
        help="Comma-separated MPI transport choices: default,shared_memory",
    )
    parser.add_argument(
        "--fpe-modes",
        default="true",
        help="Comma-separated FOAM_SIGFPE values",
    )
    parser.add_argument(
        "--runtime-modifiable-options",
        default="true",
        help="Comma-separated runTimeModifiable values",
    )
    parser.add_argument(
        "--allocators",
        default="system",
        help="Comma-separated allocator choices: system,jemalloc",
    )
    parser.add_argument(
        "--numa-policies",
        default="default",
        help="Comma-separated NUMA policies: default,localalloc,interleave",
    )
    parser.add_argument(
        "--decomposition-methods",
        default="scotch",
        help="Comma-separated methods: scotch,simple,hierarchical",
    )
    parser.add_argument(
        "--solvers",
        default="interFoam",
        help="Comma-separated solver executable choices",
    )
    parser.add_argument(
        "--allreduce-algorithms",
        default="default",
        help="Comma-separated OpenMPI tuned Allreduce algorithm numbers",
    )
    parser.add_argument(
        "--solver-performance-options",
        default="true",
        help="Comma-separated SolverPerformance logging values",
    )
    parser.add_argument(
        "--library-modes",
        default="system",
        help=(
            "Comma-separated library choices: system,native_finite_volume,"
            "native_core,native_stack,native_core_lto,native_stack_lto,"
            "native_full_lto,native_full_lto_pstream,native_physics_lto,"
            "native_transport_lto,native_fv_pgo_generate,native_fv_pgo,"
            "native_fv_pgo_nointerpose_generate,native_fv_pgo_nointerpose,"
            "native_fv_pgo_one_partition,"
            "native_fv_nointerpose"
        ),
    )
    parser.add_argument(
        "--enqueue-library-rounds",
        type=int,
        default=0,
        help=(
            "Before optimization, enqueue this many balanced round-robin "
            "repetitions of every requested library mode"
        ),
    )
    parser.add_argument(
        "--enqueue-runtime-rounds",
        type=int,
        default=0,
        help=(
            "Before optimization, enqueue this many balanced repetitions of "
            "every requested MPI transport and allocator combination"
        ),
    )
    parser.add_argument(
        "--enqueue-solver-rounds",
        type=int,
        default=0,
        help=(
            "Before optimization, enqueue this many balanced repetitions of "
            "every requested solver binary"
        ),
    )
    parser.add_argument(
        "--file-handlers",
        default="uncollated",
        help="Comma-separated OpenFOAM file handlers: uncollated,collated",
    )
    parser.add_argument(
        "--process-priorities",
        default="default",
        help="Comma-separated process priorities: default,high",
    )
    parser.add_argument(
        "--project",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    args = parser.parse_args()
    rank_options = [int(value) for value in args.ranks.split(",")]
    placement_options = args.placements.split(",")
    transport_options = args.transports.split(",")
    fpe_options = args.fpe_modes.split(",")
    runtime_modifiable_options = args.runtime_modifiable_options.split(",")
    allocator_options = args.allocators.split(",")
    numa_options = args.numa_policies.split(",")
    decomposition_options = args.decomposition_methods.split(",")
    solver_options = args.solvers.split(",")
    allreduce_options = args.allreduce_algorithms.split(",")
    solver_performance_options = args.solver_performance_options.split(",")
    library_options = args.library_modes.split(",")
    file_handler_options = args.file_handlers.split(",")
    priority_options = args.process_priorities.split(",")
    trial_root = args.trial_root.resolve() if args.trial_root else None

    project = args.project.resolve()
    study_name = args.study_name or f"interfoam_runtime_{args.end_time:.0e}"
    storage_file = args.storage_file or (
        project / "cases" / f"optuna_runtime_{args.end_time:.0e}.db"
    )
    if not storage_file.is_absolute():
        storage_file = project / storage_file
    storage = f"sqlite:///{storage_file.resolve()}"
    sampler = optuna.samplers.TPESampler(
        seed=2026,
        multivariate=True,
        n_startup_trials=8,
    )
    study = optuna.create_study(
        study_name=study_name,
        direction="minimize",
        storage=storage,
        load_if_exists=True,
        sampler=sampler,
    )
    if not study.trials:
        fixed_layout = {
            "mpi_ranks": 24 if 24 in rank_options else rank_options[0],
            "placement": (
                "sequential_cores"
                if "sequential_cores" in placement_options
                else placement_options[0]
            ),
        }
        if args.enqueue_solver_rounds > 0:
            for _ in range(args.enqueue_solver_rounds):
                for solver_binary in solver_options:
                    study.enqueue_trial(
                        {**fixed_layout, "solver_binary": solver_binary}
                    )
        elif args.enqueue_runtime_rounds > 0:
            for _ in range(args.enqueue_runtime_rounds):
                for transport_mode in transport_options:
                    for allocator in allocator_options:
                        study.enqueue_trial(
                            {
                                **fixed_layout,
                                "mpi_transport": transport_mode,
                                "allocator": allocator,
                            }
                        )
        elif args.enqueue_library_rounds > 0:
            for _ in range(args.enqueue_library_rounds):
                for library_mode in library_options:
                    study.enqueue_trial(
                        {**fixed_layout, "library_mode": library_mode}
                    )
        else:
            study.enqueue_trial(fixed_layout)
    study.optimize(
        objective_factory(
            project,
            args.end_time,
            rank_options,
            placement_options,
            transport_options,
            fpe_options,
            runtime_modifiable_options,
            allocator_options,
            numa_options,
            decomposition_options,
            solver_options,
            allreduce_options,
            solver_performance_options,
            library_options,
            file_handler_options,
            priority_options,
            trial_root,
        ),
        n_trials=args.trials,
        gc_after_trial=True,
    )

    print(f"best wall time: {study.best_value:.3f} s")
    print(f"best parameters: {study.best_params}")


if __name__ == "__main__":
    main()
