"""G06.3a lineage-safe compatibility for accepted Paper 1 G06 authority.

The accepted G06.2g execution contracts and G06.3 descendant semantics remain
unchanged. This version additionally proves that the uniquely derived
compatibility acceptance commit descends from its declared build base.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from src import paper1_g06_3_runtime as _previous


for _export_name in dir(_previous):
    if not _export_name.startswith("_"):
        globals()[_export_name] = getattr(_previous, _export_name)


G06_3A_GATE_VERSION = "PAPER1_G06.3a"
G06_3A_AUTHORITY_PATH = "documentation/PAPER1_G06_3A_ACCEPTED_AUTHORITY.json"
G06_3A_AUTHORITY_SHA256 = (
    "7047a35755f3ee6750dcb67e414ba25ee8c27322f428f0c10fc8a58cf2e78f3b"
)
G06_3A_PRODUCTION_FACADE = "src.paper1_g06_2_runtime"
G06_3A_COMPATIBILITY_MODULE = "src.paper1_g06_3a_runtime"
G06_3A_ACCEPTED_IMPLEMENTATION = "src.paper1_g06_2g_runtime"
G06_3A_PRODUCTION_FACADE_SHA256 = (
    "eaa8f7809c8bf547e631820c9965eb208ef7174278202f39e9fa8fd82020f755"
)


def _load_authority(root: Path) -> Mapping[str, object]:
    path = root / G06_3A_AUTHORITY_PATH
    if not path.is_file() or _previous._sha256_path(path) != G06_3A_AUTHORITY_SHA256:
        raise ContractError("ERR_G06_3A_AUTHORITY_RECORD_IDENTITY")
    try:
        authority = json.loads(path.read_text(encoding="ascii"))
    except Exception as exc:
        raise ContractError("ERR_G06_3A_AUTHORITY_RECORD_SCHEMA") from exc
    required = {
        "schema_version", "gate_version", "generation_build_base_head",
        "accepted_g06_commit", "accepted_commit_subject",
        "compatibility_build_base_head", "compatibility_acceptance_derivation",
        "accepted_commit_derivation", "accepted_generation", "accepted_source",
        "accepted_independent_audit", "required_independent_decision",
        "required_ancestry_rule", "supersession_policy",
    }
    if (set(authority) != required or
            authority.get("gate_version") != G06_3A_GATE_VERSION):
        raise ContractError("ERR_G06_3A_AUTHORITY_RECORD_SCHEMA")
    return MappingProxyType(authority)


def _derive_compatibility_acceptance(
        root: Path, authority: Mapping[str, object], current_head: str) -> tuple[str, str]:
    derivation = authority["compatibility_acceptance_derivation"]
    if not isinstance(derivation, dict) or derivation.get("method") != (
        "UNIQUE_GIT_ADD_COMMIT_FOR_G06_3A_AUTHORITY_RECORD"
    ):
        raise ContractError("ERR_G06_3A_COMPATIBILITY_ACCEPTANCE_DERIVATION")
    path = str(derivation.get("path", ""))
    commits = [line.strip() for line in _previous._git(
        root, "log", "--diff-filter=A", "--format=%H", "--", path
    ).stdout.splitlines() if line.strip()]

    if not commits:
        status = _previous._git(root, "status", "--short", "--", path).stdout.strip()
        if (current_head != authority["compatibility_build_base_head"] or
                status != f"?? {path}"):
            raise ContractError("ERR_G06_3A_PREACCEPTANCE_STATE")
        return "PRE_ACCEPTANCE_AUDIT", "UNCOMMITTED"

    if len(commits) != 1:
        raise ContractError("ERR_G06_3A_COMPATIBILITY_ACCEPTANCE_DERIVATION")
    compatibility_commit = commits[0]

    build_base_relation = _previous._git(
        root, "merge-base", "--is-ancestor",
        str(authority["compatibility_build_base_head"]), compatibility_commit,
        check=False,
    )
    if build_base_relation.returncode != 0:
        raise ContractError("ERR_G06_3_COMPATIBILITY_ACCEPTANCE_LINEAGE")

    current_relation = _previous._git(
        root, "merge-base", "--is-ancestor", compatibility_commit, current_head,
        check=False,
    )
    if current_relation.returncode != 0:
        raise ContractError("ERR_G06_3A_COMPATIBILITY_COMMIT_NOT_ANCESTOR")

    frozen_paths = derivation.get("frozen_paths", [])
    if not isinstance(frozen_paths, list) or len(frozen_paths) != 4:
        raise ContractError("ERR_G06_3A_COMPATIBILITY_ACCEPTANCE_DERIVATION")
    for relative_path in frozen_paths:
        committed = _previous._sha256_bytes(
            _previous._git_blob(root, compatibility_commit, relative_path)
        )
        path_object = root / relative_path
        if not path_object.is_file() or _previous._sha256_path(path_object) != committed:
            raise ContractError(
                f"ERR_G06_3A_COMPATIBILITY_SOURCE_CHANGED:{relative_path}"
            )
    return "ACCEPTED_DESCENDANT", compatibility_commit


def _validate_production_facade(root: Path) -> None:
    from src import paper1_g06_2_runtime as facade

    production = facade.PRODUCTION_API_MANIFEST
    if (_previous._sha256_path(root / "src/paper1_g06_2_runtime.py") !=
            G06_3A_PRODUCTION_FACADE_SHA256 or
            production.get("production_import") != G06_3A_PRODUCTION_FACADE or
            production.get("implementation_module") != G06_3A_COMPATIBILITY_MODULE or
            production.get("accepted_implementation_module") !=
            G06_3A_ACCEPTED_IMPLEMENTATION or
            facade.validate_validation_generation is not validate_validation_generation):
        raise ContractError("ERR_G06_3A_PRODUCTION_FACADE")


def current_generation_authority(project_root: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    authority = _load_authority(root)
    accepted_commit = _previous._derive_accepted_commit(root, authority)
    current_head = _previous._validate_ancestry(root, accepted_commit)
    compatibility_state, compatibility_commit = _derive_compatibility_acceptance(
        root, authority, current_head
    )
    manifest = _previous._validate_generation(root, authority)
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
        "facade_source_sha256": _previous._sha256_path(
            root / "src/paper1_g06_2_runtime.py"
        ),
        "runtime_source_sha256": authority["accepted_source"][
            "src/paper1_g06_2g_runtime.py"
        ],
        "validator_source_sha256": authority["accepted_source"][
            "scripts/validate_paper1_g06_2g.py"
        ],
        "compatibility_gate_version": G06_3A_GATE_VERSION,
        "generation_build_base_head": authority["generation_build_base_head"],
        "compatibility_build_base_head": authority["compatibility_build_base_head"],
        "accepted_g06_commit": accepted_commit,
        "current_downstream_head": current_head,
        "accepted_generation_id": authority["accepted_generation"]["generation_id"],
        "compatibility_acceptance_state": compatibility_state,
        "compatibility_acceptance_commit": compatibility_commit,
        "compatibility_build_base_is_ancestor": (
            compatibility_state == "PRE_ACCEPTANCE_AUDIT" or
            compatibility_commit != "UNCOMMITTED"
        ),
        "ancestry_rule": authority["required_ancestry_rule"],
        "source_integrity_rule": authority["supersession_policy"],
    })


def validate_validation_generation(
        project_root: Path, directory: Path) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    directory = Path(directory).resolve()
    authority = _load_authority(root)
    accepted_commit = _previous._derive_accepted_commit(root, authority)
    current_head = _previous._validate_ancestry(root, accepted_commit)
    compatibility_state, compatibility_commit = _derive_compatibility_acceptance(
        root, authority, current_head
    )

    accepted_source = authority["accepted_source"]
    _previous._validate_frozen_paths(root, accepted_commit, accepted_source, False)
    consequential_worktree = {
        path: digest for path, digest in accepted_source.items()
        if path != "src/paper1_g06_2_runtime.py"
    }
    _previous._validate_frozen_paths(
        root, accepted_commit, consequential_worktree, True
    )
    _previous._validate_frozen_paths(
        root, accepted_commit, authority["accepted_independent_audit"], True
    )
    decision = _previous._validate_independent_decision(root, authority)
    manifest = _previous._validate_generation(root, authority, directory)
    _validate_production_facade(root)

    result = dict(manifest)
    result["g06_3_validation"] = {
        "status": "PASS",
        "compatibility_gate_version": G06_3A_GATE_VERSION,
        "generation_build_base_head": authority["generation_build_base_head"],
        "compatibility_build_base_head": authority["compatibility_build_base_head"],
        "accepted_g06_commit": accepted_commit,
        "current_downstream_head": current_head,
        "accepted_commit_is_ancestor": True,
        "compatibility_acceptance_state": compatibility_state,
        "compatibility_acceptance_commit": compatibility_commit,
        "compatibility_build_base_is_ancestor": True,
        "accepted_source_identity": "PASS",
        "accepted_generation_identity": "PASS",
        "independent_verdict": decision["independent_verdict"],
        "g07_consumability": decision["g07_consumability"],
    }
    return MappingProxyType(result)


PRODUCTION_API_MANIFEST = MappingProxyType({
    "api_identity": API_IDENTITY,
    "production_import": G06_3A_PRODUCTION_FACADE,
    "implementation_module": G06_3A_COMPATIBILITY_MODULE,
    "accepted_implementation_module": G06_3A_ACCEPTED_IMPLEMENTATION,
    "compatibility_gate": G06_3A_GATE_VERSION,
    "accepted_gate": "PAPER1_G06.2g",
    "legacy_policy": "NONEXPORTED_AUTHORITY_APIS_FAIL_CLOSED",
})
