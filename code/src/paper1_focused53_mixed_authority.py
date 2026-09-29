"""Read-only composite authority for a completed mixed focused53 generation."""
from __future__ import annotations

import json
from pathlib import Path
import re

from src import paper1_g07_runtime as g07
from src.paper1_control_reference import canonical, digest


SCHEMA = "PAPER1_FOCUSED53_MIXED_GENERATION_AUTHORITY_V1"
SELECTION_SCHEMA = "PAPER1_FOCUSED53_DEPLOYMENT_SELECTION_V1"
CONTROL_SCHEMA = "PAPER1_FOCUSED53_EXECUTION_CONTROL_V1"
EXPECTED_ENTRY_COUNT = 55
HISTORICAL_END = 42
DIRECT_START = 43
DIRECT_END = 54
LOIO_POSITION = 55
HISTORICAL_OWNER = "HISTORICAL_1_42"
DIRECT_OWNER = "DIRECT_43_54"
LOIO_OWNER = "LOIO_55"
LOIO_ANALYSIS = "G05B_LOIO_PRIMARY_FORWARD"
LOIO_FAMILY = "DIAGNOSTIC_NO_REFIT"
PRIMARY_ANALYSIS = "G05A_01_PRIMARY_EVT_1KM"
PRIMARY_FAMILY = "L2_LOGISTIC"
PRIMARY_EVALUATIONS = {
    "B1_TO_B2", "B1_B2_TO_B3", "B1_B2_B3_TO_B4",
}


class MixedAuthorityError(RuntimeError):
    pass


def _expected_disposition(entry: dict[str, object]) -> str:
    plan = entry.get("plan_science", {})
    if (
        entry.get("disposition") == "GOVERNED_NONESTIMABLE"
        and plan.get("handler_identity") == "dispatch_governed_nonestimable"
        and plan.get("analysis_id") == "G05B_BOUNDARY_1000"
        and plan.get("evaluation_identity") == "B1_TO_B2"
    ):
        return "NONESTIMABLE"
    return "COMPLETE"


def _expected_source_entries(selection: dict[str, object]) -> list[dict[str, object]]:
    entries = [
        item for item in selection["entries"]
        if item["plan_science"]["analysis_id"] == PRIMARY_ANALYSIS
        and item["plan_science"]["model_family"] == PRIMARY_FAMILY
        and item["plan_science"]["model_role"] in {"baseline", "augmented"}
        and item["plan_science"]["evaluation_identity"] in PRIMARY_EVALUATIONS
    ]
    if len(entries) != 6:
        raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_EXPECTED_SOURCE_SET")
    return entries


