"""Serial local control for the externally selected focused-53 generation."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from src import paper1_g07_runtime as g07
from src import paper1_focused53_deployment as focused


class FocusedRunError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_selection(root: Path, path: Path, expected_sha256: str) -> focused.DeploymentSelection:
    return focused.DeploymentSelection(root, path, expected_sha256)


def control_root(release: focused.DeploymentSelection) -> Path:
    return release.output_root.parent / ("focused53_control_" + release.sha256[:16])


def append_progress(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps({"timestamp_utc": now(), **payload}, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def exclusive_worker(release: focused.DeploymentSelection):
    root = control_root(release)
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "focused53.worker.lock"
    try:
        descriptor = os.open(str(lock), os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    except FileExistsError as exc:
        raise FocusedRunError("FOCUSED53_WORKER_LOCK_PRESENT") from exc
    try:
        with os.fdopen(descriptor, "w", encoding="ascii", newline="\n") as handle:
            handle.write(json.dumps({"pid": os.getpid(), "started_utc": now()}) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        yield
    finally:
        lock.unlink(missing_ok=False)


def status(release: focused.DeploymentSelection) -> dict[str, object]:
    focused.reject_foreign_outputs(release)
    states = focused.unit_states(release)
    counts = {name: sum(item["status"] == name for item in states) for name in (
        "UNSTARTED", "STARTED", "STAGED_WAITING_PAIR", "COMPLETE"
    )}
    return {
        "schema": "PAPER1_FOCUSED53_STATUS_V1",
        "selection_sha256": release.sha256,
        "producer_commit": release.payload["producer_commit"],
        "selected_entry_count": len(states),
        "counts": counts,
        "states": states,
    }


def _request(release: focused.DeploymentSelection, selected: dict[str, object], state: dict[str, object]):
    loio = selected["plan_science"]["model_family"] == "DIAGNOSTIC_NO_REFIT"
    return g07.ProductionExecutionRequest(
        unit_id=selected["unit_id"],
        run_id=state["run_id"],
        output_root=release.output_root,
        resume=state["status"] == "STARTED",
        loio_source_manifest_paths=focused.loio_sources(release) if loio else (),
    )


def preview(release: focused.DeploymentSelection) -> dict[str, object]:
    selected, states = focused.next_selected(release)
    if selected is None:
        raise FocusedRunError("FOCUSED53_NO_NEXT_SELECTED_UNIT")
    state = next(item for item in states if item["unit_id"] == selected["unit_id"])
    try:
        focused.preview_selected(release, _request(release, selected, state))
    except focused.PreHandlerBoundary as exc:
        return {"status": "PASS_PRE_HANDLER_SENTINEL", **exc.record}
    raise FocusedRunError("FOCUSED53_PREVIEW_DID_NOT_STOP")


def run(release: focused.DeploymentSelection, require_fresh: bool) -> int:
    focused.reject_foreign_outputs(release)
    initial = status(release)
    if require_fresh and initial["counts"]["UNSTARTED"] != 55:
        raise FocusedRunError("FOCUSED53_START_REQUIRES_55_UNSTARTED")
    root = control_root(release)
    stop_file = root / "stop_after_current_unit_boundary.request"
    progress = root / "progress.jsonl"
    report_path = root / "final_report.json"
    with exclusive_worker(release):
        append_progress(progress, {
            "event": "RUN_STARTED", "selection_sha256": release.sha256,
            "require_fresh": require_fresh,
        })
        while True:
            selected, states = focused.next_selected(release)
            if selected is None:
                break
            if stop_file.exists():
                append_progress(progress, {
                    "event": "STOP_AFTER_CURRENT_UNIT_BOUNDARY_HONORED",
                    "next_unit": selected["unit_id"],
                })
                return 2
            state = next(item for item in states if item["unit_id"] == selected["unit_id"])
            request = _request(release, selected, state)
            append_progress(progress, {
                "event": "UNIT_DISPATCH", "unit_id": selected["unit_id"],
                "resume": request.resume,
            })
            try:
                result = focused.execute_selected(release, request)
            except g07.PairDependenciesPending as exc:
                append_progress(progress, {
                    "event": "EXPECTED_PAIR_DEPENDENCY",
                    "unit_id": selected["unit_id"],
                    "missing_unit_ids": list(exc.missing_unit_ids),
                })
                continue
            except Exception as exc:
                append_progress(progress, {
                    "event": "UNEXPECTED_FAILURE", "unit_id": selected["unit_id"],
                    "exception_type": type(exc).__name__, "message": str(exc)[:1000],
                })
                raise
            append_progress(progress, {
                "event": "UNIT_RETURNED", "unit_id": selected["unit_id"],
                "disposition": result.disposition.value,
            })
        final = status(release)
        if final["counts"]["COMPLETE"] != 55:
            raise FocusedRunError("FOCUSED53_INCOMPLETE_AFTER_SELECTED_PASS")
        report = {
            "schema": "PAPER1_FOCUSED53_LOCAL_RUN_REPORT_V2",
            "status": "COMPLETE_PENDING_AUDIT",
            "selection_sha256": release.sha256,
            "producer_commit": release.payload["producer_commit"],
            "completed_entries": 55,
            "states": final["states"],
            "timestamp_utc": now(),
        }
        report_path.write_text(
            json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8", newline="\n",
        )
        append_progress(progress, {"event": "RUN_COMPLETE_PENDING_AUDIT"})
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("run", "status", "preview"))
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--require-fresh", action="store_true")
    args = parser.parse_args()
    release = load_selection(
        args.project_root.resolve(), args.selection.resolve(), args.selection_sha256
    )
    if args.command == "status":
        print(json.dumps(status(release), sort_keys=True))
        return 0
    if args.command == "preview":
        print(json.dumps(preview(release), sort_keys=True))
        return 0
    return run(release, args.require_fresh)


if __name__ == "__main__":
    raise SystemExit(main())
