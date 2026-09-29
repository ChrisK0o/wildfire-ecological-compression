"""Authenticated execution adapter for the frozen focused-53 Paper 1 suite.

The adapter selects a fresh subset of the governed G07 universe. It does not
alter plan, contract, policy, model, or input semantics and does not use legacy
G08 activation as authority for the new generation.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re
from types import MappingProxyType

from src import paper1_g07_runtime as g07, paper1_g08_runtime as g08
from src import paper1_control_execution as control
from src import paper1_control_integration as integration
from src.paper1_control_reference import canonical, digest
from src.paper1_focused53_mixed_authority import MixedGenerationAuthority
from src.paper1_control_release import (
    ReleaseError, environment, git_head, identity, plain, relative_file,
    source_inventory,
)

SCHEMA = "PAPER1_FOCUSED53_DEPLOYMENT_SELECTION_V1"
MODE = "PRODUCTION_EXECUTION"
CONTROL_SCHEMA = "PAPER1_FOCUSED53_EXECUTION_CONTROL_V1"
HISTORICAL_SCHEMA = "PAPER1_FOCUSED53_HISTORICAL_GENERATION_V1"
EXPECTED_ENTRY_COUNT = 55
EXPECTED_EXECUTABLE_COUNT = 53
EXPECTED_NONESTIMABLE_COUNT = 2
class DeploymentError(ReleaseError):
    pass


class HistoricalGeneration:
    """Immutable, read-only authority for one prior focused generation."""

    def __init__(self, root: Path, path: Path, selected_sha256: str):
        self.root = Path(root).resolve()
        self.path = Path(path).resolve()
        self.sha256 = selected_sha256
        if not selected_sha256 or not self.path.is_file() or digest(self.path) != selected_sha256:
            raise DeploymentError("FOCUSED53_HISTORICAL_DESCRIPTOR_DIGEST")
        self.payload = json.loads(self.path.read_bytes())
        payload = self.payload
        if (
            payload.get("schema") != HISTORICAL_SCHEMA
            or payload.get("repository") != str(self.root)
            or payload.get("required_state") != {
                "current_phase": "COMPLETE", "terminal_disposition": "COMPLETE"
            }
            or not re.fullmatch(r"[0-9a-f]{40}", str(payload.get("producer_commit", "")))
        ):
            raise DeploymentError("FOCUSED53_HISTORICAL_DESCRIPTOR_BINDING")
        old = payload.get("old_selection", {})
        old_path = Path(str(old.get("path", ""))).resolve()
        if (
            not old_path.is_file()
            or digest(old_path) != old.get("sha256")
            or json.loads(old_path.read_bytes()).get("selection_identity_sha256")
            != old.get("selection_identity_sha256")
        ):
            raise DeploymentError("FOCUSED53_HISTORICAL_SELECTION_BINDING")
        self.old_selection_path = old_path
        self.old_selection = json.loads(old_path.read_bytes())
        if (
            self.old_selection.get("schema") != SCHEMA
            or self.old_selection.get("producer_commit") != payload["producer_commit"]
            or self.old_selection.get("output_root_relative") != payload.get("output_root_relative")
            or old.get("sha256") != payload.get("control_identity", {}).get("release_digest")
            or payload.get("control_identity") != {
                "schema": CONTROL_SCHEMA,
                "source_commit": payload["producer_commit"],
                "release_digest": old.get("sha256"),
            }
        ):
            raise DeploymentError("FOCUSED53_HISTORICAL_SELECTION_IDENTITY")
        units = payload.get("units", [])
        records = payload.get("evidence_inventory", [])
        self.units = {str(item.get("unit_id")): item for item in units}
        self.records = {str(item.get("path")): item for item in records}
        if (
            len(self.units) != len(units)
            or len(self.records) != len(records)
            or sorted(int(item["selected_position"]) for item in units)
            != list(range(1, int(payload.get("historical_selected_position_end", 0)) + 1))
        ):
            raise DeploymentError("FOCUSED53_HISTORICAL_INVENTORY_SCHEMA")
        self.units_by_run = {str(item["run_id"]): item for item in units}
        if len(self.units_by_run) != len(self.units):
            raise DeploymentError("FOCUSED53_HISTORICAL_RUN_ID_DUPLICATE")
        selected_paths = {
            str(relative)
            for unit in units for relative in unit.get("evidence_paths", ())
        } | {str(relative) for relative in payload.get("shared_evidence_paths", ())}
        if selected_paths != set(self.records):
            raise DeploymentError("FOCUSED53_HISTORICAL_RECORD_COVERAGE")
        self.check_selection()

    def check_selection(self) -> None:
        if digest(self.path) != self.sha256 or json.loads(self.path.read_bytes()) != self.payload:
            raise DeploymentError("FOCUSED53_HISTORICAL_DESCRIPTOR_CHANGED")
        old = self.payload["old_selection"]
        if (
            digest(self.old_selection_path) != old["sha256"]
            or json.loads(self.old_selection_path.read_bytes()) != self.old_selection
        ):
            raise DeploymentError("FOCUSED53_HISTORICAL_SELECTION_CHANGED")

    def bind_current(self, current_payload: dict[str, object]) -> None:
        """Require exact non-provenance continuity with the selected current release."""
        self.check_selection()
        old = self.old_selection
        end = int(self.payload["historical_selected_position_end"])
        current_entries = current_payload.get("entries", [])
        old_entries = old.get("entries", [])
        if (
            len(current_entries) != EXPECTED_ENTRY_COUNT
            or len(old_entries) != EXPECTED_ENTRY_COUNT
            or current_payload.get("selected_inputs") != old.get("selected_inputs")
            or current_payload.get("environment") != old.get("environment")
            or current_payload.get("numerical_runtime") != old.get("numerical_runtime")
        ):
            raise DeploymentError("FOCUSED53_HISTORICAL_GLOBAL_SCIENCE_DRIFT")
        for position in range(1, end + 1):
            prior = old_entries[position - 1]
            current = current_entries[position - 1]
            unit = self.units.get(str(prior.get("unit_id")))
            if (
                unit is None
                or unit.get("selected_position") != position
                or unit.get("run_id") != g07._v2_run_id(str(prior.get("unit_id")))
                or unit.get("old_contract_sha256") != prior.get("contract_sha256")
                or current.get("unit_id") != prior.get("unit_id")
                or current.get("plan_science") != prior.get("plan_science")
                or current.get("contract_science") != prior.get("contract_science")
                or current.get("policy") != prior.get("policy")
            ):
                raise DeploymentError("FOCUSED53_HISTORICAL_UNIT_SCIENCE_DRIFT")

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
            raise DeploymentError("FOCUSED53_HISTORICAL_EVIDENCE_MISMATCH:" + relative)

    def contains_run(self, run: Path) -> bool:
        resolved = Path(run).resolve()
        try:
            relative = resolved.relative_to(self.root / self.payload["output_root_relative"])
        except ValueError:
            return False
        return len(relative.parts) == 1 and relative.name in self.units_by_run

    def verify_unit(self, run: Path, state: dict[str, object] | None = None) -> dict[str, object]:
        self.check_selection()
        resolved = Path(run).resolve()
        if not self.contains_run(resolved):
            raise DeploymentError("FOCUSED53_HISTORICAL_UNIT_NOT_SELECTED")
        unit = self.units_by_run[resolved.name]
        expected_paths = tuple(str(item) for item in unit.get("evidence_paths", ()))
        observed_paths = tuple(sorted(
            path.relative_to(self.root).as_posix()
            for path in resolved.rglob("*") if path.is_file()
        ))
        if tuple(sorted(expected_paths)) != observed_paths:
            raise DeploymentError("FOCUSED53_HISTORICAL_UNIT_FILE_SET")
        for relative in expected_paths:
            self._verify_record(relative)
        if state is not None:
            control_identity = self.payload["control_identity"]
            identity = state.get("identity", {})
            if (
                state.get("current_phase") != "COMPLETE"
                or state.get("terminal_disposition") != "COMPLETE"
                or state.get("source_commit") != self.payload["producer_commit"]
                or state.get("execution_control") != control_identity
                or identity.get("unit_id") != unit["unit_id"]
                or identity.get("run_id") != unit["run_id"]
                or identity.get("contract_sha256") != unit["old_contract_sha256"]
            ):
                raise DeploymentError("FOCUSED53_HISTORICAL_UNIT_NOT_COMPLETE")
        return unit

    def verify_shared(self) -> None:
        self.check_selection()
        for relative in self.payload.get("shared_evidence_paths", []):
            self._verify_record(str(relative))

    def producer(self, source: str) -> dict[str, object]:
        if source != self.payload["producer_commit"]:
            raise DeploymentError("FOCUSED53_HISTORICAL_FOREIGN_PRODUCER")
        self.verify_shared()
        return {
            "source_commit": source,
            "transition_id": "FOCUSED53_HISTORICAL_GENERATION:" + self.sha256,
            "execution_authorized": False,
        }


class PreHandlerBoundary(RuntimeError):
    """Positive native preview result raised before the registered handler."""

    def __init__(self, context: object, handler: object, release: DeploymentSelection):
        self.record = {
            "unit_id": context.request.unit_id,
            "run_id": context.request.run_id,
            "handler": handler.__module__ + "." + handler.__name__,
            "registered_handler": context.plan_entry.handler_identity,
            "contract_sha256": context.contract.contract_sha256,
            "source_commit": context.contract.git_head,
            "selection_sha256": release.sha256,
            "context_type": type(context).__name__,
            "capability_valid": context.capability is g07._DISPATCH_CAPABILITY,
        }
        super().__init__("FOCUSED53_STOP_BEFORE_REGISTERED_HANDLER")


def _entry_science(entry: object) -> dict[str, object]:
    value = plain(asdict(entry))
    value.pop("contract_sha256", None)
    return value


def _contract_science(contract: object) -> dict[str, object]:
    value = plain(asdict(contract))
    value.pop("git_head", None)
    value.pop("contract_sha256", None)
    return value


class DeploymentSelection:
    """Externally selected, immutable descriptor for the focused generation."""

    def __init__(self, root: Path, path: Path, selected_sha256: str):
        self.root = Path(root).resolve()
        self.path = Path(path).resolve()
        self.sha256 = selected_sha256
        if not selected_sha256 or not self.path.is_file() or digest(self.path) != selected_sha256:
            raise DeploymentError("FOCUSED53_SELECTION_DIGEST")
        self.payload = json.loads(self.path.read_bytes())
        p = self.payload
        if (
            p.get("schema") != SCHEMA
            or p.get("mode") != MODE
            or p.get("repository") != str(self.root)
            or p.get("producer_commit") != git_head(self.root)
            or p.get("git_head") != p.get("producer_commit")
            or p.get("selected_entry_count") != EXPECTED_ENTRY_COUNT
            or p.get("selected_executable_count") != EXPECTED_EXECUTABLE_COUNT
            or p.get("selected_governed_nonestimable_count") != EXPECTED_NONESTIMABLE_COUNT
        ):
            raise DeploymentError("FOCUSED53_SELECTION_BINDING")
        historical = p.get("historical_generation")
        mixed = p.get("mixed_generation_authority")
        if historical is not None and mixed is not None:
            raise DeploymentError("FOCUSED53_AUTHORITY_AMBIGUOUS")
        self.historical = None
        if mixed is not None:
            if set(mixed) != {"path", "sha256", "selected_entry_count"}:
                raise DeploymentError("FOCUSED53_MIXED_SELECTION_SCHEMA")
            self.historical = MixedGenerationAuthority(
                self.root, Path(str(mixed["path"])), str(mixed["sha256"])
            )
            if mixed["selected_entry_count"] != EXPECTED_ENTRY_COUNT:
                raise DeploymentError("FOCUSED53_MIXED_SELECTION_COUNT")
        elif historical is not None:
            if set(historical) != {"path", "sha256", "historical_selected_position_end"}:
                raise DeploymentError("FOCUSED53_HISTORICAL_SELECTION_SCHEMA")
            self.historical = HistoricalGeneration(
                self.root, Path(str(historical["path"])), str(historical["sha256"])
            )
            if (
                historical["historical_selected_position_end"]
                != self.historical.payload["historical_selected_position_end"]
            ):
                raise DeploymentError("FOCUSED53_HISTORICAL_SELECTION_POSITION")

    @property
    def entries(self) -> tuple[dict[str, object], ...]:
        return tuple(self.payload["entries"])

    @property
    def output_root(self) -> Path:
        if isinstance(self.historical, MixedGenerationAuthority):
            return self.historical.output_root
        return (self.root / self.payload["output_root_relative"]).resolve()

    def authenticate(self, plan=None, contracts=None, policy_records=None) -> tuple[object, ...]:
        if digest(self.path) != self.sha256 or json.loads(self.path.read_bytes()) != self.payload:
            raise DeploymentError("FOCUSED53_SELECTION_CHANGED")
        control.committed_source(self.root)
        p = self.payload
        if git_head(self.root) != p["producer_commit"] or source_inventory(self.root) != p["sources"]:
            raise DeploymentError("FOCUSED53_SOURCE_CHANGED")
        if environment() != p["environment"] or integration.numerical_runtime() != p["numerical_runtime"]:
            raise DeploymentError("FOCUSED53_ENVIRONMENT_CHANGED")
        if plan is None or contracts is None or policy_records is None:
            plan, contracts = g08.governed_plan(self.root)
            _, policy_records, _ = g08.governed_policy_universe(self.root, contracts)
        if (
            identity(plan) != p["full_plan_sha256"]
            or identity(contracts) != p["full_contracts_sha256"]
            or identity(policy_records) != p["full_policy_records_sha256"]
        ):
            raise DeploymentError("FOCUSED53_GOVERNED_UNIVERSE_CHANGED")
        plan_by_unit = {item.unit_id: item for item in plan}
        contracts_by_unit = {g07._unit_id(item): item for item in contracts}
        policies_by_unit = {item["unit_id"]: item for item in policy_records}
        observed_ids: list[str] = []
        selected_contracts = []
        for selected in self.entries:
            unit = selected.get("unit_id")
            observed_ids.append(unit)
            entry = plan_by_unit.get(unit)
            contract = contracts_by_unit.get(unit)
            policy = policies_by_unit.get(unit)
            if entry is None or contract is None or policy is None:
                raise DeploymentError("FOCUSED53_UNIT_NOT_GOVERNED:" + str(unit))
            if (
                _entry_science(entry) != selected.get("plan_science")
                or _contract_science(contract) != selected.get("contract_science")
                or plain(policy) != selected.get("policy")
                or contract.contract_sha256 != selected.get("contract_sha256")
            ):
                raise DeploymentError("FOCUSED53_SELECTED_SCIENCE_CHANGED:" + str(unit))
            selected_contracts.append(contract)
        if len(observed_ids) != EXPECTED_ENTRY_COUNT or len(set(observed_ids)) != EXPECTED_ENTRY_COUNT:
            raise DeploymentError("FOCUSED53_SELECTION_MEMBERSHIP")
        selected_inputs = integration.declared_inputs(selected_contracts)
        if selected_inputs != p["selected_inputs"]:
            raise DeploymentError("FOCUSED53_INPUT_SET_CHANGED")
        for relative, expected in selected_inputs.items():
            if digest(relative_file(self.root, relative)) != expected:
                raise DeploymentError("FOCUSED53_INPUT_CHANGED:" + relative)
        if self.historical is not None:
            self.historical.bind_current(p)
        return tuple(selected_contracts)


class FocusedOperation(control.Operation):
    """Operation-scoped producer/checkpoint authority for one selected generation."""

    def __init__(self, release: DeploymentSelection, contracts: tuple[object, ...]):
        self.release = release
        self.contracts = {g07._unit_id(item): item for item in contracts}

    def _historical(self, run: Path) -> bool:
        historical = getattr(self.release, "historical", None)
        return historical is not None and historical.contains_run(run)

    def _control_identity(self) -> dict[str, str]:
        return {
            "schema": CONTROL_SCHEMA,
            "source_commit": self.release.payload["producer_commit"],
            "release_digest": self.release.sha256,
        }

    def producer(self, source: str) -> dict[str, object]:
        if source == self.release.payload["producer_commit"]:
            if digest(self.release.path) != self.release.sha256 or git_head(self.release.root) != source:
                raise DeploymentError("FOCUSED53_PRODUCER_SELECTION")
            return {
                "source_commit": source,
                "transition_id": "FOCUSED53_SELECTED_RELEASE:" + self.release.sha256,
                "execution_authorized": False,
            }
        historical = getattr(self.release, "historical", None)
        if historical is not None:
            return historical.producer(source)
        raise DeploymentError("FOCUSED53_FOREIGN_PRODUCER")

    def validate_new_state(self, run: Path, state: dict[str, object]) -> None:
        if self._historical(run):
            self.release.historical.verify_unit(run, state)
            return
        super().validate_new_state(run, state)

    def awaiting_pair(self, entry, state):
        """Classify staged pair members against the selected output root."""
        if state["current_phase"] != "METRICS_WRITTEN":
            return False
        self.validate_unit_state(g07._v2_run_id(entry.unit_id), state)
        contract = self.contracts[entry.unit_id]
        context = g07._DispatchContext(
            self.release.root,
            g07.ProductionExecutionRequest(
                entry.unit_id,
                g07._v2_run_id(entry.unit_id),
                self.release.output_root,
                resume=True,
            ),
            entry,
            contract,
            None,
            g07._DISPATCH_CAPABILITY,
        )
        members = g07._paired_group_contracts(context)
        if not members:
            return False
        for member in members:
            run = self.release.output_root / g07._v2_run_id(g07._unit_id(member))
            if not (run / "checkpoint.current.json").is_file():
                return True
            sibling = g07._reopen_production_state(run, self.release.root)
            if g07.PRODUCTION_PHASES.index(
                sibling["current_phase"]
            ) < g07.PRODUCTION_PHASES.index("METRICS_WRITTEN"):
                return True
        return False

    def inheritance(self, context: object, policy: object) -> MappingProxyType:
        unit = context.plan_entry.unit_id
        if (
            context.contract != self.contracts.get(unit)
            or policy != g07.v2_policy.resolve_policy(context.contract)
            or policy.mode is not g07.v2_policy.PolicyMode.INHERIT
        ):
            raise DeploymentError("FOCUSED53_INHERIT_POLICY")
        parent = policy.inheritance_parent_unit_id
        if parent not in self.contracts:
            raise DeploymentError("FOCUSED53_INHERIT_PARENT_NOT_SELECTED")
        contract = self.contracts[parent]
        run = self.release.output_root / g07._v2_run_id(parent)
        pointer_path = run / "checkpoint.current.json"
        manifest_path = run / "execution_manifest.json"
        if not pointer_path.is_file() or not manifest_path.is_file():
            raise DeploymentError("FOCUSED53_INHERIT_PARENT_MISSING")
        state = g07._reopen_production_state(run, self.release.root)
        manifest = g07.g06.validate_execution_manifest(
            self.release.root, manifest_path, True
        ).record
        producer = g07._read_evidence_producer(
            self.release.root, contract, run, manifest_path, "execution_manifest"
        )
        self.producer(producer.source_commit)
        if (
            state.get("current_phase") != "COMPLETE"
            or state.get("terminal_disposition") != "COMPLETE"
            or state.get("source_commit") != producer.source_commit
            or state.get("identity", {}).get("unit_id") != parent
            or state.get("identity", {}).get("run_id") != g07._v2_run_id(parent)
            or state.get("identity", {}).get("contract_sha256") != producer.contract_sha256
            or manifest.get("execution_contract_id") != producer.contract_sha256
            or manifest.get("paper1_run_id") != g07._v2_run_id(parent)
            or manifest.get("runner_source_commit") != producer.source_commit
            or manifest.get("scientific_run_git_commit") != producer.source_commit
            or manifest.get("runner_identity") != g07.SCHEMA_VERSION
            or manifest.get("terminal_status") != "COMPLETE"
        ):
            raise DeploymentError("FOCUSED53_INHERIT_PARENT_BINDING")
        parent_policy = g07.v2_policy.resolve_policy(contract)
        g07.v2_policy.validate_checkpoint_policy(state["identity"], parent_policy)
        selected = state.get("selected_hyperparameter")
        if selected is None or (
            parent_policy.mode is g07.v2_policy.PolicyMode.FIXED
            and float(selected) != parent_policy.fixed_value
        ) or (
            parent_policy.mode is g07.v2_policy.PolicyMode.TUNE
            and float(selected) not in parent_policy.candidates
        ):
            raise DeploymentError("FOCUSED53_INHERIT_VALUE")
        pointer = json.loads(pointer_path.read_bytes())
        return g07.v2_policy.validate_inheritance_claim(
            policy,
            parent_unit_id=parent,
            parent_policy_sha256=parent_policy.policy_sha256,
            parent_checkpoint_sha256=pointer["sha256"],
            parent_manifest_sha256=digest(manifest_path),
            selected_hyperparameter=float(selected),
        )

def _state(release: DeploymentSelection, operation: FocusedOperation, selected: dict[str, object]) -> dict[str, object]:
    unit = selected["unit_id"]
    run_id = g07._v2_run_id(unit)
    run = release.output_root / run_id
    if not run.exists():
        return {"unit_id": unit, "run_id": run_id, "status": "UNSTARTED", "phase": None}
    if isinstance(release.historical, MixedGenerationAuthority):
        authority_unit = release.historical.verify_unit(run)
        return {
            "unit_id": unit,
            "run_id": run_id,
            "status": "COMPLETE",
            "phase": (
                "LOIO_COMPLETE"
                if authority_unit["evidence_form"] == "LOIO_MANIFEST_TERMINAL"
                else "COMPLETE"
            ),
            "terminal_disposition": authority_unit["expected_terminal_disposition"],
        }
    loio = run / "loio_evidence_manifest.json"
    if loio.is_file():
        if operation._historical(run):
            release.historical.verify_unit(run)
        context = _context_for(release, selected, resume=True)
        with operation.use():
            g07._validate_loio_evidence(
                context,
                g07._authenticate_execution_input(context),
                loio,
            )
        return {"unit_id": unit, "run_id": run_id, "status": "COMPLETE", "phase": "LOIO_COMPLETE"}
    pointer = run / "checkpoint.current.json"
    if not pointer.is_file():
        raise DeploymentError("FOCUSED53_RUN_WITHOUT_POINTER:" + unit)
    with operation.use():
        state = g07._reopen_production_state(run, release.root)
    if state.get("current_phase") == "COMPLETE":
        return {
            "unit_id": unit, "run_id": run_id, "status": "COMPLETE",
            "phase": "COMPLETE", "terminal_disposition": state.get("terminal_disposition"),
        }
    plan_entry = _plan_entry(release, unit)
    with operation.use():
        waiting_for_pair = operation.awaiting_pair(plan_entry, state)
    if waiting_for_pair:
        return {
            "unit_id": unit, "run_id": run_id, "status": "STAGED_WAITING_PAIR",
            "phase": state.get("current_phase"), "terminal_disposition": state.get("terminal_disposition"),
        }
    return {
        "unit_id": unit, "run_id": run_id, "status": "STARTED",
        "phase": state.get("current_phase"), "terminal_disposition": state.get("terminal_disposition"),
    }


def _plan_entry(release: DeploymentSelection, unit: str):
    plan = g07.build_run_plan(release.root)
    matches = [entry for entry in plan if entry.unit_id == unit]
    if len(matches) != 1:
        raise DeploymentError("FOCUSED53_PLAN_ENTRY")
    return matches[0]


def _context_for(release: DeploymentSelection, selected: dict[str, object], resume: bool):
    unit = selected["unit_id"]
    entry = _plan_entry(release, unit)
    contract = g07.g06.governed_execution_contracts(release.root)
    matches = [item for item in contract if g07._unit_id(item) == unit]
    if len(matches) != 1:
        raise DeploymentError("FOCUSED53_CONTRACT_ENTRY")
    loio = selected["plan_science"]["model_family"] == "DIAGNOSTIC_NO_REFIT"
    request = g07.ProductionExecutionRequest(
        unit,
        g07._v2_run_id(unit),
        release.output_root,
        resume=resume,
        loio_source_manifest_paths=loio_sources(release) if loio else (),
    )
    return g07._DispatchContext(
        release.root, request, entry, matches[0], _receipt(release), g07._DISPATCH_CAPABILITY
    )


def unit_states(release: DeploymentSelection) -> tuple[dict[str, object], ...]:
    contracts = release.authenticate()
    operation = FocusedOperation(release, contracts)
    return tuple(_state(release, operation, selected) for selected in release.entries)


def next_selected(release: DeploymentSelection) -> tuple[dict[str, object] | None, tuple[dict[str, object], ...]]:
    contracts = release.authenticate()
    operation = FocusedOperation(release, contracts)
    states = tuple(_state(release, operation, selected) for selected in release.entries)
    for selected, state in zip(release.entries, states):
        if state["status"] in {"COMPLETE", "STAGED_WAITING_PAIR"}:
            continue
        return selected, states
    return None, states


def reject_foreign_outputs(release: DeploymentSelection) -> None:
    root = release.output_root
    if not root.exists():
        return
    allowed = {g07._v2_run_id(item["unit_id"]) for item in release.entries}
    allowed.add(g08.SHARED_PAIRED_EVIDENCE_DIRECTORY)
    foreign = sorted(path.name for path in root.iterdir() if path.name not in allowed)
    if foreign:
        raise DeploymentError("FOCUSED53_FOREIGN_OUTPUT:" + repr(foreign))


def loio_sources(release: DeploymentSelection) -> tuple[Path, ...]:
    entries = [
        item for item in release.entries
        if item["plan_science"]["analysis_id"] == "G05A_01_PRIMARY_EVT_1KM"
        and item["plan_science"]["model_family"] == "L2_LOGISTIC"
    ]
    paths = tuple(
        release.output_root / g07._v2_run_id(item["unit_id"]) / "execution_manifest.json"
        for item in entries
    )
    if len(paths) != 6 or not all(path.is_file() for path in paths):
        raise DeploymentError("FOCUSED53_LOIO_SOURCE_SET")
    contracts = release.authenticate()
    operation = FocusedOperation(release, contracts)
    contracts_by_unit = {g07._unit_id(item): item for item in contracts}
    with operation.use():
        for entry, manifest_path in zip(entries, paths):
            unit = entry["unit_id"]
            run = manifest_path.parent
            state = g07._reopen_production_state(run, release.root)
            if state.get("current_phase") != "COMPLETE":
                raise DeploymentError("FOCUSED53_LOIO_SOURCE_NOT_COMPLETE")
            producer = g07._read_evidence_producer(
                release.root, contracts_by_unit[unit], run, manifest_path, "execution_manifest"
            )
            operation.producer(producer.source_commit)
    return paths


def _receipt(release: DeploymentSelection) -> MappingProxyType:
    return MappingProxyType({
        "schema": CONTROL_SCHEMA,
        "source_commit": release.payload["producer_commit"],
        "selection_sha256": release.sha256,
    })


def _dispatch(release: DeploymentSelection, request: object, preview: bool):
    if not isinstance(release, DeploymentSelection) or not isinstance(request, g07.ProductionExecutionRequest):
        raise DeploymentError("FOCUSED53_REQUEST_TYPE")
    reject_foreign_outputs(release)
    selected, states = next_selected(release)
    if selected is None or selected["unit_id"] != request.unit_id:
        raise DeploymentError("FOCUSED53_NOT_NEXT_SELECTED_UNIT")
    state = next(item for item in states if item["unit_id"] == request.unit_id)
    expected_resume = state["status"] == "STARTED"
    if request.resume != expected_resume:
        raise DeploymentError("FOCUSED53_RESUME_STATE_MISMATCH")
    if request.run_id != g07._v2_run_id(request.unit_id) or Path(request.output_root).resolve() != release.output_root:
        raise DeploymentError("FOCUSED53_REQUEST_IDENTITY")
    contracts = release.authenticate()
    operation = FocusedOperation(release, contracts)

    def boundary(context, handler):
        release.authenticate()
        if context.contract.git_head != release.payload["producer_commit"]:
            raise DeploymentError("FOCUSED53_CONTRACT_SOURCE")
        if preview:
            raise PreHandlerBoundary(context, handler, release)

    with operation.use():
        return g07._run_authorized_scientific(
            release.root, request, _receipt(release), before_handler=boundary
        )


def preview_selected(release: DeploymentSelection, request: object):
    with integration.final.no_new_predictions():
        return _dispatch(release, request, True)


def execute_selected(release: DeploymentSelection, request: object):
    return _dispatch(release, request, False)


__all__ = [
    "DeploymentError", "DeploymentSelection", "FocusedOperation", "PreHandlerBoundary",
    "HistoricalGeneration",
    "execute_selected", "loio_sources", "next_selected", "preview_selected",
    "reject_foreign_outputs", "unit_states",
]
