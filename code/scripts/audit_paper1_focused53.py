"""Standalone no-refit audit for a completed focused Paper 1 generation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from src import paper1_g06_2g_runtime as g06
from src import paper1_g07_runtime as g07
from src import paper1_g07_v2_policy as v2_policy
from src import paper1_g08_runtime as g08
from src import paper1_focused53_deployment as focused
from scripts.run_paper1_focused53 import load_selection


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def validate_nonestimable_terminal(
    state: dict[str, object], manifest: dict[str, object], run_root: Path,
) -> None:
    """Validate native checkpoint and manifest vocabularies without conflating them."""
    if (state.get("terminal_disposition") != g07.TerminalDisposition.NONESTIMABLE.value or
            manifest.get("terminal_status") != "GOVERNED_NONESTIMABLE" or
            state.get("prediction_path") is not None or
            (run_root / "predictions.csv").exists()):
        raise RuntimeError("FOCUSED53_NONESTIMABLE_INVALID")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--selection-sha256", required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    root = args.project_root.resolve()
    selection = load_selection(root, args.selection.resolve(), args.selection_sha256)
    output_root = selection.output_root
    focused.reject_foreign_outputs(selection)
    plan, contracts = g08.governed_plan(root)
    _, policy_records, _ = g08.governed_policy_universe(root, contracts)
    selected_contracts = selection.authenticate(plan, contracts, policy_records)
    operation = focused.FocusedOperation(selection, selected_contracts)
    contract_by_unit = {g07._unit_id(item): item for item in contracts}
    records: list[dict[str, object]] = []
    executable_complete = 0
    nonestimable_complete = 0
    loio_complete = 0
    prediction_key_checks = 0
    tuning_scope_checks = 0
    pair_status_paths: set[str] = set()
    partial_boundary_groups = 0
    benchmark_checks = 0
    producer_counts: dict[str, int] = {}
    loio_manifest_paths = focused.loio_sources(selection)
    operation_scope = operation.use()
    operation_scope.__enter__()
    try:
      for selected in selection.entries:
        unit = selected["unit_id"]
        contract = contract_by_unit[unit]
        run_root = output_root / g08.deterministic_unit_run_id(unit)
        if contract.model_family == "DIAGNOSTIC_NO_REFIT":
            manifest_path = run_root / "loio_evidence_manifest.json"
            result_path = run_root / "loio_result.csv"
            terminal_path = run_root / "terminal_evidence.json"
            if not all(path.is_file() for path in (manifest_path, result_path, terminal_path)):
                raise RuntimeError("FOCUSED53_LOIO_MISSING")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            terminal = json.loads(terminal_path.read_text(encoding="utf-8"))
            if (manifest.get("model_family") != "DIAGNOSTIC_NO_REFIT" or
                    terminal.get("disposition") != "COMPLETE" or
                    terminal.get("model_fit_count") != 0 or
                    terminal.get("prediction_generated") is not False or
                    len(pd.read_csv(result_path)) != 24):
                raise RuntimeError("FOCUSED53_LOIO_INVALID")
            loio_complete += 1
            producer = selection.payload["producer_commit"]
            producer_counts[producer] = producer_counts.get(producer, 0) + 1
            records.append({"unit_id": unit, "status": "COMPLETE", "kind": "LOIO_NO_REFIT",
                            "producer_commit": producer})
            continue
        state = g07._reopen_production_state(run_root, root)
        manifest_path = run_root / "execution_manifest.json"
        manifest = g06.validate_execution_manifest(root, manifest_path, True).record
        producer = g07._read_evidence_producer(
            root, contract, run_root, manifest_path, "execution_manifest"
        )
        operation.producer(producer.source_commit)
        producer_counts[producer.source_commit] = producer_counts.get(producer.source_commit, 0) + 1
        if state.get("current_phase") != "COMPLETE":
            raise RuntimeError("FOCUSED53_UNIT_NOT_COMPLETE:" + unit)
        expected_nonestimable = selected["disposition"] == "GOVERNED_NONESTIMABLE"
        if expected_nonestimable:
            try:
                validate_nonestimable_terminal(state, manifest, run_root)
            except RuntimeError as exc:
                raise RuntimeError(f"{exc}:{unit}") from exc
            nonestimable_complete += 1
            records.append({"unit_id": unit, "status": "COMPLETE", "kind": "GOVERNED_NONESTIMABLE",
                            "producer_commit": producer.source_commit})
            continue
        if (state.get("terminal_disposition") != "COMPLETE" or
                manifest.get("terminal_status") != "COMPLETE"):
            raise RuntimeError("FOCUSED53_EXECUTABLE_TERMINAL:" + unit)
        prediction = pd.read_csv(run_root / "predictions.csv")
        expected = g07._read_scientific_ingress(root, contract).frame
        heldout = expected.loc[
            expected.interval_number.isin(contract.heldout_intervals),
            [*g06.KEY_FIELDS, "interval_number"],
        ].sort_values(list(g06.KEY_FIELDS), kind="stable").reset_index(drop=True)
        observed = prediction.loc[:, [*g06.KEY_FIELDS, "interval_number"]]
        if not observed.equals(heldout) or observed.duplicated(list(g06.KEY_FIELDS)).any():
            raise RuntimeError("FOCUSED53_PREDICTION_KEY_ALIGNMENT:" + unit)
        prediction_key_checks += 1
        policy_receipt = json.loads((run_root / "hyperparameter_policy_receipt.json").read_text(encoding="utf-8"))
        if policy_receipt.get("policy_sha256") != state["identity"]["hyperparameter_policy_sha256"]:
            raise RuntimeError("FOCUSED53_POLICY_RECEIPT:" + unit)
        if state.get("hyperparameter_source") == "GOVERNED_OUTER_TUNING":
            tuning = json.loads((run_root / "tuning_receipt.json").read_text(encoding="utf-8"))
            if (tuple(tuple(tuple(part) for part in split) for split in tuning["splits"])
                    != tuple(g07.TUNING_SPLITS[contract.evaluation_identity])):
                raise RuntimeError("FOCUSED53_INNER_SCOPE:" + unit)
            tuning_scope_checks += 1
        pair_status = run_root / "paired_publication_status.json"
        if not pair_status.is_file():
            raise RuntimeError("FOCUSED53_PAIR_STATUS:" + unit)
        status = json.loads(pair_status.read_text(encoding="utf-8"))
        if status.get("status") != "PUBLISHED_AND_VALIDATED":
            raise RuntimeError("FOCUSED53_PAIR_NOT_PUBLISHED:" + unit)
        pair_status_paths.add(str(status.get("paired_evidence_path")))
        for required in ("metrics.json", "prediction_stage_receipt.json",
                         "postprediction_unit_receipt.json", "v2_publication_gate.json"):
            if not (run_root / required).is_file():
                raise RuntimeError("FOCUSED53_REQUIRED_EVIDENCE:" + unit + ":" + required)
        metrics = json.loads((run_root / "metrics.json").read_text(encoding="utf-8"))
        required_metric_fields = {
            "schema_version", "prediction_artifact_sha256", "aggregation_scope",
            "interval_records", "log_loss_equal_interval_mean", "brier_equal_interval_mean",
        }
        required_interval_fields = {
            "interval_number", "rows", "positives", "log_loss", "brier",
            "average_precision", "roc_auc", "calibration_intercept",
            "calibration_slope", "reliability",
        }
        if (not required_metric_fields.issubset(metrics) or not metrics["interval_records"] or
                any(not required_interval_fields.issubset(item) for item in metrics["interval_records"])):
            raise RuntimeError("FOCUSED53_METRIC_CALIBRATION_SUPPORT:" + unit)
        if (contract.analysis_id == "G05A_01_PRIMARY_EVT_1KM" and
                contract.model_family == "L2_LOGISTIC" and contract.model_role == "baseline"):
            for benchmark in ("geometry_logistic", "training_prevalence"):
                benchmark_root = run_root / "benchmarks" / benchmark
                for required in ("predictions.csv", "execution_manifest.json",
                                 "terminal_evidence.json", "evidence_record.json"):
                    if not (benchmark_root / required).is_file():
                        raise RuntimeError("FOCUSED53_SIMPLE_BENCHMARK:" + unit + ":" + benchmark)
                benchmark_checks += 1
        executable_complete += 1
        records.append({"unit_id": unit, "status": "COMPLETE", "kind": "PREDICTIVE",
                        "prediction_rows": len(prediction), "prediction_sha256": digest(run_root / "predictions.csv"),
                        "producer_commit": producer.source_commit})
    finally:
        operation_scope.__exit__(None, None, None)
    if (executable_complete, nonestimable_complete, loio_complete) != (52, 2, 1):
        raise RuntimeError("FOCUSED53_FINAL_COUNTS")
    for relative in pair_status_paths:
        path = (root / relative).resolve()
        try:
            path.relative_to(output_root.resolve())
        except ValueError as exc:
            raise RuntimeError("FOCUSED53_PAIR_PATH") from exc
        if not path.is_file():
            raise RuntimeError("FOCUSED53_PAIR_EVIDENCE_MISSING")
        evidence = json.loads(path.read_text(encoding="utf-8"))
        if evidence.get("schema_version") == v2_policy.BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION:
            v2_policy.validate_boundary_partial_benefit_evidence(evidence)
            partial_boundary_groups += 1
        else:
            v2_policy.validate_paired_evidence(evidence)
    if partial_boundary_groups != 1:
        raise RuntimeError("FOCUSED53_BOUNDARY_PARTIAL_GROUP_COUNT")
    report = {
        "schema": "PAPER1_FOCUSED53_END_OF_SUITE_AUDIT_V1",
        "status": "PASS",
        "selection_identity_sha256": selection.payload["selection_identity_sha256"],
        "selected_entries": len(records),
        "predictive_executable_complete": executable_complete,
        "loio_no_refit_complete": loio_complete,
        "governed_nonestimable_complete": nonestimable_complete,
        "prediction_key_alignment_checks": prediction_key_checks,
        "tuned_inner_scope_checks": tuning_scope_checks,
        "paired_evidence_groups": len(pair_status_paths),
        "partial_boundary_groups": partial_boundary_groups,
        "simple_benchmark_checks": benchmark_checks,
        "foreign_or_deferred_units": 0,
        "duplicate_or_missing_selected_outputs": 0,
        "models_fit_by_audit": 0,
        "predictions_generated_by_audit": 0,
        "producer_counts": producer_counts,
        "records": records,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
