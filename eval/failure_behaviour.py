"""Failure-behaviour test: what the system does while a fault is injected into the model server, then restored.

A fixed-concurrency closed loop keeps running while operator-supplied commands inject and later restore a fault (for
example stalling or killing the model server process). The run records error rates before, during and after the fault,
time to first error, time to recovery, the `/health/serving` timeline against its documented behaviour, and whether any
request succeeded while the fault was active.

For `LLM_PROVIDER=local` the documented behaviour is that there is NO hosted fallback: failures surface to the caller.
This test confirms that; it does not add or exercise any fallback. It measures one fault on one deployment.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import shlex
import subprocess
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.core.config import settings
from app.services import llm
from eval.serving_load import (DEPLOYMENT_FIELDS, ArtifactWriter, api_request, http_url, positive_float, positive_int,
                               read_token, replay_request, run_cell, source_provenance)
from eval.workloads import load_workloads

DOCUMENTED_FALLBACK = "none for provider local: failures surface to the caller; no hosted fallback exists"


def _window_stats(rows):
    by_status = {}
    for row in rows:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    ok = by_status.get("ok", 0)
    return {"offered": len(rows), "ok": ok, "error_rate": (len(rows) - ok) / len(rows) if rows else None,
            "by_status": by_status}


def _health(probes, faults):
    inject, restore = faults["inject_at_s"], faults["restore_at_s"]
    empty = {"probed": False, "probes": 0,
             "documented_behaviour": {"healthy_before_fault": None, "unhealthy_during_fault": None,
                                      "healthy_after_restore": None},
             "matches_documentation": None, "first_unhealthy_after_inject_s": None,
             "healthy_again_after_restore_s": None}
    if not probes:
        return empty
    up = lambda probe: probe.get("status") == 200  # noqa: E731 - any non-200 or connection error is "not healthy"
    ordered = sorted(probes, key=lambda probe: probe["t"])
    before = [p for p in ordered if p["t"] < inject]
    during = [p for p in ordered if inject <= p["t"] < restore]
    after = [p for p in ordered if p["t"] >= restore]
    down_after_inject = [p["t"] for p in ordered if p["t"] >= inject and not up(p)]
    up_after_restore = [p["t"] for p in after if up(p)]
    documented = {"healthy_before_fault": all(up(p) for p in before) if before else None,
                  "unhealthy_during_fault": any(not up(p) for p in during) if during else None,
                  "healthy_after_restore": bool(up_after_restore) if after else None}
    values = list(documented.values())
    matches = False if False in values else (None if None in values else True)
    return {"probed": True, "probes": len(ordered), "documented_behaviour": documented, "matches_documentation": matches,
            "first_unhealthy_after_inject_s": (down_after_inject[0] - inject) if down_after_inject else None,
            "healthy_again_after_restore_s": (up_after_restore[0] - restore) if up_after_restore else None}


def analyze(requests, health_probes, faults, *, duration_s):
    """Pure analysis. All times are seconds from the start of the load.

    requests: request rows as written by the load cell (status, dispatch_offset_s, scheduled_offset_s, total_s).
    health_probes: [{"t", "status", "error_type"?}]. faults: inject_at_s, inject_returned_s, restore_at_s,
    restore_returned_s and the commands' exit codes.
    """
    rows = [{**row, "dispatched": row["dispatch_offset_s"], "done": row["scheduled_offset_s"] + row["total_s"]}
            for row in requests if "dispatch_offset_s" in row]
    inject, restore = faults["inject_at_s"], faults["restore_at_s"]
    inject_returned = faults.get("inject_returned_s") or inject
    restore_returned = faults.get("restore_returned_s")
    # `before` is requests that COMPLETED before the injection, so the baseline is clean. The inject command takes time
    # to run (an SSH round trip), and the fault lands somewhere between "issued" and "returned". Requests that were in
    # flight when it was issued, or were sent before it returned, are in `injection_transition`; `during` starts only
    # once the command has returned and the fault is in effect.
    windows = {"before": [r for r in rows if r["done"] < inject],
               "injection_transition": [r for r in rows if r["done"] >= inject and r["dispatched"] < inject_returned],
               "during": [r for r in rows if inject_returned <= r["dispatched"] < restore],
               "after": [r for r in rows if r["dispatched"] >= restore]}
    failed_after_inject = [r["done"] for r in rows if r["status"] != "ok" and r["done"] >= inject]
    recovered = [r["done"] for r in rows if r["status"] == "ok" and r["dispatched"] >= restore]
    recovered_after_return = ([r["done"] for r in rows if r["status"] == "ok" and r["dispatched"] >= restore_returned]
                              if restore_returned is not None else [])
    served_while_faulted = [r for r in rows if r["status"] == "ok" and r["dispatched"] >= inject_returned
                            and r["done"] < restore]
    observations = []
    if not failed_after_inject:
        observations.append("no error was observed after the fault was injected; the fault may not have taken effect")
    if not recovered:
        observations.append("no successful request was dispatched after the restore; recovery is not claimed")
    unexpected = len(served_while_faulted)
    if unexpected:
        observations.append(f"UNEXPECTED: {unexpected} request(s) succeeded while the fault was active")
    window_stats = {name: _window_stats(window) for name, window in windows.items()}
    # Requests sent just before the restore can finish after it and succeed. They stay in `during` (that is when they
    # were sent) but are counted separately so the headline error rate is not misread.
    late = [r for r in windows["during"] if r["done"] >= restore]
    window_stats["during"]["of_which_finished_after_restore"] = {
        "offered": len(late), "ok": sum(r["status"] == "ok" for r in late)}
    return {
        "load_duration_s": duration_s, "fault": dict(faults),
        "windows": window_stats,
        "time_to_first_error_s": (min(failed_after_inject) - inject) if failed_after_inject else None,
        "time_to_recovery_s": (min(recovered) - restore) if recovered else None,
        "time_to_recovery_after_restore_returned_s": ((min(recovered_after_return) - restore_returned)
                                                       if recovered_after_return else None),
        "recovered_by_end": bool(recovered),
        "fallback_behaviour": {
            "documented": DOCUMENTED_FALLBACK, "succeeded_while_fault_active": unexpected,
            "observed": ("no fallback observed: no request succeeded while the fault was active" if not unexpected else
                         f"UNEXPECTED: {unexpected} request(s) succeeded while the fault was active; either the fault "
                         "did not take effect or something other than the model server answered")},
        "health_serving": _health(health_probes, faults), "observations": observations}


class FaultCommandError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc)


async def run_command(command, timeout_s):
    """Run an operator-supplied command without a shell; return its exit code, or None on timeout. Output is discarded."""
    process = await asyncio.create_subprocess_exec(*shlex.split(command), stdout=subprocess.DEVNULL,
                                                   stderr=subprocess.DEVNULL)
    try:
        return await asyncio.wait_for(process.wait(), timeout_s)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    except BaseException:
        process.kill()
        raise


def command_sha256(command):
    return hashlib.sha256(command.encode()).hexdigest()


async def run_failure_behaviour(*, cases, request, out_dir, manifest, concurrency, duration_s, timeout_s, fault_at_s,
                                fault_duration_s, inject, restore, health=None, health_interval_s=1.0,
                                command_hashes=None):
    """Hold a fixed-concurrency closed loop while `inject` and later `restore` run; write artifacts; return the analysis.

    `inject` and `restore` are async callables returning an exit code (0 = success). After any attempted inject the
    restore always runs exactly once, even if the run is cancelled or fails, so a faulted server is not left faulted.
    `health` is an optional async callable returning (http_status | None, error_type | None).
    """
    if fault_at_s + fault_duration_s >= duration_s:
        raise ValueError("the fault must end before the load does, leaving time to observe recovery")
    writer = ArtifactWriter(Path(out_dir), manifest)
    hashes = command_hashes or {}
    rows, probes, marks = [], [], {}
    loop = asyncio.get_running_loop()
    started = loop.time()

    def write(record):
        if record.get("event") == "request":
            rows.append(record)
        writer.write(record)

    async def perform(kind, action):
        issued = _now()
        code = await action()
        returned = _now()
        marks[kind] = {"issued": issued, "returned": returned, "exit": code}
        writer.write({"event": "fault_event", "kind": kind, "issued_at": issued.isoformat(),
                      "returned_at": returned.isoformat(), "exit_code": code, "command_sha256": hashes.get(kind)})
        return code

    async def controller():
        attempted = False
        try:
            await asyncio.sleep(max(0.0, started + fault_at_s - loop.time()))
            attempted = True
            if await perform("inject", inject) != 0:
                raise FaultCommandError(f"inject command failed (exit {marks['inject']['exit']})")
            await asyncio.sleep(max(0.0, started + fault_at_s + fault_duration_s - loop.time()))
            attempted = False
            if await perform("restore", restore) != 0:
                raise FaultCommandError(f"restore command failed (exit {marks['restore']['exit']}); the server may "
                                        "still be faulted")
        finally:
            if attempted:
                await perform("restore", restore)

    async def poller(stop):
        while not stop.is_set():
            begun = loop.time()
            status, error_type = await health()
            record = {"event": "health_probe", "ts": _now().isoformat(), "status": status, "error_type": error_type,
                      "latency_s": loop.time() - begun}
            probes.append(record)
            writer.write(record)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), health_interval_s)

    stop = asyncio.Event()
    load = asyncio.create_task(run_cell(cases, request, concurrency=concurrency, duration_s=duration_s,
                                        max_requests=10**9, timeout_s=timeout_s, write=write,
                                        cell_id="failure-behaviour", phase="measurement"))
    control = asyncio.create_task(controller())
    watcher = asyncio.create_task(poller(stop)) if health else None
    outcome, analysis = "error", None
    try:
        cell, _ = await asyncio.gather(load, control)
        begin = datetime.fromisoformat(cell["window"]["started_at"])
        offset = lambda moment: (moment - begin).total_seconds()  # noqa: E731
        faults = {"inject_at_s": offset(marks["inject"]["issued"]), "inject_returned_s": offset(marks["inject"]["returned"]),
                  "restore_at_s": offset(marks["restore"]["issued"]),
                  "restore_returned_s": offset(marks["restore"]["returned"]),
                  "inject_exit": marks["inject"]["exit"], "restore_exit": marks["restore"]["exit"]}
        inputs = [{"t": offset(datetime.fromisoformat(p["ts"])), "status": p["status"], "error_type": p["error_type"]}
                  for p in probes]
        analysis = analyze(rows, inputs, faults, duration_s=cell["summary"]["wall_s"])
        writer.write({"event": "failure_behaviour_summary", **analysis})
        outcome = "complete"
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    finally:
        stop.set()
        for task in (load, control):
            if not task.done():
                task.cancel()
        await asyncio.gather(load, control, return_exceptions=True)   # lets the controller's cleanup restore the fault
        if watcher:
            await asyncio.gather(watcher, return_exceptions=True)
        writer.write({"event": "run_end", "outcome": outcome, "timestamp": _now().isoformat()})
        writer.close()
    return analysis


def make_http_probe(client, url, timeout_s):
    async def probe():
        try:
            response = await client.get(url, timeout=timeout_s)
            return response.status_code, None
        except Exception as exc:  # noqa: BLE001 - any failure to answer is an unhealthy probe; keep only the type
            return None, type(exc).__name__
    return probe


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--workloads", type=Path, required=True)
    parser.add_argument("--target", choices=["replay", "api"], default="replay")
    parser.add_argument("--provider", choices=["groq", "mistral", "openai", "local"], default="local")
    parser.add_argument("--api-base-url", type=http_url, default="http://127.0.0.1:8081/api/v1/")
    parser.add_argument("--auth-token-file", type=Path)
    parser.add_argument("--deployment-manifest", type=Path)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--concurrency", type=positive_int, default=16)
    parser.add_argument("--duration", type=positive_float, default=180)
    parser.add_argument("--timeout", type=positive_float, default=60)
    parser.add_argument("--cache-mode", choices=["bust", "reuse"], default="bust")
    parser.add_argument("--fault-at", type=positive_float, default=30, help="seconds after the load starts")
    parser.add_argument("--fault-duration", type=positive_float, default=60, help="seconds the fault stays injected")
    parser.add_argument("--inject-cmd", help="command that injects the fault (run without a shell; recorded only as a hash)")
    parser.add_argument("--restore-cmd", help="command that undoes the fault (run without a shell; recorded only as a hash)")
    parser.add_argument("--command-timeout", type=positive_float, default=600)
    parser.add_argument("--health-url", type=http_url, help="the app's /api/v1/health/serving, polled during the run")
    parser.add_argument("--health-token-file", type=Path)
    parser.add_argument("--health-interval", type=positive_float, default=1.0)
    parser.add_argument("--yes-run-fault-commands", action="store_true",
                        help="required to actually execute the inject and restore commands")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.inject_cmd or not args.restore_cmd:
        parser.error("--inject-cmd and --restore-cmd are both required")
    if args.fault_at + args.fault_duration >= args.duration:
        parser.error("--fault-at plus --fault-duration must be less than --duration (time to observe recovery)")
    if args.target == "api" and not args.auth_token_file and not args.validate_only:
        parser.error("API runs require --auth-token-file")
    if args.target == "api" and args.cache_mode == "bust":
        args.cache_mode = "reuse"   # API mode preserves queries
    if not args.validate_only and not args.yes_run_fault_commands:
        parser.error("refusing to run fault commands without --yes-run-fault-commands")
    return args


async def main(argv=None):
    args = parse_args(argv)
    workloads = load_workloads(args.workloads, args.target)
    if args.validate_only:
        print(json.dumps({"valid": True, "cases": len(workloads.cases), "workload_sha256": workloads.fingerprint()}))
        return None
    deployment = json.loads(args.deployment_manifest.read_text()) if args.deployment_manifest else None
    hashes = {"inject": command_sha256(args.inject_cmd), "restore": command_sha256(args.restore_cmd)}
    manifest = {
        "schema_version": 2, "mode": "failure_behaviour", "run_id": str(uuid.uuid4()),
        "created_at": _now().isoformat(), "target": args.target,
        "provider": args.provider if args.target == "replay" else "remote_application",
        "workload_sha256": workloads.fingerprint(), "corpus_sha256": workloads.corpus_sha256,
        "deployment": {k: v for k, v in (deployment or {}).items() if k in DEPLOYMENT_FIELDS},
        "source": source_provenance(), "concurrency": args.concurrency, "duration_s": args.duration,
        "timeout_s": args.timeout, "cache_mode": args.cache_mode,
        "fault": {"inject_at_s": args.fault_at, "duration_s": args.fault_duration,
                  "inject_command_sha256": hashes["inject"], "restore_command_sha256": hashes["restore"]},
        "health_probe": {"enabled": bool(args.health_url), "interval_s": args.health_interval,
                         "documented": "GET /api/v1/health/serving returns 200 when the configured model is listed "
                                       "and 503 when the probe fails"},
        "documented_fallback": DOCUMENTED_FALLBACK,
        "notes": ["One fault on one deployment; not an availability or reliability claim",
                  "No hosted fallback exists for provider local; this test does not add or exercise one",
                  "Commands are recorded only as hashes and exit codes"]}
    original = (settings.llm_provider, settings.fallback_llm_provider, settings.groq_fallback_chat_model)
    try:
        if args.target == "replay":
            await llm.close_llm_clients()
            settings.llm_provider, settings.fallback_llm_provider, settings.groq_fallback_chat_model = (
                args.provider, "none", "")
            if args.provider == "local":
                llm.validate_local_endpoint()
        async with httpx.AsyncClient(base_url=args.api_base_url.rstrip("/") + "/",
                                     headers=read_token(args.auth_token_file), timeout=args.timeout) as api_client, \
                   httpx.AsyncClient(headers=read_token(args.health_token_file)) as health_client:
            async def request(case, identifier):
                if args.target == "api":
                    return await api_request(api_client, case, identifier)
                return await replay_request(case, identifier, args.cache_mode)
            health = make_http_probe(health_client, args.health_url, 5.0) if args.health_url else None
            analysis = await run_failure_behaviour(
                cases=workloads.cases, request=request, out_dir=args.out_dir, manifest=manifest,
                concurrency=args.concurrency, duration_s=args.duration, timeout_s=args.timeout,
                fault_at_s=args.fault_at, fault_duration_s=args.fault_duration,
                inject=lambda: run_command(args.inject_cmd, args.command_timeout),
                restore=lambda: run_command(args.restore_cmd, args.command_timeout),
                health=health, health_interval_s=args.health_interval, command_hashes=hashes)
        print(json.dumps({key: analysis[key] for key in ("time_to_first_error_s", "time_to_recovery_s", "recovered_by_end",
                                                         "observations")}, indent=2))
        return analysis
    finally:
        settings.llm_provider, settings.fallback_llm_provider, settings.groq_fallback_chat_model = original
        if args.target == "replay":
            await llm.close_llm_clients()