class MixedGenerationAuthority:
    """Authenticate a completed focused53 set without changing producer history."""

    def __init__(self, root: Path, path: Path, selected_sha256: str):
        self.deployment_root = Path(root).resolve()
        self.path = Path(path).resolve()
        self.sha256 = selected_sha256
        if not selected_sha256 or not self.path.is_file() or digest(self.path) != selected_sha256:
            raise MixedAuthorityError("FOCUSED53_MIXED_DESCRIPTOR_DIGEST")
        self.payload = json.loads(self.path.read_bytes())
        payload = self.payload
        self.root = Path(str(payload.get("repository", ""))).resolve()
        if (
            payload.get("schema") != SCHEMA
            or not self.root.is_dir()
            or payload.get("selected_entry_count") != EXPECTED_ENTRY_COUNT
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_DESCRIPTOR_BINDING")

        accepted = payload.get("accepted_selection", {})
        accepted_path = Path(str(accepted.get("path", ""))).resolve()
        if (
            not accepted_path.is_file()
            or digest(accepted_path) != accepted.get("sha256")
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_SELECTION_DIGEST")
        self.selection_path = accepted_path
        self.selection = json.loads(accepted_path.read_bytes())
        if (
            self.selection.get("schema") != SELECTION_SCHEMA
            or self.selection.get("repository") != str(self.root)
            or self.selection.get("selected_entry_count") != EXPECTED_ENTRY_COUNT
            or self.selection.get("selection_identity_sha256")
            != accepted.get("selection_identity_sha256")
            or self.selection.get("producer_commit") != accepted.get("producer_commit")
            or self.selection.get("output_root_relative")
            != payload.get("output_root_relative")
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_SELECTION_BINDING")

        component = payload.get("historical_component", {})
        if (
            component.get("component_id") != HISTORICAL_OWNER
            or component.get("selected_position_start") != 1
            or component.get("selected_position_end") != HISTORICAL_END
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_HISTORICAL_COMPONENT")
        from src.paper1_focused53_deployment import HistoricalGeneration
        self.historical = HistoricalGeneration(
            self.root, Path(str(component.get("path", ""))), str(component.get("sha256", ""))
        )
        if self.historical.payload.get("historical_selected_position_end") != HISTORICAL_END:
            raise MixedAuthorityError("FOCUSED53_MIXED_HISTORICAL_BOUNDARY")

        direct = payload.get("direct_generation", {})
        expected_control = {
            "schema": CONTROL_SCHEMA,
            "source_commit": self.selection["producer_commit"],
            "release_digest": accepted["sha256"],
        }
        if (
            direct.get("component_id") != DIRECT_OWNER
            or direct.get("selected_position_start") != DIRECT_START
            or direct.get("selected_position_end") != DIRECT_END
            or direct.get("producer_commit") != self.selection["producer_commit"]
            or direct.get("control_identity") != expected_control
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_DIRECT_GENERATION")
        self.direct_producer = str(direct["producer_commit"])
        self.direct_control = expected_control

        loio = payload.get("loio_generation", {})
        if (
            loio.get("component_id") != LOIO_OWNER
            or loio.get("selected_position") != LOIO_POSITION
            or loio.get("producer_commit") != self.direct_producer
            or loio.get("execution_kind") != "NO_REFIT_DIAGNOSTIC"
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_GENERATION")

        units = payload.get("units", [])
        records = payload.get("evidence_inventory", [])
        self.units = {str(item.get("unit_id")): item for item in units}
        self.units_by_run = {str(item.get("run_id")): item for item in units}
        self.records = {str(item.get("path")): item for item in records}
        if (
            len(units) != EXPECTED_ENTRY_COUNT
            or len(self.units) != EXPECTED_ENTRY_COUNT
            or len(self.units_by_run) != EXPECTED_ENTRY_COUNT
            or len(self.records) != len(records)
            or sorted(int(item.get("selected_position", 0)) for item in units)
            != list(range(1, EXPECTED_ENTRY_COUNT + 1))
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_UNIT_COVERAGE")

        direct_paths: set[str] = set()
        expected_mapping: list[dict[str, object]] = []
        for position, selected in enumerate(self.selection["entries"], start=1):
            unit_id = str(selected["unit_id"])
            unit = self.units.get(unit_id)
            expected_owner = (
                HISTORICAL_OWNER if position <= HISTORICAL_END
                else DIRECT_OWNER if position <= DIRECT_END
                else LOIO_OWNER
            )
            expected_form = (
                "REFERENCED_HISTORICAL_GENERATION"
                if position <= HISTORICAL_END else
                "CHECKPOINT_TERMINAL" if position <= DIRECT_END else
                "LOIO_MANIFEST_TERMINAL"
            )
            expected_disposition = _expected_disposition(selected)
            if (
                unit is None
                or unit.get("selected_position") != position
                or unit.get("native_ordinal") != selected.get("native_ordinal")
                or unit.get("run_id") != g07._v2_run_id(unit_id)
                or unit.get("owner_id") != expected_owner
                or unit.get("evidence_form") != expected_form
                or unit.get("expected_terminal_disposition") != expected_disposition
                or unit.get("contract_sha256") != selected.get("contract_sha256")
            ):
                raise MixedAuthorityError("FOCUSED53_MIXED_UNIT_BINDING:" + unit_id)
            if position <= HISTORICAL_END:
                historical_unit = self.historical.units.get(unit_id)
                if (
                    historical_unit is None
                    or historical_unit.get("selected_position") != position
                    or historical_unit.get("run_id") != unit["run_id"]
                ):
                    raise MixedAuthorityError("FOCUSED53_MIXED_HISTORICAL_UNIT:" + unit_id)
            else:
                direct_paths.update(str(item) for item in unit.get("evidence_paths", ()))
            expected_mapping.append({
                "selected_position": position,
                "unit_id": unit_id,
                "owner_id": expected_owner,
            })
        if payload.get("selected_position_to_generation") != expected_mapping:
            raise MixedAuthorityError("FOCUSED53_MIXED_POSITION_MAPPING")

        direct_paths.update(str(item) for item in payload.get("shared_evidence_paths", ()))
        if direct_paths != set(self.records):
            raise MixedAuthorityError("FOCUSED53_MIXED_RECORD_COVERAGE")

        expected_sources = _expected_source_entries(self.selection)
        observed_sources = payload.get("loio_source_manifests", [])
        expected_source_rows = []
        for selected in expected_sources:
            unit_id = str(selected["unit_id"])
            relative = (
                Path(self.payload["output_root_relative"])
                / g07._v2_run_id(unit_id) / "execution_manifest.json"
            ).as_posix()
            expected_source_rows.append((
                unit_id,
                relative,
                selected["plan_science"]["model_role"],
                selected["plan_science"]["evaluation_identity"],
            ))
        observed_source_rows = [(
            str(item.get("unit_id")), str(item.get("path")),
            str(item.get("model_role")), str(item.get("evaluation_identity")),
        ) for item in observed_sources]
        if observed_source_rows != expected_source_rows or len(set(observed_source_rows)) != 6:
            raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_SOURCE_BINDING")
        self.loio_sources = tuple(observed_sources)
        self.check_selection()

    def check_selection(self) -> None:
        if digest(self.path) != self.sha256 or json.loads(self.path.read_bytes()) != self.payload:
            raise MixedAuthorityError("FOCUSED53_MIXED_DESCRIPTOR_CHANGED")
        accepted = self.payload["accepted_selection"]
        if (
            digest(self.selection_path) != accepted["sha256"]
            or json.loads(self.selection_path.read_bytes()) != self.selection
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_SELECTION_CHANGED")

    def bind_current(self, current_payload: dict[str, object]) -> None:
        self.check_selection()
        old = self.selection
        current_entries = current_payload.get("entries", [])
        old_entries = old.get("entries", [])
        if (
            current_payload.get("repository") != str(self.deployment_root)
            or len(current_entries) != EXPECTED_ENTRY_COUNT
            or len(old_entries) != EXPECTED_ENTRY_COUNT
            or current_payload.get("selected_inputs") != old.get("selected_inputs")
            or current_payload.get("environment") != old.get("environment")
            or current_payload.get("numerical_runtime") != old.get("numerical_runtime")
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_GLOBAL_SCIENCE_DRIFT")
        for position, (prior, current) in enumerate(zip(old_entries, current_entries), start=1):
            unit = self.units.get(str(prior.get("unit_id")))
            if (
                unit is None
                or unit.get("selected_position") != position
                or current.get("unit_id") != prior.get("unit_id")
                or current.get("plan_science") != prior.get("plan_science")
                or current.get("contract_science") != prior.get("contract_science")
                or current.get("policy") != prior.get("policy")
            ):
                raise MixedAuthorityError("FOCUSED53_MIXED_SCIENCE_DRIFT")

    @property
    def output_root(self) -> Path:
        return (self.root / self.payload["output_root_relative"]).resolve()

    def _verify_record(self, relative: str) -> None:
        record = self.records.get(relative)
        path = (self.root / relative).resolve()
        if (
            record is None
            or not path.is_relative_to(self.root)
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != record.get("size")
            or digest(path) != record.get("sha256")
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_EVIDENCE_MISMATCH:" + relative)

    def contains_run(self, run: Path) -> bool:
        resolved = Path(run).resolve()
        try:
            relative = resolved.relative_to(self.root / self.payload["output_root_relative"])
        except ValueError:
            return False
        return len(relative.parts) == 1 and relative.name in self.units_by_run

    def _verify_direct_state(self, unit: dict[str, object], state: dict[str, object]) -> None:
        identity = state.get("identity", {})
        expected = unit["expected_terminal_disposition"]
        if (
            state.get("current_phase") != "COMPLETE"
            or state.get("terminal_disposition") != expected
            or state.get("source_commit") != self.direct_producer
            or state.get("execution_control") != self.direct_control
            or identity.get("unit_id") != unit["unit_id"]
            or identity.get("run_id") != unit["run_id"]
            or identity.get("contract_sha256") != unit["contract_sha256"]
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_DIRECT_STATE")

    def _verify_loio(self, unit: dict[str, object]) -> None:
        run = self.root / self.payload["output_root_relative"] / unit["run_id"]
        manifest_path = run / "loio_evidence_manifest.json"
        terminal_path = run / "terminal_evidence.json"
        if not manifest_path.is_file() or not terminal_path.is_file():
            raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_FILES")
        manifest = json.loads(manifest_path.read_bytes())
        terminal = json.loads(terminal_path.read_bytes())
        record = manifest.get("terminal_record", {})
        if (
            manifest.get("analysis_id") != LOIO_ANALYSIS
            or manifest.get("model_family") != LOIO_FAMILY
            or manifest.get("model_role") != "paired_delta"
            or manifest.get("hyperparameter_policy_mode") != "NO_REFIT"
            or manifest.get("execution_unit_id") != unit["unit_id"]
            or manifest.get("paper1_run_id") != unit["run_id"]
            or record.get("execution_kind") != "NO_REFIT_DIAGNOSTIC"
            or record.get("model_fit_count") != 0
            or record.get("prediction_generated") is not False
            or record.get("disposition") != "COMPLETE"
            or record.get("sha256") != digest(terminal_path)
            or terminal.get("model_fit_count") != 0
            or terminal.get("prediction_generated") is not False
            or terminal.get("disposition") != "COMPLETE"
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_SEMANTICS")
        observed = [(
            item.get("execution_manifest_path"), item.get("execution_manifest_sha256"),
            item.get("model_role"), item.get("outer_evaluation"), item.get("analysis_id"),
        ) for item in manifest.get("source_oof_evidence", [])]
        expected = [(
            item["path"], item["sha256"], item["model_role"],
            item["evaluation_identity"], PRIMARY_ANALYSIS,
        ) for item in self.loio_sources]
        if observed != expected or len(set(observed)) != 6:
            raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_MANIFEST_SOURCES")
        for item in self.loio_sources:
            path = (self.root / item["path"]).resolve()
            if (
                not path.is_relative_to(self.root)
                or not path.is_file()
                or path.is_symlink()
                or digest(path) != item["sha256"]
            ):
                raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_SOURCE_HASH")

    def _terminal_state(
            self, unit: dict[str, object], run: Path) -> dict[str, object]:
        """Reconstruct a terminal payload only from authority-pinned evidence."""
        pointer_path = run / "checkpoint.current.json"
        pointer_relative = pointer_path.relative_to(self.root).as_posix()
        if pointer_relative not in unit.get("evidence_paths", ()):
            raise MixedAuthorityError("FOCUSED53_MIXED_DIRECT_POINTER_RECORD")
        self._verify_record(pointer_relative)
        pointer = json.loads(pointer_path.read_bytes())
        if set(pointer) != {"path", "sha256"}:
            raise MixedAuthorityError("FOCUSED53_MIXED_DIRECT_POINTER_SCHEMA")
        checkpoint_relative = str(pointer["path"])
        if checkpoint_relative not in unit.get("evidence_paths", ()):
            raise MixedAuthorityError("FOCUSED53_MIXED_DIRECT_CHECKPOINT_RECORD")
        checkpoint_path = (self.root / checkpoint_relative).resolve()
        try:
            checkpoint_path.relative_to(run)
        except ValueError as exc:
            raise MixedAuthorityError(
                "FOCUSED53_MIXED_DIRECT_CHECKPOINT_PATH"
            ) from exc
        self._verify_record(checkpoint_relative)
        if digest(checkpoint_path) != pointer["sha256"]:
            raise MixedAuthorityError("FOCUSED53_MIXED_DIRECT_POINTER_HASH")
        wrapper = json.loads(checkpoint_path.read_bytes())
        if (
            set(wrapper) != {"payload", "payload_sha256"}
            or g07.sha256_bytes(canonical(wrapper["payload"]))
            != wrapper["payload_sha256"]
        ):
            raise MixedAuthorityError("FOCUSED53_MIXED_DIRECT_CHECKPOINT_HASH")
        return dict(wrapper["payload"])

    def verify_unit(self, run: Path, state: dict[str, object] | None = None) -> dict[str, object]:
        self.check_selection()
        resolved = Path(run).resolve()
        if not self.contains_run(resolved):
            raise MixedAuthorityError("FOCUSED53_MIXED_UNIT_NOT_SELECTED")
        unit = self.units_by_run[resolved.name]
        if unit["owner_id"] == HISTORICAL_OWNER:
            self.historical.verify_unit(resolved, state)
            return unit
        expected_paths = tuple(sorted(str(item) for item in unit.get("evidence_paths", ())))
        observed_paths = tuple(sorted(
            path.relative_to(self.root).as_posix()
            for path in resolved.rglob("*") if path.is_file()
        ))
        if expected_paths != observed_paths:
            raise MixedAuthorityError("FOCUSED53_MIXED_UNIT_FILE_SET")
        for relative in expected_paths:
            self._verify_record(relative)
        if unit["owner_id"] == LOIO_OWNER:
            if state is not None:
                raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_CHECKPOINT_FORM")
            self._verify_loio(unit)
            return unit
        if state is None:
            state = self._terminal_state(unit, resolved)
        self._verify_direct_state(unit, state)
        if unit["expected_terminal_disposition"] == "NONESTIMABLE":
            names = {Path(path).name for path in expected_paths}
            if "predictions.csv" in names or "metrics.json" in names:
                raise MixedAuthorityError("FOCUSED53_MIXED_NONESTIMABLE_PREDICTION")
            terminal = json.loads((resolved / "terminal_evidence.json").read_bytes())
            if terminal != {
                "disposition": "NONESTIMABLE",
                "exception_metadata": None,
                "prediction_available": False,
                "schema_version": "PAPER1_G07_TERMINAL_V1",
            }:
                raise MixedAuthorityError("FOCUSED53_MIXED_NONESTIMABLE_TERMINAL")
        return unit

    def verify_shared(self) -> None:
        self.check_selection()
        self.historical.verify_shared()
        for relative in self.payload.get("shared_evidence_paths", ()):
            self._verify_record(str(relative))
        for item in self.loio_sources:
            path = self.root / item["path"]
            if digest(path) != item["sha256"]:
                raise MixedAuthorityError("FOCUSED53_MIXED_LOIO_SOURCE_HASH")

    def producer(self, source: str) -> dict[str, object]:
        if source == self.historical.payload["producer_commit"]:
            return self.historical.producer(source)
        if source != self.direct_producer or not re.fullmatch(r"[0-9a-f]{40}", source):
            raise MixedAuthorityError("FOCUSED53_MIXED_FOREIGN_PRODUCER")
        self.verify_shared()
        return {
            "source_commit": source,
            "transition_id": "FOCUSED53_MIXED_GENERATION:" + self.sha256,
            "execution_authorized": False,
        }


__all__ = ["MixedAuthorityError", "MixedGenerationAuthority", "SCHEMA"]
