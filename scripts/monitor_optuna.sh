#!/usr/bin/env bash
set -u

project_dir="${1:-/workspace}"
container_name="${2:-biomod_optuna_safe}"
run_log="${3:-${project_dir}/cases/optuna_runtime_safe_1e6.log}"
monitor_log="${4:-${project_dir}/cases/optuna_monitor.log}"
interval="${MONITOR_INTERVAL_SECONDS:-300}"

while true; do
    timestamp="$(date '+%Y-%m-%d %H:%M:%S %Z')"
    completed="$(grep -c 'Trial [0-9][0-9]* finished' "${run_log}" 2>/dev/null || true)"
    pruned="$(grep -c 'Trial [0-9][0-9]* pruned' "${run_log}" 2>/dev/null || true)"
    failures="$(grep -cE 'Trial [0-9]+ failed|FOAM FATAL|Traceback' "${run_log}" 2>/dev/null || true)"
    best="$(grep 'Best is trial' "${run_log}" 2>/dev/null | tail -1 || true)"

    if docker inspect -f '{{.State.Running}}' "${container_name}" 2>/dev/null |
        grep -qx true; then
        status="running"
    else
        status="stopped"
    fi

    printf '[%s] status=%s completed=%s pruned=%s failures=%s %s\n' \
        "${timestamp}" "${status}" "${completed}" "${pruned}" "${failures}" "${best}" \
        >>"${monitor_log}"

    if [[ "${status}" == "stopped" ]]; then
        exit 0
    fi
    sleep "${interval}"
done
