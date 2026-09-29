"""Descendant-compatible validation for the accepted Paper 1 G06.2g generation.

This module does not replace the accepted execution contracts. It authenticates
their acceptance commit and immutable disk generation while allowing ordinary
descendant commits to consume that accepted authority.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from src import paper1_g06_2g_runtime as _accepted


for _export_name in dir(_accepted):
    if not _export_name.startswith("_"):
        globals()[_export_name] = getattr(_accepted, _export_name)


G06_3_GATE_VERSION = "PAPER1_G06.3"
G06_3_AUTHORITY_PATH = "documentation/PAPER1_G06_3_ACCEPTED_AUTHORITY.json"
G06_3_AUTHORITY_SHA256 = (
    "45a86fdf0c246a0e9aae59b6585f69dbd8a7c0447a44d3431861d20798d0654e"
)
G06_3_PRODUCTION_FACADE = "src.paper1_g06_2_runtime"
G06_3_COMPATIBILITY_MODULE = "src.paper1_g06_3_runtime"
G06_3_ACCEPTED_IMPLEMENTATION = "src.paper1_g06_2g_runtime"
G06_3_PRODUCTION_FACADE_SHA256 = (
    "563af2cfa7269c074c299f26d56e7154c874440655f2a697963c8ef25a36f4e3"
)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _git(root: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True, capture_output=True, check=False,
    )
    if check and completed.returncode != 0:
        raise ContractError(
            f"ERR_G06_3_GIT:{arguments[0]}:{completed.stderr.strip()}"
        )
    return completed


def _git_blob(root: Path, commit: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=root, capture_output=True, check=False,
    )
    if completed.returncode != 0:
        raise ContractError(f"ERR_G06_3_ACCEPTED_BLOB_MISSING:{relative_path}")
    return completed.stdout


def _load_authority(root: Path) -> Mapping[str, object]:
    path = root / G06_3_AUTHORITY_PATH
    if not path.is_file() or _sha256_path(path) != G06_3_AUTHORITY_SHA256:
        raise ContractError("ERR_G06_3_AUTHORITY_RECORD_IDENTITY")
    try:
        authority = json.loads(path.read_text(encoding="ascii"))
    except Exception as exc:
        raise ContractError("ERR_G06_3_AUTHORITY_RECORD_SCHEMA") from exc
    required = {
        "schema_version", "gate_version", "generation_build_base_head",
        "accepted_g06_commit", "accepted_commit_subject",
        "compatibility_build_base_head", "compatibility_acceptance_derivation",
        "accepted_commit_derivation", "accepted_generation", "accepted_source",
        "accepted_independent_audit", "required_independent_decision",
        "required_ancestry_rule", "supersession_policy",
    }
    if set(authority) != required:
        raise ContractError("ERR_G06_3_AUTHORITY_RECORD_SCHEMA")
    return MappingProxyType(authority)


def _derive_accepted_commit(root: Path, authority: Mapping[str, object]) -> str:
    derivation = authority["accepted_commit_derivation"]
    if not isinstance(derivation, dict) or derivation.get("method") != (
        "UNIQUE_GIT_ADD_COMMIT_FOR_ACCEPTED_GENERATION_MANIFEST"
    ):
        raise ContractError("ERR_G06_3_ACCEPTED_COMMIT_DERIVATION")
    path = str(derivation.get("path", ""))
    commits = [
        line.strip() for line in _git(
            root, "log", "--diff-filter=A", "--format=%H", "--", path
        ).stdout.splitlines() if line.strip()
    ]
    if len(commits) != 1 or commits[0] != authority["accepted_g06_commit"]:
        raise ContractError("ERR_G06_3_ACCEPTED_COMMIT_DERIVATION")
    subject = _git(root, "show", "-s", "--format=%s", commits[0]).stdout.strip()
    if subject != authority["accepted_commit_subject"]:
        raise ContractError("ERR_G06_3_ACCEPTED_COMMIT_SUBJECT")
    return commits[0]


def _validate_ancestry(root: Path, accepted_commit: str) -> str:
    current_head = _git(root, "rev-parse", "HEAD").stdout.strip()
    relation = _git(
        root, "merge-base", "--is-ancestor", accepted_commit, current_head,
        check=False,
    )
    if relation.returncode != 0:
        raise ContractError("ERR_G06_3_ACCEPTED_COMMIT_NOT_ANCESTOR")
    return current_head


def _derive_compatibility_acceptance(
        root: Path, authority: Mapping[str, object], current_head: str) -> tuple[str, str]:
    derivation = authority["compatibility_acceptance_derivation"]
    if not isinstance(derivation, dict) or derivation.get("method") != (
        "UNIQUE_GIT_ADD_COMMIT_FOR_G06_3_AUTHORITY_RECORD"
    ):
        raise ContractError("ERR_G06_3_COMPATIBILITY_ACCEPTANCE_DERIVATION")
    path = str(derivation.get("path", ""))
    commits = [line.strip() for line in _git(
        root, "log", "--diff-filter=A", "--format=%H", "--", path
    ).stdout.splitlines() if line.strip()]
    if not commits:
        status = _git(root, "status", "--short", "--", path).stdout.strip()
        if (current_head != authority["compatibility_build_base_head"] or
                status != f"?? {path}"):
            raise ContractError("ERR_G06_3_PREACCEPTANCE_STATE")
        return "PRE_ACCEPTANCE_AUDIT", "UNCOMMITTED"
    if len(commits) != 1:
        raise ContractError("ERR_G06_3_COMPATIBILITY_ACCEPTANCE_DERIVATION")
    compatibility_commit = commits[0]
    relation = _git(
        root, "merge-base", "--is-ancestor", compatibility_commit, current_head,
        check=False,
    )
    if relation.returncode != 0:
        raise ContractError("ERR_G06_3_COMPATIBILITY_COMMIT_NOT_ANCESTOR")
    frozen_paths = derivation.get("frozen_paths", [])
    if not isinstance(frozen_paths, list) or len(frozen_paths) != 4:
        raise ContractError("ERR_G06_3_COMPATIBILITY_ACCEPTANCE_DERIVATION")
    for relative_path in frozen_paths:
        committed = _sha256_bytes(_git_blob(root, compatibility_commit, relative_path))
        path_object = root / relative_path
        if not path_object.is_file() or _sha256_path(path_object) != committed:
            raise ContractError(f"ERR_G06_3_COMPATIBILITY_SOURCE_CHANGED:{relative_path}")
    return "ACCEPTED_DESCENDANT", compatibility_commit


def _validate_frozen_paths(
        root: Path, accepted_commit: str, identities: Mapping[str, str],
        require_worktree_identity: bool) -> None:
    for relative_path, expected_sha256 in identities.items():
        accepted_sha256 = _sha256_bytes(_git_blob(root, accepted_commit, relative_path))
        if accepted_sha256 != expected_sha256:
            raise ContractError(f"ERR_G06_3_ACCEPTED_BLOB_IDENTITY:{relative_path}")
        if require_worktree_identity:
            path = root / relative_path
            if not path.is_file() or _sha256_path(path) != expected_sha256:
                raise ContractError(f"ERR_G06_3_ACCEPTED_SOURCE_CHANGED:{relative_path}")


def _validate_independent_decision(
        root: Path, authority: Mapping[str, object]) -> Mapping[str, str]:
    path = root / "documentation/PAPER1_SOL_G06_2G_GATE_DECISION.csv"
    with path.open("r", encoding="ascii", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len(rows) != 1:
        raise ContractError("ERR_G06_3_INDEPENDENT_DECISION_SCHEMA")
    row = rows[0]
    required = authority["required_independent_decision"]
    allowed = set(required["independent_verdict"])
    if row.get("independent_verdict") not in allowed:
        raise ContractError("ERR_G06_3_INDEPENDENT_DECISION_SEMANTICS")
    for field, expected in required.items():
        if field == "independent_verdict":
            continue
        if row.get(field) != expected:
            raise ContractError("ERR_G06_3_INDEPENDENT_DECISION_SEMANTICS")
    return MappingProxyType(row)


def _validate_generation(
        root: Path, authority: Mapping[str, object],
        directory: Path | None = None) -> Mapping[str, object]:
    accepted_generation = authority["accepted_generation"]
    base = ((root / "documentation").resolve() if directory is None
            else Path(directory).resolve())
    manifest_path = base / Path(accepted_generation["manifest_path"]).name
    if not manifest_path.is_file():
        raise ContractError("ERR_G06_3_GENERATION_MARKER_MISSING")
    if _sha256_path(manifest_path) != accepted_generation["manifest_sha256"]:
        raise ContractError("ERR_G06_3_GENERATION_MANIFEST_IDENTITY")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="ascii"))
    except Exception as exc:
        raise ContractError("ERR_G06_3_GENERATION_MANIFEST_SCHEMA") from exc
    if manifest.get("generation_id") != accepted_generation["generation_id"]:
        raise ContractError("ERR_G06_3_GENERATION_IDENTITY")
    if manifest.get("git_head") != authority["generation_build_base_head"]:
        raise ContractError("ERR_G06_3_GENERATION_BUILD_BASE")
    if manifest.get("publication_protocol") != accepted_generation["publication_protocol"]:
        raise ContractError("ERR_G06_3_GENERATION_PUBLICATION_PROTOCOL")
    accepted_source = authority["accepted_source"]
    source_fields = {
        "facade_source_sha256": "src/paper1_g06_2_runtime.py",
        "runtime_source_sha256": "src/paper1_g06_2g_runtime.py",
        "validator_source_sha256": "scripts/validate_paper1_g06_2g.py",
    }
    for field, path in source_fields.items():
        if manifest.get(field) != accepted_source[path]:
            raise ContractError(f"ERR_G06_3_GENERATION_SOURCE_BINDING:{field}")
    expected_payloads = accepted_generation["payloads"]
    declared = manifest.get("payloads", {})
    if set(declared) != {Path(path).name for path in expected_payloads}:
        raise ContractError("ERR_G06_3_GENERATION_PAYLOAD_SET")
    for relative_path, expected_sha256 in expected_payloads.items():
        path = base / Path(relative_path).name
        if not path.is_file():
            raise ContractError("ERR_G06_3_GENERATION_PAYLOAD_SET")
        raw = path.read_bytes()
        identity = declared[Path(relative_path).name]
        if (_sha256_bytes(raw) != expected_sha256 or
                identity.get("sha256") != expected_sha256 or
                identity.get("bytes") != len(raw) or
                identity.get("role") != Path(relative_path).name):
            raise ContractError(f"ERR_G06_3_GENERATION_PAYLOAD_IDENTITY:{relative_path}")
    fresh = manifest.get("fresh_process_execution_receipt", {})
    records = fresh.get("child_execution_records", [])
    results = fresh.get("results", [])
    if (fresh.get("status") != "PASS" or fresh.get("execution_count") != 16 or
            fresh.get("unique_test_count") != 16 or
            fresh.get("child_process_count") != 16 or
            fresh.get("successful_result_count") != 16 or
            len(records) != 16 or len(results) != 16 or
            len({row[0] for row in records}) != 16 or
            len({row[0] for row in results}) != 16):
        raise ContractError("ERR_G06_3_CHILD_EXECUTION_EVIDENCE")
    if any(row[1] != "PASS" for row in results):
        raise ContractError("ERR_G06_3_CHILD_EXECUTION_RESULT")
    return MappingProxyType(manifest)


def _validate_production_facade(root: Path) -> None:
    from src import paper1_g06_2_runtime as facade

    production = facade.PRODUCTION_API_MANIFEST
    if (_sha256_path(root / "src/paper1_g06_2_runtime.py") !=
            G06_3_PRODUCTION_FACADE_SHA256 or
            production.get("production_import") != G06_3_PRODUCTION_FACADE or
            production.get("implementation_module") != G06_3_COMPATIBILITY_MODULE or
            production.get("accepted_implementation_module") != G06_3_ACCEPTED_IMPLEMENTATION or
            facade.validate_validation_generation is not validate_validation_generation):
        raise ContractError("ERR_G06_3_PRODUCTION_FACADE")


def current_generation_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    accepted_commit = _derive_accepted_commit(root, authority)
    current_head = _validate_ancestry(root, accepted_commit)
    compatibility_state, compatibility_commit = _derive_compatibility_acceptance(
        root, authority, current_head
    )
    manifest = _validate_generation(root, authority)
    inherited_fields = (
        "gate_version", "schema_version", "api_identity",
        "behavioral_universe_sha256", "static_universe_sha256",
        "integration_universe_sha256", "fresh_process_universe_sha256",
        "g05a_authority_sha256", "g05b_authority_sha256",
        "rf_authority_sha256", "metric_authority_sha256",
        "behavioral_test_count", "static_test_count", "integration_test_count",
        "fresh_process_test_count", "publication_guard_test_count",
        "local_provenance_test_count", "contract_combination_count",
        "required_payload_roles", "publication_protocol", "decision_status",
    )
    inherited = {field: manifest[field] for field in inherited_fields}
    return MappingProxyType({
        **inherited,
        "git_head": current_head,
        "facade_source_sha256": _sha256_path(root / "src/paper1_g06_2_runtime.py"),
        "runtime_source_sha256": authority["accepted_source"]["src/paper1_g06_2g_runtime.py"],
        "validator_source_sha256": authority["accepted_source"]["scripts/validate_paper1_g06_2g.py"],
        "compatibility_gate_version": G06_3_GATE_VERSION,
        "generation_build_base_head": authority["generation_build_base_head"],
        "accepted_g06_commit": accepted_commit,
        "current_downstream_head": current_head,
        "accepted_generation_id": authority["accepted_generation"]["generation_id"],
        "compatibility_acceptance_state": compatibility_state,
        "compatibility_acceptance_commit": compatibility_commit,
        "ancestry_rule": authority["required_ancestry_rule"],
        "source_integrity_rule": authority["supersession_policy"],
    })


def validate_validation_generation(
        project_root: Path, directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    directory = Path(directory).resolve()
    authority = _load_authority(root)
    accepted_commit = _derive_accepted_commit(root, authority)
    current_head = _validate_ancestry(root, accepted_commit)
    compatibility_state, compatibility_commit = _derive_compatibility_acceptance(
        root, authority, current_head
    )

    accepted_source = authority["accepted_source"]
    _validate_frozen_paths(root, accepted_commit, accepted_source, False)
    consequential_worktree = {
        path: digest for path, digest in accepted_source.items()
        if path != "src/paper1_g06_2_runtime.py"
    }
    _validate_frozen_paths(root, accepted_commit, consequential_worktree, True)
    _validate_frozen_paths(
        root, accepted_commit, authority["accepted_independent_audit"], True
    )
    decision = _validate_independent_decision(root, authority)
    manifest = _validate_generation(root, authority, directory)
    _validate_production_facade(root)

    result = dict(manifest)
    result["g06_3_validation"] = {
        "status": "PASS",
        "generation_build_base_head": authority["generation_build_base_head"],
        "accepted_g06_commit": accepted_commit,
        "current_downstream_head": current_head,
        "accepted_commit_is_ancestor": True,
        "compatibility_acceptance_state": compatibility_state,
        "compatibility_acceptance_commit": compatibility_commit,
        "accepted_source_identity": "PASS",
        "accepted_generation_identity": "PASS",
        "independent_verdict": decision["independent_verdict"],
        "g07_consumability": decision["g07_consumability"],
    }
    return MappingProxyType(result)


PRODUCTION_API_MANIFEST = MappingProxyType({
    "api_identity": API_IDENTITY,
    "production_import": G06_3_PRODUCTION_FACADE,
    "implementation_module": G06_3_COMPATIBILITY_MODULE,
    "accepted_implementation_module": G06_3_ACCEPTED_IMPLEMENTATION,
    "compatibility_gate": G06_3_GATE_VERSION,
    "accepted_gate": "PAPER1_G06.2g",
    "legacy_policy": "NONEXPORTED_AUTHORITY_APIS_FAIL_CLOSED",
})
