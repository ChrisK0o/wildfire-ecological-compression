"""Fail-closed Paper 1 G08 pre-execution readiness and authorization gate."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import asdict, dataclass, replace
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from types import MappingProxyType, SimpleNamespace
from typing import Mapping, Sequence

import pandas as pd

from src import paper1_analysis_registry as registry
from src import paper1_g05a_contract_oracle as schema_oracle
import src.paper1_g06_2_runtime as g06
from src import paper1_g06_4f_runtime as g06_4f
import src.paper1_g07_runtime as g07
from src import paper1_g07_v2_policy as g07_v2
from src import paper1_pr34_modeling as model_spec


GATE_VERSION = "PAPER1_G08_V2_CORRECTION_6"
SCHEMA_VERSION = "PAPER1_G08_AUTHORIZATION_V2"
EXECUTION_IDENTITY_SCHEMA_VERSION = "PAPER1_G08_EXECUTION_IDENTITY_V2"
AUTHORIZATION_SCHEMA_NAME = "PAPER1_G08_ACTIVE_AUTHORIZATION_V2"
ACCEPTED_G07_IMPLEMENTATION_COMMIT = "d49e86c7326beb3c563ac724cc1ebb79ba232e96"
INDEPENDENT_G07_ACCEPTANCE_COMMIT = "90c74591530d87636eaf48605cba7c8789c24263"
ACCEPTED_G07_COMMIT = ACCEPTED_G07_IMPLEMENTATION_COMMIT
ACCEPTED_G07_RUNTIME_SHA256 = "5b9a9234e764d4f92335d7bda89c3df8f9d4e4017727f2fdf44f2f3d1aa9d05b"
ACCEPTED_G07_POLICY_SHA256 = "1feecfcb7a9503501a3c8afeb08aa4eaea08d2bbc0d267bd49ae3ca95650e443"
ACCEPTED_POLICY_MATRIX_SHA256 = "feedc3947877d7e9b46410a4b9fde7b794e8308d37e8146e397589c1cc0d179f"
ACCEPTED_G07_SOURCE_SHA256 = ACCEPTED_G07_RUNTIME_SHA256
ACCEPTED_G07_SOURCE_PATHS = MappingProxyType({
    "src/paper1_g07_runtime.py": ACCEPTED_G07_RUNTIME_SHA256,
    "src/paper1_g07_v2_policy.py": ACCEPTED_G07_POLICY_SHA256,
})
ACCEPTED_POLICY_MATRIX_RELATIVE = Path(
    "documentation/PAPER1_G07_V2_CORRECTION_1_POLICY_MATRIX.csv"
)
G07_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G07_V2_CORRECTION_4_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G07_V2_CORRECTION_4_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G07_V2_CORRECTION_4_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G07_V2_CORRECTION_4_GATE_DECISION.csv",
)
EXPECTED_G07_ACCEPTANCE_AGGREGATE_SHA256 = (
    "ddadbd392d2544df172ab8abcdcc5c9395b68bbe34ee4c44a656b08483c8fdbe"
)
CORRECTION2_ACCEPTED_G08_V2_IMPLEMENTATION_COMMIT = (
    "bc625d36162a4e8c1f2ea0d38bba00248afeb952"
)
CORRECTION2_INDEPENDENT_G08_V2_ACCEPTANCE_COMMIT = (
    "4bb7e99c9f242a64624c51c34b144ce3e9dcd5e4"
)
CORRECTION2_G08_V2_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_V2_CORRECTION_2_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_V2_CORRECTION_2_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_V2_CORRECTION_2_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_V2_CORRECTION_2_GATE_DECISION.csv",
)
CORRECTION2_G08_V2_ACCEPTANCE_ARTIFACT_SHA256 = MappingProxyType({
    CORRECTION2_G08_V2_ACCEPTANCE_PATHS[0]:
        "0ae10d75e580999e988be09e4b7c275a815772a97680ba2ca85e05128e137459",
    CORRECTION2_G08_V2_ACCEPTANCE_PATHS[1]:
        "33b762546c28a14fdafccbd79aeb0c1718ea6d7bf5413c34def69137f5c9c5a4",
    CORRECTION2_G08_V2_ACCEPTANCE_PATHS[2]:
        "1437e40f51f4ef00f5a839f6e788ddb4b5ebfb9c0985f88edb65e86454914a73",
    CORRECTION2_G08_V2_ACCEPTANCE_PATHS[3]:
        "23e90d75aa2aa5f2cebfad74f7ce0c6ca54011abf65fb700754dcba88f727a53",
})
CORRECTION2_G08_V2_ACCEPTANCE_AGGREGATE_SHA256 = (
    "2da0abe1ea6b146d11ca3dd639b2d2bdb4828aa62fc10c10b04cd6b337af6bf3"
)
CORRECTION4_BASE_COMMIT = "23ad96a3cf6a93de230ece5f94e7725c8b44ee86"
CORRECTION4_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_v2_correction_4.py",
    "documentation/PAPER1_G08_V2_CORRECTION_4_DECISION.md",
    "documentation/PAPER1_G08_V2_CORRECTION_4_LINEAGE_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_4_REAL_TOPOLOGY_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_4_ACCEPTANCE_SCHEMA_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_4_REGRESSION_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_4_TEST_EXECUTION.csv",
})
CORRECTION5_BASE_COMMIT = "75c2fc5d8ef02c2b24715961ef3c45696a61171b"
CORRECTION5_IMPLEMENTATION_TEST_PATH = (
    "documentation/PAPER1_G08_V2_CORRECTION_5_TEST_EXECUTION.csv"
)
CORRECTION5_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_v2_correction_5.py",
    "documentation/PAPER1_G08_V2_CORRECTION_5_DECISION.md",
    "documentation/PAPER1_G08_V2_CORRECTION_5_OPERATOR_TRUST_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_5_IMPLEMENTATION_BINDING_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_5_TEST_RESULT_BINDING_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_5_REAL_TOPOLOGY_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_5_REGRESSION_QC.csv",
    CORRECTION5_IMPLEMENTATION_TEST_PATH,
})
CORRECTION6_BASE_COMMIT = "25f894315c996b3cb64c08a7117e8a5a1be11463"
CORRECTION6_IMPLEMENTATION_TEST_PATH = (
    "documentation/PAPER1_G08_V2_CORRECTION_6_TEST_EXECUTION.csv"
)
CORRECTION6_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_v2_correction_6.py",
    "documentation/PAPER1_G08_V2_CORRECTION_6_DECISION.md",
    "documentation/PAPER1_G08_V2_CORRECTION_6_ISSUE_STATUS_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_6_BLOCKER_RECONCILIATION_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_6_TRUST_ROOT_REGRESSION_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_6_TEST_BINDING_REGRESSION_QC.csv",
    "documentation/PAPER1_G08_V2_CORRECTION_6_REGRESSION_QC.csv",
    CORRECTION6_IMPLEMENTATION_TEST_PATH,
})
PRIOR_G08_ACTIVATION_COMMIT = "5d30361ffbcf4acba301339cd5e6eefd5bdd0908"
OUTPUT_COLLISION_CORRECTION1_COMMIT = "b97d9df5bfc22b15fed217b19ad183dc799b9a3d"
OUTPUT_COLLISION_REJECTION_COMMIT = "23a7dc5c0863d2e5bd54b6995dfead622dd6ddf5"
OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_COMMIT = (
    "fed0982cb4797b3ec9cd6d19b0f7591f504d6c80"
)
OUTPUT_COLLISION_CORRECTION2_ACCEPTANCE_COMMIT = (
    "4c2230e00bb3b978b6843e506d08c02396a89467"
)
OUTPUT_COLLISION_CORRECTION1_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_v2_output_collision_correction.py",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_CORRECTION.md",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_CLASSIFICATION_QC.csv",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_TEST_EXECUTION.csv",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_DECISION.csv",
})
OUTPUT_COLLISION_REJECTION_PATHS = frozenset({
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_GATE_DECISION.csv",
})
OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_v2_output_collision_correction_2.py",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_CORRECTION_2.md",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_CORRECTION_2_CONTRACT_QC.csv",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_CORRECTION_2_TEST_EXECUTION.csv",
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_CORRECTION_2_DECISION.csv",
})
OUTPUT_COLLISION_CORRECTION2_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_CORRECTION_2_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_CORRECTION_2_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_CORRECTION_2_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_V2_OUTPUT_COLLISION_CORRECTION_2_GATE_DECISION.csv",
)
OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_TEST_PATH = (
    "documentation/PAPER1_G08_V2_OUTPUT_COLLISION_CORRECTION_2_TEST_EXECUTION.csv"
)
AUTHORITY_LINEAGE_CORRECTION_BASE_COMMIT = (
    OUTPUT_COLLISION_CORRECTION2_ACCEPTANCE_COMMIT
)
AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_v2_authority_lineage_correction.py",
    "documentation/PAPER1_G08_V2_AUTHORITY_LINEAGE_CORRECTION.md",
    "documentation/PAPER1_G08_V2_AUTHORITY_LINEAGE_CORRECTION_LINEAGE_QC.csv",
    "documentation/PAPER1_G08_V2_AUTHORITY_LINEAGE_CORRECTION_TEST_EXECUTION.csv",
    "documentation/PAPER1_G08_V2_AUTHORITY_LINEAGE_CORRECTION_DECISION.csv",
})
AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_TEST_PATH = (
    "documentation/PAPER1_G08_V2_AUTHORITY_LINEAGE_CORRECTION_TEST_EXECUTION.csv"
)
AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_V2_AUTHORITY_LINEAGE_CORRECTION_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_V2_AUTHORITY_LINEAGE_CORRECTION_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_V2_AUTHORITY_LINEAGE_CORRECTION_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_V2_AUTHORITY_LINEAGE_CORRECTION_GATE_DECISION.csv",
)
G08_V2_ACCEPTANCE_PATHS = AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_PATHS
AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT = (
    "c879c8cb686787ffc994f6e5134240df9f9e06e1"
)
AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT = (
    "d16cabfccb9fd7fcb200bfce29f971f8aa50e4fa"
)
AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT = (
    "6e74e581786889dc0a29aa524e092dd87bd904f9"
)
DOWNSTREAM_G06_G07_CORRECTION_COMMIT = (
    "fa0c7629c2a3e45bcb962bdb51d3637d633d7bbf"
)
DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT = (
    "80e82227a64f8de4b66fc7391f637bab11318466"
)
DOWNSTREAM_G06_G07_CORRECTION_PATHS = frozenset({
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_CORRECTION.md",
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_QC.csv",
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_DECISION.csv",
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_NEGATIVE_TESTS.csv",
    "scripts/validate_paper1_g06_g07_no_early_benchmark_authority.py",
    "src/paper1_g06_4f_runtime.py",
    "src/paper1_g07_runtime.py",
})
DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_GATE_DECISION.csv",
    "documentation/PAPER1_SOL_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_TEST_COVERAGE.csv",
)
DOWNSTREAM_G06_G07_CORRECTION_SHA256 = MappingProxyType({
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_CORRECTION.md":
        "227c2b3cfc8985a046788a2324a640bd053753f8be6391c27d0b62ddd9802b8d",
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_QC.csv":
        "d36013a350d0a13107c1e99dfb11e2b51cb7d7ed0653d46c9cd1d924cf93feee",
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_DECISION.csv":
        "d313b3265b79f645b9da3579aa9a18e8611a6b67aca34da98a28e7ac97fdcfbd",
    "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_NEGATIVE_TESTS.csv":
        "f301b770471206c8fd42c43b60b9517c5e15d9b7c7bd665e3d955dac2bdb1579",
    "scripts/validate_paper1_g06_g07_no_early_benchmark_authority.py":
        "d3aca1f7767671390af849367fe17775c10988f02ae12e3d5175a2407c6db254",
    "src/paper1_g06_4f_runtime.py":
        "878db81a900c1dc2e04faa6e13b1ff3ab0c0d8a5576d14395b39a22af3a84aef",
    "src/paper1_g07_runtime.py":
        "1a851c5f6e38b03f7ee8bd27892633e52a93aea023a27e1c76bb6203cb6c0e27",
})
DOWNSTREAM_G06_G07_ACCEPTANCE_SHA256 = MappingProxyType({
    DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[0]:
        "e18996826061f817b9d051357d7200406f6f86bbe24f5b0703ba5232ab6a78ce",
    DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[1]:
        "9e88c9d99d7564cbadfb060802f96e795032fcf35090ddaf0c7b79a9ee6d1b4a",
    DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[2]:
        "3f6f48b010ab6e8220987de44f9ca2fe3fb99ac3cf6c90496411473c57b29e8b",
    DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[3]:
        "fe22b55554f7a2bc118a0e277cb0244a318deb3ec8d8c15e405eb1b4cc8d339d",
})
PRIOR_ACCEPTED_ACTIVATION_SHA256 = MappingProxyType({
    "documentation/PAPER1_G08_ACTIVE_AUTHORIZATION.json":
        "b23afa201edcb46d2596f3870bcf55207c85134f6ab510f768e1119e73a4cf85",
    "documentation/PAPER1_SOL_G08_FINAL_GATE_DECISION.csv":
        "c59b1d4597d49b255d6e0ac860ff96ddd16dfbb1b4024d4bfd57f1f0cbf189bb",
})
DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_downstream_authority_lineage.py",
    "documentation/PAPER1_G08_DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION.md",
    "documentation/PAPER1_G08_DOWNSTREAM_AUTHORITY_LINEAGE_QC.csv",
    "documentation/PAPER1_G08_DOWNSTREAM_AUTHORITY_LINEAGE_TEST_EXECUTION.csv",
    "documentation/PAPER1_G08_DOWNSTREAM_AUTHORITY_LINEAGE_DECISION.csv",
})
DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_TEST_PATH = (
    "documentation/PAPER1_G08_DOWNSTREAM_AUTHORITY_LINEAGE_TEST_EXECUTION.csv"
)
DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_DOWNSTREAM_AUTHORITY_LINEAGE_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_DOWNSTREAM_AUTHORITY_LINEAGE_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_DOWNSTREAM_AUTHORITY_LINEAGE_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_DOWNSTREAM_AUTHORITY_LINEAGE_GATE_DECISION.csv",
)
GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT = (
    "80bd9bb5da1792107e7288eb2cd26d3ecf410211"
)
GOVERNED_TRANSITION_REGISTRY_RELATIVE = Path(
    "documentation/PAPER1_G08_GOVERNED_DOWNSTREAM_TRANSITIONS.json"
)
GOVERNED_TRANSITION_REGISTRY_SCHEMA = (
    "PAPER1_G08_GOVERNED_DOWNSTREAM_TRANSITIONS_V1"
)
GOVERNED_TRANSITION_CORRECTION_TEST_PATH = (
    "documentation/PAPER1_G08_GOVERNED_DOWNSTREAM_TRANSITION_TEST_EXECUTION.csv"
)
GOVERNED_TRANSITION_CORRECTION_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_governed_downstream_transitions.py",
    GOVERNED_TRANSITION_REGISTRY_RELATIVE.as_posix(),
    "documentation/PAPER1_G08_GOVERNED_DOWNSTREAM_TRANSITION_CORRECTION.md",
    "documentation/PAPER1_G08_GOVERNED_DOWNSTREAM_TRANSITION_QC.csv",
    GOVERNED_TRANSITION_CORRECTION_TEST_PATH,
    "documentation/PAPER1_G08_GOVERNED_DOWNSTREAM_TRANSITION_DECISION.csv",
})
GOVERNED_TRANSITION_CORRECTION_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_GOVERNED_DOWNSTREAM_TRANSITION_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_GOVERNED_DOWNSTREAM_TRANSITION_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_GOVERNED_DOWNSTREAM_TRANSITION_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_GOVERNED_DOWNSTREAM_TRANSITION_GATE_DECISION.csv",
)
GOVERNED_TRANSITION_GATE_NAME = (
    "PAPER1_SOL_G08_GOVERNED_DOWNSTREAM_TRANSITION_FINAL_ACCEPTANCE"
)
GOVERNED_SUCCESSOR_SCOPE_CORRECTION_BASE_COMMIT = (
    "c9cde731d19fc07b12ef6000ed9eb7696b56e07e"
)
GOVERNED_SUCCESSOR_SCOPE_CORRECTION_TEST_PATH = (
    "documentation/PAPER1_G08_GOVERNED_SUCCESSOR_SCOPE_CORRECTION_TEST_EXECUTION.csv"
)
GOVERNED_SUCCESSOR_SCOPE_CORRECTION_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_governed_successor_scope.py",
    "documentation/PAPER1_G08_GOVERNED_SUCCESSOR_SCOPE_CORRECTION.md",
    "documentation/PAPER1_G08_GOVERNED_SUCCESSOR_SCOPE_CORRECTION_QC.csv",
    GOVERNED_SUCCESSOR_SCOPE_CORRECTION_TEST_PATH,
    "documentation/PAPER1_G08_GOVERNED_SUCCESSOR_SCOPE_CORRECTION_DECISION.csv",
})
GOVERNED_SUCCESSOR_SCOPE_CORRECTION_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_GOVERNED_SUCCESSOR_SCOPE_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_GOVERNED_SUCCESSOR_SCOPE_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_GOVERNED_SUCCESSOR_SCOPE_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_GOVERNED_SUCCESSOR_SCOPE_GATE_DECISION.csv",
)
GOVERNED_SUCCESSOR_SCOPE_GATE_NAME = (
    "PAPER1_SOL_G08_GOVERNED_SUCCESSOR_SCOPE_FINAL_ACCEPTANCE"
)
GOVERNED_CORRECTION_LINEAGE_TEST_PATH = (
    "documentation/PAPER1_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_TEST_EXECUTION.csv"
)
GOVERNED_CORRECTION_LINEAGE_IMPLEMENTATION_PATHS = frozenset({
    "src/paper1_g08_runtime.py",
    "scripts/validate_paper1_g08_governed_transition_correction_lineage.py",
    "documentation/PAPER1_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE.md",
    "documentation/PAPER1_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_QC.csv",
    GOVERNED_CORRECTION_LINEAGE_TEST_PATH,
    "documentation/PAPER1_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_DECISION.csv",
})
GOVERNED_CORRECTION_LINEAGE_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_GATE_DECISION.csv",
)
GOVERNED_CORRECTION_LINEAGE_GATE_NAME = (
    "PAPER1_SOL_G08_GOVERNED_TRANSITION_CORRECTION_LINEAGE_FINAL_ACCEPTANCE"
)
TRUSTED_IMPLEMENTATION_CONFIG_KEY = "paper1.g08.trustedImplementation"
TRUSTED_ACCEPTANCE_CONFIG_KEY = "paper1.g08.trustedAcceptance"
COMMIT_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_CORRECTION5_IMPLEMENTATION_TEST_IDS = frozenset({
    "T01_MISSING_TRUST_PINS",
    "T02_MALFORMED_TRUST_PINS",
    "T03_EXACT_TRUST_PINS",
    "T04_ALTERNATE_IMPLEMENTATION_REJECTED",
    "T05_IMPLEMENTATION_COUNTS_RECONSTRUCTED",
    "T06_IMPLEMENTATION_COUNT_MISMATCH_REJECTED",
    "T07_INDEPENDENT_COUNTS_RECONSTRUCTED",
    "T08_INDEPENDENT_999_VS_1_REJECTED",
    "T09_CROSS_ARTIFACT_MISMATCH_REJECTED",
    "T10_I_A_X_TOPOLOGY",
    "R01_POLICY_REGRESSION",
    "R02_EVIDENCE_REGRESSION",
    "R03_DEPENDENCY_REGRESSION",
    "R04_V1_INVENTORY",
    "R05_V2_ROOT_ABSENT",
    "R06_NO_SCIENTIFIC_CALLS",
})
REQUIRED_CORRECTION5_INDEPENDENT_TEST_IDS = frozenset({
    "I01_OPERATOR_TRUST_PINS",
    "I02_ALTERNATE_CHAIN_REJECTED",
    "I03_IMPLEMENTATION_COUNTS",
    "I04_INDEPENDENT_COUNTS",
    "I05_CROSS_ARTIFACT_RECONCILIATION",
    "I06_V1_IMMUTABLE",
    "I07_V2_ABSENT",
    "I08_NO_SCIENTIFIC_EXECUTION",
})
REQUIRED_CORRECTION6_IMPLEMENTATION_TEST_IDS = frozenset({
    "P01_BRANCH",
    "P02_HEAD",
    "P03_INITIAL_SCOPE",
    "C01_UNRESOLVED_BLOCKER",
    "C02_OPEN_BLOCKER",
    "C08_BLANK_STATUS",
    "C09_MISSING_STATUS",
    "C13_NONBLOCKING_CRITICAL",
    "C14_CLOSED_PASS",
    "C15_DOCUMENTED_LIMITATION_PASS",
    "C16_ZERO_REPORTED_ONE_BLOCKER",
    "C17_ONE_REPORTED_ZERO_BLOCKERS",
    "C20_MUTATION_REHASH",
    "T01_MISSING_TRUST_PINS",
    "T02_MALFORMED_TRUST_PINS",
    "T03_EXACT_TRUST_PINS",
    "T04_ALTERNATE_IMPLEMENTATION_REJECTED",
    "E01_IMPLEMENTATION_COUNTS",
    "E02_INDEPENDENT_COUNTS",
    "E03_INDEPENDENT_999_VS_1",
    "G01_I_A_X_TOPOLOGY",
    "R01_POLICY_REGRESSION",
    "R02_EVIDENCE_REGRESSION",
    "R03_DEPENDENCY_REGRESSION",
    "R04_V1_INVENTORY",
    "R05_V2_ROOT_ABSENT",
    "R06_NO_SCIENTIFIC_CALLS",
})
REQUIRED_CORRECTION6_INDEPENDENT_TEST_IDS = frozenset({
    "I01_OPERATOR_TRUST_PINS",
    "I02_ALTERNATE_CHAIN_REJECTED",
    "I03_IMPLEMENTATION_COUNTS",
    "I04_INDEPENDENT_COUNTS",
    "I05_ISSUE_STATUS_SEMANTICS",
    "I06_BLOCKER_COUNT_RECONCILIATION",
    "I07_CROSS_ARTIFACT_RECONCILIATION",
    "I08_V1_IMMUTABLE",
    "I09_V2_ABSENT",
    "I10_NO_SCIENTIFIC_EXECUTION",
})
ISSUE_STATUS_SEMANTICS = "EXPLICIT_FAIL_CLOSED_ALLOWLIST"
ISSUE_STATUS_CLOSED_OR_RESOLVED = frozenset({"CLOSED", "RESOLVED"})
ISSUE_STATUS_DOCUMENTED_NONBLOCKING = frozenset({"DOCUMENTED_LIMITATION"})
ISSUE_STATUS_ALLOWLIST = (
    ISSUE_STATUS_CLOSED_OR_RESOLVED | ISSUE_STATUS_DOCUMENTED_NONBLOCKING
)
ISSUE_STATUS_KNOWN_BLOCKING = frozenset({
    "OPEN",
    "OPEN_BLOCKER",
    "OPEN_BLOCKING",
    "UNRESOLVED_BLOCKER",
    "ACTIVE_BLOCKER",
    "PENDING_BLOCKER",
    "REQUIRES_CORRECTION",
    "TODO",
    "RESOLUTION_PENDING",
})
ISSUE_CLOSED_ALLOWED_SEVERITIES = frozenset({
    "NONBLOCKING", "HIGH", "CRITICAL",
})
ISSUE_NONBLOCKING_ALLOWED_SEVERITIES = frozenset({"NONBLOCKING"})
EXPECTED_POLICY_MODE_COUNTS = MappingProxyType({
    "TUNE": 180,
    "FIXED": 40,
    "INHERIT": 120,
    "NO_TUNING": 6,
    "NO_REFIT": 1,
    "NOT_APPLICABLE": 5,
})
ACCEPTED_G06_4E_SHA256 = "80584b50db9dbaaa7a77bee7263bed1e0733d76b8734aabf684437a39f3d96ae"
ACCEPTED_G06_4F_SHA256 = "878db81a900c1dc2e04faa6e13b1ff3ab0c0d8a5576d14395b39a22af3a84aef"
ACCEPTED_LOIO_AUTHORITY_SHA256 = "04bf8ed6f26b3af37db33cacbc51150e0362cf0746b134ebd327fa09b92c5d93"
PRODUCTION_OUTPUT_ROOT_RELATIVE = g07_v2.V2_OUTPUT_ROOT_RELATIVE
SUITE_RUN_ID = g07_v2.V2_SUITE_RUN_ID
V1_OUTPUT_ROOT_RELATIVE = Path(
    "data/processed/propagation/paper1/g07_scientific_execution"
)
V1_SUITE_RUN_ID = "PAPER1_G07_SCIENTIFIC_V1"
ACTIVE_AUTHORIZATION_RELATIVE = Path("documentation/PAPER1_G08_ACTIVE_AUTHORIZATION.json")
INDEPENDENT_GATE_RELATIVE = Path("documentation/PAPER1_SOL_G08_FINAL_GATE_DECISION.csv")
PERMITTED_ACTIVATION_PATHS = frozenset({
    ACTIVE_AUTHORIZATION_RELATIVE.as_posix(),
    INDEPENDENT_GATE_RELATIVE.as_posix(),
})

SOURCE_IDENTITIES = MappingProxyType({
    "src/paper1_g06_4e_runtime.py": ACCEPTED_G06_4E_SHA256,
    "src/paper1_g06_4f_runtime.py": ACCEPTED_G06_4F_SHA256,
    "documentation/PAPER1_G07_LOIO_EVIDENCE_AUTHORITY_DECISION.md":
        ACCEPTED_LOIO_AUTHORITY_SHA256,
})


class G08Error(RuntimeError):
    """Fail-closed G08 readiness or authorization error."""


@dataclass(frozen=True)
class ExecutionContextIdentity:
    schema_version: str
    accepted_g07_implementation_commit: str
    independent_g07_acceptance_commit: str
    accepted_g07_runtime_sha256: str
    accepted_g07_v2_policy_sha256: str
    independent_g07_acceptance_artifacts_sha256: str
    current_g07_runtime_sha256: str
    current_g07_v2_policy_sha256: str
    current_g08_runtime_sha256: str
    g06_4e_sha256: str
    g06_4f_sha256: str
    loio_authority_sha256: str
    execution_universe_sha256: str
    policy_universe_sha256: str
    g07_v2_interface_sha256: str
    v2_evidence_lifecycle_sha256: str
    dependency_graph_sha256: str
    real_input_aggregate_sha256: str
    environment_identity_sha256: str
    production_configuration_sha256: str
    output_root: str
    suite_run_id: str
    authorized_unit_count: int
    execution_identity_sha256: str


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str
    ).encode("ascii")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git(root: Path, *arguments: str) -> str:
    from src import paper1_control_reference as reference
    if proof := reference.preparation(root):
        return proof.query(root, arguments, False)
    completed = subprocess.run(
        ["git", *arguments], cwd=root, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise G08Error(f"G08_GIT_COMMAND:{' '.join(arguments)}:{completed.stderr.strip()}")
    return completed.stdout.strip()


def _git_bytes(root: Path, *arguments: str) -> bytes:
    from src import paper1_control_reference as reference
    if proof := reference.preparation(root):
        return proof.query(root, arguments, True)
    completed = subprocess.run(
        ["git", *arguments], cwd=root,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise G08Error(
            f"G08_GIT_COMMAND:{' '.join(arguments)}:"
            f"{completed.stderr.decode('utf-8', errors='replace').strip()}"
        )
    return completed.stdout


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "NOT_INSTALLED"


def _require_commit(root: Path, commit: str, marker: str) -> None:
    try:
        observed = _git(root, "rev-parse", f"{commit}^{{commit}}")
    except G08Error as exc:
        raise G08Error(marker) from exc
    if observed != commit:
        raise G08Error(marker)


def _require_ancestor(root: Path, ancestor: str, descendant: str, marker: str) -> None:
    try:
        _git(root, "merge-base", "--is-ancestor", ancestor, descendant)
    except G08Error as exc:
        raise G08Error(marker) from exc


def _accepted_blob(root: Path, commit: str, relative: str, expected: str) -> bytes:
    payload = _git_bytes(root, "show", f"{commit}:{relative}")
    validate_bound_blob_bytes(payload, expected, f"G08_ACCEPTED_BLOB_IDENTITY:{relative}")
    return payload


def _require_unchanged_tracked_blob(root: Path, relative: str, marker: str) -> None:
    head_oid = _git(root, "rev-parse", f"HEAD:{relative}")
    index_oid = _git(root, "rev-parse", f":{relative}")
    worktree_oid = _git(root, "hash-object", f"--path={relative}", relative)
    if head_oid != index_oid or head_oid != worktree_oid:
        raise G08Error(marker)


def _canonical_clean_tracked_bytes(root: Path, relative: str, marker: str) -> bytes:
    """Return committed bytes only after Git proves the tracked path is clean."""
    path = root / relative
    if not path.is_file():
        raise G08Error(marker)
    _require_unchanged_tracked_blob(root, relative, marker)
    return _git_bytes(root, "show", f"HEAD:{relative}")


def validate_bound_blob_bytes(payload: bytes, expected: str, marker: str) -> str:
    observed = sha256_bytes(payload)
    if observed != expected:
        raise G08Error(marker)
    return observed


def validate_g07_acceptance_payloads(
    payloads: Mapping[str, bytes],
) -> tuple[str, tuple[dict[str, object], ...]]:
    if set(payloads) != set(G07_ACCEPTANCE_PATHS):
        raise G08Error("G08_G07_ACCEPTANCE_ARTIFACT_SET")
    records = []
    for relative in G07_ACCEPTANCE_PATHS:
        payload = payloads[relative]
        if not isinstance(payload, bytes):
            raise G08Error("G08_G07_ACCEPTANCE_ARTIFACT_TYPE")
        records.append({
            "path": relative,
            "size": len(payload),
            "sha256": sha256_bytes(payload),
        })
    aggregate = sha256_bytes(canonical_json(records))
    if aggregate != EXPECTED_G07_ACCEPTANCE_AGGREGATE_SHA256:
        raise G08Error("G08_G07_ACCEPTANCE_AGGREGATE")
    gate_path = "documentation/PAPER1_SOL_G07_V2_CORRECTION_4_GATE_DECISION.csv"
    rows = list(csv.DictReader(payloads[gate_path].decode("utf-8").splitlines()))
    if len(rows) != 1:
        raise G08Error("G08_G07_ACCEPTANCE_GATE_SCHEMA")
    gate = rows[0]
    required = {
        "verdict": "ACCEPT",
        "reviewed_commit": ACCEPTED_G07_IMPLEMENTATION_COMMIT,
        "implementation_pass": "28",
        "implementation_fail": "0",
        "independent_pass": "30",
        "independent_fail": "0",
        "g08_correction_required": "YES",
        "scientific_fitting_authorized": "NO",
    }
    if any(gate.get(key) != value for key, value in required.items()):
        raise G08Error("G08_G07_ACCEPTANCE_SEMANTICS")
    acceptance_text = payloads[G07_ACCEPTANCE_PATHS[0]].decode("utf-8")
    for declaration in (
        "`G08_CORRECTION_REQUIRED=YES`",
        "`SCIENTIFIC_FITTING_AUTHORIZED_NOW=NO`",
    ):
        if declaration not in acceptance_text:
            raise G08Error("G08_G07_ACCEPTANCE_DECLARATION")
    return aggregate, tuple(records)


def _g07_acceptance_identity(root: Path) -> tuple[str, tuple[dict[str, object], ...]]:
    payloads: dict[str, bytes] = {}
    for relative in G07_ACCEPTANCE_PATHS:
        payload = _git_bytes(
            root, "show", f"{INDEPENDENT_G07_ACCEPTANCE_COMMIT}:{relative}"
        )
        payloads[relative] = payload
        current_blob = _git_bytes(root, "show", f"HEAD:{relative}")
        _require_unchanged_tracked_blob(
            root, relative, f"G08_G07_ACCEPTANCE_DISK_IDENTITY:{relative}"
        )
        if current_blob != payload:
            raise G08Error(f"G08_G07_ACCEPTANCE_DISK_IDENTITY:{relative}")
    return validate_g07_acceptance_payloads(payloads)


def validate_g08_v2_acceptance_payloads(
    payloads: Mapping[str, bytes],
) -> tuple[str, tuple[dict[str, object], ...]]:
    """Authenticate the actual Correction-2 independent-acceptance schema."""
    if set(payloads) != set(CORRECTION2_G08_V2_ACCEPTANCE_PATHS):
        raise G08Error("G08_V2_ACCEPTANCE_ARTIFACT_SET")
    records = []
    for relative in CORRECTION2_G08_V2_ACCEPTANCE_PATHS:
        payload = payloads[relative]
        if not isinstance(payload, bytes):
            raise G08Error("G08_V2_ACCEPTANCE_ARTIFACT_TYPE")
        observed = sha256_bytes(payload)
        if observed != CORRECTION2_G08_V2_ACCEPTANCE_ARTIFACT_SHA256[relative]:
            raise G08Error(f"G08_V2_ACCEPTANCE_ARTIFACT_IDENTITY:{relative}")
        records.append({"path": relative, "sha256": observed})
    aggregate = sha256_bytes(canonical_json(records))
    if aggregate != CORRECTION2_G08_V2_ACCEPTANCE_AGGREGATE_SHA256:
        raise G08Error("G08_V2_ACCEPTANCE_AGGREGATE")

    gate_path = CORRECTION2_G08_V2_ACCEPTANCE_PATHS[3]
    rows = list(csv.DictReader(payloads[gate_path].decode("utf-8").splitlines()))
    if len(rows) != 1:
        raise G08Error("G08_V2_ACCEPTANCE_GATE_SCHEMA")
    gate = rows[0]
    required = {
        "verdict": "ACCEPT",
        "reviewed_commit": CORRECTION2_ACCEPTED_G08_V2_IMPLEMENTATION_COMMIT,
        "reviewed_parent": "ced8e83332170077f0f3b78230f692c849a5279e",
        "implementation_pass": "116",
        "implementation_fail": "0",
        "independent_pass": "76",
        "independent_fail": "0",
        "v2_active_authorization_created": "NO",
        "scientific_fitting_authorized": "NO",
        "models_fit": "0",
        "real_predictions_generated": "0",
        "real_performance_inspected": "0",
        "final_gate": "ACCEPT",
        "next_authorized_action": "G08_V2_ACTIVATION_ONLY_GATE",
    }
    if any(gate.get(key) != value for key, value in required.items()):
        raise G08Error("G08_V2_ACCEPTANCE_SEMANTICS")

    acceptance_text = payloads[CORRECTION2_G08_V2_ACCEPTANCE_PATHS[0]].decode(
        "utf-8"
    )
    for declaration in (
        "`ACCEPT`",
        CORRECTION2_ACCEPTED_G08_V2_IMPLEMENTATION_COMMIT,
        "Scientific fitting remains unauthorized.",
        "G08 V2 activation-only gate/commit",
    ):
        if declaration not in acceptance_text:
            raise G08Error("G08_V2_ACCEPTANCE_DECLARATION")
    return aggregate, tuple(records)


def correction2_g08_v2_acceptance_identity(
    root: Path,
) -> tuple[str, tuple[dict[str, object], ...]]:
    """Reopen frozen Correction-2 acceptance as regression authority."""
    root = Path(root).resolve()
    acceptance_commit = CORRECTION2_INDEPENDENT_G08_V2_ACCEPTANCE_COMMIT
    _require_commit(root, acceptance_commit, "G08_V2_CORRECTION2_ACCEPTANCE_COMMIT")
    if _git(root, "rev-parse", f"{acceptance_commit}^") != (
        CORRECTION2_ACCEPTED_G08_V2_IMPLEMENTATION_COMMIT
    ):
        raise G08Error("G08_V2_CORRECTION2_ACCEPTANCE_PARENT")
    payloads = {
        relative: _git_bytes(root, "show", f"{acceptance_commit}:{relative}")
        for relative in CORRECTION2_G08_V2_ACCEPTANCE_PATHS
    }
    return validate_g08_v2_acceptance_payloads(payloads)


def _commit_changed_paths(root: Path, commit: str) -> frozenset[str]:
    return frozenset(
        _git(
            root, "diff-tree", "--no-commit-id", "--name-only", "-r", commit
        ).splitlines()
    )


def _csv_rows(payload: bytes, marker: str) -> tuple[list[str], list[dict[str, str]]]:
    try:
        reader = csv.DictReader(payload.decode("utf-8").splitlines())
        rows = [dict(row) for row in reader]
    except (UnicodeDecodeError, csv.Error) as exc:
        raise G08Error(marker) from exc
    if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise G08Error(marker)
    return list(reader.fieldnames), rows


def _test_result(
    rows: Sequence[Mapping[str, str]],
    required_ids: frozenset[str],
    marker: str,
    *,
    independent_only: bool = False,
) -> Mapping[str, object]:
    if not rows:
        raise G08Error(marker)
    identifiers = [row.get("test_id", "") for row in rows]
    if any(not identifier for identifier in identifiers) or len(identifiers) != len(
        set(identifiers)
    ):
        raise G08Error(f"{marker}_TEST_ID")
    selected: list[Mapping[str, str]] = []
    for row in rows:
        if row.get("result") not in {"PASS", "FAIL"}:
            raise G08Error(f"{marker}_RESULT")
        try:
            if int(row.get("assertion_count", "")) <= 0:
                raise ValueError
        except ValueError as exc:
            raise G08Error(f"{marker}_ASSERTION_COUNT") from exc
        if independent_only:
            if row.get("independent_test") not in {"YES", "NO"}:
                raise G08Error(f"{marker}_INDEPENDENT_FLAG")
            if row.get("independent_test") == "YES":
                selected.append(row)
        else:
            selected.append(row)
    selected_ids = {row["test_id"] for row in selected}
    if not required_ids.issubset(selected_ids):
        raise G08Error(f"{marker}_REQUIRED_COVERAGE")
    passed = sum(row["result"] == "PASS" for row in selected)
    failed = sum(row["result"] == "FAIL" for row in selected)
    return MappingProxyType({
        "pass": passed,
        "fail": failed,
        "count": len(selected),
        "test_ids": tuple(sorted(selected_ids)),
    })


def validate_correction5_implementation_test_payload(
    payload: bytes,
) -> Mapping[str, object]:
    fieldnames, rows = _csv_rows(payload, "G08_V2_IMPLEMENTATION_TEST_SCHEMA")
    if set(fieldnames) != {
        "area", "test_id", "result", "assertion_count", "expected", "observed"
    }:
        raise G08Error("G08_V2_IMPLEMENTATION_TEST_SCHEMA")
    return _test_result(
        rows,
        REQUIRED_CORRECTION5_IMPLEMENTATION_TEST_IDS,
        "G08_V2_IMPLEMENTATION_TEST",
    )


def correction5_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(),
        "show",
        f"{implementation_commit}:{CORRECTION5_IMPLEMENTATION_TEST_PATH}",
    )
    return validate_correction5_implementation_test_payload(payload)


def validate_correction6_implementation_test_payload(
    payload: bytes,
) -> Mapping[str, object]:
    fieldnames, rows = _csv_rows(payload, "G08_V2_IMPLEMENTATION_TEST_SCHEMA")
    if set(fieldnames) != {
        "area", "test_id", "result", "assertion_count", "expected", "observed"
    }:
        raise G08Error("G08_V2_IMPLEMENTATION_TEST_SCHEMA")
    return _test_result(
        rows,
        REQUIRED_CORRECTION6_IMPLEMENTATION_TEST_IDS,
        "G08_V2_IMPLEMENTATION_TEST",
    )


def correction6_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(),
        "show",
        f"{implementation_commit}:{CORRECTION6_IMPLEMENTATION_TEST_PATH}",
    )
    return validate_correction6_implementation_test_payload(payload)


def _acceptance_report_fields(payload: bytes) -> Mapping[str, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise G08Error("G08_V2_ACCEPTANCE_REPORT_SCHEMA") from exc
    fields: dict[str, str] = {}
    for line in text.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            if key in fields:
                raise G08Error("G08_V2_ACCEPTANCE_REPORT_SCHEMA")
            fields[key] = value.strip()
    return MappingProxyType(fields)


def classify_g08_acceptance_issue(row: Mapping[str, str]) -> Mapping[str, object]:
    """Classify one issue row using the exact fail-closed G08 vocabulary."""
    raw_status = row.get("status")
    raw_severity = row.get("severity")
    status = raw_status.strip().upper() if isinstance(raw_status, str) else ""
    severity = raw_severity.strip().upper() if isinstance(raw_severity, str) else ""

    if (
        status in ISSUE_STATUS_CLOSED_OR_RESOLVED
        and severity in ISSUE_CLOSED_ALLOWED_SEVERITIES
    ):
        category = "CLOSED_OR_RESOLVED"
        acceptable = True
        invalid = False
    elif (
        status in ISSUE_STATUS_DOCUMENTED_NONBLOCKING
        and severity in ISSUE_NONBLOCKING_ALLOWED_SEVERITIES
    ):
        category = "DOCUMENTED_NONBLOCKING"
        acceptable = True
        invalid = False
    elif status in ISSUE_STATUS_KNOWN_BLOCKING:
        category = "BLOCKING_OR_UNRESOLVED"
        acceptable = False
        invalid = False
    else:
        category = "UNKNOWN_INVALID"
        acceptable = False
        invalid = True

    return MappingProxyType({
        "status": status,
        "severity": severity,
        "category": category,
        "acceptable": acceptable,
        "blocking": not acceptable,
        "invalid": invalid,
    })


def validate_current_g08_v2_acceptance_payloads(
    payloads: Mapping[str, bytes],
    reviewed_implementation_commit: str,
    implementation_result: Mapping[str, object],
) -> tuple[str, tuple[dict[str, object], ...], Mapping[str, str]]:
    """Reconstruct and reconcile the future Correction-6 acceptance evidence."""
    if set(payloads) != set(G08_V2_ACCEPTANCE_PATHS):
        raise G08Error("G08_V2_ACCEPTANCE_ARTIFACT_SET")
    records: list[dict[str, object]] = []
    for relative in G08_V2_ACCEPTANCE_PATHS:
        payload = payloads[relative]
        if not isinstance(payload, bytes) or not payload:
            raise G08Error(f"G08_V2_ACCEPTANCE_ARTIFACT_TYPE:{relative}")
        records.append({
            "path": relative,
            "size": len(payload),
            "sha256": sha256_bytes(payload),
        })
    aggregate = sha256_bytes(canonical_json(records))
    payload_identity = sha256_bytes(canonical_json(records[:3]))

    gate_fields, gate_rows = _csv_rows(
        payloads[G08_V2_ACCEPTANCE_PATHS[3]], "G08_V2_ACCEPTANCE_GATE_SCHEMA"
    )
    if not gate_fields or len(gate_rows) != 1:
        raise G08Error("G08_V2_ACCEPTANCE_GATE_SCHEMA")
    gate = gate_rows[0]
    issue_fields, issue_rows = _csv_rows(
        payloads[G08_V2_ACCEPTANCE_PATHS[1]], "G08_V2_ACCEPTANCE_ISSUE_SCHEMA"
    )
    artifact_context_fields = {
        "verdict", "reviewed_commit", "models_fit", "real_predictions_generated",
        "real_performance_inspected", "scientific_fitting_authorized",
        "next_authorized_action", "open_blockers",
        "invalid_issue_status_count", "issue_status_semantics",
    }
    if not (
        {"issue_id", "status", "severity", "finding"} | artifact_context_fields
    ).issubset(issue_fields):
        raise G08Error("G08_V2_ACCEPTANCE_ISSUE_SCHEMA")
    issue_ids = [row.get("issue_id", "") for row in issue_rows]
    if any(not item for item in issue_ids) or len(issue_ids) != len(set(issue_ids)):
        raise G08Error("G08_V2_ACCEPTANCE_ISSUE_ID")
    issue_classifications = tuple(
        classify_g08_acceptance_issue(row) for row in issue_rows
    )
    reconstructed_blockers = sum(
        bool(item["blocking"]) for item in issue_classifications
    )
    reconstructed_invalid = sum(
        bool(item["invalid"]) for item in issue_classifications
    )

    test_fields, test_rows = _csv_rows(
        payloads[G08_V2_ACCEPTANCE_PATHS[2]], "G08_V2_ACCEPTANCE_TEST_SCHEMA"
    )
    if not (
        {
            "test_id", "area", "result", "independent_test", "assertion_count",
            "evidence",
        } | artifact_context_fields
    ).issubset(test_fields):
        raise G08Error("G08_V2_ACCEPTANCE_TEST_SCHEMA")
    independent_result = _test_result(
        test_rows,
        REQUIRED_CORRECTION6_INDEPENDENT_TEST_IDS,
        "G08_V2_INDEPENDENT_TEST",
        independent_only=True,
    )
    report = _acceptance_report_fields(payloads[G08_V2_ACCEPTANCE_PATHS[0]])
    next_action = "OPERATOR_TRUST_PIN_CONFIGURATION_THEN_G08_V2_ACTIVATION_ONLY_GATE"
    shared = {
        "verdict": "ACCEPT",
        "reviewed_commit": reviewed_implementation_commit,
        "implementation_pass": str(implementation_result["pass"]),
        "implementation_fail": str(implementation_result["fail"]),
        "independent_pass": str(independent_result["pass"]),
        "independent_fail": str(independent_result["fail"]),
        "open_blockers": str(reconstructed_blockers),
        "invalid_issue_status_count": str(reconstructed_invalid),
        "issue_status_semantics": ISSUE_STATUS_SEMANTICS,
        "models_fit": "0",
        "real_predictions_generated": "0",
        "real_performance_inspected": "0",
        "scientific_fitting_authorized": "NO",
        "next_authorized_action": next_action,
    }
    required_gate = {
        **shared,
        "reviewed_parent": CORRECTION6_BASE_COMMIT,
        "v2_active_authorization_created": "NO",
        "final_gate": "ACCEPT",
        "final_acceptance_path": G08_V2_ACCEPTANCE_PATHS[0],
        "final_acceptance_sha256": str(records[0]["sha256"]),
        "final_issues_path": G08_V2_ACCEPTANCE_PATHS[1],
        "final_issues_sha256": str(records[1]["sha256"]),
        "test_coverage_path": G08_V2_ACCEPTANCE_PATHS[2],
        "test_coverage_sha256": str(records[2]["sha256"]),
        "acceptance_payload_identity_sha256": payload_identity,
    }
    report_names = {
        "verdict": "VERDICT",
        "reviewed_commit": "REVIEWED_IMPLEMENTATION",
        "implementation_pass": "IMPLEMENTATION_PASS",
        "implementation_fail": "IMPLEMENTATION_FAIL",
        "independent_pass": "INDEPENDENT_PASS",
        "independent_fail": "INDEPENDENT_FAIL",
        "open_blockers": "OPEN_BLOCKERS",
        "invalid_issue_status_count": "INVALID_ISSUE_STATUS_COUNT",
        "issue_status_semantics": "ISSUE_STATUS_SEMANTICS",
        "models_fit": "MODELS_FIT",
        "real_predictions_generated": "REAL_PREDICTIONS_GENERATED",
        "real_performance_inspected": "REAL_PERFORMANCE_INSPECTED",
        "scientific_fitting_authorized": "SCIENTIFIC_FITTING_AUTHORIZED",
        "next_authorized_action": "NEXT_AUTHORIZED_ACTION",
    }
    context = {
        "verdict": shared["verdict"],
        "reviewed_commit": shared["reviewed_commit"],
        "models_fit": shared["models_fit"],
        "real_predictions_generated": shared["real_predictions_generated"],
        "real_performance_inspected": shared["real_performance_inspected"],
        "scientific_fitting_authorized": shared["scientific_fitting_authorized"],
        "next_authorized_action": shared["next_authorized_action"],
        "open_blockers": shared["open_blockers"],
        "invalid_issue_status_count": shared["invalid_issue_status_count"],
        "issue_status_semantics": shared["issue_status_semantics"],
    }
    if any(gate.get(key) != value for key, value in required_gate.items()):
        raise G08Error("G08_V2_ACCEPTANCE_SEMANTICS")
    if any(report.get(report_names[key]) != value for key, value in shared.items()):
        raise G08Error("G08_V2_ACCEPTANCE_CROSS_ARTIFACT")
    if any(
        any(row.get(key) != value for key, value in context.items())
        for row in (*issue_rows, *test_rows)
    ):
        raise G08Error("G08_V2_ACCEPTANCE_CROSS_ARTIFACT")
    if (
        reconstructed_blockers
        or reconstructed_invalid
        or implementation_result["fail"] != 0
        or independent_result["fail"] != 0
        or any(row.get("result") == "FAIL" for row in test_rows)
    ):
        raise G08Error("G08_V2_ACCEPTANCE_OPEN_ISSUE")
    return aggregate, tuple(records), MappingProxyType({
        **dict(gate),
        "reconstructed_implementation_pass": str(implementation_result["pass"]),
        "reconstructed_implementation_fail": str(implementation_result["fail"]),
        "reconstructed_independent_pass": str(independent_result["pass"]),
        "reconstructed_independent_fail": str(independent_result["fail"]),
        "reconstructed_open_blockers": str(reconstructed_blockers),
        "reconstructed_invalid_issue_status_count": str(reconstructed_invalid),
    })


def _simple_all_pass_test_result(
    payload: bytes,
    expected_fields: frozenset[str],
    marker: str,
) -> Mapping[str, object]:
    fieldnames, rows = _csv_rows(payload, marker)
    if set(fieldnames) != set(expected_fields) or not rows:
        raise G08Error(marker)
    identifiers = [row.get("test_id", "") for row in rows]
    if any(not item for item in identifiers) or len(identifiers) != len(set(identifiers)):
        raise G08Error(f"{marker}_TEST_ID")
    if any(row.get("result") not in {"PASS", "FAIL"} for row in rows):
        raise G08Error(f"{marker}_RESULT")
    passed = sum(row["result"] == "PASS" for row in rows)
    failed = sum(row["result"] == "FAIL" for row in rows)
    return MappingProxyType({
        "pass": passed,
        "fail": failed,
        "count": len(rows),
        "test_ids": tuple(sorted(identifiers)),
    })


def output_collision_correction2_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(), "show",
        f"{implementation_commit}:{OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_TEST_PATH}",
    )
    result = _simple_all_pass_test_result(
        payload,
        frozenset({"area", "test_id", "result", "expected", "observed"}),
        "G08_OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_TEST",
    )
    if result["count"] != 65 or result["pass"] != 65 or result["fail"] != 0:
        raise G08Error("G08_OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_TEST_COUNT")
    return result


def authority_lineage_correction_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(), "show",
        f"{implementation_commit}:{AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_TEST_PATH}",
    )
    result = _simple_all_pass_test_result(
        payload,
        frozenset({"area", "test_id", "result", "expected", "observed"}),
        "G08_AUTHORITY_LINEAGE_IMPLEMENTATION_TEST",
    )
    if result["fail"] != 0:
        raise G08Error("G08_AUTHORITY_LINEAGE_IMPLEMENTATION_TEST_FAILURE")
    return result


def downstream_authority_lineage_extension_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(), "show",
        f"{implementation_commit}:{DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_TEST_PATH}",
    )
    result = _simple_all_pass_test_result(
        payload,
        frozenset({"area", "test_id", "result", "expected", "observed"}),
        "G08_DOWNSTREAM_AUTHORITY_LINEAGE_IMPLEMENTATION_TEST",
    )
    if result["fail"] != 0:
        raise G08Error("G08_DOWNSTREAM_AUTHORITY_LINEAGE_IMPLEMENTATION_TEST_FAILURE")
    return result


def _validate_exact_artifact_payloads(
    payloads: Mapping[str, bytes],
    expected: Mapping[str, str],
    marker: str,
) -> tuple[dict[str, object], ...]:
    if set(payloads) != set(expected):
        raise G08Error(f"{marker}_ARTIFACT_SET")
    records = []
    for relative in expected:
        payload = payloads[relative]
        if not isinstance(payload, bytes) or not payload:
            raise G08Error(f"{marker}_ARTIFACT_TYPE:{relative}")
        observed = sha256_bytes(payload)
        if observed != expected[relative]:
            raise G08Error(f"{marker}_ARTIFACT_IDENTITY:{relative}")
        records.append({"path": relative, "size": len(payload), "sha256": observed})
    return tuple(records)


def validate_accepted_downstream_authority_payloads(
    correction_payloads: Mapping[str, bytes],
    acceptance_payloads: Mapping[str, bytes],
) -> Mapping[str, object]:
    """Authenticate the exact accepted downstream G06/G07 correction pair."""
    correction_records = _validate_exact_artifact_payloads(
        correction_payloads,
        DOWNSTREAM_G06_G07_CORRECTION_SHA256,
        "G08_DOWNSTREAM_CORRECTION",
    )
    acceptance_records = _validate_exact_artifact_payloads(
        acceptance_payloads,
        DOWNSTREAM_G06_G07_ACCEPTANCE_SHA256,
        "G08_DOWNSTREAM_ACCEPTANCE",
    )

    correction_decision = list(csv.DictReader(
        correction_payloads[
            "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_DECISION.csv"
        ].decode("utf-8").splitlines()
    ))
    if len(correction_decision) != 1:
        raise G08Error("G08_DOWNSTREAM_CORRECTION_DECISION_SCHEMA")
    required_correction = {
        "status": "COMPLETE_PENDING_INDEPENDENT_ACCEPTANCE",
        "tests_pass": "44",
        "tests_fail": "0",
        "benchmark_consuming_units": "27",
        "scoped_benchmark_contracts": "54",
        "predictable_mismatches_before": "3",
        "predictable_mismatches_after": "0",
        "model_fits": "0",
        "predictions_generated": "0",
        "independent_acceptance_required": "YES",
        "g08_reauthorization_required": "YES",
        "scientific_fitting_authorized": "NO",
    }
    if any(correction_decision[0].get(key) != value
           for key, value in required_correction.items()):
        raise G08Error("G08_DOWNSTREAM_CORRECTION_DECISION_SEMANTICS")

    correction_qc = _simple_all_pass_test_result(
        correction_payloads[
            "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_QC.csv"
        ],
        frozenset({"test_id", "category", "result", "detail"}),
        "G08_DOWNSTREAM_CORRECTION_QC",
    )
    if correction_qc["count"] != 44 or correction_qc["pass"] != 44 or correction_qc["fail"]:
        raise G08Error("G08_DOWNSTREAM_CORRECTION_QC_COUNT")
    negative_qc = _simple_all_pass_test_result(
        correction_payloads[
            "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_NEGATIVE_TESTS.csv"
        ],
        frozenset({"test_id", "category", "result", "detail"}),
        "G08_DOWNSTREAM_CORRECTION_NEGATIVE_TEST",
    )
    if negative_qc["count"] != 15 or negative_qc["pass"] != 15 or negative_qc["fail"]:
        raise G08Error("G08_DOWNSTREAM_CORRECTION_NEGATIVE_TEST_COUNT")

    correction_text = correction_payloads[
        "documentation/PAPER1_G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_CORRECTION.md"
    ].decode("utf-8")
    for declaration in (
        "There are no new scientific or statistical decisions",
        "no data, policy,\npackage, model-specification, or `NO_EARLY` definition changes",
        "G08 source and\noperator trust pins are unchanged",
        "Scientific fitting is currently unauthorized",
        "Ordinals 28 and 29 were not run",
    ):
        if declaration not in correction_text:
            raise G08Error("G08_DOWNSTREAM_CORRECTION_DECLARATION")

    gate_rows = list(csv.DictReader(
        acceptance_payloads[DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[2]].decode(
            "utf-8"
        ).splitlines()
    ))
    if len(gate_rows) != 1:
        raise G08Error("G08_DOWNSTREAM_ACCEPTANCE_GATE_SCHEMA")
    gate = gate_rows[0]
    required_acceptance = {
        "verdict": "ACCEPT",
        "reviewed_commit": DOWNSTREAM_G06_G07_CORRECTION_COMMIT,
        "reviewed_parent": AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT,
        "blocking_issue_count": "0",
        "root_cause_confirmed": "YES",
        "history_guard_fail_closed": "YES",
        "governed_consumers": "27",
        "governed_contracts": "54",
        "contracts_derived_from_accepted_authority": "YES",
        "mismatches_before": "3",
        "mismatches_after": "0",
        "independent_pass": "28",
        "independent_fail": "0",
        "implementation_pass": "44",
        "implementation_fail": "0",
        "ordinal28_dispatched": "NO",
        "models_fit": "0",
        "predictions_generated": "0",
        "v2_immutable": "YES",
        "v1_immutable": "YES",
        "g08_reauthorization_required": "YES",
        "current_g08_pin_pair_valid": "YES",
        "g08_pin_change_required": "YES",
        "scientific_fitting_authorized": "NO",
        "final_gate": "ACCEPT",
    }
    if any(gate.get(key) != value for key, value in required_acceptance.items()):
        raise G08Error("G08_DOWNSTREAM_ACCEPTANCE_GATE_SEMANTICS")

    issue_rows = list(csv.DictReader(
        acceptance_payloads[DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[1]].decode(
            "utf-8"
        ).splitlines()
    ))
    if (
        len(issue_rows) != 1
        or issue_rows[0].get("severity") != "NONBLOCKING_GOVERNANCE_FOLLOWUP"
        or issue_rows[0].get("status") != "OPEN"
    ):
        raise G08Error("G08_DOWNSTREAM_ACCEPTANCE_ISSUE_SEMANTICS")
    acceptance_tests = _simple_all_pass_test_result(
        acceptance_payloads[DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[3]],
        frozenset({"test_id", "category", "method", "result", "evidence"}),
        "G08_DOWNSTREAM_ACCEPTANCE_TEST",
    )
    if acceptance_tests["count"] != 36 or acceptance_tests["pass"] != 36 or acceptance_tests["fail"]:
        raise G08Error("G08_DOWNSTREAM_ACCEPTANCE_TEST_COUNT")
    acceptance_text = acceptance_payloads[
        DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[0]
    ].decode("utf-8")
    for declaration in (
        "`ACCEPTED`",
        DOWNSTREAM_G06_G07_CORRECTION_COMMIT,
        AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT,
        "No data, production output, policy, package, model specification, G08 source,\nor no-early definition changed.",
        "Scientific fitting remains unauthorized.",
    ):
        if declaration not in acceptance_text:
            raise G08Error("G08_DOWNSTREAM_ACCEPTANCE_DECLARATION")

    return MappingProxyType({
        "acceptance_status": "ACCEPTED",
        "final_gate": gate["final_gate"],
        "blocking_issue_count": 0,
        "acceptance_artifact_aggregate_sha256": sha256_bytes(
            canonical_json(acceptance_records)
        ),
        "correction_records": correction_records,
        "acceptance_records": acceptance_records,
        "correction_qc": correction_qc,
        "negative_qc": negative_qc,
        "acceptance_tests": acceptance_tests,
    })


def _validate_modern_g08_acceptance_payloads(
    payloads: Mapping[str, bytes],
    paths: Sequence[str],
    reviewed_implementation_commit: str,
    reviewed_parent: str,
    implementation_result: Mapping[str, object],
    gate_name: str,
    reviewed_implementation_paths: Sequence[str] | None = None,
) -> tuple[str, tuple[dict[str, object], ...], Mapping[str, str]]:
    if set(payloads) != set(paths):
        raise G08Error("G08_V2_ACCEPTANCE_ARTIFACT_SET")
    records = tuple({
        "path": relative,
        "size": len(payloads[relative]),
        "sha256": sha256_bytes(payloads[relative]),
    } for relative in paths)
    if any(not payloads[relative] for relative in paths):
        raise G08Error("G08_V2_ACCEPTANCE_ARTIFACT_TYPE")
    aggregate = sha256_bytes(canonical_json(records))

    gate_fields, gate_rows = _csv_rows(payloads[paths[3]], "G08_V2_ACCEPTANCE_GATE_SCHEMA")
    if not gate_fields or len(gate_rows) != 1:
        raise G08Error("G08_V2_ACCEPTANCE_GATE_SCHEMA")
    gate = gate_rows[0]
    issue_fields, issue_rows = _csv_rows(
        payloads[paths[1]], "G08_V2_ACCEPTANCE_ISSUE_SCHEMA"
    )
    if not {"issue_id", "severity", "status", "blocking"}.issubset(issue_fields):
        raise G08Error("G08_V2_ACCEPTANCE_ISSUE_SCHEMA")
    issue_ids = [row.get("issue_id", "") for row in issue_rows]
    if any(not item for item in issue_ids) or len(issue_ids) != len(set(issue_ids)):
        raise G08Error("G08_V2_ACCEPTANCE_ISSUE_ID")
    classifications = tuple(classify_g08_acceptance_issue(row) for row in issue_rows)
    blocking = sum(bool(item["blocking"]) for item in classifications)
    invalid = sum(bool(item["invalid"]) for item in classifications)
    if any(row.get("blocking") != "NO" for row in issue_rows) or blocking or invalid:
        raise G08Error("G08_V2_ACCEPTANCE_OPEN_ISSUE")

    test_fields, test_rows = _csv_rows(
        payloads[paths[2]], "G08_V2_ACCEPTANCE_TEST_SCHEMA"
    )
    if not {"test_id", "area", "result", "independent_test", "evidence"}.issubset(
        test_fields
    ):
        raise G08Error("G08_V2_ACCEPTANCE_TEST_SCHEMA")
    test_ids = [row.get("test_id", "") for row in test_rows]
    if (
        not test_rows
        or any(not item for item in test_ids)
        or len(test_ids) != len(set(test_ids))
        or any(row.get("result") != "PASS" for row in test_rows)
        or any(row.get("independent_test") != "YES" for row in test_rows)
    ):
        raise G08Error("G08_V2_ACCEPTANCE_TEST_RESULT")
    independent_pass = len(test_rows)

    authority_lineage_gate = gate_name in {
        BRIDGE_GATE_NAME,
        "PAPER1_SOL_G08_V2_AUTHORITY_LINEAGE_CORRECTION_FINAL_ACCEPTANCE",
        "PAPER1_SOL_G08_DOWNSTREAM_AUTHORITY_LINEAGE_FINAL_ACCEPTANCE",
        GOVERNED_TRANSITION_GATE_NAME,
        GOVERNED_SUCCESSOR_SCOPE_GATE_NAME,
        GOVERNED_CORRECTION_LINEAGE_GATE_NAME,
    }
    required = {
        "gate": gate_name,
        "verdict": "ACCEPT" if authority_lineage_gate else "ACCEPTED",
        "reviewed_commit": reviewed_implementation_commit,
        "reviewed_parent": reviewed_parent,
        "blocking_issue_count": "0",
        "implementation_pass": str(implementation_result["pass"]),
        "implementation_fail": "0",
        "independent_pass": str(independent_pass),
        "independent_fail": "0",
        "ordinal7_dispatched": "NO",
        "models_fit": "0",
        "real_operator_pins_changed": "NO",
        "scientific_fitting_authorized": "NO",
        "final_gate": "ACCEPT",
        "next_authorized_action": (
            "OPERATOR_TRUST_PIN_CONFIGURATION_THEN_G08_V2_ACTIVATION_ONLY_GATE"
        ),
    }
    if authority_lineage_gate:
        required.update({
            "v2_active_authorization_created": "NO",
            "real_predictions_generated": "0",
            "real_performance_inspected": "0",
        })
    else:
        required["predictions_generated"] = "0"
    scope_bound_gate = gate_name in {
        BRIDGE_GATE_NAME,
        GOVERNED_TRANSITION_GATE_NAME,
        GOVERNED_SUCCESSOR_SCOPE_GATE_NAME,
        GOVERNED_CORRECTION_LINEAGE_GATE_NAME,
    }
    if scope_bound_gate:
        if reviewed_implementation_paths is None:
            raise G08Error("G08_V2_ACCEPTANCE_SCOPE_MISSING")
        _successor_g08_implementation_path_policy(
            tuple(reviewed_implementation_paths),
            "G08_V2_ACCEPTANCE",
            require_registry=gate_name == GOVERNED_TRANSITION_GATE_NAME,
        )
        required.update({
            "reviewed_changed_path_count": str(len(set(reviewed_implementation_paths))),
            "reviewed_changed_paths_sha256": _implementation_scope_sha256(
                reviewed_implementation_paths
            ),
            "scope_authority": "INDEPENDENT_ACCEPTANCE_BINDS_GIT_DIFF",
        })
    if any(gate.get(key) != value for key, value in required.items()):
        raise G08Error("G08_V2_ACCEPTANCE_SEMANTICS")
    if implementation_result["fail"] != 0:
        raise G08Error("G08_V2_ACCEPTANCE_IMPLEMENTATION_FAILURE")
    return aggregate, records, MappingProxyType(dict(gate))


def operator_g08_trust_pins(root: Path) -> Mapping[str, str]:
    from src import paper1_control_reference as reference
    if proof := reference.preparation(root):
        return MappingProxyType({key: proof.anchors[key] for key in ('implementation', 'acceptance')})
    root = Path(root).resolve()
    pins: dict[str, str] = {}
    for field, key in (
        ("implementation", TRUSTED_IMPLEMENTATION_CONFIG_KEY),
        ("acceptance", TRUSTED_ACCEPTANCE_CONFIG_KEY),
    ):
        completed = subprocess.run(
            ["git", "config", "--local", "--get-all", key],
            cwd=root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        values = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if completed.returncode != 0 or len(values) != 1:
            raise G08Error(f"G08_OPERATOR_TRUST_PIN_MISSING:{key}")
        value = values[0]
        if COMMIT_SHA_PATTERN.fullmatch(value) is None:
            raise G08Error(f"G08_OPERATOR_TRUST_PIN_FORMAT:{key}")
        _require_commit(root, value, f"G08_OPERATOR_TRUST_PIN_COMMIT:{key}")
        pins[field] = value
    return MappingProxyType(pins)


def _require_direct_commit(
    root: Path,
    commit: str,
    parent: str,
    changed_paths: frozenset[str],
    marker: str,
) -> None:
    _require_commit(root, commit, marker)
    if _git(root, "rev-parse", f"{commit}^") != parent:
        raise G08Error(f"{marker}_PARENT")

    _require_exact_changed_paths(_commit_changed_paths(root, commit), changed_paths, marker)


def _require_exact_changed_paths(
    actual: Sequence[str],
    expected: Sequence[str],
    marker: str,
) -> None:
    if frozenset(actual) != frozenset(expected):
        raise G08Error(f"{marker}_SCOPE")


def _validate_prior_accepted_activation(root: Path) -> Mapping[str, object]:
    _require_direct_commit(
        root,
        AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT,
        AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT,
        PERMITTED_ACTIVATION_PATHS,
        "G08_PRIOR_ACCEPTED_ACTIVATION",
    )
    payloads = {
        relative: _git_bytes(
            root, "show",
            f"{AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT}:{relative}",
        )
        for relative in PRIOR_ACCEPTED_ACTIVATION_SHA256
    }
    records = _validate_exact_artifact_payloads(
        payloads,
        PRIOR_ACCEPTED_ACTIVATION_SHA256,
        "G08_PRIOR_ACCEPTED_ACTIVATION",
    )
    try:
        receipt = json.loads(
            payloads[ACTIVE_AUTHORIZATION_RELATIVE.as_posix()].decode("ascii")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise G08Error("G08_PRIOR_ACCEPTED_ACTIVATION_RECEIPT") from exc
    gate_rows = list(csv.DictReader(
        payloads[INDEPENDENT_GATE_RELATIVE.as_posix()].decode("utf-8").splitlines()
    ))
    if len(gate_rows) != 1:
        raise G08Error("G08_PRIOR_ACCEPTED_ACTIVATION_GATE_SCHEMA")
    gate = gate_rows[0]
    if (
        receipt.get("authorization_parent_commit")
        != AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT
        or receipt.get("authorization_state") != "AUTHORIZED"
        or gate.get("verdict") != "TRUSTED"
        or gate.get("g08_accepted") != "YES"
        or gate.get("accepted_g08_commit")
        != AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT
        or gate.get("accepted_g08_implementation_commit")
        != AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT
    ):
        raise G08Error("G08_PRIOR_ACCEPTED_ACTIVATION_SEMANTICS")
    return MappingProxyType({"records": records, "gate": MappingProxyType(gate)})


def validate_accepted_downstream_authority_lineage(
    root: Path,
) -> Mapping[str, object]:
    """Authenticate the exact prior G08 I/A/X and downstream correction I/A."""
    root = Path(root).resolve()
    _require_direct_commit(
        root,
        AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT,
        AUTHORITY_LINEAGE_CORRECTION_BASE_COMMIT,
        AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_PATHS,
        "G08_PRIOR_AUTHORITY_LINEAGE_IMPLEMENTATION",
    )
    _require_direct_commit(
        root,
        AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT,
        AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT,
        frozenset(AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_PATHS),
        "G08_PRIOR_AUTHORITY_LINEAGE_ACCEPTANCE",
    )
    prior_implementation_result = authority_lineage_correction_implementation_test_result(
        root, AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT
    )
    prior_acceptance_payloads = {
        relative: _git_bytes(
            root, "show",
            f"{AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT}:{relative}",
        )
        for relative in AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_PATHS
    }
    _validate_modern_g08_acceptance_payloads(
        prior_acceptance_payloads,
        AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_PATHS,
        AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT,
        AUTHORITY_LINEAGE_CORRECTION_BASE_COMMIT,
        prior_implementation_result,
        "PAPER1_SOL_G08_V2_AUTHORITY_LINEAGE_CORRECTION_FINAL_ACCEPTANCE",
    )
    activation = _validate_prior_accepted_activation(root)

    _require_direct_commit(
        root,
        DOWNSTREAM_G06_G07_CORRECTION_COMMIT,
        AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT,
        DOWNSTREAM_G06_G07_CORRECTION_PATHS,
        "G08_DOWNSTREAM_G06_G07_CORRECTION",
    )
    _require_direct_commit(
        root,
        DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT,
        DOWNSTREAM_G06_G07_CORRECTION_COMMIT,
        frozenset(DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS),
        "G08_DOWNSTREAM_G06_G07_ACCEPTANCE",
    )
    correction_payloads = {
        relative: _git_bytes(
            root, "show", f"{DOWNSTREAM_G06_G07_CORRECTION_COMMIT}:{relative}"
        )
        for relative in DOWNSTREAM_G06_G07_CORRECTION_PATHS
    }
    acceptance_payloads = {
        relative: _git_bytes(
            root, "show", f"{DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT}:{relative}"
        )
        for relative in DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS
    }
    downstream = validate_accepted_downstream_authority_payloads(
        correction_payloads, acceptance_payloads
    )
    return MappingProxyType({
        "prior_activation": activation,
        "downstream_authority": downstream,
        "downstream_correction_commit": DOWNSTREAM_G06_G07_CORRECTION_COMMIT,
        "downstream_acceptance_commit": DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT,
    })


def _historical_governed_transition_record() -> Mapping[str, object]:
    return MappingProxyType({
        "transition_id": "G06_G07_NO_EARLY_BENCHMARK_AUTHORITY_D1",
        "prior_g08_implementation_commit": (
            AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT
        ),
        "prior_g08_acceptance_commit": AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT,
        "prior_authority_tip": AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT,
        "prior_activation_sha256": dict(PRIOR_ACCEPTED_ACTIVATION_SHA256),
        "downstream_implementation_commit": DOWNSTREAM_G06_G07_CORRECTION_COMMIT,
        "downstream_acceptance_commit": DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT,
        "allowed_changed_paths": sorted(DOWNSTREAM_G06_G07_CORRECTION_PATHS),
        "implementation_sha256": dict(DOWNSTREAM_G06_G07_CORRECTION_SHA256),
        "acceptance_paths": list(DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS),
        "acceptance_sha256": dict(DOWNSTREAM_G06_G07_ACCEPTANCE_SHA256),
        "acceptance_gate_path": DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS[2],
        "acceptance_gate_expected": {
            "verdict": "ACCEPT",
            "reviewed_commit": DOWNSTREAM_G06_G07_CORRECTION_COMMIT,
            "reviewed_parent": AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT,
            "blocking_issue_count": "0",
            "scientific_fitting_authorized": "NO",
            "final_gate": "ACCEPT",
        },
        "next_g08_implementation_commit": (
            GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT
        ),
        "next_g08_implementation_allowed_paths": sorted(
            DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_IMPLEMENTATION_PATHS
        ),
        "execution_authority_implementation_commit": (
            DOWNSTREAM_G06_G07_CORRECTION_COMMIT
        ),
        "execution_authority_acceptance_commit": (
            DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT
        ),
        "authority_source_sha256": {
            "src/paper1_g06_4f_runtime.py": DOWNSTREAM_G06_G07_CORRECTION_SHA256[
                "src/paper1_g06_4f_runtime.py"
            ],
            "src/paper1_g07_runtime.py": DOWNSTREAM_G06_G07_CORRECTION_SHA256[
                "src/paper1_g07_runtime.py"
            ],
        },
    })


_GOVERNED_TRANSITION_RECORD_KEYS = frozenset({
    "transition_id",
    "prior_g08_implementation_commit",
    "prior_g08_acceptance_commit",
    "prior_authority_tip",
    "prior_activation_sha256",
    "downstream_implementation_commit",
    "downstream_acceptance_commit",
    "allowed_changed_paths",
    "implementation_sha256",
    "acceptance_paths",
    "acceptance_sha256",
    "acceptance_gate_path",
    "acceptance_gate_expected",
    "next_g08_implementation_commit",
    "next_g08_implementation_allowed_paths",
    "execution_authority_implementation_commit",
    "execution_authority_acceptance_commit",
    "authority_source_sha256",
})

_CHAIN_TRANSITION_RECORD_KEYS = _GOVERNED_TRANSITION_RECORD_KEYS | {
    "chain_schema_version", "implementation_chain", "transition_authority",
}


def downstream_chain_facts(
    root: Path, base: str, chain: Sequence[str],
) -> Mapping[str, object]:
    """Derive descriptive facts, never permission, from a complete linear chain."""
    marker = "G08_DOWNSTREAM_CHAIN"
    if (
        not isinstance(chain, (list, tuple)) or not chain
        or any(not isinstance(item, str) or COMMIT_SHA_PATTERN.fullmatch(item) is None
               for item in (base, *chain))
        or len(set(chain)) != len(chain) or base in chain
    ):
        raise G08Error(f"{marker}_SCHEMA")
    previous = base
    commits = []
    touched: set[str] = set()
    for commit in chain:
        parents = _git(root, "rev-list", "--parents", "-n", "1", commit).split()
        if parents != [commit, previous]:
            raise G08Error(f"{marker}_PARENT")
        paths = _git_bytes(
            root, "diff", "--no-renames", "--name-only", "-z", previous, commit,
        ).decode("utf-8").split("\0")
        paths = sorted(path for path in paths if path)
        if not paths:
            raise G08Error(f"{marker}_EMPTY_COMMIT")
        _transition_path_policy(paths, marker)
        changes = []
        for path in paths:
            versions = {}
            for label, revision in (("before", previous), ("after", commit)):
                entry = _git_bytes(root, "ls-tree", "-z", revision, "--", path)
                if not entry:
                    versions[label] = None
                    continue
                metadata, actual_path = entry.rstrip(b"\0").split(b"\t", 1)
                mode, kind, object_id = metadata.decode("ascii").split()
                if actual_path.decode("utf-8") != path or kind != "blob" or mode not in {"100644", "100755"}:
                    raise G08Error(f"{marker}_FILE_MODE")
                versions[label] = {
                    "mode": mode,
                    "sha256": sha256_bytes(_git_bytes(root, "cat-file", "blob", object_id)),
                }
            changes.append({"path": path, **versions})
        touched.update(paths)
        commits.append({
            "commit": commit, "parent": previous,
            "tree": _git(root, "rev-parse", f"{commit}^{{tree}}"),
            "changes": changes,
        })
        previous = commit
    return MappingProxyType({
        "prior_authority_tip": base, "implementation_chain": list(chain),
        "final_implementation": chain[-1],
        "final_implementation_parent": base if len(chain) == 1 else chain[-2],
        "touched_paths": sorted(touched), "commits": commits,
    })


def _validate_chain_scope_authority(
    root: Path, record: Mapping[str, object], facts: Mapping[str, object],
) -> str:
    """Require independent cumulative review; the registry is only an index.

    As with legacy DA evidence, the enclosing accepted/pinned G08 generation
    authenticates this reference. This helper alone never grants execution.
    """
    reference = record["transition_authority"]
    pending = "G08_FAIL_CLOSED_PENDING_TRANSITION_AUTHORITY"
    if reference is None:
        raise G08Error(pending)
    if not isinstance(reference, Mapping) or set(reference) != {"commit", "path", "sha256"}:
        raise G08Error("G08_CHAIN_AUTHORITY_REFERENCE")
    commit, path = reference["commit"], reference["path"]
    if (
        not isinstance(commit, str) or COMMIT_SHA_PATTERN.fullmatch(commit) is None
        or not isinstance(path, str) or not path.startswith("documentation/PAPER1_SOL_")
        or not path.endswith(".json") or ".." in Path(path).parts
    ):
        raise G08Error("G08_CHAIN_AUTHORITY_REFERENCE")
    acceptance = str(record["downstream_acceptance_commit"])
    if commit == acceptance:
        if path not in record["acceptance_paths"]:
            raise G08Error("G08_CHAIN_AUTHORITY_NOT_REVIEWED")
    else:
        if _git(root, "rev-list", "--parents", "-n", "1", commit).split() != [commit, acceptance]:
            raise G08Error("G08_CHAIN_AUTHORITY_PARENT")
        _require_exact_changed_paths(_commit_changed_paths(root, commit), (path,), "G08_CHAIN_AUTHORITY_SCOPE")
    payload = _git_bytes(root, "show", f"{commit}:{path}")
    validate_bound_blob_bytes(payload, str(reference["sha256"]), "G08_CHAIN_AUTHORITY_HASH")
    try:
        authority = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise G08Error("G08_CHAIN_AUTHORITY_JSON") from exc
    expected = {
        "schema": "PAPER1_INDEPENDENT_DOWNSTREAM_CHAIN_AUTHORITY_V1",
        "verdict": "ACCEPT", "blocking_issue_count": 0,
        "scientific_fitting_authorized": "NO",
        "review_scope": "CUMULATIVE_IMPLEMENTATION_CHAIN",
        "chain_facts": dict(facts),
    }
    if canonical_json(authority) != canonical_json(expected):
        raise G08Error("G08_CHAIN_AUTHORITY_SEMANTICS")
    return commit



TRUSTED_TRANSITION_BRIDGE_CONFIG_KEY = "paper1.g08.trustedTransitionBridge"
TRANSITION_BRIDGE_PATH = "documentation/PAPER1_G08_TRANSITION_BRIDGE.json"
BRIDGE_LINEAGE_PATH = "documentation/PAPER1_G08_TRANSITION_BRIDGE_LINEAGE.json"
BRIDGE_QC_PATH = "documentation/PAPER1_G08_TRANSITION_BRIDGE_QC.csv"
BRIDGE_ACCEPTANCE_PATHS = (
    "documentation/PAPER1_SOL_G08_TRANSITION_BRIDGE_FINAL_ACCEPTANCE.md",
    "documentation/PAPER1_SOL_G08_TRANSITION_BRIDGE_FINAL_ISSUES.csv",
    "documentation/PAPER1_SOL_G08_TRANSITION_BRIDGE_TEST_COVERAGE.csv",
    "documentation/PAPER1_SOL_G08_TRANSITION_BRIDGE_GATE_DECISION.csv",
)
BRIDGE_GATE_NAME = "PAPER1_SOL_G08_TRANSITION_BRIDGE_FINAL_ACCEPTANCE"

# Reviewed historical authority, not permission to execute or to trust a new I/A.
MIXED_GENERATION_SCHEMA = "PAPER1_G08_MIXED_GENERATION_LINEAGE_V1"
MIXED_GENERATION_LINEAGE_PATH = "documentation/PAPER1_G08_MIXED_GENERATION_LINEAGE.json"
MIXED_GENERATION_QC_PATH = "documentation/PAPER1_G08_MIXED_GENERATION_QC.csv"
MIXED_GENERATION_HISTORY = MappingProxyType({
    "schema": MIXED_GENERATION_SCHEMA,
    "prior_g08_implementation_commit": "378c7f9676b8a8775eba2519f0d45b2d0e43c3a8",
    "prior_g08_acceptance_commit": "8b2f99f6285d5271d29188b6ae1df36e2a5bcd59",
    "prior_transition_bridge_commit": "dda77a2f2a9a8f513caa192d4b2f8ed2fa07bc29",
    "prior_authority_tip": "ca83c130bb3359ae6342ab45e710eadde476b04a",
    "implementation_chain": (
        "eb253dfc50a87ffe16deb8a85a9eaf28b91a47fb",
        "4e12cb68104887c66389dbb4e9f888b054a9d40a",
    ),
    "downstream_acceptance_commit": "26449c0d71cc5d0e1a3802524e39a15b18053128",
})


def _mixed_generation_facts(
    root: Path, implementation: str, index: Mapping[str, object],
) -> Mapping[str, object]:
    marker = "G08_MIXED_GENERATION"
    if canonical_json(index) != canonical_json(dict(MIXED_GENERATION_HISTORY)):
        raise G08Error(f"{marker}_HISTORY")
    prior_i = str(index["prior_g08_implementation_commit"])
    prior_a = str(index["prior_g08_acceptance_commit"])
    prior_b = str(index["prior_transition_bridge_commit"])
    base = str(index["prior_authority_tip"])
    chain = list(index["implementation_chain"])
    da = str(index["downstream_acceptance_commit"])
    # Historical validation does not read or substitute the current external pins.
    _validate_bridge_history(root, prior_i, prior_a, prior_b)
    _bridge_commit_facts(root, base, prior_b)
    prior_hashes = {p: sha256_bytes(_git_bytes(root, "show", f"{base}:{p}"))
                    for p in PERMITTED_ACTIVATION_PATHS}
    _validate_governed_activation(root, {
        "prior_g08_implementation_commit": prior_i,
        "prior_g08_acceptance_commit": prior_a,
        "prior_authority_tip": base, "prior_activation_sha256": prior_hashes,
    })
    commits = []
    previous = base
    for commit in chain:
        facts = _bridge_commit_facts(root, commit, previous)
        commits.append({**facts, "tree": _git(root, "rev-parse", f"{commit}^{{tree}}")})
        previous = commit
    review = _bridge_review_gate(root, da, chain[-1], chain[-2])
    paths = sorted({c["path"] for item in commits for c in item["changes"]})
    expected_paths = sorted((
        "src/paper1_g07_runtime.py", "src/paper1_g08_runtime.py",
        "scripts/validate_paper1_pair_lifecycle.py",
        "scripts/validate_paper1_migration_authority.py",
        "documentation/PAPER1_G07_G08_STAGED_PAIR_LIFECYCLE_CORRECTION.md",
        "documentation/PAPER1_G07_PERSISTED_MIGRATION_AUTHORITY_CORRECTION.md",
    ))
    if (paths != expected_paths
            or review.get("reviewed_base_commit") != base
            or review.get("reviewed_first_implementation_commit") != chain[0]
            or review.get("scope_authority") != "INDEPENDENT_ACCEPTANCE_BINDS_CUMULATIVE_GIT_DIFF"
            or review.get("reviewed_changed_paths_sha256") != sha256_bytes(canonical_json(paths))):
        raise G08Error(f"{marker}_CUMULATIVE_SCOPE")
    current = _bridge_commit_facts(root, implementation, da)
    current_paths = tuple(c["path"] for c in current["changes"])
    _successor_g08_implementation_path_policy(current_paths, marker, require_registry=False)
    if not {MIXED_GENERATION_LINEAGE_PATH, MIXED_GENERATION_QC_PATH, "src/paper1_g08_runtime.py"} <= set(current_paths):
        raise G08Error(f"{marker}_REGISTRATION_SCOPE")
    if {BRIDGE_LINEAGE_PATH, BRIDGE_QC_PATH, TRANSITION_BRIDGE_PATH} & set(current_paths):
        raise G08Error(f"{marker}_HISTORICAL_BRIDGE_CHANGED")
    registry = GOVERNED_TRANSITION_REGISTRY_RELATIVE.as_posix()
    if _git_bytes(root, "show", f"{implementation}:{registry}") != _git_bytes(root, "show", f"{base}:{registry}"):
        raise G08Error(f"{marker}_REGISTRY_CHANGE")
    return MappingProxyType({
        "generation_kind": MIXED_GENERATION_SCHEMA,
        "prior_g08_implementation_commit": prior_i,
        "prior_g08_acceptance_commit": prior_a,
        "prior_transition_bridge_commit": prior_b,
        "prior_activation_sha256": prior_hashes,
        "downstream": {
            "prior_authority_tip": base, "implementation_chain": chain,
            "final_implementation": chain[-1], "final_implementation_parent": chain[-2],
            "touched_paths": paths, "commits": commits,
        },
        "downstream_acceptance": _bridge_commit_facts(root, da, chain[-1]),
        "bootstrap": [], "g08_implementation": current,
    })


def _bridge_pin(root: Path) -> str:
    from src import paper1_control_reference as reference
    if proof := reference.preparation(root):
        return proof.anchors['bridge']
    result = subprocess.run(
        ["git", "config", "--local", "--get-all", TRUSTED_TRANSITION_BRIDGE_CONFIG_KEY],
        cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    values = result.stdout.splitlines()
    if result.returncode != 0 or len(values) != 1:
        raise G08Error("G08_BRIDGE_PIN_MISSING_OR_DUPLICATE")
    value = values[0]
    if COMMIT_SHA_PATTERN.fullmatch(value) is None:
        raise G08Error("G08_BRIDGE_PIN_FORMAT")
    _require_commit(root, value, "G08_BRIDGE_PIN_COMMIT")
    return value


def _bridge_registration(root: Path, implementation: str) -> bool:
    # A changed descriptor identifies a registration generation. It cannot opt out
    # of review; deleting it also enters this route and then fails closed.
    return bool({BRIDGE_LINEAGE_PATH, MIXED_GENERATION_LINEAGE_PATH}
                & _commit_changed_paths(root, implementation))


def _bridge_read_json(root: Path, commit: str, path: str) -> dict[str, object]:
    try:
        value = json.loads(_git_bytes(root, "show", f"{commit}:{path}").decode("ascii"))
    except (UnicodeError, json.JSONDecodeError, G08Error) as exc:
        raise G08Error("G08_BRIDGE_JSON") from exc
    if not isinstance(value, dict):
        raise G08Error("G08_BRIDGE_JSON")
    return value


def _bridge_commit_facts(root: Path, commit: str, parent: str) -> dict[str, object]:
    if _git(root, "rev-list", "--parents", "-n", "1", commit).split() != [commit, parent]:
        raise G08Error("G08_BRIDGE_HISTORY_PARENT")
    paths = sorted(_commit_changed_paths(root, commit))
    if not paths:
        raise G08Error("G08_BRIDGE_EMPTY_COMMIT")
    changes = []
    for path in paths:
        versions = {}
        for label, revision in (("before", parent), ("after", commit)):
            entry = _git_bytes(root, "ls-tree", "-z", revision, "--", path)
            if not entry:
                versions[label] = None
                continue
            metadata, actual = entry.rstrip(b"\0").split(b"\t", 1)
            mode, kind, oid = metadata.decode("ascii").split()
            if actual.decode("utf-8") != path or kind != "blob" or mode not in {"100644", "100755"}:
                raise G08Error("G08_BRIDGE_FILE_MODE")
            versions[label] = {"mode": mode, "sha256": sha256_bytes(_git_bytes(root, "cat-file", "blob", oid))}
        changes.append({"path": path, **versions})
    return {"commit": commit, "parent": parent, "changes": changes}


def _bridge_review_gate(root: Path, acceptance: str, implementation: str, parent: str) -> Mapping[str, str]:
    paths = sorted(_commit_changed_paths(root, acceptance))
    _bridge_commit_facts(root, acceptance, implementation)
    if not paths or any(
        not p.startswith("documentation/PAPER1_SOL_")
        or ".." in Path(p).parts or Path(p).suffix not in {".md", ".csv", ".json"}
        for p in paths
    ):
        raise G08Error("G08_BRIDGE_REVIEW_SCOPE")
    gates = [p for p in paths if p.endswith("_GATE_DECISION.csv")]
    if len(gates) != 1:
        raise G08Error("G08_BRIDGE_REVIEW_GATE")
    _, rows = _csv_rows(_git_bytes(root, "show", f"{acceptance}:{gates[0]}"), "G08_BRIDGE_REVIEW_GATE")
    expected = {"reviewed_commit": implementation, "reviewed_parent": parent,
                "verdict": "ACCEPT", "blocking_issue_count": "0", "scientific_fitting_authorized": "NO"}
    if len(rows) != 1 or any(rows[0].get(k) != v for k, v in expected.items()):
        raise G08Error("G08_BRIDGE_REVIEW_SEMANTICS")
    return rows[0]


def bridge_lineage_facts(root: Path, implementation: str) -> Mapping[str, object]:
    """Reconstruct proposed lineage, not permission. B must independently bind it."""
    root = Path(root).resolve()
    if MIXED_GENERATION_LINEAGE_PATH in _commit_changed_paths(root, implementation):
        index = _bridge_read_json(root, implementation, MIXED_GENERATION_LINEAGE_PATH)
        return _mixed_generation_facts(root, implementation, index)
    index = _bridge_read_json(root, implementation, BRIDGE_LINEAGE_PATH)
    required = {"schema", "prior_g08_implementation_commit", "prior_g08_acceptance_commit",
                "prior_authority_tip", "implementation_chain", "downstream_acceptance_commit",
                "bootstrap_commits"}
    if set(index) != required or index["schema"] != "PAPER1_G08_BRIDGE_LINEAGE_V1":
        raise G08Error("G08_BRIDGE_LINEAGE_SCHEMA")
    base = index["prior_authority_tip"]
    chain = index["implementation_chain"]
    downstream = dict(downstream_chain_facts(root, base, chain))
    da = index["downstream_acceptance_commit"]
    for key in ("prior_g08_implementation_commit", "prior_g08_acceptance_commit", "downstream_acceptance_commit"):
        if not isinstance(index[key], str) or COMMIT_SHA_PATTERN.fullmatch(index[key]) is None:
            raise G08Error("G08_BRIDGE_LINEAGE_COMMIT")
    prior_i, prior_a = index["prior_g08_implementation_commit"], index["prior_g08_acceptance_commit"]
    prior_hashes = {p: sha256_bytes(_git_bytes(root, "show", f"{base}:{p}")) for p in PERMITTED_ACTIVATION_PATHS}
    prior_record = {"prior_g08_implementation_commit": prior_i, "prior_g08_acceptance_commit": prior_a,
                    "prior_authority_tip": base, "prior_activation_sha256": prior_hashes}
    _validate_governed_activation(root, prior_record)
    _bridge_review_gate(root, da, chain[-1], downstream["final_implementation_parent"])
    review = _bridge_commit_facts(root, da, chain[-1])
    bootstrap = index["bootstrap_commits"]
    if (not isinstance(bootstrap, list) or len(bootstrap) % 2
            or any(not isinstance(c, str) or COMMIT_SHA_PATTERN.fullmatch(c) is None for c in bootstrap)
            or len(set([base, *chain, da, *bootstrap, implementation])) != len([base, *chain, da, *bootstrap, implementation])):
        raise G08Error("G08_BRIDGE_BOOTSTRAP_SCHEMA")
    # Intervening I/A pairs are historical review evidence, never current trust.
    # The external B pin binds their actual full content, including legacy review
    # records that do not implement the current acceptance schema.
    history = []
    previous = da
    for offset in range(0, len(bootstrap), 2):
        i, a = bootstrap[offset:offset + 2]
        item = _bridge_commit_facts(root, i, previous)
        _successor_g08_implementation_path_policy(tuple(c["path"] for c in item["changes"]), "G08_BRIDGE_BOOTSTRAP", require_registry=False)
        _bridge_review_gate(root, a, i, previous)
        history.extend([item, _bridge_commit_facts(root, a, i)])
        previous = a
    current = _bridge_commit_facts(root, implementation, previous)
    _successor_g08_implementation_path_policy(tuple(c["path"] for c in current["changes"]), "G08_BRIDGE_IMPLEMENTATION", require_registry=False)
    if BRIDGE_QC_PATH not in _commit_changed_paths(root, implementation):
        raise G08Error("G08_BRIDGE_IMPLEMENTATION_QC_REQUIRED")
    # No registry content selects a bridge or bypasses its requirement.
    if _git_bytes(root, "show", f"{implementation}:{GOVERNED_TRANSITION_REGISTRY_RELATIVE.as_posix()}") != _git_bytes(
        root, "show", f"{base}:{GOVERNED_TRANSITION_REGISTRY_RELATIVE.as_posix()}"
    ):
        raise G08Error("G08_BRIDGE_REGISTRY_CHANGE")
    return MappingProxyType({
        "prior_g08_implementation_commit": prior_i, "prior_g08_acceptance_commit": prior_a,
        "prior_activation_sha256": prior_hashes, "downstream": downstream,
        "downstream_acceptance": review, "bootstrap": history, "g08_implementation": current,
    })


def _bridge_registration_lineage(root: Path, implementation: str) -> Mapping[str, object]:
    facts = bridge_lineage_facts(root, implementation)
    downstream = facts["downstream"]
    da = facts["downstream_acceptance"]["commit"]
    hashes = {p: sha256_bytes(_git_bytes(root, "show", f"{da}:{p}")) for p in
              ("src/paper1_g06_4f_runtime.py", "src/paper1_g07_runtime.py")}
    return MappingProxyType({
        "implementation_commit": implementation,
        "implementation_parent": facts["g08_implementation"]["parent"],
        "implementation_paths": frozenset(c["path"] for c in facts["g08_implementation"]["changes"]),
        "lineage_kind": "OPERATOR_PINNED_TRANSITION_BRIDGE_REQUIRED",
        "bridge_required": True,
        "chain_facts": facts,
        "execution_authority_implementation_commit": downstream["final_implementation"],
        "execution_authority_acceptance_commit": da,
        "authority_source_sha256": hashes,
    })


def _bridge_expected_payload(implementation: str, acceptance: str, facts: Mapping[str, object]) -> dict[str, object]:
    return {
        "schema": "PAPER1_G08_OPERATOR_PINNED_TRANSITION_BRIDGE_V1",
        "verdict": "ACCEPT", "blocking_issue_count": 0, "scientific_fitting_authorized": "NO",
        "review_scope": "CUMULATIVE_IMPLEMENTATION_CHAIN",
        "normative_cumulative_scope": "ACCEPT",
        "g08_implementation_commit": implementation, "g08_acceptance_commit": acceptance,
        "chain_facts": dict(facts),
    }


def validate_transition_bridge(
    root: Path, implementation: str, acceptance: str, bridge: str,
) -> Mapping[str, object]:
    """External operator I/A/B identity plus independent committed content."""
    root = Path(root).resolve()
    pins = operator_g08_trust_pins(root)
    if pins != {"implementation": implementation, "acceptance": acceptance}:
        raise G08Error("G08_BRIDGE_I_A_PINS")
    if _bridge_pin(root) != bridge:
        raise G08Error("G08_BRIDGE_PIN_MISMATCH")
    return _validate_bridge_history(root, implementation, acceptance, bridge)


def _validate_bridge_history(
    root: Path, implementation: str, acceptance: str, bridge: str,
) -> Mapping[str, object]:
    # Historical use is permitted only from a later authenticated lineage.
    # Current execution must enter through validate_transition_bridge above.
    accepted = _validate_g08_acceptance_without_pins(root, implementation, acceptance)
    lineage = accepted["implementation_lineage"]
    if lineage.get("bridge_required") is not True:
        raise G08Error("G08_BRIDGE_NOT_REQUIRED")
    item = _bridge_commit_facts(root, bridge, acceptance)
    if [c["path"] for c in item["changes"]] != [TRANSITION_BRIDGE_PATH]:
        raise G08Error("G08_BRIDGE_COMMIT_SCOPE")
    observed = _bridge_read_json(root, bridge, TRANSITION_BRIDGE_PATH)
    expected = _bridge_expected_payload(implementation, acceptance, lineage["chain_facts"])
    if canonical_json(observed) != canonical_json(expected):
        raise G08Error("G08_BRIDGE_FACTS_OR_REVIEW")
    return MappingProxyType({**dict(accepted), "bridge_commit": bridge,
                             "bridge_sha256": sha256_bytes(_git_bytes(root, "show", f"{bridge}:{TRANSITION_BRIDGE_PATH}"))})


def _activation_parent_authority(root: Path, activation_parent: str) -> tuple[Mapping[str, object], str]:
    pins = operator_g08_trust_pins(root)
    accepted = g08_v2_acceptance_authority(root, pins["acceptance"])
    if accepted["implementation_lineage"].get("bridge_required") is True:
        bridge = _bridge_pin(root)
        authority = validate_transition_bridge(root, pins["implementation"], pins["acceptance"], bridge)
        if activation_parent != bridge:
            raise G08Error("G08_BRIDGE_ACTIVATION_PARENT")
        return authority, pins["acceptance"]
    # Ignore an unrelated stale bridge pin for normal direct A -> X activation.
    if activation_parent != pins["acceptance"]:
        raise G08Error("G08_NORMAL_ACTIVATION_PARENT")
    return accepted, pins["acceptance"]


def _artifact_records_from_hashes(
    paths: Sequence[str], hashes: Mapping[str, str], marker: str,
) -> tuple[dict[str, str], ...]:
    if set(paths) != set(hashes) or len(paths) != len(set(paths)):
        raise G08Error(f"{marker}_ARTIFACT_SET")
    records = []
    for relative in paths:
        expected = hashes.get(relative)
        if not isinstance(relative, str) or not relative or not isinstance(expected, str):
            raise G08Error(f"{marker}_ARTIFACT_SCHEMA")
        if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise G08Error(f"{marker}_ARTIFACT_HASH")
        records.append({"path": relative, "sha256": expected})
    return tuple(records)


def _transition_path_policy(paths: Sequence[str], marker: str) -> None:
    forbidden_exact = {
        "environment.yml",
        "pyproject.toml",
        "requirements.txt",
        "setup.cfg",
        "setup.py",
        "src/paper1_g08_runtime.py",
        "src/paper1_g07_v2_policy.py",
        "src/paper1_pr34_modeling.py",
    }
    forbidden_prefixes = ("data/", "outputs/", ".git/", ".github/")
    for relative in paths:
        if (
            not isinstance(relative, str)
            or not relative
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or relative in forbidden_exact
            or relative.startswith(forbidden_prefixes)
            or (
                relative.startswith("src/")
                and relative not in {
                    "src/paper1_g06_4f_runtime.py",
                    "src/paper1_g07_runtime.py",
                }
            )
        ):
            raise G08Error(f"{marker}_FORBIDDEN_PATH:{relative}")
        if not relative.startswith(("documentation/", "scripts/", "src/")):
            raise G08Error(f"{marker}_PATH_CLASS:{relative}")


def _successor_g08_implementation_path_policy(
    paths: Sequence[str], marker: str, *, require_registry: bool = True,
) -> None:
    """Enforce the non-self-authored outer boundary for successor G08 work."""
    if not paths or len(paths) != len(set(paths)):
        raise G08Error(f"{marker}_SUCCESSOR_PATH_SCHEMA")
    registry = GOVERNED_TRANSITION_REGISTRY_RELATIVE.as_posix()
    for relative in paths:
        path = Path(relative) if isinstance(relative, str) else Path()
        allowed = (
            relative in {"src/paper1_g08_runtime.py", registry}
            or (
                isinstance(relative, str)
                and relative.startswith("scripts/validate_paper1_g08_")
                and relative.endswith(".py")
            )
            or (
                isinstance(relative, str)
                and relative.startswith("documentation/PAPER1_G08_")
                and path.suffix.lower() in {".md", ".csv", ".json"}
            )
        )
        if (
            not isinstance(relative, str)
            or not relative
            or path.is_absolute()
            or ".." in path.parts
            or not allowed
        ):
            raise G08Error(f"{marker}_SUCCESSOR_FORBIDDEN_PATH:{relative}")
    if require_registry and registry not in paths:
        raise G08Error(f"{marker}_NEXT_IMPLEMENTATION_REGISTRY")


def _implementation_scope_sha256(paths: Sequence[str]) -> str:
    return sha256_bytes(canonical_json(sorted(set(paths))))


def _validate_extension_transition_record(
    record: Mapping[str, object],
) -> Mapping[str, object]:
    marker = "G08_GOVERNED_TRANSITION_RECORD"
    if not isinstance(record, Mapping) or set(record) not in (
        _GOVERNED_TRANSITION_RECORD_KEYS, _CHAIN_TRANSITION_RECORD_KEYS,
    ):
        raise G08Error(f"{marker}_SCHEMA")
    chain_mode = set(record) == _CHAIN_TRANSITION_RECORD_KEYS
    if chain_mode:
        chain = record["implementation_chain"]
        if (
            record["chain_schema_version"] != "1"
            or not isinstance(chain, list) or not chain
            or any(not isinstance(item, str) or COMMIT_SHA_PATTERN.fullmatch(item) is None for item in chain)
            or len(chain) != len(set(chain))
            or chain[-1] != record["downstream_implementation_commit"]
        ):
            raise G08Error(f"{marker}_CHAIN")
    commit_fields = (
        "prior_g08_implementation_commit",
        "prior_g08_acceptance_commit",
        "prior_authority_tip",
        "downstream_implementation_commit",
        "downstream_acceptance_commit",
        "execution_authority_implementation_commit",
        "execution_authority_acceptance_commit",
    )
    if any(
        not isinstance(record.get(field), str)
        or COMMIT_SHA_PATTERN.fullmatch(str(record[field])) is None
        for field in commit_fields
    ):
        raise G08Error(f"{marker}_COMMIT")
    next_commit = record.get("next_g08_implementation_commit")
    if next_commit is not None and (
        not isinstance(next_commit, str)
        or COMMIT_SHA_PATTERN.fullmatch(next_commit) is None
    ):
        raise G08Error(f"{marker}_NEXT_IMPLEMENTATION_COMMIT")
    transition_id = record.get("transition_id")
    if not isinstance(transition_id, str) or not transition_id.strip():
        raise G08Error(f"{marker}_ID")
    paths = record.get("allowed_changed_paths")
    acceptance_paths = record.get("acceptance_paths")
    next_paths = record.get("next_g08_implementation_allowed_paths")
    if not all(isinstance(value, list) and value for value in (paths, acceptance_paths, next_paths)):
        raise G08Error(f"{marker}_PATH_SCHEMA")
    _transition_path_policy(paths, marker)
    _successor_g08_implementation_path_policy(next_paths, marker)
    implementation_hashes = record.get("implementation_sha256")
    acceptance_hashes = record.get("acceptance_sha256")
    activation_hashes = record.get("prior_activation_sha256")
    authority_hashes = record.get("authority_source_sha256")
    if not all(isinstance(value, Mapping) for value in (
        implementation_hashes, acceptance_hashes, activation_hashes, authority_hashes
    )):
        raise G08Error(f"{marker}_HASH_SCHEMA")
    implementation_records = _artifact_records_from_hashes(
        paths, implementation_hashes, f"{marker}_IMPLEMENTATION"
    )
    _artifact_records_from_hashes(
        acceptance_paths, acceptance_hashes, f"{marker}_ACCEPTANCE"
    )
    _artifact_records_from_hashes(
        sorted(PERMITTED_ACTIVATION_PATHS), activation_hashes,
        f"{marker}_ACTIVATION",
    )
    source_records = _artifact_records_from_hashes(
        sorted(authority_hashes), authority_hashes, f"{marker}_AUTHORITY_SOURCE"
    )
    gate_path = record.get("acceptance_gate_path")
    gate_expected = record.get("acceptance_gate_expected")
    if gate_path not in acceptance_paths or not isinstance(gate_expected, Mapping):
        raise G08Error(f"{marker}_GATE")
    required_future_gate = {
        "transition_id": transition_id,
        "reviewed_commit": record["downstream_implementation_commit"],
        "reviewed_parent": record["prior_authority_tip"],
        "verdict": "ACCEPT",
        "blocking_issue_count": "0",
        "allowed_changed_paths_sha256": sha256_bytes(canonical_json(sorted(paths))),
        "implementation_artifact_identity_sha256": sha256_bytes(
            canonical_json(implementation_records)
        ),
        "scientific_fitting_authorized": "NO",
    }
    if chain_mode:
        required_future_gate = {
            "reviewed_commit": chain[-1],
            "reviewed_parent": record["prior_authority_tip"] if len(chain) == 1 else chain[-2],
            "verdict": "ACCEPT", "blocking_issue_count": "0",
            "scientific_fitting_authorized": "NO",
        }
    if any(str(gate_expected.get(key)) != str(value)
           for key, value in required_future_gate.items()):
        raise G08Error(f"{marker}_GATE_AUTHORITY")
    if set(authority_hashes) != {
        "src/paper1_g06_4f_runtime.py", "src/paper1_g07_runtime.py"
    } or len(source_records) != 2:
        raise G08Error(f"{marker}_AUTHORITY_SOURCE_SET")
    return MappingProxyType(dict(record))


def _load_governed_transition_extensions(
    root: Path, implementation_commit: str,
) -> tuple[Mapping[str, object], ...]:
    try:
        payload = _git_bytes(
            root, "show",
            f"{implementation_commit}:{GOVERNED_TRANSITION_REGISTRY_RELATIVE.as_posix()}",
        )
        document = json.loads(payload.decode("ascii"))
    except (G08Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise G08Error("G08_GOVERNED_TRANSITION_REGISTRY") from exc
    if (
        not isinstance(document, Mapping)
        or set(document) != {"schema_name", "schema_version", "transitions"}
        or document.get("schema_name") != GOVERNED_TRANSITION_REGISTRY_SCHEMA
        or document.get("schema_version") != "1"
        or not isinstance(document.get("transitions"), list)
    ):
        raise G08Error("G08_GOVERNED_TRANSITION_REGISTRY_SCHEMA")
    return tuple(
        _validate_extension_transition_record(record)
        for record in document["transitions"]
    )


def _validate_governed_activation(
    root: Path, record: Mapping[str, object],
) -> Mapping[str, object]:
    implementation_commit = str(record["prior_g08_implementation_commit"])
    acceptance_commit = str(record["prior_g08_acceptance_commit"])
    activation_commit = str(record["prior_authority_tip"])
    prior_acceptance = _validate_g08_acceptance_without_pins(
        root, implementation_commit, acceptance_commit
    )
    activation_parent = acceptance_commit
    if prior_acceptance["implementation_lineage"].get("bridge_required") is True:
        activation_parent = _git(root, "rev-parse", f"{activation_commit}^")
        _validate_bridge_history(root, implementation_commit, acceptance_commit, activation_parent)
    _require_direct_commit(
        root, activation_commit, activation_parent, PERMITTED_ACTIVATION_PATHS,
        "G08_GOVERNED_TRANSITION_PRIOR_ACTIVATION",
    )
    activation_hashes = record["prior_activation_sha256"]
    payloads = {
        relative: _git_bytes(root, "show", f"{activation_commit}:{relative}")
        for relative in PERMITTED_ACTIVATION_PATHS
    }
    _validate_exact_artifact_payloads(
        payloads, activation_hashes, "G08_GOVERNED_TRANSITION_PRIOR_ACTIVATION"
    )
    try:
        authorization = json.loads(
            payloads[ACTIVE_AUTHORIZATION_RELATIVE.as_posix()].decode("ascii")
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise G08Error("G08_GOVERNED_TRANSITION_ACTIVATION_RECEIPT") from exc
    gate_rows = list(csv.DictReader(
        payloads[INDEPENDENT_GATE_RELATIVE.as_posix()].decode("utf-8").splitlines()
    ))
    if len(gate_rows) != 1:
        raise G08Error("G08_GOVERNED_TRANSITION_ACTIVATION_GATE")
    gate = gate_rows[0]
    if (
        authorization.get("authorization_parent_commit") != activation_parent
        or authorization.get("authorization_state") != "AUTHORIZED"
        or gate.get("verdict") not in {"TRUSTED", "TRUSTED_WITH_LIMITATIONS"}
        or gate.get("g08_accepted") != "YES"
        or gate.get("accepted_g08_commit") != acceptance_commit
        or gate.get("accepted_g08_implementation_commit") != implementation_commit
    ):
        raise G08Error("G08_GOVERNED_TRANSITION_ACTIVATION_SEMANTICS")
    return MappingProxyType({
        "implementation_commit": implementation_commit,
        "acceptance_commit": acceptance_commit,
        "activation_commit": activation_commit,
    })


def validate_governed_downstream_transition(
    root: Path, record: Mapping[str, object],
) -> Mapping[str, object]:
    root = Path(root).resolve()
    marker = "G08_GOVERNED_DOWNSTREAM_TRANSITION"
    chain_mode = "chain_schema_version" in record
    if chain_mode:
        record = _validate_extension_transition_record(record)
    activation = _validate_governed_activation(root, record)
    correction_commit = str(record["downstream_implementation_commit"])
    acceptance_commit = str(record["downstream_acceptance_commit"])
    allowed_paths = frozenset(str(item) for item in record["allowed_changed_paths"])
    acceptance_paths = tuple(str(item) for item in record["acceptance_paths"])
    _transition_path_policy(tuple(allowed_paths), marker)
    if chain_mode:
        facts = downstream_chain_facts(
            root, str(record["prior_authority_tip"]), record["implementation_chain"],
        )
        _require_exact_changed_paths(facts["touched_paths"], allowed_paths, f"{marker}_CUMULATIVE")
        derived_id = "CHAIN_" + sha256_bytes(canonical_json(facts))
        if record["transition_id"] != derived_id:
            raise G08Error(f"{marker}_DERIVED_ID")
    else:
        _require_direct_commit(
            root, correction_commit, str(record["prior_authority_tip"]),
            allowed_paths, marker,
        )
    correction_payloads = {
        relative: _git_bytes(root, "show", f"{correction_commit}:{relative}")
        for relative in allowed_paths
    }
    implementation_records = _validate_exact_artifact_payloads(
        correction_payloads, record["implementation_sha256"],
        f"{marker}_IMPLEMENTATION",
    )
    _require_direct_commit(
        root, acceptance_commit, correction_commit, frozenset(acceptance_paths),
        f"{marker}_ACCEPTANCE",
    )
    if chain_mode:
        if _git(root, "rev-list", "--parents", "-n", "1", acceptance_commit).split() != [acceptance_commit, correction_commit]:
            raise G08Error(f"{marker}_ACCEPTANCE_PARENT")
        if any(
            not path.startswith("documentation/PAPER1_SOL_")
            or ".." in Path(path).parts
            or Path(path).suffix not in {".json", ".csv", ".md"}
            for path in acceptance_paths
        ):
            raise G08Error(f"{marker}_ACCEPTANCE_PATH")
    acceptance_payloads = {
        relative: _git_bytes(root, "show", f"{acceptance_commit}:{relative}")
        for relative in acceptance_paths
    }
    acceptance_records = _validate_exact_artifact_payloads(
        acceptance_payloads, record["acceptance_sha256"],
        f"{marker}_ACCEPTANCE",
    )
    gate_path = str(record["acceptance_gate_path"])
    gate_rows = list(csv.DictReader(
        acceptance_payloads[gate_path].decode("utf-8").splitlines()
    ))
    if len(gate_rows) != 1:
        raise G08Error(f"{marker}_ACCEPTANCE_GATE")
    gate = gate_rows[0]
    expected_gate = record["acceptance_gate_expected"]
    if (
        gate.get("reviewed_commit") != correction_commit
        or gate.get("verdict") != "ACCEPT"
        or gate.get("blocking_issue_count") != "0"
        or any(str(gate.get(key)) != str(value) for key, value in expected_gate.items())
    ):
        raise G08Error(f"{marker}_ACCEPTANCE_SEMANTICS")
    successor_parent = acceptance_commit
    if chain_mode:
        if (
            gate.get("reviewed_parent") != facts["final_implementation_parent"]
            or record["execution_authority_implementation_commit"] != correction_commit
            or record["execution_authority_acceptance_commit"] != acceptance_commit
        ):
            raise G08Error(f"{marker}_CHAIN_REVIEW_TARGET")
        successor_parent = _validate_chain_scope_authority(root, record, facts)
    execution_commit = str(record["execution_authority_implementation_commit"])
    execution_acceptance = str(record["execution_authority_acceptance_commit"])
    _require_ancestor(root, execution_commit, acceptance_commit, f"{marker}_AUTHORITY")
    _require_ancestor(
        root, execution_acceptance, acceptance_commit, f"{marker}_AUTHORITY_ACCEPTANCE"
    )
    source_hashes = record["authority_source_sha256"]
    for relative, expected in source_hashes.items():
        payload = _git_bytes(root, "show", f"{acceptance_commit}:{relative}")
        validate_bound_blob_bytes(payload, str(expected), f"{marker}_SOURCE:{relative}")
    next_commit = record.get("next_g08_implementation_commit")
    if next_commit is not None:
        indexed_paths = tuple(
            str(item) for item in record["next_g08_implementation_allowed_paths"]
        )
        _successor_g08_implementation_path_policy(
            indexed_paths,
            marker,
            require_registry=(
                str(next_commit) != GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT
            ),
        )
        _require_direct_commit(
            root, str(next_commit), successor_parent,
            frozenset(indexed_paths),
            f"{marker}_NEXT_IMPLEMENTATION",
        )
    return MappingProxyType({
        "transition_id": str(record["transition_id"]),
        "activation": activation,
        "downstream_implementation_commit": correction_commit,
        "downstream_acceptance_commit": acceptance_commit,
        "implementation_records": implementation_records,
        "acceptance_records": acceptance_records,
        "next_g08_implementation_commit": next_commit,
        "execution_authority_implementation_commit": execution_commit,
        "execution_authority_acceptance_commit": execution_acceptance,
        "authority_source_sha256": MappingProxyType(dict(source_hashes)),
        **({"successor_parent": successor_parent, "chain_facts": facts} if chain_mode else {}),
    })


def validate_governed_downstream_transition_sequence(
    root: Path, implementation_commit: str,
) -> Mapping[str, object]:
    root = Path(root).resolve()
    historical = _historical_governed_transition_record()
    extensions = _load_governed_transition_extensions(root, implementation_commit)
    records = (historical, *extensions)
    identifiers = [str(record["transition_id"]) for record in records]
    if len(identifiers) != len(set(identifiers)):
        raise G08Error("G08_GOVERNED_TRANSITION_DUPLICATE")
    results = []
    previous_acceptance = None
    for index, record in enumerate(records):
        if previous_acceptance is not None:
            _require_ancestor(
                root, previous_acceptance,
                str(record["prior_g08_implementation_commit"]),
                "G08_GOVERNED_TRANSITION_ORDER",
            )
        if index > 0:
            prior_extensions = _load_governed_transition_extensions(
                root, str(record["prior_g08_implementation_commit"])
            )
            expected_prefix = extensions[:index - 1]
            def stable(value: Mapping[str, object]) -> dict[str, object]:
                return {
                    key: item for key, item in value.items()
                    if key != "next_g08_implementation_commit"
                }
            if (
                len(prior_extensions) != len(expected_prefix)
                or any(
                    stable(prior) != stable(expected)
                    for prior, expected in zip(prior_extensions, expected_prefix)
                )
            ):
                raise G08Error("G08_GOVERNED_TRANSITION_HISTORY_PREFIX")
        result = validate_governed_downstream_transition(root, record)
        results.append(result)
        previous_acceptance = str(result["downstream_acceptance_commit"])
    last_record = records[-1]
    if extensions:
        if last_record.get("next_g08_implementation_commit") is not None:
            raise G08Error("G08_GOVERNED_TRANSITION_LAST_FUTURE_SHA")
        indexed_paths = tuple(str(item) for item in last_record[
            "next_g08_implementation_allowed_paths"
        ])
        _successor_g08_implementation_path_policy(
            indexed_paths, "G08_GOVERNED_TRANSITION_TARGET_IMPLEMENTATION"
        )
        _require_direct_commit(
            root, implementation_commit,
            str(results[-1].get("successor_parent", last_record["downstream_acceptance_commit"])),
            frozenset(indexed_paths),
            "G08_GOVERNED_TRANSITION_TARGET_IMPLEMENTATION",
        )
        lineage_kind = "GOVERNED_DOWNSTREAM_TRANSITION"
        implementation_parent = str(results[-1].get("successor_parent", last_record["downstream_acceptance_commit"]))
    else:
        _require_direct_commit(
            root, implementation_commit, GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT,
            GOVERNED_TRANSITION_CORRECTION_IMPLEMENTATION_PATHS,
            "G08_GOVERNED_TRANSITION_CORRECTION",
        )
        lineage_kind = "GOVERNED_DOWNSTREAM_TRANSITION_CORRECTION"
        implementation_parent = GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT
    latest = results[-1]
    return MappingProxyType({
        "implementation_commit": implementation_commit,
        "implementation_parent": implementation_parent,
        "implementation_paths": (
            GOVERNED_TRANSITION_CORRECTION_IMPLEMENTATION_PATHS
            if not extensions else frozenset(indexed_paths)
        ),
        "lineage_kind": lineage_kind,
        "transition_count": len(results),
        "transition_ids": tuple(identifiers),
        "transitions": tuple(results),
        "execution_authority_implementation_commit": latest[
            "execution_authority_implementation_commit"
        ],
        "execution_authority_acceptance_commit": latest[
            "execution_authority_acceptance_commit"
        ],
        "authority_source_sha256": latest["authority_source_sha256"],
    })


def _governed_g08_correction_contract(
    changed_paths: Sequence[str],
) -> Mapping[str, object] | None:
    paths = frozenset(changed_paths)
    contracts = (
        {
            "implementation_paths": GOVERNED_SUCCESSOR_SCOPE_CORRECTION_IMPLEMENTATION_PATHS,
            "implementation_test_path": GOVERNED_SUCCESSOR_SCOPE_CORRECTION_TEST_PATH,
            "acceptance_paths": GOVERNED_SUCCESSOR_SCOPE_CORRECTION_ACCEPTANCE_PATHS,
            "gate_name": GOVERNED_SUCCESSOR_SCOPE_GATE_NAME,
            "lineage_kind": "GOVERNED_SUCCESSOR_SCOPE_CORRECTION",
            "parent_kind": "SUPERSEDED_G08_IMPLEMENTATION",
        },
        {
            "implementation_paths": GOVERNED_CORRECTION_LINEAGE_IMPLEMENTATION_PATHS,
            "implementation_test_path": GOVERNED_CORRECTION_LINEAGE_TEST_PATH,
            "acceptance_paths": GOVERNED_CORRECTION_LINEAGE_ACCEPTANCE_PATHS,
            "gate_name": GOVERNED_CORRECTION_LINEAGE_GATE_NAME,
            "lineage_kind": "GOVERNED_G08_CORRECTION_AFTER_ACCEPTANCE",
            "parent_kind": "ACCEPTED_G08_GENERATION",
        },
    )
    for contract in contracts:
        if paths == contract["implementation_paths"]:
            _successor_g08_implementation_path_policy(
                tuple(sorted(paths)),
                "G08_GOVERNED_CORRECTION_LINEAGE",
                require_registry=False,
            )
            return MappingProxyType(dict(contract))
    return None


def _inherited_execution_authority(
    lineage: Mapping[str, object],
) -> Mapping[str, object]:
    required = {
        "execution_authority_implementation_commit",
        "execution_authority_acceptance_commit",
        "authority_source_sha256",
        "transition_count",
        "transition_ids",
        "transitions",
    }
    if not required.issubset(lineage):
        raise G08Error("G08_GOVERNED_CORRECTION_EXECUTION_AUTHORITY")
    return MappingProxyType({key: lineage[key] for key in required})


def validate_g08_implementation_lineage(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    """Authenticate the explicit correction/rejection chain leading to trusted I."""
    root = Path(root).resolve()
    if _bridge_registration(root, implementation_commit):
        return _bridge_registration_lineage(root, implementation_commit)
    inherited: Mapping[str, object] | None = None
    correction_contract: Mapping[str, object] | None = None
    _require_commit(root, PRIOR_G08_ACTIVATION_COMMIT, "G08_PRIOR_ACTIVATION")
    _require_direct_commit(
        root,
        OUTPUT_COLLISION_CORRECTION1_COMMIT,
        PRIOR_G08_ACTIVATION_COMMIT,
        OUTPUT_COLLISION_CORRECTION1_PATHS,
        "G08_OUTPUT_COLLISION_CORRECTION1",
    )
    _require_direct_commit(
        root,
        OUTPUT_COLLISION_REJECTION_COMMIT,
        OUTPUT_COLLISION_CORRECTION1_COMMIT,
        OUTPUT_COLLISION_REJECTION_PATHS,
        "G08_OUTPUT_COLLISION_REJECTION",
    )
    _require_direct_commit(
        root,
        OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_COMMIT,
        OUTPUT_COLLISION_REJECTION_COMMIT,
        OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_PATHS,
        "G08_OUTPUT_COLLISION_CORRECTION2",
    )
    _require_direct_commit(
        root,
        OUTPUT_COLLISION_CORRECTION2_ACCEPTANCE_COMMIT,
        OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_COMMIT,
        frozenset(OUTPUT_COLLISION_CORRECTION2_ACCEPTANCE_PATHS),
        "G08_OUTPUT_COLLISION_CORRECTION2_ACCEPTANCE",
    )

    if implementation_commit == OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_COMMIT:
        implementation_parent = OUTPUT_COLLISION_REJECTION_COMMIT
        implementation_paths = OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_PATHS
        lineage_kind = "ACCEPTED_OUTPUT_COLLISION_CORRECTION2"
    elif implementation_commit == AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT:
        _require_direct_commit(
            root,
            implementation_commit,
            AUTHORITY_LINEAGE_CORRECTION_BASE_COMMIT,
            AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_PATHS,
            "G08_AUTHORITY_LINEAGE_CORRECTION",
        )
        implementation_parent = AUTHORITY_LINEAGE_CORRECTION_BASE_COMMIT
        implementation_paths = AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_PATHS
        lineage_kind = "AUTHORITY_LINEAGE_CORRECTION"
    elif implementation_commit == GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT:
        validate_governed_downstream_transition(
            root, _historical_governed_transition_record()
        )
        _require_direct_commit(
            root,
            implementation_commit,
            DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT,
            DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_IMPLEMENTATION_PATHS,
            "G08_DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION",
        )
        implementation_parent = DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT
        implementation_paths = (
            DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_IMPLEMENTATION_PATHS
        )
        lineage_kind = "DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION"
    elif implementation_commit == GOVERNED_SUCCESSOR_SCOPE_CORRECTION_BASE_COMMIT:
        return validate_governed_downstream_transition_sequence(
            root, implementation_commit
        )
    else:
        _require_commit(root, implementation_commit, "G08_IMPLEMENTATION_COMMIT")
        implementation_parent = _git(root, "rev-parse", f"{implementation_commit}^")
        implementation_paths = _commit_changed_paths(root, implementation_commit)
        correction_contract = _governed_g08_correction_contract(
            implementation_paths
        )
        if correction_contract is None:
            return validate_governed_downstream_transition_sequence(
                root, implementation_commit
            )
        if correction_contract["parent_kind"] == "ACCEPTED_G08_GENERATION":
            parent_implementation = _git(
                root, "rev-parse", f"{implementation_parent}^"
            )
            parent_acceptance = _validate_g08_acceptance_without_pins(
                root, parent_implementation, implementation_parent
            )
            parent_lineage = parent_acceptance["implementation_lineage"]
        else:
            parent_lineage = validate_g08_implementation_lineage(
                root, implementation_parent
            )
        inherited = _inherited_execution_authority(parent_lineage)
        lineage_kind = str(correction_contract["lineage_kind"])
        implementation_test_path = str(
            correction_contract["implementation_test_path"]
        )
        acceptance_paths = tuple(correction_contract["acceptance_paths"])
        gate_name = str(correction_contract["gate_name"])
    result = {
        "implementation_commit": implementation_commit,
        "implementation_parent": implementation_parent,
        "implementation_paths": implementation_paths,
        "lineage_kind": lineage_kind,
        "prior_activation_commit": PRIOR_G08_ACTIVATION_COMMIT,
        "rejection_commit": OUTPUT_COLLISION_REJECTION_COMMIT,
    }
    if inherited is not None and correction_contract is not None:
        result.update(inherited)
        result.update({
            "correction_parent_kind": correction_contract["parent_kind"],
            "implementation_test_path": implementation_test_path,
            "acceptance_paths": acceptance_paths,
            "gate_name": gate_name,
        })
    return MappingProxyType(result)


def _acceptance_paths_for_implementation(
    implementation_commit: str,
    reviewed_parent: str | None = None,
    lineage_kind: str | None = None,
) -> tuple[str, ...]:
    if implementation_commit == OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_COMMIT:
        return OUTPUT_COLLISION_CORRECTION2_ACCEPTANCE_PATHS
    if implementation_commit == AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT:
        return AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_PATHS
    if implementation_commit == GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT:
        return DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_ACCEPTANCE_PATHS
    if (
        reviewed_parent == GOVERNED_SUCCESSOR_SCOPE_CORRECTION_BASE_COMMIT
        or lineage_kind == "GOVERNED_SUCCESSOR_SCOPE_CORRECTION"
    ):
        return GOVERNED_SUCCESSOR_SCOPE_CORRECTION_ACCEPTANCE_PATHS
    if lineage_kind == "GOVERNED_G08_CORRECTION_AFTER_ACCEPTANCE":
        return GOVERNED_CORRECTION_LINEAGE_ACCEPTANCE_PATHS
    return GOVERNED_TRANSITION_CORRECTION_ACCEPTANCE_PATHS


def governed_transition_correction_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(), "show",
        f"{implementation_commit}:{GOVERNED_TRANSITION_CORRECTION_TEST_PATH}",
    )
    result = _simple_all_pass_test_result(
        payload,
        frozenset({"area", "test_id", "result", "expected", "observed"}),
        "G08_GOVERNED_TRANSITION_IMPLEMENTATION_TEST",
    )
    if result["fail"] != 0:
        raise G08Error("G08_GOVERNED_TRANSITION_IMPLEMENTATION_TEST_FAILURE")
    return result


def governed_successor_scope_correction_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(), "show",
        f"{implementation_commit}:{GOVERNED_SUCCESSOR_SCOPE_CORRECTION_TEST_PATH}",
    )
    result = _simple_all_pass_test_result(
        payload,
        frozenset({"area", "test_id", "result", "expected", "observed"}),
        "G08_GOVERNED_SUCCESSOR_SCOPE_IMPLEMENTATION_TEST",
    )
    if result["fail"] != 0:
        raise G08Error("G08_GOVERNED_SUCCESSOR_SCOPE_IMPLEMENTATION_TEST_FAILURE")
    return result


def governed_correction_lineage_implementation_test_result(
    root: Path,
    implementation_commit: str,
) -> Mapping[str, object]:
    payload = _git_bytes(
        Path(root).resolve(), "show",
        f"{implementation_commit}:{GOVERNED_CORRECTION_LINEAGE_TEST_PATH}",
    )
    result = _simple_all_pass_test_result(
        payload,
        frozenset({"area", "test_id", "result", "expected", "observed"}),
        "G08_GOVERNED_CORRECTION_LINEAGE_IMPLEMENTATION_TEST",
    )
    if result["fail"] != 0:
        raise G08Error("G08_GOVERNED_CORRECTION_LINEAGE_IMPLEMENTATION_TEST_FAILURE")
    return result


def _g08_acceptance_contract(
    root: Path,
    implementation_commit: str,
) -> tuple[Mapping[str, object], tuple[str, ...], Mapping[str, object], str]:
    lineage = validate_g08_implementation_lineage(root, implementation_commit)
    if lineage.get("bridge_required") is True:
        qc_path = (MIXED_GENERATION_QC_PATH
                   if lineage["chain_facts"].get("generation_kind") == MIXED_GENERATION_SCHEMA
                   else BRIDGE_QC_PATH)
        result = _simple_all_pass_test_result(
            _git_bytes(root, "show", f"{implementation_commit}:{qc_path}"),
            frozenset({"area", "test_id", "result", "expected", "observed"}),
            "G08_BRIDGE_IMPLEMENTATION_TEST",
        )
        if result["fail"] != 0:
            raise G08Error("G08_BRIDGE_IMPLEMENTATION_TEST_FAILURE")
        return lineage, BRIDGE_ACCEPTANCE_PATHS, result, BRIDGE_GATE_NAME
    reviewed_parent = str(lineage["implementation_parent"])
    paths = _acceptance_paths_for_implementation(
        implementation_commit, reviewed_parent, str(lineage["lineage_kind"])
    )
    if implementation_commit == OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_COMMIT:
        result = output_collision_correction2_implementation_test_result(
            root, implementation_commit
        )
        gate_name = "PAPER1_SOL_G08_V2_OUTPUT_COLLISION_CORRECTION_2_FINAL_ACCEPTANCE"
    elif implementation_commit == AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT:
        result = authority_lineage_correction_implementation_test_result(
            root, implementation_commit
        )
        gate_name = "PAPER1_SOL_G08_V2_AUTHORITY_LINEAGE_CORRECTION_FINAL_ACCEPTANCE"
    elif implementation_commit == GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT:
        result = downstream_authority_lineage_extension_implementation_test_result(
            root, implementation_commit
        )
        gate_name = "PAPER1_SOL_G08_DOWNSTREAM_AUTHORITY_LINEAGE_FINAL_ACCEPTANCE"
    elif lineage["lineage_kind"] == "GOVERNED_SUCCESSOR_SCOPE_CORRECTION":
        result = governed_successor_scope_correction_implementation_test_result(
            root, implementation_commit
        )
        gate_name = GOVERNED_SUCCESSOR_SCOPE_GATE_NAME
    elif lineage["lineage_kind"] == "GOVERNED_G08_CORRECTION_AFTER_ACCEPTANCE":
        result = governed_correction_lineage_implementation_test_result(
            root, implementation_commit
        )
        gate_name = GOVERNED_CORRECTION_LINEAGE_GATE_NAME
    else:
        result = governed_transition_correction_implementation_test_result(
            root, implementation_commit
        )
        gate_name = GOVERNED_TRANSITION_GATE_NAME
    return lineage, paths, result, gate_name


def _validate_g08_acceptance_without_pins(
    root: Path,
    implementation_commit: str,
    acceptance_commit: str,
) -> Mapping[str, object]:
    root = Path(root).resolve()
    _require_commit(root, acceptance_commit, "G08_V2_ACCEPTANCE_COMMIT")
    if _git(root, "rev-list", "--parents", "-n", "1", acceptance_commit).split() != [acceptance_commit, implementation_commit]:
        raise G08Error("G08_V2_ACCEPTANCE_PARENT")
    lineage, paths, implementation_result, gate_name = _g08_acceptance_contract(
        root, implementation_commit
    )
    actual_implementation_paths = _commit_changed_paths(root, implementation_commit)
    _require_exact_changed_paths(
        actual_implementation_paths,
        lineage["implementation_paths"],
        "G08_V2_IMPLEMENTATION_COMMIT",
    )
    _require_exact_changed_paths(
        _commit_changed_paths(root, acceptance_commit), paths,
        "G08_V2_ACCEPTANCE_COMMIT",
    )
    payloads = {
        relative: _git_bytes(root, "show", f"{acceptance_commit}:{relative}")
        for relative in paths
    }
    aggregate, records, gate = _validate_modern_g08_acceptance_payloads(
        payloads,
        paths,
        implementation_commit,
        str(lineage["implementation_parent"]),
        implementation_result,
        gate_name,
        tuple(actual_implementation_paths),
    )
    return MappingProxyType({
        "acceptance_commit": acceptance_commit,
        "implementation_commit": implementation_commit,
        "acceptance_artifact_aggregate_sha256": aggregate,
        "acceptance_records": records,
        "acceptance_gate": gate,
        "implementation_test_result": implementation_result,
        "implementation_lineage": lineage,
        "acceptance_paths": paths,
        "reviewed_changed_paths": tuple(sorted(actual_implementation_paths)),
        "reviewed_changed_paths_sha256": _implementation_scope_sha256(
            actual_implementation_paths
        ),
    })


def g08_v2_acceptance_authority(
    root: Path,
    acceptance_commit: str,
) -> Mapping[str, object]:
    """Authenticate pinned I and A using topology and operator-local authority."""
    root = Path(root).resolve()
    _require_commit(root, acceptance_commit, "G08_V2_ACCEPTANCE_COMMIT")
    implementation_commit = _git(root, "rev-parse", f"{acceptance_commit}^")
    _require_commit(root, implementation_commit, "G08_V2_IMPLEMENTATION_COMMIT")
    pins = operator_g08_trust_pins(root)
    if pins["acceptance"] != acceptance_commit:
        raise G08Error("G08_OPERATOR_TRUSTED_ACCEPTANCE_MISMATCH")
    if pins["implementation"] != implementation_commit:
        raise G08Error("G08_OPERATOR_TRUSTED_IMPLEMENTATION_MISMATCH")
    authority = dict(_validate_g08_acceptance_without_pins(
        root, implementation_commit, acceptance_commit
    ))
    return MappingProxyType({
        **authority,
        "operator_trust_pins": pins,
    })


def g08_v2_acceptance_identity(
    root: Path,
    acceptance_commit: str,
) -> tuple[str, tuple[dict[str, object], ...]]:
    """Return the relationally authenticated current G08 acceptance identity."""
    authority = g08_v2_acceptance_authority(root, acceptance_commit)
    return (
        str(authority["acceptance_artifact_aggregate_sha256"]),
        tuple(authority["acceptance_records"]),
    )


def repository_authority(
    root: Path,
    descendant_commit: str | None = None,
) -> Mapping[str, object]:
    root = Path(root).resolve()
    current_head = _git(root, "rev-parse", "HEAD")
    descendant = descendant_commit or current_head
    _require_commit(root, ACCEPTED_G07_IMPLEMENTATION_COMMIT, "G08_G07_IMPLEMENTATION_COMMIT")
    _require_commit(root, INDEPENDENT_G07_ACCEPTANCE_COMMIT, "G08_G07_ACCEPTANCE_COMMIT")
    _require_commit(root, descendant, "G08_AUTHORITY_DESCENDANT_COMMIT")
    _require_ancestor(
        root, ACCEPTED_G07_IMPLEMENTATION_COMMIT,
        INDEPENDENT_G07_ACCEPTANCE_COMMIT, "G08_G07_ACCEPTANCE_ANCESTRY",
    )
    _require_ancestor(
        root, INDEPENDENT_G07_ACCEPTANCE_COMMIT,
        descendant, "G08_G07_ACCEPTANCE_NOT_IN_LINEAGE",
    )
    pins = operator_g08_trust_pins(root)
    pinned_implementation = pins["implementation"]
    if pinned_implementation in {
        AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT,
        GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT,
    }:
        historical_transition = validate_governed_downstream_transition(
            root, _historical_governed_transition_record()
        )
        execution_implementation = DOWNSTREAM_G06_G07_CORRECTION_COMMIT
        execution_acceptance = DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT
        authority_hashes = {
            "src/paper1_g06_4f_runtime.py": DOWNSTREAM_G06_G07_CORRECTION_SHA256[
                "src/paper1_g06_4f_runtime.py"
            ],
            "src/paper1_g07_runtime.py": DOWNSTREAM_G06_G07_CORRECTION_SHA256[
                "src/paper1_g07_runtime.py"
            ],
        }
        downstream_acceptance_aggregate = sha256_bytes(canonical_json(
            historical_transition["acceptance_records"]
        ))
    else:
        downstream_lineage = validate_g08_implementation_lineage(
            root, pinned_implementation
        )
        execution_implementation = str(
            downstream_lineage["execution_authority_implementation_commit"]
        )
        execution_acceptance = str(
            downstream_lineage["execution_authority_acceptance_commit"]
        )
        authority_hashes = dict(downstream_lineage["authority_source_sha256"])
        if downstream_lineage.get("bridge_required") is True:
            bridge = _bridge_pin(root)
            validate_transition_bridge(root, pinned_implementation, pins["acceptance"], bridge)
            _require_ancestor(root, bridge, descendant, "G08_BRIDGE_NOT_IN_EXECUTION_LINEAGE")
            records = [
                {"path": p, "sha256": sha256_bytes(_git_bytes(root, "show", f"{execution_acceptance}:{p}"))}
                for p in sorted(_commit_changed_paths(root, execution_acceptance))
            ]
            downstream_acceptance_aggregate = sha256_bytes(canonical_json(records))
        else:
            latest_transition = downstream_lineage["transitions"][-1]
            downstream_acceptance_aggregate = sha256_bytes(canonical_json(
                latest_transition["acceptance_records"]
            ))
    _require_ancestor(
        root, execution_acceptance,
        descendant, "G08_DOWNSTREAM_ACCEPTANCE_NOT_IN_LINEAGE",
    )
    accepted_hashes = {}
    for relative, expected in ACCEPTED_G07_SOURCE_PATHS.items():
        accepted = _accepted_blob(
            root, ACCEPTED_G07_IMPLEMENTATION_COMMIT, relative, expected
        )
        accepted_hashes[relative] = expected
        if relative == "src/paper1_g07_v2_policy.py":
            current = _canonical_clean_tracked_bytes(
                root, relative, f"G08_ACCEPTED_G07_SOURCE_CHANGED:{relative}"
            )
            if current != accepted:
                raise G08Error(f"G08_ACCEPTED_G07_SOURCE_CHANGED:{relative}")
    corrected_g07_sha256 = authority_hashes["src/paper1_g07_runtime.py"]
    corrected_g07 = _accepted_blob(
        root,
        execution_acceptance,
        "src/paper1_g07_runtime.py",
        corrected_g07_sha256,
    )
    current_g07 = _canonical_clean_tracked_bytes(
        root,
        "src/paper1_g07_runtime.py",
        "G08_ACCEPTED_G07_SOURCE_CHANGED:src/paper1_g07_runtime.py",
    )
    if current_g07 != corrected_g07:
        raise G08Error("G08_ACCEPTED_G07_SOURCE_CHANGED:src/paper1_g07_runtime.py")
    corrected_g06_sha256 = authority_hashes["src/paper1_g06_4f_runtime.py"]
    corrected_g06 = _accepted_blob(
        root,
        execution_acceptance,
        "src/paper1_g06_4f_runtime.py",
        corrected_g06_sha256,
    )
    current_g06 = _canonical_clean_tracked_bytes(
        root,
        "src/paper1_g06_4f_runtime.py",
        "G08_ACCEPTED_G06_SOURCE_CHANGED:src/paper1_g06_4f_runtime.py",
    )
    if current_g06 != corrected_g06:
        raise G08Error("G08_ACCEPTED_G06_SOURCE_CHANGED:src/paper1_g06_4f_runtime.py")
    matrix = _accepted_blob(
        root, ACCEPTED_G07_IMPLEMENTATION_COMMIT,
        ACCEPTED_POLICY_MATRIX_RELATIVE.as_posix(), ACCEPTED_POLICY_MATRIX_SHA256,
    )
    matrix_relative = ACCEPTED_POLICY_MATRIX_RELATIVE.as_posix()
    _require_unchanged_tracked_blob(
        root, matrix_relative, "G08_ACCEPTED_POLICY_MATRIX_CHANGED"
    )
    if _git_bytes(root, "show", f"HEAD:{matrix_relative}") != matrix:
        raise G08Error("G08_ACCEPTED_POLICY_MATRIX_CHANGED")
    acceptance_aggregate, acceptance_records = _g07_acceptance_identity(root)
    for relative, expected in SOURCE_IDENTITIES.items():
        marker = f"G08_ACCEPTED_SOURCE_CHANGED:{relative}"
        current = _canonical_clean_tracked_bytes(root, relative, marker)
        validate_bound_blob_bytes(current, expected, marker)
    branch = _git(root, "branch", "--show-current")
    if branch != "main":
        raise G08Error("G08_AUTHORIZED_BRANCH")
    return MappingProxyType({
        "branch": branch,
        "head": current_head,
        "authority_descendant_commit": descendant,
        "accepted_g07_implementation_commit": execution_implementation,
        "independent_g07_acceptance_commit": execution_acceptance,
        "accepted_g07_runtime_sha256": corrected_g07_sha256,
        "accepted_g07_v2_policy_sha256": accepted_hashes["src/paper1_g07_v2_policy.py"],
        "independent_g07_acceptance_artifacts_sha256": downstream_acceptance_aggregate,
        "prior_independent_g07_acceptance_artifacts_sha256": acceptance_aggregate,
        "independent_g07_acceptance_artifacts": acceptance_records,
        "accepted_policy_matrix_sha256": ACCEPTED_POLICY_MATRIX_SHA256,
        "g06_4e_sha256": ACCEPTED_G06_4E_SHA256,
        "g06_4f_sha256": corrected_g06_sha256,
        "loio_authority_sha256": ACCEPTED_LOIO_AUTHORITY_SHA256,
    })


def governed_plan(root: Path) -> tuple[tuple[g07.DispatchPlanEntry, ...], tuple[object, ...]]:
    root = Path(root).resolve()
    plan = g07.build_run_plan(root)
    contracts = g06.governed_execution_contracts(root)
    by_unit = {g07._unit_id(contract): contract for contract in contracts}
    if set(by_unit) != {entry.unit_id for entry in plan}:
        raise G08Error("G08_PLAN_CONTRACT_SET")
    for entry in plan:
        contract = by_unit[entry.unit_id]
        g06.validate_execution_contract(root, contract)
        if entry.contract_sha256 != contract.contract_sha256:
            raise G08Error("G08_PLAN_CONTRACT_BINDING")
        g07.resolve_governed_model_schema(contract)
    return plan, contracts


def _policy_record(unit_id: str, policy: g07_v2.HyperparameterPolicy) -> dict[str, object]:
    payload = asdict(policy)
    payload["mode"] = policy.mode.value
    return {
        "unit_id": unit_id,
        **payload,
        "candidates": list(policy.candidates),
        "authority_source": list(policy.authority_source),
    }


def _accepted_policy_records(root: Path) -> tuple[dict[str, object], ...]:
    payload = _accepted_blob(
        Path(root).resolve(), ACCEPTED_G07_IMPLEMENTATION_COMMIT,
        ACCEPTED_POLICY_MATRIX_RELATIVE.as_posix(), ACCEPTED_POLICY_MATRIX_SHA256,
    )
    rows = list(csv.DictReader(payload.decode("utf-8").splitlines()))
    records = []
    for row in rows:
        candidates = [] if not row["candidates"] else [
            float(value) for value in row["candidates"].split(";")
        ]
        fixed_value = None if not row["fixed_value"] else float(row["fixed_value"])
        records.append({
            "unit_id": row["unit_id"],
            "schema_version": g07_v2.POLICY_SCHEMA_VERSION,
            "analysis_id": row["analysis_id"],
            "analysis_family": row["analysis_family"],
            "model_family": row["model_family"],
            "model_role": row["model_role"],
            "outer_evaluation": row["outer_evaluation"],
            "resolution_m": int(row["resolution_m"]),
            "risk_set_id": row["risk_set_id"],
            "support_identity": row["support_identity"],
            "mode": row["policy_mode"],
            "candidates": candidates,
            "fixed_value": fixed_value,
            "inheritance_parent_unit_id": row["inheritance_parent_unit_id"] or None,
            "authority_source": row["authority_source"].split(";") if row["authority_source"] else [],
            "policy_sha256": row["policy_sha256"],
        })
    return tuple(sorted(records, key=lambda item: str(item["unit_id"])))


def validate_policy_records(
    records: Sequence[Mapping[str, object]],
    expected_records: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    observed = tuple(sorted((dict(item) for item in records), key=lambda item: str(item.get("unit_id"))))
    expected = tuple(sorted((dict(item) for item in expected_records), key=lambda item: str(item.get("unit_id"))))
    if len(observed) != 352 or len(expected) != 352:
        raise G08Error("G08_POLICY_UNIVERSE_COUNT")
    unit_ids = [str(item.get("unit_id")) for item in observed]
    if len(unit_ids) != len(set(unit_ids)):
        raise G08Error("G08_POLICY_UNIVERSE_DUPLICATE_UNIT")
    required = {
        "unit_id", "schema_version", "analysis_id", "analysis_family",
        "model_family", "model_role", "outer_evaluation", "resolution_m",
        "risk_set_id", "support_identity", "mode", "candidates", "fixed_value",
        "inheritance_parent_unit_id", "authority_source", "policy_sha256",
    }
    for record in observed:
        if set(record) != required:
            raise G08Error("G08_POLICY_RECORD_SCHEMA")
        policy_payload = {key: value for key, value in record.items()
                          if key not in {"unit_id", "policy_sha256"}}
        if record["policy_sha256"] != sha256_bytes(canonical_json(policy_payload)):
            raise G08Error("G08_POLICY_RECORD_HASH")
    if canonical_json(observed) != canonical_json(expected):
        raise G08Error("G08_POLICY_AUTHORITY_MISMATCH")
    counts = Counter(str(item["mode"]) for item in observed)
    if dict(counts) != dict(EXPECTED_POLICY_MODE_COUNTS):
        raise G08Error(f"G08_POLICY_MODE_COUNTS:{dict(counts)}")
    aggregate = sha256_bytes(canonical_json(observed))
    return MappingProxyType({
        "total": len(observed),
        "mode_counts": MappingProxyType(dict(counts)),
        "policy_universe_sha256": aggregate,
    })


def governed_policy_universe(
    root: Path,
    contracts: Sequence[object] | None = None,
) -> tuple[tuple[g07_v2.HyperparameterPolicy, ...], tuple[dict[str, object], ...], Mapping[str, object]]:
    root = Path(root).resolve()
    if contracts is None:
        _, contracts = governed_plan(root)
    policies = []
    records = []
    for contract in contracts:
        policy = g07_v2.resolve_policy(contract)
        g07_v2.validate_policy(policy)
        policies.append(policy)
        records.append(_policy_record(g07._unit_id(contract), policy))
    ordered = tuple(record for _, record in sorted(
        zip((str(item["unit_id"]) for item in records), records), key=lambda item: item[0]
    ))
    policy_by_unit = {str(record["unit_id"]): policy for record, policy in zip(records, policies)}
    ordered_policies = tuple(policy_by_unit[str(record["unit_id"])] for record in ordered)
    validation = validate_policy_records(ordered, _accepted_policy_records(root))
    accepted_aggregate = g07_v2.policy_aggregate_sha256(ordered_policies)
    interface = g07_v2.v2_interface_identity(ordered_policies)
    if interface["policy_aggregate_sha256"] != accepted_aggregate:
        raise G08Error("G08_G07_POLICY_INTERFACE_AGGREGATE")
    return ordered_policies, ordered, validation


def dependency_graph_payload(
    contracts: Sequence[object],
    policy_records: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    by_unit = {g07._unit_id(contract): contract for contract in contracts}
    if len(by_unit) != len(contracts):
        raise G08Error("G08_DEPENDENCY_DUPLICATE_UNIT")
    inherited = []
    for record in policy_records:
        if record["mode"] != g07_v2.PolicyMode.INHERIT.value:
            continue
        child = str(record["unit_id"])
        parent = str(record["inheritance_parent_unit_id"])
        if parent not in by_unit or parent.startswith(V1_SUITE_RUN_ID):
            raise G08Error("G08_DEPENDENCY_INHERIT_PARENT")
        inherited.append({"child_unit_id": child, "parent_unit_id": parent})

    adjacency = {edge["child_unit_id"]: edge["parent_unit_id"] for edge in inherited}
    for origin in adjacency:
        seen = set()
        current = origin
        while current in adjacency:
            if current in seen:
                raise G08Error("G08_DEPENDENCY_INHERIT_CYCLE")
            seen.add(current)
            current = adjacency[current]

    pair_groups = []
    grouped: dict[tuple[object, ...], list[object]] = {}
    for contract in contracts:
        if (contract.execution_enabled and contract.model_role in {"baseline", "augmented"}
                and contract.evaluation_identity in g07.LOIO_SOURCE_EVALUATIONS):
            key = (
                contract.analysis_id, contract.model_family, contract.resolution_m,
                contract.risk_set_id, contract.support_identity,
            )
            grouped.setdefault(key, []).append(contract)
    expected_pairs = {
        (role, evaluation) for role in ("baseline", "augmented")
        for evaluation in g07.LOIO_SOURCE_EVALUATIONS
    }
    for key, members in grouped.items():
        observed_pairs = {(item.model_role, item.evaluation_identity) for item in members}
        if observed_pairs != expected_pairs:
            continue
        unit_ids = sorted(g07._unit_id(item) for item in members)
        pair_groups.append({
            "analysis_id": key[0], "model_family": key[1],
            "resolution_m": int(key[2]), "risk_set_id": key[3],
            "support_identity": key[4], "unit_ids": unit_ids,
        })

    loio_units = [contract for contract in contracts
                  if contract.analysis_family == "LEAVE_ONE_INTERVAL_OUT_DIAGNOSTIC"]
    if len(loio_units) != 1:
        raise G08Error("G08_DEPENDENCY_LOIO_UNIT_COUNT")
    loio_sources = sorted(
        g07._unit_id(contract) for contract in contracts
        if contract.analysis_id == "G05A_01_PRIMARY_EVT_1KM"
        and contract.model_family == "L2_LOGISTIC"
        and contract.model_role in {"baseline", "augmented"}
        and contract.evaluation_identity in g07.LOIO_SOURCE_EVALUATIONS
    )
    if len(loio_sources) != 6 or any(unit not in by_unit for unit in loio_sources):
        raise G08Error("G08_DEPENDENCY_LOIO_SOURCE_SET")
    payload = {
        "schema_version": "PAPER1_G08_V2_DEPENDENCY_GRAPH_V1",
        "inheritance_edges": sorted(inherited, key=lambda item: item["child_unit_id"]),
        "paired_staging_groups": sorted(pair_groups, key=lambda item: (
            str(item["analysis_id"]), str(item["model_family"]), int(item["resolution_m"]),
            str(item["risk_set_id"]), str(item["support_identity"]),
        )),
        "loio_staged_dependency": {
            "unit_id": g07._unit_id(loio_units[0]),
            "source_unit_ids": loio_sources,
            "semantics": "REQUIRES_EARLIER_GOVERNED_V2_OUTPUT_DURING_SUITE_EXECUTION",
        },
        "v1_dependencies_permitted": False,
    }
    identity = sha256_bytes(canonical_json(payload))
    return MappingProxyType({**payload, "dependency_graph_sha256": identity})


def validate_dependency_graph(
    observed: Mapping[str, object],
    expected: Mapping[str, object],
) -> Mapping[str, object]:
    if canonical_json(dict(observed)) != canonical_json(dict(expected)):
        raise G08Error("G08_DEPENDENCY_GRAPH_MISMATCH")
    return MappingProxyType(dict(observed))


def v2_evidence_lifecycle_identity(
    policies: Sequence[g07_v2.HyperparameterPolicy],
) -> Mapping[str, object]:
    interface = dict(g07_v2.v2_interface_identity(policies))
    payload = {
        "schema_version": "PAPER1_G08_G07_V2_EVIDENCE_LIFECYCLE_IDENTITY_V1",
        "g07_runner_schema_version": g07.SCHEMA_VERSION,
        "prediction_stage_schema_version": g07.PREDICTION_STAGE_SCHEMA_VERSION,
        "rf_seed_metric_schema_version": g07.RF_SEED_METRIC_SCHEMA_VERSION,
        "g07_v2_interface": interface,
    }
    return MappingProxyType({
        **payload,
        "evidence_lifecycle_sha256": sha256_bytes(canonical_json(payload)),
    })


def validate_v2_evidence_lifecycle_identity(
    observed: Mapping[str, object],
    expected: Mapping[str, object],
) -> Mapping[str, object]:
    if canonical_json(dict(observed)) != canonical_json(dict(expected)):
        raise G08Error("G08_V2_EVIDENCE_LIFECYCLE_MISMATCH")
    return MappingProxyType(dict(observed))


def validate_v2_namespace(output_root: str | Path, suite_run_id: str) -> Mapping[str, str]:
    observed_root = Path(output_root).as_posix()
    expected_root = PRODUCTION_OUTPUT_ROOT_RELATIVE.as_posix()
    if observed_root != expected_root:
        raise G08Error("G08_V2_NAMESPACE_OUTPUT_ROOT")
    if suite_run_id != SUITE_RUN_ID:
        raise G08Error("G08_V2_NAMESPACE_SUITE_RUN_ID")
    if observed_root == V1_OUTPUT_ROOT_RELATIVE.as_posix() or suite_run_id == V1_SUITE_RUN_ID:
        raise G08Error("G08_V1_NAMESPACE_REUSE")
    return MappingProxyType({"output_root": expected_root, "suite_run_id": SUITE_RUN_ID})


def validate_execution_universe_entries(
    observed: Sequence[g07.DispatchPlanEntry],
    expected: Sequence[g07.DispatchPlanEntry],
) -> str:
    if len(observed) != 352 or canonical_json([asdict(item) for item in observed]) != canonical_json(
        [asdict(item) for item in expected]
    ):
        raise G08Error("G08_EXECUTION_UNIVERSE_IDENTITY")
    return execution_universe_identity(observed)


def plan_summary(plan: Sequence[g07.DispatchPlanEntry]) -> Mapping[str, object]:
    counts = {
        "runner_resolvable": sum(
            item.disposition is g07.DispatchDisposition.EXECUTABLE for item in plan
        ),
        "environment_blocked": sum(
            item.disposition is g07.DispatchDisposition.ENVIRONMENT_BLOCKED for item in plan
        ),
        "nonestimable": sum(
            item.disposition is g07.DispatchDisposition.NONESTIMABLE for item in plan
        ),
        "disabled": sum(
            item.disposition is g07.DispatchDisposition.DISABLED for item in plan
        ),
        "authority_blocked": sum(
            item.disposition is g07.DispatchDisposition.AUTHORITY_BLOCKED for item in plan
        ),
    }
    observed = {
        "g05a": sum(item.unit_id.startswith("G05A_") for item in plan),
        "g05b": sum(item.unit_id.startswith("G05B_") for item in plan),
        "total": len(plan),
        **counts,
    }
    expected = {
        "g05a": 305, "g05b": 47, "total": 352,
        **dict(g07.expected_environment_dispositions(sum(
            item.model_family == "FRACTIONAL_LOGIT_GLM" for item in plan
        ))),
        "nonestimable": 4, "disabled": 5, "authority_blocked": 0,
    }
    if observed != expected:
        raise G08Error(f"G08_EXECUTION_UNIVERSE:{observed}")
    return MappingProxyType(observed)


def _artifact_descriptors(
    root: Path,
    plan: Sequence[g07.DispatchPlanEntry],
    contracts: Sequence[object],
) -> tuple[dict[str, object], ...]:
    executable = {
        item.unit_id for item in plan
        if item.disposition is g07.DispatchDisposition.EXECUTABLE
    }
    descriptors: dict[str, dict[str, object]] = {}
    for contract in contracts:
        if g07._unit_id(contract) not in executable:
            continue
        for role, path_value, expected in (
            ("predictor", contract.predictor_path, contract.predictor_sha256),
            ("support", contract.support_path, contract.support_sha256),
            ("response", contract.response_path, contract.response_sha256),
        ):
            prior = descriptors.get(path_value)
            if prior is not None and prior["expected_sha256"] != expected:
                raise G08Error(f"G08_CONFLICTING_ARTIFACT_AUTHORITY:{path_value}")
            path = root / path_value
            observed = sha256_file(path) if path.is_file() else "MISSING"
            descriptors[path_value] = {
                "role": role, "path": path_value, "expected_sha256": expected,
                "observed_sha256": observed,
                "status": "PASS" if observed == expected else "FAIL",
            }
    authority_path = root / "documentation/PAPER1_G06_4_ACCEPTED_AUTHORITY.json"
    authority = json.loads(authority_path.read_text(encoding="ascii"))
    special: list[tuple[str, str, str]] = []
    for section in authority["realized_weather"]["authorities"].values():
        special.append(("realized_weather", section["relative_path"], section["expected_sha256"]))
    realized = authority["realized_weather"]
    special.append(("realized_weather_manifest", realized["manifest_path"], realized["manifest_sha256"]))
    boundary = authority["boundary_filters"]
    special.append(("boundary_filter", boundary["relative_path"], boundary["expected_sha256"]))
    for role, path_value, expected in special:
        path = root / path_value
        observed = sha256_file(path) if path.is_file() else "MISSING"
        descriptors[f"special:{path_value}"] = {
            "role": role, "path": path_value, "expected_sha256": expected,
            "observed_sha256": observed,
            "status": "PASS" if observed == expected else "FAIL",
        }
    return tuple(sorted(descriptors.values(), key=lambda item: (str(item["path"]), str(item["role"]))))


def real_input_aggregate_identity(
    root: Path,
    plan: Sequence[g07.DispatchPlanEntry] | None = None,
    contracts: Sequence[object] | None = None,
) -> tuple[str, tuple[dict[str, object], ...]]:
    if plan is None or contracts is None:
        plan, contracts = governed_plan(root)
    descriptors = _artifact_descriptors(Path(root).resolve(), plan, contracts)
    if any(item["status"] != "PASS" for item in descriptors):
        raise G08Error("G08_REAL_INPUT_ARTIFACT_HASH")
    executable_contracts = sorted(
        contract.contract_sha256 for contract in contracts
        if any(
            entry.unit_id == g07._unit_id(contract)
            and entry.disposition is g07.DispatchDisposition.EXECUTABLE
            for entry in plan
        )
    )
    payload = {"artifacts": descriptors, "execution_contracts": executable_contracts}
    return sha256_bytes(canonical_json(payload)), descriptors


def _authenticate_readiness_ingress(
    root: Path,
    contract: object,
) -> g07.AuthenticatedExecutionInput:
    """Reopen accepted real inputs without G07's production clean-tree guard."""
    predictor_handle = g06.authenticate_predictor_artifact(
        root, contract.risk_set_id, contract.resolution_m, root / contract.predictor_path
    )
    predictor_data = g06.load_authenticated_predictors(predictor_handle, contract)
    g06.validate_authenticated_predictor_data(predictor_data, contract)
    predictor = predictor_data.to_frame()
    outcome_handle = g06.authenticate_outcome_for_contract(root, contract)
    outcome = pd.DataFrame([asdict(row) for row in outcome_handle.rows]).rename(
        columns={"response_y": "y"}
    )
    support = g07._support_frame(root, contract)
    frame = g07._merge_authoritative_interval_inputs(predictor, support, outcome)
    if contract.analysis_family == "REALIZED_WEATHER":
        weather = g07._authenticate_realized_weather_ingress(
            root, contract, g07.RunnerMode.SCIENTIFIC.value
        )
        frame = frame.merge(
            weather.to_frame(), on=[*g06.KEY_FIELDS, "interval_number"],
            validate="one_to_one",
        )
    if contract.analysis_family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY":
        boundary = g07._authenticate_boundary_ingress(
            root, contract, g07.RunnerMode.SCIENTIFIC.value
        )
        flags = boundary.to_filter_frame()
        frame = frame.merge(
            flags, on=[*g06.KEY_FIELDS, "interval_number"], validate="one_to_one"
        )
        frame = frame.loc[~frame[boundary.governed_flag_field].astype(bool)].copy()
    input_artifacts = (
        MappingProxyType({"path": contract.predictor_path, "sha256": contract.predictor_sha256,
                          "schema": "PAPER1_G06_AUTHENTICATED_PREDICTOR_INPUT_V1",
                          "key_identity": contract.predictor_key_sha256}),
        MappingProxyType({"path": contract.response_path, "sha256": contract.response_sha256,
                          "schema": g06.OUTCOME_INPUT_SCHEMA,
                          "key_identity": contract.response_key_interval_value_sha256}),
        MappingProxyType({"path": contract.support_path, "sha256": contract.support_sha256,
                          "schema": "PAPER1_G06_AUTHENTICATED_SUPPORT_INPUT_V1",
                          "key_identity": sha256_bytes(contract.support_identity.encode("utf-8"))}),
    )
    return g07.AuthenticatedExecutionInput(
        g07.RunnerMode.SCIENTIFIC.value, str(root), frame, input_artifacts,
        sha256_bytes(canonical_json([dict(item) for item in input_artifacts])),
        "G08_REAL_INPUT_READINESS", MappingProxyType({}),
    )


def audit_real_inputs(
    root: Path,
    plan: Sequence[g07.DispatchPlanEntry] | None = None,
    contracts: Sequence[object] | None = None,
) -> tuple[dict[str, object], ...]:
    root = Path(root).resolve()
    if plan is None or contracts is None:
        plan, contracts = governed_plan(root)
    executable = {
        item.unit_id for item in plan
        if item.disposition is g07.DispatchDisposition.EXECUTABLE
    }
    groups: dict[tuple[object, ...], list[object]] = {}
    for contract in contracts:
        if g07._unit_id(contract) not in executable:
            continue
        special = (
            contract.analysis_id
            if contract.analysis_family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY"
            else contract.analysis_family
            if contract.analysis_family == "REALIZED_WEATHER"
            else "STANDARD"
        )
        key = (
            special, contract.risk_set_id, contract.resolution_m,
            contract.predictor_path, contract.support_path, contract.support_identity,
            contract.response_path,
        )
        groups.setdefault(key, []).append(contract)
    records: list[dict[str, object]] = []
    for key, members in sorted(groups.items(), key=lambda item: str(item[0])):
        representative = members[0]
        class_id = sha256_bytes(canonical_json(key))[:16]
        try:
            authenticated = _authenticate_readiness_ingress(root, representative)
            frame = authenticated.frame
            if "interval_number" not in frame.columns:
                interval_columns = sorted(
                    column for column in frame.columns if column.startswith("interval_number")
                )
                raise G08Error(
                    f"G08_INPUT_INTERVAL_COLUMN_MISSING:{interval_columns}"
                )
            expected_intervals = set(representative.training_intervals) | set(
                representative.heldout_intervals
            )
            observed_intervals = set(int(value) for value in frame["interval_number"].unique())
            if not expected_intervals.issubset(observed_intervals):
                raise G08Error("G08_INPUT_INTERVAL_COMPLETENESS")
            if frame.loc[:, list(g06.KEY_FIELDS)].duplicated().any():
                raise G08Error("G08_INPUT_DUPLICATE_KEYS")
            status, error = "PASS", ""
            row_count, column_count = len(frame), len(frame.columns)
        except Exception as exc:
            status, error = "BLOCKING", f"{type(exc).__name__}:{exc}"
            row_count, column_count = 0, 0
        records.append({
            "input_class_id": class_id,
            "input_class": key[0],
            "risk_set_id": representative.risk_set_id,
            "resolution_m": representative.resolution_m,
            "support_identity": representative.support_identity,
            "unit_count": len(members),
            "row_count": row_count,
            "column_count": column_count,
            "status": status,
            "error": error,
            "predictor_path": representative.predictor_path,
            "support_path": representative.support_path,
            "response_path": representative.response_path,
        })
    loio_units = [
        item for item in plan
        if item.analysis_family == "LEAVE_ONE_INTERVAL_OUT_DIAGNOSTIC"
        and item.disposition is g07.DispatchDisposition.EXECUTABLE
    ]
    if len(loio_units) != 1:
        raise G08Error("G08_LOIO_UNIT_COUNT")
    records.append({
        "input_class_id": "LOIO_STAGED_SOURCE",
        "input_class": "LOIO_GOVERNED_OOF_OUTPUTS",
        "risk_set_id": loio_units[0].risk_set_id,
        "resolution_m": loio_units[0].resolution_m,
        "support_identity": "PRIMARY_CONFIRMATORY",
        "unit_count": 1,
        "row_count": 0,
        "column_count": 0,
        "status": "STAGED_DEPENDENCY",
        "error": "Requires six governed OOF manifests produced earlier in the authorized suite",
        "predictor_path": "",
        "support_path": "",
        "response_path": "",
    })
    return tuple(records)


def production_configuration_payload(root: Path) -> Mapping[str, object]:
    root = Path(root).resolve()
    plan, contracts = governed_plan(root)
    logistic_baseline, _ = schema_oracle.expected_schemas("PRIMARY_EVT", "logistic")
    geometry = [
        asdict(g06.governed_geometry_contract(root, evaluation))
        for evaluation in g07.LOIO_SOURCE_EVALUATIONS
    ]
    prevalence = [
        asdict(g06_4f.governed_prevalence_contract(root, evaluation))
        for evaluation in g07.LOIO_SOURCE_EVALUATIONS
    ]
    payload = {
        "baseline24": list(model_spec.BASELINE_FIELDS),
        "logistic_coordinates": list(logistic_baseline),
        "evt_fields": list(model_spec.EVT_FIELDS),
        "blocks": {key: list(values) for key, values in model_spec.BLOCKS.items()},
        "outer_evaluations": [
            [name, list(training), list(heldout)]
            for name, training, heldout in model_spec.OUTER_EVALUATIONS
        ],
        "no_early_intervals": list(g07.NO_EARLY_INTERVALS),
        "hybrid_levels": list(model_spec.HYBRID_LEVELS),
        "risk_sets": sorted({item.risk_set_id for item in plan}),
        "logistic": {
            "penalty": "l2", "solver": "lbfgs", "fit_intercept": True,
            "max_iter": 5000, "tol": 1e-8,
            "candidates": list(g07.LOGISTIC_CANDIDATES),
        },
        "geometry_contracts": geometry,
        "prevalence_contracts": prevalence,
        "prevalence_formula": "(training_positive + 0.5) / (training_rows + 1)",
        "rf": {
            "trees": g07.SCIENTIFIC_RF_TREES,
            "seeds": list(g07.RF_SEEDS),
            "leaf_candidates": list(g07.RF_LEAF_CANDIDATES),
        },
        "preprocessing": sorted({contract.preprocessing_identity for contract in contracts}),
        "zero_sd": "TRAINING_CONSTANT_FIXED_ZERO_COORDINATE",
        "bootstrap_replicates": g07.SCIENTIFIC_BOOTSTRAP_REPLICATES,
        "boundary_analyses": sorted({
            item.analysis_id for item in plan
            if item.analysis_family == "BOUNDARY_EXCLUSION_RESPONSE_QC_SENSITIVITY"
        }),
        "symmetric_cv_units": sum(
            item.analysis_family == "SYMMETRIC_BLOCKED_TEMPORAL_CV" for item in plan
        ),
        "loio": {
            "unit_count": sum(
                item.analysis_family == "LEAVE_ONE_INTERVAL_OUT_DIAGNOSTIC" for item in plan
            ),
            "meaning": "NO_REFIT_DIAGNOSTIC",
        },
        "fdist_executable": any(
            "FDIST" in item.analysis_family
            and item.disposition is g07.DispatchDisposition.EXECUTABLE for item in plan
        ),
        "realized_weather_isolation": list(registry.REALIZED_WEATHER),
        "firebrand_executable_units": sum(
            "FIREBRAND" in item.analysis_family
            and item.disposition is g07.DispatchDisposition.EXECUTABLE for item in plan
        ),
    }
    if len(payload["baseline24"]) != 24 or len(payload["logistic_coordinates"]) != 25:
        raise G08Error("G08_BASELINE_SCHEMA_DRIFT")
    return MappingProxyType(payload)


def environment_payload() -> Mapping[str, object]:
    return MappingProxyType({
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "executable": str(Path(sys.executable).resolve()),
        "numpy": _package_version("numpy"),
        "pandas": _package_version("pandas"),
        "scikit_learn": _package_version("scikit-learn"),
        "pyarrow": _package_version("pyarrow"),
        "statsmodels": _package_version("statsmodels"),
    })


def output_root_readiness(root: Path) -> Mapping[str, object]:
    root = Path(root).resolve()
    output_root = (root / PRODUCTION_OUTPUT_ROOT_RELATIVE).resolve()
    if not output_root.exists():
        return MappingProxyType({
            "output_root": output_root.as_posix(), "status": "PASS_ABSENT",
            "collision_count": 0, "collisions": (),
        })
    collisions = tuple(sorted(path.relative_to(output_root).as_posix() for path in output_root.rglob("*")))
    return MappingProxyType({
        "output_root": output_root.as_posix(),
        "status": "PASS_EMPTY" if not collisions else "FAIL_COLLISION",
        "collision_count": len(collisions), "collisions": collisions,
    })


def execution_universe_identity(plan: Sequence[g07.DispatchPlanEntry]) -> str:
    return sha256_bytes(canonical_json([asdict(item) for item in plan]))


def _source_sha256_at_commit(root: Path, commit: str, relative: str) -> str:
    return sha256_bytes(_git_bytes(root, "show", f"{commit}:{relative}"))


def _current_source_sha256(root: Path, relative: str) -> str:
    """Use canonical Git bytes for a clean path and worktree bytes for a real edit."""
    head_oid = _git(root, "rev-parse", f"HEAD:{relative}")
    index_oid = _git(root, "rev-parse", f":{relative}")
    worktree_oid = _git(root, "hash-object", f"--path={relative}", relative)
    if head_oid == index_oid == worktree_oid:
        return sha256_bytes(_git_bytes(root, "show", f"HEAD:{relative}"))
    return sha256_file(root / relative)


def _parent_scoped_plan_and_contracts(
    plan: Sequence[g07.DispatchPlanEntry],
    contracts: Sequence[object],
    parent_commit: str,
) -> tuple[tuple[g07.DispatchPlanEntry, ...], tuple[object, ...]]:
    """Rebind only G06's HEAD-dependent contract identity to an accepted parent."""
    rebound_contracts = []
    hashes_by_unit: dict[str, str] = {}
    for contract in contracts:
        values = asdict(contract)
        values.pop("contract_sha256")
        values["git_head"] = parent_commit
        contract_sha256 = sha256_bytes(g06.canonical_json(values))
        rebound = replace(
            contract, git_head=parent_commit, contract_sha256=contract_sha256
        )
        unit_id = g07._unit_id(contract)
        if unit_id in hashes_by_unit:
            raise G08Error("G08_PARENT_CONTRACT_DUPLICATE_UNIT")
        hashes_by_unit[unit_id] = contract_sha256
        rebound_contracts.append(rebound)
    if set(hashes_by_unit) != {entry.unit_id for entry in plan}:
        raise G08Error("G08_PARENT_PLAN_CONTRACT_SET")
    rebound_plan = tuple(
        replace(entry, contract_sha256=hashes_by_unit[entry.unit_id])
        for entry in plan
    )
    return rebound_plan, tuple(rebound_contracts)


def _build_execution_identity(
    root: Path,
    plan: Sequence[g07.DispatchPlanEntry],
    contracts: Sequence[object],
    source_commit: str | None = None,
) -> ExecutionContextIdentity:
    root = Path(root).resolve()
    authority = repository_authority(root, source_commit)
    summary = plan_summary(plan)
    policies, policy_records, policy_validation = governed_policy_universe(root, contracts)
    interface = g07_v2.v2_interface_identity(policies)
    evidence_identity = v2_evidence_lifecycle_identity(policies)
    dependency_identity = dependency_graph_payload(contracts, policy_records)
    input_identity, _ = real_input_aggregate_identity(root, plan, contracts)
    configuration_identity = sha256_bytes(
        canonical_json(dict(production_configuration_payload(root)))
    )
    environment_identity = sha256_bytes(canonical_json(dict(environment_payload())))
    payload = {
        "schema_version": EXECUTION_IDENTITY_SCHEMA_VERSION,
        "accepted_g07_implementation_commit": authority[
            "accepted_g07_implementation_commit"
        ],
        "independent_g07_acceptance_commit": authority[
            "independent_g07_acceptance_commit"
        ],
        "accepted_g07_runtime_sha256": authority["accepted_g07_runtime_sha256"],
        "accepted_g07_v2_policy_sha256": authority["accepted_g07_v2_policy_sha256"],
        "independent_g07_acceptance_artifacts_sha256": (
            authority["independent_g07_acceptance_artifacts_sha256"]
        ),
        "current_g07_runtime_sha256": (
            _source_sha256_at_commit(root, source_commit, "src/paper1_g07_runtime.py")
            if source_commit else _current_source_sha256(root, "src/paper1_g07_runtime.py")
        ),
        "current_g07_v2_policy_sha256": (
            _source_sha256_at_commit(root, source_commit, "src/paper1_g07_v2_policy.py")
            if source_commit else _current_source_sha256(root, "src/paper1_g07_v2_policy.py")
        ),
        "current_g08_runtime_sha256": (
            _source_sha256_at_commit(root, source_commit, "src/paper1_g08_runtime.py")
            if source_commit else _current_source_sha256(root, "src/paper1_g08_runtime.py")
        ),
        "g06_4e_sha256": authority["g06_4e_sha256"],
        "g06_4f_sha256": authority["g06_4f_sha256"],
        "loio_authority_sha256": authority["loio_authority_sha256"],
        "execution_universe_sha256": execution_universe_identity(plan),
        "policy_universe_sha256": policy_validation["policy_universe_sha256"],
        "g07_v2_interface_sha256": interface["interface_sha256"],
        "v2_evidence_lifecycle_sha256": evidence_identity["evidence_lifecycle_sha256"],
        "dependency_graph_sha256": dependency_identity["dependency_graph_sha256"],
        "real_input_aggregate_sha256": input_identity,
        "environment_identity_sha256": environment_identity,
        "production_configuration_sha256": configuration_identity,
        "output_root": PRODUCTION_OUTPUT_ROOT_RELATIVE.as_posix(),
        "suite_run_id": SUITE_RUN_ID,
        "authorized_unit_count": summary["runner_resolvable"],
    }
    identity = sha256_bytes(canonical_json(payload))
    return ExecutionContextIdentity(**payload, execution_identity_sha256=identity)


def build_execution_identity(root: Path) -> ExecutionContextIdentity:
    root = Path(root).resolve()
    plan, contracts = governed_plan(root)
    return _build_execution_identity(root, plan, contracts)


def build_parent_execution_identity(
    root: Path,
    parent_commit: str,
    plan: Sequence[g07.DispatchPlanEntry] | None = None,
    contracts: Sequence[object] | None = None,
) -> ExecutionContextIdentity:
    root = Path(root).resolve()
    _require_commit(root, parent_commit, "G08_AUTHORIZATION_PARENT_COMMIT")
    authority = repository_authority(root, parent_commit)
    _require_ancestor(
        root, str(authority["independent_g07_acceptance_commit"]), parent_commit,
        "G08_AUTHORIZATION_PARENT_PRECEDES_G07_ACCEPTANCE",
    )
    if plan is None or contracts is None:
        plan, contracts = governed_plan(root)
    parent_plan, parent_contracts = _parent_scoped_plan_and_contracts(
        plan, contracts, parent_commit
    )
    return _build_execution_identity(
        root, parent_plan, parent_contracts, source_commit=parent_commit
    )


def deterministic_unit_run_id(unit_id: str) -> str:
    return f"{SUITE_RUN_ID}__{sha256_bytes(unit_id.encode('utf-8'))[:20]}"


SHARED_PAIRED_EVIDENCE_DIRECTORY = "paired_evidence"
SHARED_PAIRED_EVIDENCE_FILENAME = "paired_benefit_evidence.json"


def _stale_output(reason: str) -> G08Error:
    return G08Error(f"G08_STALE_OUTPUT_COLLISION:{reason}")


def _read_shared_json(path: Path, role: str) -> Mapping[str, object]:
    if not path.is_file() or path.is_symlink():
        raise _stale_output(f"{role}_MISSING_OR_NONREGULAR")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _stale_output(f"{role}_JSON") from exc
    if not isinstance(payload, dict):
        raise _stale_output(f"{role}_SCHEMA")
    return MappingProxyType(payload)


def _shared_artifact_path(root: Path, record: Mapping[str, object], role: str) -> Path:
    value = record.get("path")
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise _stale_output(f"{role}_PATH")
    resolved = (root / value).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise _stale_output(f"{role}_PATH_ESCAPE") from exc
    return resolved


def _checkpoint_path_matches(
    state: Mapping[str, object], field: str, root: Path, expected: Path
) -> bool:
    recorded_root_value = state.get("validation_root")
    recorded_value = state.get(field)
    if not isinstance(recorded_root_value, str) or not isinstance(recorded_value, str):
        return False
    try:
        recorded_relative = Path(recorded_value).relative_to(Path(recorded_root_value))
        expected_relative = expected.relative_to(root)
    except ValueError:
        return False
    return recorded_relative.as_posix() == expected_relative.as_posix()


def _producer_scoped_source_contract(
    authority_root: Path,
    reviewer_contract: object,
    state: Mapping[str, object],
    stage: Mapping[str, object],
    issuance_path: Path,
    unit_root: Path,
) -> tuple[object, Mapping[str, str]]:
    """Reconstruct a historical source contract from its governed producer chain."""
    unit_id = g07._unit_id(reviewer_contract)
    issuance_wrapper = dict(_read_shared_json(
        issuance_path, "PAIR_SOURCE_ISSUANCE_CHECKPOINT"
    ))
    if set(issuance_wrapper) != {"payload", "payload_sha256"}:
        raise _stale_output(f"PAIR_SOURCE_ISSUANCE_SCHEMA:{unit_id}")
    issuance_checkpoint = issuance_wrapper.get("payload")
    if (
        not isinstance(issuance_checkpoint, dict)
        or issuance_wrapper.get("payload_sha256")
        != sha256_bytes(canonical_json(issuance_checkpoint))
        or issuance_checkpoint.get("current_phase") != "PREDICTION_WRITTEN"
    ):
        raise _stale_output(f"PAIR_SOURCE_ISSUANCE_HASH:{unit_id}")
    issuance = issuance_checkpoint.get("prediction_issuance")
    if not isinstance(issuance, dict):
        raise _stale_output(f"PAIR_SOURCE_ISSUANCE_PAYLOAD:{unit_id}")

    manifest = dict(_read_shared_json(
        unit_root / "execution_manifest.json", "PAIR_SOURCE_EXECUTION_MANIFEST"
    ))
    evidence_manifest = dict(_read_shared_json(
        unit_root / "v2_execution_evidence_manifest.json",
        "PAIR_SOURCE_EVIDENCE_MANIFEST",
    ))
    policy_receipt = dict(_read_shared_json(
        unit_root / "hyperparameter_policy_receipt.json", "PAIR_SOURCE_POLICY_RECEIPT"
    ))
    postprediction_receipt = dict(_read_shared_json(
        unit_root / "postprediction_unit_receipt.json",
        "PAIR_SOURCE_POSTPREDICTION_RECEIPT",
    ))

    producer_claims = {
        state.get("source_commit"),
        stage.get("source_commit"),
        issuance.get("source_commit"),
        manifest.get("runner_source_commit"),
        manifest.get("scientific_run_git_commit"),
        evidence_manifest.get("source_commit"),
    }
    # A legitimate completed run may retain prediction/policy evidence from
    # before a provenance-only migration. Authenticate each immutable artifact
    # separately; do not replace the active execution contract with its producer.
    if len(producer_claims) != 1 or len({
        state.get("identity", {}).get("contract_sha256"),
        stage.get("contract_sha256"), issuance.get("contract_sha256"),
        manifest.get("execution_contract_id"), evidence_manifest.get("contract_sha256"),
        policy_receipt.get("contract_sha256"), postprediction_receipt.get("contract_sha256"),
    }) != 1:
        roles = (
            ("prediction_stage_receipt", unit_root / "prediction_stage_receipt.json", stage, "contract_sha256"),
            ("prediction_issuance", issuance_path, issuance, "contract_sha256"),
            ("policy_receipt", unit_root / "hyperparameter_policy_receipt.json", policy_receipt, "contract_sha256"),
            ("postprediction_receipt", unit_root / "postprediction_unit_receipt.json", postprediction_receipt, "contract_sha256"),
            ("v2_execution_evidence_manifest", unit_root / "v2_execution_evidence_manifest.json", evidence_manifest, "contract_sha256"),
            ("execution_manifest", unit_root / "execution_manifest.json", manifest, "execution_contract_id"),
        )
        producers = {}
        for role, path, payload, field in roles:
            proof = g07._read_evidence_producer(authority_root, reviewer_contract, unit_root, path, role)
            if payload.get(field) != proof.contract_sha256:
                raise _stale_output(f"PAIR_SOURCE_ARTIFACT_PRODUCER:{unit_id}:{role}")
            for source_field in ("source_commit", "runner_source_commit", "scientific_run_git_commit"):
                if source_field in payload and payload[source_field] != proof.source_commit:
                    raise _stale_output(f"PAIR_SOURCE_ARTIFACT_SOURCE:{unit_id}:{role}")
            producers[role] = proof
        producer = producers["prediction_stage_receipt"]
        if producer.source_commit != producers["prediction_issuance"].source_commit:
            raise _stale_output(f"PAIR_SOURCE_ISSUANCE_PRODUCER:{unit_id}")
        latest_source = state.get("source_commit")
        validate_evidence_producer_activation(authority_root, latest_source)
        values = asdict(reviewer_contract)
        values.pop("contract_sha256")
        values["git_head"] = latest_source
        if state.get("identity", {}).get("contract_sha256") != sha256_bytes(g06.canonical_json(values)):
            raise _stale_output(f"PAIR_SOURCE_CURRENT_CHECKPOINT_CONTRACT:{unit_id}")
        return replace(reviewer_contract, git_head=producer.source_commit,
                       contract_sha256=producer.contract_sha256), MappingProxyType({
            "producer_commit": producer.source_commit,
            "producer_contract_sha256": producer.contract_sha256,
            "reviewer_contract_sha256": reviewer_contract.contract_sha256,
        })
    if (
        len(producer_claims) != 1
        or not isinstance(next(iter(producer_claims)), str)
        or not re.fullmatch(r"[0-9a-f]{40}", str(next(iter(producer_claims))))
    ):
        raise _stale_output(f"PAIR_SOURCE_PRODUCER_IDENTITY:{unit_id}")
    producer_commit = str(next(iter(producer_claims)))
    authority_root = Path(authority_root).resolve()
    _require_commit(
        authority_root, producer_commit, f"PAIR_SOURCE_PRODUCER_COMMIT:{unit_id}"
    )
    _require_ancestor(
        authority_root,
        producer_commit,
        _git(authority_root, "rev-parse", "HEAD"),
        f"PAIR_SOURCE_PRODUCER_NOT_ANCESTOR:{unit_id}",
    )

    state_identity = state.get("identity")
    if not isinstance(state_identity, dict):
        raise _stale_output(f"PAIR_SOURCE_CHECKPOINT_IDENTITY:{unit_id}")
    contract_claims = {
        state_identity.get("contract_sha256"),
        stage.get("contract_sha256"),
        issuance.get("contract_sha256"),
        manifest.get("execution_contract_id"),
        evidence_manifest.get("contract_sha256"),
        policy_receipt.get("contract_sha256"),
        postprediction_receipt.get("contract_sha256"),
    }
    if (
        len(contract_claims) != 1
        or not isinstance(next(iter(contract_claims)), str)
        or not re.fullmatch(r"[0-9a-f]{64}", str(next(iter(contract_claims))))
    ):
        raise _stale_output(f"PAIR_SOURCE_CONTRACT_IDENTITY:{unit_id}")
    producer_contract_sha256 = str(next(iter(contract_claims)))

    values = asdict(reviewer_contract)
    reviewer_contract_sha256 = str(values.pop("contract_sha256"))
    values["git_head"] = producer_commit
    reconstructed_sha256 = sha256_bytes(g06.canonical_json(values))
    if reconstructed_sha256 != producer_contract_sha256:
        raise _stale_output(f"PAIR_SOURCE_PRODUCER_CONTRACT:{unit_id}")
    producer_contract = replace(
        reviewer_contract,
        git_head=producer_commit,
        contract_sha256=producer_contract_sha256,
    )
    return producer_contract, MappingProxyType({
        "producer_commit": producer_commit,
        "producer_contract_sha256": producer_contract_sha256,
        "reviewer_contract_sha256": reviewer_contract_sha256,
    })


def _pair_source_lifecycle(
    state: Mapping[str, object],
    *,
    source_unit_id: str,
    request_unit_id: str,
    group_unit_ids: frozenset[str],
) -> str:
    """Classify a source, without granting publication or terminal authority."""
    phase = state.get("current_phase")
    if state.get("identity", {}).get("unit_id") != source_unit_id:
        raise _stale_output("PAIR_SOURCE_LIFECYCLE_IDENTITY")
    if source_unit_id not in group_unit_ids:
        raise _stale_output("PAIR_SOURCE_LIFECYCLE_GROUP")
    if phase not in g07.PRODUCTION_PHASES:
        raise _stale_output("PAIR_SOURCE_LIFECYCLE_PHASE")
    expected = list(g07.PRODUCTION_PHASES[:g07.PRODUCTION_PHASES.index(phase) + 1])
    if state.get("completed_phases") != expected:
        raise _stale_output("PAIR_SOURCE_LIFECYCLE_LINEAGE")
    terminal = state.get("terminal_disposition")
    if phase == "COMPLETE" and terminal == "COMPLETE":
        return "TERMINAL_SOURCE"
    if request_unit_id not in group_unit_ids:
        raise _stale_output("PAIR_SOURCE_STAGED_REQUEST_GROUP")
    if phase not in {
        "METRICS_WRITTEN", "POSTPREDICTION_EVIDENCE_WRITTEN",
        "PUBLICATION_VALIDATED", "TERMINAL_EVIDENCE_WRITTEN",
    }:
        raise _stale_output("PAIR_SOURCE_INVALID_STAGED_PHASE")
    expected_terminal = "COMPLETE" if phase == "TERMINAL_EVIDENCE_WRITTEN" else None
    if terminal != expected_terminal:
        raise _stale_output("PAIR_SOURCE_STAGED_TERMINAL_CLAIM")
    return "STAGED_SOURCE_REQUIRES_ARTIFACT_AUTHENTICATION"


def _validate_terminal_source_execution_manifest(
    root: Path,
    authority_root: Path,
    unit_root: Path,
    contract: object,
    producer_contract: object,
    producer_authority: Mapping[str, str],
    state: Mapping[str, object],
    prediction_path: Path,
    prediction: pd.DataFrame,
) -> None:
    """Bind terminal metadata to the same governed source reconstructed elsewhere."""
    unit_id = g07._unit_id(contract)
    manifest_path = unit_root / "execution_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise _stale_output(f"PAIR_SOURCE_EXECUTION_MANIFEST:{unit_id}")
    try:
        validated = g06.validate_execution_manifest(root, manifest_path, True)
        producer = g07._read_evidence_producer(
            authority_root, contract, unit_root, manifest_path, "execution_manifest"
        )
    except Exception as exc:
        raise _stale_output(f"PAIR_SOURCE_EXECUTION_MANIFEST:{unit_id}") from exc
    manifest = dict(validated.record)
    expected_inputs = [
        {
            "path": producer_contract.predictor_path,
            "sha256": producer_contract.predictor_sha256,
            "schema": "PAPER1_G06_AUTHENTICATED_PREDICTOR_INPUT_V1",
            "key_identity": producer_contract.predictor_key_sha256,
        },
        {
            "path": producer_contract.response_path,
            "sha256": producer_contract.response_sha256,
            "schema": g06.OUTCOME_INPUT_SCHEMA,
            "key_identity": producer_contract.response_key_interval_value_sha256,
        },
        {
            "path": producer_contract.support_path,
            "sha256": producer_contract.support_sha256,
            "schema": "PAPER1_G06_AUTHENTICATED_SUPPORT_INPUT_V1",
            "key_identity": sha256_bytes(
                producer_contract.support_identity.encode("utf-8")
            ),
        },
    ]
    expected_fields = {
        "paper1_run_id": deterministic_unit_run_id(unit_id),
        "runner_identity": g07.SCHEMA_VERSION,
        "runner_source_commit": producer_authority["producer_commit"],
        "scientific_run_git_commit": producer_authority["producer_commit"],
        "execution_contract_id": producer_contract.contract_sha256,
        "analysis_id": producer_contract.analysis_id,
        "model_family": producer_contract.model_family,
        "model_role": producer_contract.model_role,
        "outer_evaluation": producer_contract.evaluation_identity,
        "training_history": list(producer_contract.training_intervals),
        "validation_history": sorted({
            value for _, validation in g07.TUNING_SPLITS.get(
                producer_contract.evaluation_identity, ()) for value in validation
        }),
        "heldout_history": list(producer_contract.heldout_intervals),
        "input_artifacts": expected_inputs,
        "terminal_status": "COMPLETE",
        "exception_metadata": None,
        "evidence_classification": state["identity"]["classification"],
    }
    if any(manifest.get(key) != value for key, value in expected_fields.items()):
        raise _stale_output(f"PAIR_SOURCE_EXECUTION_MANIFEST_BINDING:{unit_id}")
    expected_output = {
        "path": prediction_path.relative_to(root).as_posix(),
        "sha256": sha256_file(prediction_path),
        "schema": g06.PREDICTION_ARTIFACT_SCHEMA,
        "row_count": len(prediction),
        "key_identity": g07._g06_4e_key_identity(prediction),
        "required_columns": list(g06.PREDICTION_INTEGRITY_COLUMNS),
    }
    if manifest.get("output_prediction_artifact") != expected_output:
        raise _stale_output(f"PAIR_SOURCE_EXECUTION_MANIFEST_OUTPUT:{unit_id}")
    expected_checkpoints = []
    for sequence, checkpoint_path in enumerate(sorted((unit_root / "checkpoints").glob("*.json")), start=1):
        wrapper = dict(_read_shared_json(checkpoint_path, "PAIR_SOURCE_MANIFEST_CHECKPOINT"))
        payload = wrapper.get("payload")
        if (
            set(wrapper) != {"payload", "payload_sha256"}
            or not isinstance(payload, dict)
            or wrapper.get("payload_sha256") != sha256_bytes(canonical_json(payload))
        ):
            raise _stale_output(f"PAIR_SOURCE_MANIFEST_CHECKPOINT:{unit_id}")
        expected_checkpoints.append({
            "path": checkpoint_path.relative_to(root).as_posix(),
            "sha256": sha256_file(checkpoint_path),
            "sequence": sequence,
            "resume_from_sequence": payload.get("resume_from_sequence"),
        })
    if manifest.get("checkpoints") != expected_checkpoints:
        raise _stale_output(f"PAIR_SOURCE_EXECUTION_MANIFEST_CHECKPOINTS:{unit_id}")
    if (
        producer.source_commit != producer_authority["producer_commit"]
        or producer.contract_sha256 != producer_contract.contract_sha256
    ):
        raise _stale_output(f"PAIR_SOURCE_EXECUTION_MANIFEST_PRODUCER:{unit_id}")


def _validate_shared_source_unit(
    root: Path,
    authority_root: Path,
    output_root: Path,
    contract: object,
    pair_path: Path,
    evidence_sha256: str,
) -> Mapping[str, object]:
    unit_id = g07._unit_id(contract)
    unit_root = output_root / deterministic_unit_run_id(unit_id)
    try:
        state = g07._reopen_production_state(unit_root, root)
    except Exception as exc:
        raise _stale_output(f"PAIR_SOURCE_CHECKPOINT:{unit_id}") from exc
    if (state.get("current_phase") != "COMPLETE"
            or state.get("terminal_disposition") != "COMPLETE"):
        raise _stale_output(f"PAIR_SOURCE_NOT_TERMINAL:{unit_id}")

    prediction_path = unit_root / "predictions.csv"
    stage_path = unit_root / "prediction_stage_receipt.json"
    issuance_path = g07._prediction_issuance_checkpoint_path(unit_root)
    for role, path in (
        ("PREDICTION", prediction_path),
        ("STAGE", stage_path),
        ("ISSUANCE", issuance_path),
    ):
        if not path.is_file() or path.is_symlink():
            raise _stale_output(f"PAIR_SOURCE_{role}:{unit_id}")

    stage = dict(_read_shared_json(stage_path, "PAIR_SOURCE_STAGE"))
    stage_hash = stage.pop("receipt_sha256", None)
    if stage_hash != sha256_bytes(canonical_json(stage)):
        raise _stale_output(f"PAIR_SOURCE_STAGE_HASH:{unit_id}")
    producer_contract, producer_authority = _producer_scoped_source_contract(
        authority_root, contract, state, stage, issuance_path, unit_root
    )
    policy = g07_v2.resolve_policy(producer_contract)
    state_identity = state["identity"]
    expected_stage = {
        "schema_version": g07.PREDICTION_STAGE_SCHEMA_VERSION,
        "stage_status": "PREDICTION_VALIDATED_NOT_TERMINAL",
        "run_id": deterministic_unit_run_id(unit_id),
        "unit_id": unit_id,
        "contract_sha256": producer_contract.contract_sha256,
        "analysis_id": producer_contract.analysis_id,
        "model_family": producer_contract.model_family,
        "model_role": producer_contract.model_role,
        "outer_evaluation": producer_contract.evaluation_identity,
        "resolution_m": producer_contract.resolution_m,
        "risk_set_id": producer_contract.risk_set_id,
        "support_identity": producer_contract.support_identity,
        "evidence_classification": state_identity.get("classification"),
        "policy_sha256": policy.policy_sha256,
        "input_identity": state_identity.get("input_identity"),
        "source_commit": producer_authority["producer_commit"],
        "environment_configuration_sha256": state_identity.get(
            "environment_configuration_sha256"
        ),
    }
    if any(stage.get(key) != value for key, value in expected_stage.items()):
        raise _stale_output(f"PAIR_SOURCE_STAGE_BINDING:{unit_id}")
    prediction_record = stage.get("prediction_artifact")
    if not isinstance(prediction_record, dict):
        raise _stale_output(f"PAIR_SOURCE_PREDICTION_RECORD:{unit_id}")
    if (
        _shared_artifact_path(root, prediction_record, "PAIR_SOURCE_PREDICTION").resolve()
        != prediction_path.resolve()
        or prediction_record.get("sha256") != sha256_file(prediction_path)
        or prediction_record.get("schema") != g06.PREDICTION_ARTIFACT_SCHEMA
    ):
        raise _stale_output(f"PAIR_SOURCE_PREDICTION_BINDING:{unit_id}")
    try:
        prediction = pd.read_csv(prediction_path)
    except Exception as exc:
        raise _stale_output(f"PAIR_SOURCE_PREDICTION_PARSE:{unit_id}") from exc
    if tuple(prediction.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS):
        raise _stale_output(f"PAIR_SOURCE_PREDICTION_SCHEMA:{unit_id}")
    if (
        stage.get("prediction_rows") != len(prediction)
        or stage.get("prediction_key_sha256") != g07._g06_4e_key_identity(prediction)
    ):
        raise _stale_output(f"PAIR_SOURCE_PREDICTION_IDENTITY:{unit_id}")
    _validate_terminal_source_execution_manifest(
        root, authority_root, unit_root, contract, producer_contract,
        producer_authority, state, prediction_path, prediction,
    )

    pair_relative = pair_path.relative_to(root).as_posix()
    pair_sha256 = sha256_file(pair_path)
    status_path = unit_root / "paired_publication_status.json"
    status = dict(_read_shared_json(status_path, "PAIR_SOURCE_STATUS"))
    expected_status = {
        "schema_version": "PAPER1_G07_V2_PAIRED_STATUS_V1",
        "status": "PUBLISHED_AND_VALIDATED",
        "paired_evidence_path": pair_relative,
        "paired_evidence_sha256": pair_sha256,
        "evidence_sha256": evidence_sha256,
    }
    if status != expected_status:
        raise _stale_output(f"PAIR_SOURCE_STATUS_BINDING:{unit_id}")
    if (
        state.get("paired_publication_status_sha256") != sha256_file(status_path)
        or not _checkpoint_path_matches(
            state, "paired_publication_status_path", root, status_path
        )
    ):
        raise _stale_output(f"PAIR_SOURCE_STATUS_CHECKPOINT:{unit_id}")

    gate_path = unit_root / "v2_publication_gate.json"
    gate = dict(_read_shared_json(gate_path, "PAIR_SOURCE_PUBLICATION_GATE"))
    observed_gate_hash = gate.pop("publication_gate_sha256", None)
    if observed_gate_hash != sha256_bytes(canonical_json(gate)):
        raise _stale_output(f"PAIR_SOURCE_PUBLICATION_GATE_HASH:{unit_id}")
    if (
        gate.get("schema_version") != g07_v2.PUBLICATION_SCHEMA_VERSION
        or gate.get("publication_state") != "VALIDATED_READY_FOR_TERMINAL"
        or state.get("publication_gate_sha256") != sha256_file(gate_path)
        or not _checkpoint_path_matches(state, "publication_gate_path", root, gate_path)
    ):
        raise _stale_output(f"PAIR_SOURCE_PUBLICATION_GATE_BINDING:{unit_id}")
    records = gate.get("artifact_records")
    required = gate.get("required_artifacts")
    if not isinstance(records, dict) or set(required or ()) != set(records):
        raise _stale_output(f"PAIR_SOURCE_PUBLICATION_RECORDS:{unit_id}")
    for role, record in records.items():
        if not isinstance(record, dict):
            raise _stale_output(f"PAIR_SOURCE_PUBLICATION_RECORD:{unit_id}:{role}")
        artifact = _shared_artifact_path(root, record, "PAIR_SOURCE_PUBLICATION")
        if (
            not artifact.is_file()
            or artifact.is_symlink()
            or record.get("sha256") != sha256_file(artifact)
        ):
            raise _stale_output(f"PAIR_SOURCE_PUBLICATION_HASH:{unit_id}:{role}")
    expected_pair_record = {
        "path": pair_relative,
        "sha256": pair_sha256,
        "schema": json.loads(pair_path.read_text(encoding="utf-8"))["schema_version"],
    }
    if records.get("paired_evidence") != expected_pair_record:
        raise _stale_output(f"PAIR_SOURCE_PUBLICATION_PAIR:{unit_id}")

    return MappingProxyType({
        "unit_id": unit_id,
        "contract_sha256": producer_contract.contract_sha256,
        "policy_sha256": policy.policy_sha256,
        "prediction_path": prediction_path.relative_to(root).as_posix(),
        "prediction_sha256": sha256_file(prediction_path),
        "prediction_stage_receipt_path": stage_path.relative_to(root).as_posix(),
        "prediction_stage_receipt_sha256": sha256_file(stage_path),
        "prediction_issuance_checkpoint_path": issuance_path.relative_to(root).as_posix(),
        "prediction_issuance_checkpoint_sha256": sha256_file(issuance_path),
        "evaluation": contract.evaluation_identity,
        "model_role": contract.model_role,
    })


def _validate_staged_pair_source(
    root: Path, authority_root: Path, output_root: Path, contract: object,
    pair_path: Path, evidence_sha256: str,
) -> tuple[pd.DataFrame, Mapping[str, object]]:
    """Authenticate nonterminal evidence without invoking execution or publication."""
    unit_id = g07._unit_id(contract)
    unit_root = output_root / deterministic_unit_run_id(unit_id)
    state = g07._reopen_production_state(unit_root, root)
    stage_path = unit_root / "prediction_stage_receipt.json"
    issuance_path = g07._prediction_issuance_checkpoint_path(unit_root)
    prediction_path = unit_root / "predictions.csv"
    stage = dict(_read_shared_json(stage_path, "PAIR_SOURCE_STAGE"))
    stage_hash = stage.pop("receipt_sha256", None)
    if stage_hash != sha256_bytes(canonical_json(stage)):
        raise _stale_output("PAIR_SOURCE_STAGE_HASH")
    issuance = dict(_read_shared_json(issuance_path, "PAIR_SOURCE_ISSUANCE"))
    if (set(issuance) != {"payload", "payload_sha256"}
            or issuance["payload_sha256"] != sha256_bytes(canonical_json(issuance["payload"]))):
        raise _stale_output("PAIR_SOURCE_ISSUANCE_HASH")
    issued = issuance["payload"]
    if (issued.get("current_phase") != "PREDICTION_WRITTEN"
            or issued.get("completed_phases") != list(g07.PRODUCTION_PHASES[:6])):
        raise _stale_output("PAIR_SOURCE_ISSUANCE_PHASE")
    source = stage.get("source_commit")
    if not isinstance(source, str) or re.fullmatch(r"[0-9a-f]{40}", source) is None:
        raise _stale_output("PAIR_SOURCE_PRODUCER_COMMIT")
    stage_producer = g07._read_evidence_producer(
        authority_root, contract, unit_root, stage_path, "prediction_stage_receipt"
    )
    if source != stage_producer.source_commit:
        raise _stale_output("PAIR_SOURCE_PRODUCER_COMMIT")
    values = asdict(contract)
    values.pop("contract_sha256")
    values["git_head"] = source
    producer_hash = sha256_bytes(g06.canonical_json(values))
    if (stage.get("contract_sha256") != producer_hash
            or issued.get("source_commit") != source
            or issued.get("identity", {}).get("contract_sha256") != producer_hash):
        raise _stale_output("PAIR_SOURCE_PRODUCER_CONTRACT")
    authenticated = g07._read_scientific_ingress(root, contract)
    context = SimpleNamespace(
        project_root=root, contract=contract,
        plan_entry=SimpleNamespace(unit_id=unit_id),
        request=SimpleNamespace(run_id=deterministic_unit_run_id(unit_id), output_root=output_root),
    )
    identity = g07._checkpoint_identity(context, authenticated)
    for observed in (issued.get("identity", {}), state.get("identity", {})):
        if ({k: v for k, v in observed.items() if k != "contract_sha256"}
                != {k: v for k, v in identity.items() if k != "contract_sha256"}):
            raise _stale_output("PAIR_SOURCE_IDENTITY")
    policy = g07_v2.resolve_policy(contract)
    policy_path = unit_root / "hyperparameter_policy_receipt.json"
    policy_receipt = dict(_read_shared_json(policy_path, "PAIR_SOURCE_POLICY"))
    policy_producer = g07._read_evidence_producer(
        authority_root, contract, unit_root, policy_path, "policy_receipt"
    )
    expected_policy = {**asdict(policy), "mode": policy.mode.value}
    if (policy_receipt.get("schema_version") != "PAPER1_G07_V2_POLICY_RECEIPT_V1"
            or policy_receipt.get("unit_id") != unit_id
            or policy_receipt.get("contract_sha256") != policy_producer.contract_sha256
            or canonical_json(policy_receipt.get("policy")) != canonical_json(expected_policy)
            or policy_receipt.get("policy_sha256") != policy.policy_sha256
            or policy_receipt.get("selected_hyperparameter") != state.get("selected_hyperparameter")
            or state.get("policy_receipt_sha256") != sha256_file(policy_path)):
        raise _stale_output("PAIR_SOURCE_POLICY_BINDING")
    expected_stage = {
        "schema_version": g07.PREDICTION_STAGE_SCHEMA_VERSION,
        "stage_status": "PREDICTION_VALIDATED_NOT_TERMINAL",
        "unit_id": unit_id, "run_id": deterministic_unit_run_id(unit_id),
        "analysis_id": contract.analysis_id, "model_family": contract.model_family,
        "model_role": contract.model_role, "outer_evaluation": contract.evaluation_identity,
        "resolution_m": contract.resolution_m, "risk_set_id": contract.risk_set_id,
        "support_identity": contract.support_identity, "evidence_classification": "SCIENTIFIC",
        "policy_sha256": policy.policy_sha256,
        "input_identity": authenticated.source_manifest_sha256,
        "environment_configuration_sha256": identity["environment_configuration_sha256"],
    }
    if any(stage.get(k) != v for k, v in expected_stage.items()):
        raise _stale_output("PAIR_SOURCE_STAGE_BINDING")
    record = stage.get("prediction_artifact", {})
    if (_shared_artifact_path(root, record, "PAIR_SOURCE_PREDICTION") != prediction_path.resolve()
            or prediction_path.is_symlink() or not prediction_path.is_file()
            or record.get("sha256") != sha256_file(prediction_path)
            or record.get("schema") != g06.PREDICTION_ARTIFACT_SCHEMA):
        raise _stale_output("PAIR_SOURCE_PREDICTION_BINDING")
    issue = issued.get("prediction_issuance", {})
    expected_issue = {
        "schema_version": "PAPER1_G07_V2_PREDICTION_ISSUANCE_V1",
        **{k: stage[k] for k in (
            "run_id", "unit_id", "contract_sha256", "policy_sha256", "input_identity",
            "source_commit", "environment_configuration_sha256", "prediction_artifact",
            "prediction_rows", "prediction_key_sha256",
        )},
    }
    if issue != expected_issue:
        raise _stale_output("PAIR_SOURCE_ISSUANCE_BINDING")
    prediction = pd.read_csv(prediction_path)
    keys = [*g06.KEY_FIELDS, "interval_number"]
    expected = authenticated.frame.loc[
        authenticated.frame.interval_number.isin(contract.heldout_intervals), keys + ["y"]
    ]
    if (tuple(prediction.columns) != tuple(g06.PREDICTION_INTEGRITY_COLUMNS)
            or prediction[keys].duplicated().any()
            or not prediction[keys].sort_values(keys).reset_index(drop=True).equals(
                expected[keys].sort_values(keys).reset_index(drop=True))
            or stage.get("prediction_rows") != len(prediction)
            or stage.get("prediction_key_sha256") != g07._g06_4e_key_identity(prediction)):
        raise _stale_output("PAIR_SOURCE_PREDICTION_IDENTITY")
    metrics = dict(_read_shared_json(unit_root / "metrics.json", "PAIR_SOURCE_METRICS"))
    if metrics != dict(g07._build_production_metrics(
        context, authenticated, prediction, sha256_file(prediction_path)
    )):
        raise _stale_output("PAIR_SOURCE_METRICS_RECONSTRUCTION")
    if contract.model_family == "RANDOM_FOREST":
        g07._validate_rf_seed_evidence_from_disk(
            context, authenticated, state, unit_root, expected, prediction_path
        )
    # COMPLETE sources retain their existing terminal/publication contract in
    # _validate_shared_source_unit. Do not reinterpret historical benchmark IDs
    # using a newer scoped benchmark authority as part of this staged correction.
    if (state.get("current_phase") != "COMPLETE"
            and contract.model_family == "L2_LOGISTIC" and contract.model_role == "baseline"
            and contract.analysis_family == "PRIMARY_EVT"):
        heldout = authenticated.frame.index[authenticated.frame.interval_number.isin(contract.heldout_intervals)]
        for kind in ("TRAINING_PREVALENCE", "GEOMETRY_LOGISTIC"):
            g07._reconcile_governed_benchmark_evidence(
                context, authenticated, state, authenticated.frame, heldout, kind
            )
    if "POSTPREDICTION_EVIDENCE_WRITTEN" in state["completed_phases"]:
        post_path = unit_root / "postprediction_unit_receipt.json"
        status_path = unit_root / "paired_publication_status.json"
        post = dict(_read_shared_json(post_path, "PAIR_SOURCE_POSTPREDICTION"))
        producer = g07._read_evidence_producer(
            authority_root, contract, unit_root, post_path, "postprediction_receipt"
        )
        expected_post = {
            "schema_version": "PAPER1_G07_V2_POSTPREDICTION_UNIT_RECEIPT_V1",
            "unit_id": unit_id, "contract_sha256": producer.contract_sha256,
            "policy_sha256": policy.policy_sha256,
            "input_identity": authenticated.source_manifest_sha256,
            "prediction_sha256": sha256_file(prediction_path),
            "metrics_sha256": sha256_file(unit_root / "metrics.json"),
            "prediction_stage_receipt_sha256": sha256_file(stage_path),
            "rf_seed_evidence_sha256": state.get("rf_seed_evidence_sha256"),
            "postprediction_requirements": dict(g07_v2.v2_interface_identity([policy]))["postprediction_requirements"],
        }
        expected_status = {
            "schema_version": "PAPER1_G07_V2_PAIRED_STATUS_V1",
            "status": "PUBLISHED_AND_VALIDATED",
            "paired_evidence_path": pair_path.relative_to(root).as_posix(),
            "paired_evidence_sha256": sha256_file(pair_path),
            "evidence_sha256": evidence_sha256,
        }
        if (canonical_json(post) != canonical_json(expected_post)
                or dict(_read_shared_json(status_path, "PAIR_SOURCE_STATUS")) != expected_status
                or state.get("postprediction_receipt_sha256") != sha256_file(post_path)
                or state.get("paired_publication_status_sha256") != sha256_file(status_path)):
            raise _stale_output("PAIR_SOURCE_STAGED_POSTPREDICTION_BINDING")
    source_record = {
        "unit_id": unit_id, "contract_sha256": producer_hash,
        "policy_sha256": policy.policy_sha256,
        "prediction_path": prediction_path.relative_to(root).as_posix(),
        "prediction_sha256": sha256_file(prediction_path),
        "prediction_stage_receipt_path": stage_path.relative_to(root).as_posix(),
        "prediction_stage_receipt_sha256": sha256_file(stage_path),
        "prediction_issuance_checkpoint_path": issuance_path.relative_to(root).as_posix(),
        "prediction_issuance_checkpoint_sha256": sha256_file(issuance_path),
        "evaluation": contract.evaluation_identity, "model_role": contract.model_role,
    }
    return prediction.merge(expected, on=keys, validate="one_to_one"), MappingProxyType(source_record)


def _validate_governed_shared_paired_evidence(
    root: Path,
    authority_root: Path,
    output_root: Path,
    request_unit_id: str,
    contracts: Sequence[object],
    policy_records: Sequence[Mapping[str, object]],
) -> Mapping[str, object]:
    paired_root = output_root / SHARED_PAIRED_EVIDENCE_DIRECTORY
    if not paired_root.exists():
        return MappingProxyType({"group_count": 0, "group_ids": ()})
    if not paired_root.is_dir() or paired_root.is_symlink():
        raise _stale_output("PAIR_ROOT_NOT_DIRECTORY")

    graph = dependency_graph_payload(contracts, policy_records)
    governed_groups = {
        frozenset(str(unit_id) for unit_id in group["unit_ids"]): group
        for group in graph["paired_staging_groups"]
    }
    contract_by_unit = {g07._unit_id(contract): contract for contract in contracts}
    if request_unit_id not in contract_by_unit:
        raise _stale_output("CURRENT_UNIT_NOT_GOVERNED")
    group_directories = sorted(paired_root.iterdir(), key=lambda path: path.name)
    if not group_directories:
        raise _stale_output("PAIR_ROOT_EMPTY")
    accepted_groups = []
    seen_sources: set[frozenset[str]] = set()
    for group_root in group_directories:
        if not group_root.is_dir() or group_root.is_symlink():
            raise _stale_output(f"PAIR_GROUP_PATH:{group_root.name}")
        children = sorted(group_root.iterdir(), key=lambda path: path.name)
        if [path.name for path in children] != [SHARED_PAIRED_EVIDENCE_FILENAME]:
            raise _stale_output(f"PAIR_GROUP_CONTENT:{group_root.name}")
        pair_path = children[0]
        evidence = dict(_read_shared_json(pair_path, "PAIR_EVIDENCE"))
        try:
            if evidence.get("schema_version") == g07_v2.BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION:
                g07_v2.validate_boundary_partial_benefit_evidence(evidence)
            else:
                g07_v2.validate_paired_evidence(evidence)
        except g07_v2.PolicyError as exc:
            raise _stale_output(f"PAIR_EVIDENCE_VALIDATION:{group_root.name}") from exc

        source_records = evidence.get("source_prediction_records")
        nonestimable_records = evidence.get("source_nonestimable_records", [])
        if not isinstance(source_records, list) or not isinstance(nonestimable_records, list):
            raise _stale_output(f"PAIR_SOURCE_RECORDS:{group_root.name}")
        source_units = frozenset(
            str(record.get("unit_id")) for record in source_records
            if isinstance(record, dict)
        ).union(
            str(record.get("unit_id")) for record in nonestimable_records
            if isinstance(record, dict)
        )
        if len(source_units) != len(source_records) + len(nonestimable_records) or source_units not in governed_groups:
            raise _stale_output(f"PAIR_SOURCE_UNITS:{group_root.name}")
        if source_units in seen_sources:
            raise _stale_output(f"PAIR_GROUP_DUPLICATE:{group_root.name}")
        seen_sources.add(source_units)
        group = governed_groups[source_units]

        baseline_identity = evidence.get("baseline_identity")
        augmented_identity = evidence.get("augmented_identity")
        expected_identity_fields = {
            "analysis_id", "model_family", "resolution_m", "support_identity",
            "source_identity", "model_role",
        }
        if (
            not isinstance(baseline_identity, dict)
            or not isinstance(augmented_identity, dict)
            or set(baseline_identity) != expected_identity_fields
            or set(augmented_identity) != expected_identity_fields
        ):
            raise _stale_output(f"PAIR_OWNER_SCHEMA:{group_root.name}")
        common = {key: value for key, value in baseline_identity.items() if key != "model_role"}
        expected_common = {
            "analysis_id": group["analysis_id"],
            "model_family": group["model_family"],
            "resolution_m": int(group["resolution_m"]),
            "support_identity": group["support_identity"],
        }
        if (
            any(common.get(key) != value for key, value in expected_common.items())
            or {key: value for key, value in augmented_identity.items() if key != "model_role"}
            != common
            or baseline_identity.get("model_role") != "baseline"
            or augmented_identity.get("model_role") != "augmented"
        ):
            raise _stale_output(f"PAIR_OWNER_IDENTITY:{group_root.name}")

        states = {
            unit_id: g07._reopen_production_state(
                output_root / deterministic_unit_run_id(unit_id), root
            ) for unit_id in source_units
        }
        partial_boundary = evidence.get("schema_version") == g07_v2.BOUNDARY_PARTIAL_EVIDENCE_SCHEMA_VERSION
        lifecycles = {}
        for unit_id, state in states.items():
            contract = contract_by_unit[unit_id]
            if contract.special_condition == "BOUNDARY_1000_B1_GOVERNED_NONESTIMABLE":
                if (not partial_boundary or state.get("current_phase") != "COMPLETE"
                        or state.get("terminal_disposition") != g07.TerminalDisposition.NONESTIMABLE.value):
                    raise _stale_output(f"PAIR_NONESTIMABLE_LIFECYCLE:{unit_id}")
                lifecycles[unit_id] = "NONESTIMABLE_TERMINAL_SOURCE"
            else:
                lifecycles[unit_id] = _pair_source_lifecycle(
                    state, source_unit_id=unit_id, request_unit_id=request_unit_id,
                    group_unit_ids=source_units,
                )
        expected_records = []
        frames = {"baseline": [], "augmented": []}
        for unit_id in sorted(source_units):
            contract = contract_by_unit[unit_id]
            if lifecycles[unit_id] == "NONESTIMABLE_TERMINAL_SOURCE":
                record = dict(g07._reopen_pair_nonestimable_source(
                    SimpleNamespace(project_root=root), contract,
                    output_root / deterministic_unit_run_id(unit_id),
                ))
                expected_records.append(record)
                continue
            prediction, source_record = _validate_staged_pair_source(
                root, authority_root, output_root, contract, pair_path,
                str(evidence.get("evidence_sha256")),
            )
            if lifecycles[unit_id] == "TERMINAL_SOURCE":
                terminal_record = _validate_shared_source_unit(
                    root, authority_root, output_root, contract, pair_path,
                    str(evidence.get("evidence_sha256")),
                )
                if dict(terminal_record) != dict(source_record):
                    raise _stale_output("PAIR_TERMINAL_SOURCE_RECONSTRUCTION")
            expected_records.append(dict(source_record))
            frames[contract.model_role].append(prediction)
        # Pair generation can postdate prediction production after an accepted
        # provenance-only migration. Bind all six contract claims to one such
        # recorded producer, never to an arbitrary caller-supplied commit.
        candidates = {str(state["source_commit"]) for state in states.values()}
        for unit_id in source_units:
            unit_root = output_root / deterministic_unit_run_id(unit_id)
            for checkpoint_path in sorted((unit_root / "checkpoints").glob("*.json")):
                checkpoint = _read_shared_json(checkpoint_path, "PAIR_PROVENANCE_CHECKPOINT")["payload"]
                if checkpoint.get("paired_publication_status_sha256") is not None:
                    candidates.add(str(checkpoint["source_commit"]))
        combined_records = sorted(
            [*source_records, *nonestimable_records], key=lambda item: item["unit_id"]
        )
        matching_records = []
        for producer in sorted(candidates):
            reconstructed = []
            for record in expected_records:
                values = asdict(contract_by_unit[record["unit_id"]])
                values.pop("contract_sha256")
                values["git_head"] = producer
                reconstructed.append({**record, "contract_sha256": sha256_bytes(g06.canonical_json(values))})
            if reconstructed == combined_records:
                validate_evidence_producer_activation(authority_root, producer)
                matching_records.append(reconstructed)
        if combined_records == expected_records:
            matching_records.append(expected_records)
        if not matching_records:
            raise _stale_output(f"PAIR_PRODUCER_RECORD_BINDING:{group_root.name}")
        expected_records = matching_records[0]
        try:
            if partial_boundary:
                g07_v2.validate_boundary_partial_benefit_evidence(
                    evidence,
                    baseline=pd.concat(frames["baseline"], ignore_index=True),
                    augmented=pd.concat(frames["augmented"], ignore_index=True),
                )
            else:
                g07_v2.validate_paired_evidence(
                    evidence,
                    baseline=pd.concat(frames["baseline"], ignore_index=True),
                    augmented=pd.concat(frames["augmented"], ignore_index=True),
                )
        except g07_v2.PolicyError as exc:
            raise _stale_output("PAIR_SOURCE_SEMANTIC_RECONSTRUCTION") from exc
        if combined_records != expected_records:
            raise _stale_output(f"PAIR_SOURCE_RECORD_BINDING:{group_root.name}")
        response_hashes = {
            contract_by_unit[unit_id].response_sha256 for unit_id in source_units
        }
        if len(response_hashes) != 1:
            raise _stale_output(f"PAIR_RESPONSE_IDENTITY:{group_root.name}")
        expected_source_identity = sha256_bytes(canonical_json({
            "analysis_id": group["analysis_id"],
            "model_family": group["model_family"],
            "resolution_m": int(group["resolution_m"]),
            "support_identity": group["support_identity"],
            "response_sha256": next(iter(response_hashes)),
            "unit_records": expected_records,
        }))
        if common.get("source_identity") != expected_source_identity:
            raise _stale_output(f"PAIR_SOURCE_IDENTITY:{group_root.name}")
        canonical_group_id = sha256_bytes(canonical_json(common))
        if group_root.name != canonical_group_id:
            raise _stale_output(f"PAIR_CANONICAL_OWNER:{group_root.name}")
        accepted_groups.append(canonical_group_id)

    return MappingProxyType({
        "group_count": len(accepted_groups),
        "group_ids": tuple(accepted_groups),
    })


def expected_authorization_payload(
    identity: ExecutionContextIdentity,
    authorization_parent_commit: str,
) -> Mapping[str, object]:
    return MappingProxyType({
        "schema_name": AUTHORIZATION_SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "authorization_state": "AUTHORIZED",
        "authorization_parent_commit": authorization_parent_commit,
        "execution_identity": asdict(identity),
        "execution_identity_sha256": identity.execution_identity_sha256,
    })


def validate_authorization_payload(
    payload: Mapping[str, object],
    expected_identity: ExecutionContextIdentity,
) -> Mapping[str, object]:
    expected_keys = {
        "schema_name", "schema_version", "authorization_state",
        "authorization_parent_commit", "execution_identity",
        "execution_identity_sha256",
    }
    if not isinstance(payload, Mapping) or set(payload) != expected_keys:
        raise G08Error("G08_AUTHORIZATION_SCHEMA")
    if payload.get("schema_name") != AUTHORIZATION_SCHEMA_NAME:
        raise G08Error("G08_AUTHORIZATION_NAME")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise G08Error("G08_AUTHORIZATION_VERSION")
    if payload.get("authorization_state") != "AUTHORIZED":
        raise G08Error("G08_AUTHORIZATION_STATE")
    if payload.get("execution_identity") != asdict(expected_identity):
        raise G08Error("G08_AUTHORIZATION_EXECUTION_IDENTITY")
    if payload.get("execution_identity_sha256") != expected_identity.execution_identity_sha256:
        raise G08Error("G08_AUTHORIZATION_IDENTITY_HASH")
    parent = payload.get("authorization_parent_commit")
    if not isinstance(parent, str) or len(parent) != 40:
        raise G08Error("G08_AUTHORIZATION_PARENT_COMMIT")
    return MappingProxyType(dict(payload))


def validate_activation_metadata(
    changed_paths: Sequence[str],
    activation_parent: str,
    payload: Mapping[str, object],
    gate: Mapping[str, str],
    final_acceptance_bytes: bytes,
    final_acceptance_gate_bytes: bytes,
    reviewed_implementation_commit: str,
    acceptance_artifact_aggregate_sha256: str,
    reviewed_parent: str | None = None,
    reviewed_implementation_scope_sha256: str | None = None,
    authenticated_acceptance_paths: Sequence[str] | None = None,
    independent_acceptance_commit: str | None = None,
) -> Mapping[str, object]:
    if set(changed_paths) != PERMITTED_ACTIVATION_PATHS:
        raise G08Error("G08_AUTHORIZATION_ACTIVATION_COMMIT_SCOPE")
    if payload.get("authorization_parent_commit") != activation_parent:
        raise G08Error("G08_AUTHORIZATION_COMMIT_LINEAGE")
    if (
        gate.get("g08_accepted") != "YES"
        or gate.get("scientific_fitting_authorized") != "YES"
        or gate.get("verdict") not in {"TRUSTED", "TRUSTED_WITH_LIMITATIONS"}
        or gate.get("accepted_g08_commit") != (independent_acceptance_commit or activation_parent)
        or gate.get("accepted_g08_implementation_commit")
        != reviewed_implementation_commit
        or gate.get("g08_v2_acceptance_artifacts_sha256")
        != acceptance_artifact_aggregate_sha256
    ):
        raise G08Error("G08_INDEPENDENT_GATE_NOT_ACCEPTED")
    acceptance_path = gate.get("final_acceptance_path", "")
    acceptance_gate_path = gate.get("final_acceptance_gate_path", "")
    expected_acceptance_paths = (
        tuple(authenticated_acceptance_paths)
        if authenticated_acceptance_paths is not None
        else _acceptance_paths_for_implementation(
            reviewed_implementation_commit, reviewed_parent
        )
    )
    if (
        acceptance_path != expected_acceptance_paths[0]
        or acceptance_gate_path != expected_acceptance_paths[3]
    ):
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_PATH")
    acceptance_parts = Path(acceptance_path).parts
    acceptance_gate_parts = Path(acceptance_gate_path).parts
    if (not acceptance_path.startswith("documentation/")
            or not acceptance_gate_path.startswith("documentation/")
            or ".." in acceptance_parts or ".." in acceptance_gate_parts
            or Path(acceptance_path).is_absolute()
            or Path(acceptance_gate_path).is_absolute()):
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_PATH")
    acceptance_sha = sha256_bytes(final_acceptance_bytes)
    acceptance_gate_sha = sha256_bytes(final_acceptance_gate_bytes)
    if (gate.get("final_acceptance_sha256") != acceptance_sha
            or gate.get("final_acceptance_gate_sha256") != acceptance_gate_sha):
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_HASH")
    records = [
        {"path": acceptance_path, "sha256": acceptance_sha},
        {"path": acceptance_gate_path, "sha256": acceptance_gate_sha},
    ]
    if gate.get("independent_acceptance_identity_sha256") != sha256_bytes(
        canonical_json(records)
    ):
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_IDENTITY")
    final_rows = list(csv.DictReader(
        final_acceptance_gate_bytes.decode("utf-8").splitlines()
    ))
    if len(final_rows) != 1:
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_GATE_SCHEMA")
    final_gate = final_rows[0]
    if reviewed_parent is None:
        if reviewed_implementation_commit == OUTPUT_COLLISION_CORRECTION2_IMPLEMENTATION_COMMIT:
            reviewed_parent = OUTPUT_COLLISION_REJECTION_COMMIT
        elif reviewed_implementation_commit == AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT:
            reviewed_parent = AUTHORITY_LINEAGE_CORRECTION_BASE_COMMIT
        elif reviewed_implementation_commit == GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT:
            reviewed_parent = DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT
        else:
            raise G08Error("G08_INDEPENDENT_ACCEPTANCE_REVIEWED_PARENT_REQUIRED")
    if (
        final_gate.get("verdict") != "ACCEPT"
        or final_gate.get("reviewed_commit") != reviewed_implementation_commit
        or final_gate.get("reviewed_parent") != reviewed_parent
        or final_gate.get("implementation_fail") != "0"
        or final_gate.get("independent_fail") != "0"
        or not final_gate.get("implementation_pass", "").isdigit()
        or int(final_gate["implementation_pass"]) <= 0
        or not final_gate.get("independent_pass", "").isdigit()
        or int(final_gate["independent_pass"]) <= 0
        or final_gate.get("v2_active_authorization_created") != "NO"
        or final_gate.get("scientific_fitting_authorized") != "NO"
        or final_gate.get("models_fit") != "0"
        or final_gate.get("real_predictions_generated") != "0"
        or final_gate.get("real_performance_inspected") != "0"
        or final_gate.get("final_gate") != "ACCEPT"
        or final_gate.get("next_authorized_action")
        != "OPERATOR_TRUST_PIN_CONFIGURATION_THEN_G08_V2_ACTIVATION_ONLY_GATE"
    ):
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_SEMANTICS")
    if reviewed_implementation_scope_sha256 is not None and (
        final_gate.get("reviewed_changed_paths_sha256")
        != reviewed_implementation_scope_sha256
        or final_gate.get("scope_authority")
        != "INDEPENDENT_ACCEPTANCE_BINDS_GIT_DIFF"
    ):
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_SCOPE")
    return MappingProxyType({
        "activation_parent_commit": activation_parent,
        "reviewed_implementation_commit": reviewed_implementation_commit,
        "acceptance_artifact_aggregate_sha256": (
            acceptance_artifact_aggregate_sha256
        ),
        "independent_acceptance_identity_sha256": gate[
            "independent_acceptance_identity_sha256"
        ],
    })


def _tracked_bytes(root: Path, relative: Path) -> bytes:
    if _git(root, "ls-files", "--error-unmatch", relative.as_posix()) != relative.as_posix():
        raise G08Error(f"G08_AUTHORIZATION_UNTRACKED:{relative.as_posix()}")
    return _canonical_clean_tracked_bytes(
        root, relative.as_posix(),
        f"G08_AUTHORIZATION_NOT_COMMITTED:{relative.as_posix()}",
    )


def validate_committed_activation(
    root: Path,
    activation_commit: str,
    plan: Sequence[g07.DispatchPlanEntry] | None = None,
    contracts: Sequence[object] | None = None,
) -> Mapping[str, object]:
    """Authenticate direct or operator-bridged activation without dispatch."""
    root = Path(root).resolve()
    _require_commit(root, activation_commit, "G08_AUTHORIZATION_COMMIT")
    activation_parent = _git(root, "rev-parse", f"{activation_commit}^")
    acceptance, acceptance_commit = _activation_parent_authority(root, activation_parent)
    if _git(root, "rev-list", "--parents", "-n", "1", activation_commit).split() != [activation_commit, activation_parent]:
        raise G08Error("G08_AUTHORIZATION_ACTIVATION_PARENT")
    changed = _commit_changed_paths(root, activation_commit)
    if changed != PERMITTED_ACTIVATION_PATHS:
        raise G08Error("G08_AUTHORIZATION_ACTIVATION_COMMIT_SCOPE")

    receipt_bytes = _git_bytes(
        root, "show", f"{activation_commit}:{ACTIVE_AUTHORIZATION_RELATIVE.as_posix()}"
    )
    gate_bytes = _git_bytes(
        root, "show", f"{activation_commit}:{INDEPENDENT_GATE_RELATIVE.as_posix()}"
    )
    try:
        payload = json.loads(receipt_bytes.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise G08Error("G08_AUTHORIZATION_SCHEMA") from exc
    gate_rows = list(csv.DictReader(gate_bytes.decode("utf-8").splitlines()))
    if len(gate_rows) != 1:
        raise G08Error("G08_INDEPENDENT_GATE_SCHEMA")
    gate = gate_rows[0]

    if plan is None or contracts is None:
        plan, contracts = governed_plan(root)
    expected_identity = build_parent_execution_identity(
        root, activation_parent, plan, contracts
    )
    validate_authorization_payload(payload, expected_identity)

    acceptance_path = gate.get("final_acceptance_path", "")
    acceptance_gate_path = gate.get("final_acceptance_gate_path", "")
    if not acceptance_path or not acceptance_gate_path:
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_PATH")
    final_acceptance_bytes = _git_bytes(
        root, "show", f"{acceptance_commit}:{acceptance_path}"
    )
    final_acceptance_gate_bytes = _git_bytes(
        root, "show", f"{acceptance_commit}:{acceptance_gate_path}"
    )
    validate_activation_metadata(
        tuple(changed),
        activation_parent,
        payload,
        gate,
        final_acceptance_bytes,
        final_acceptance_gate_bytes,
        str(acceptance["implementation_commit"]),
        str(acceptance["acceptance_artifact_aggregate_sha256"]),
        str(acceptance["implementation_lineage"]["implementation_parent"]),
        str(acceptance["reviewed_changed_paths_sha256"]),
        tuple(acceptance["acceptance_paths"]),
        acceptance_commit,
    )
    return MappingProxyType(dict(payload))


def validate_evidence_producer_activation(
    root: Path, source_commit: object,
) -> Mapping[str, object]:
    """Authenticate historical evidence provenance, never current execution.

    Only frozen, validated transitions or an activation authenticated by the
    current external pins qualify. An arbitrary ancestor is not authority.
    """
    from src import paper1_control_reference as reference
    if selected := reference.selected(root):
        return MappingProxyType(selected.producer(source_commit))
    from src.paper1_control_execution import active_operation
    if operation := active_operation(root):
        return MappingProxyType(operation.producer(source_commit))
    root = Path(root).resolve()
    if not isinstance(source_commit, str) or COMMIT_SHA_PATTERN.fullmatch(source_commit) is None:
        raise G08Error("G08_EVIDENCE_PRODUCER_COMMIT")
    _require_commit(root, source_commit, "G08_EVIDENCE_PRODUCER_COMMIT")
    _require_ancestor(root, source_commit, _git(root, "rev-parse", "HEAD"),
                      "G08_EVIDENCE_PRODUCER_ANCESTRY")
    if _commit_changed_paths(root, source_commit) != PERMITTED_ACTIVATION_PATHS:
        raise G08Error("G08_EVIDENCE_PRODUCER_NOT_ACTIVATION")
    pins = operator_g08_trust_pins(root)
    accepted = g08_v2_acceptance_authority(root, pins["acceptance"])
    if source_commit == PRIOR_G08_ACTIVATION_COMMIT:
        # Exact frozen activation already anchors the accepted correction
        # history. This is not a rule accepting arbitrary earlier activations.
        _require_ancestor(root, source_commit, pins["implementation"],
                          "G08_EVIDENCE_FROZEN_PRIOR_ACTIVATION")
        return MappingProxyType({
            "source_commit": source_commit,
            "transition_id": "FROZEN_PRIOR_ACTIVATION:" + source_commit,
            "execution_authorized": False,
        })
    records = (
        _historical_governed_transition_record(),
        *_load_governed_transition_extensions(root, pins["implementation"]),
    )
    for record in records:
        if record.get("prior_authority_tip") == source_commit:
            transition = validate_governed_downstream_transition(root, record)
            return MappingProxyType({
                "source_commit": source_commit,
                "transition_id": transition["transition_id"],
                "execution_authorized": False,
            })
    lineage = accepted["implementation_lineage"]
    if (lineage.get("bridge_required") is True
            and lineage["chain_facts"]["downstream"]["prior_authority_tip"] == source_commit):
        bridge = _bridge_pin(root)
        validated = validate_transition_bridge(root, pins["implementation"], pins["acceptance"], bridge)
        return MappingProxyType({
            "source_commit": source_commit,
            "transition_id": "PINNED_TRANSITION_BRIDGE:" + str(validated["bridge_commit"]),
            "execution_authorized": False,
        })
    # Inspect immutable producer authority, not current working-tree execution
    # readiness. The latter still uses validate_committed_activation unchanged.
    parent = _git(root, "rev-parse", f"{source_commit}^")
    acceptance, acceptance_commit = _activation_parent_authority(root, parent)
    _require_direct_commit(root, source_commit, parent, PERMITTED_ACTIVATION_PATHS,
                           "G08_EVIDENCE_PRODUCER_ACTIVATION")
    if _git(root, "rev-list", "--parents", "-n", "1", source_commit).split() != [source_commit, parent]:
        raise G08Error("G08_EVIDENCE_PRODUCER_ACTIVATION_PARENT")
    payload = json.loads(_git_bytes(root, "show", f"{source_commit}:{ACTIVE_AUTHORIZATION_RELATIVE.as_posix()}"))
    gate_rows = list(csv.DictReader(_git_bytes(
        root, "show", f"{source_commit}:{INDEPENDENT_GATE_RELATIVE.as_posix()}"
    ).decode("utf-8").splitlines()))
    if len(gate_rows) != 1:
        raise G08Error("G08_EVIDENCE_PRODUCER_GATE")
    gate = gate_rows[0]
    identity = payload.get("execution_identity")
    if not isinstance(identity, dict):
        raise G08Error("G08_EVIDENCE_PRODUCER_IDENTITY")
    identity_body = dict(identity)
    identity_hash = identity_body.pop("execution_identity_sha256", None)
    if (set(payload) != {"schema_name", "schema_version", "authorization_state",
                         "authorization_parent_commit", "execution_identity", "execution_identity_sha256"}
            or payload.get("schema_name") != AUTHORIZATION_SCHEMA_NAME
            or payload.get("schema_version") != SCHEMA_VERSION
            or payload.get("authorization_state") != "AUTHORIZED"
            or identity_hash != sha256_bytes(canonical_json(identity_body))
            or payload.get("execution_identity_sha256") != identity_hash):
        raise G08Error("G08_EVIDENCE_PRODUCER_RECEIPT")
    for key, relative in (
        ("current_g07_runtime_sha256", "src/paper1_g07_runtime.py"),
        ("current_g07_v2_policy_sha256", "src/paper1_g07_v2_policy.py"),
        ("current_g08_runtime_sha256", "src/paper1_g08_runtime.py"),
    ):
        if identity.get(key) != _source_sha256_at_commit(root, parent, relative):
            raise G08Error("G08_EVIDENCE_PRODUCER_SOURCE_HASH")
    validate_activation_metadata(
        tuple(_commit_changed_paths(root, source_commit)), parent, payload, gate,
        _git_bytes(root, "show", f"{acceptance_commit}:{gate.get('final_acceptance_path', '')}"),
        _git_bytes(root, "show", f"{acceptance_commit}:{gate.get('final_acceptance_gate_path', '')}"),
        str(acceptance["implementation_commit"]),
        str(acceptance["acceptance_artifact_aggregate_sha256"]),
        str(acceptance["implementation_lineage"]["implementation_parent"]),
        str(acceptance["reviewed_changed_paths_sha256"]),
        tuple(acceptance["acceptance_paths"]), acceptance_commit,
    )
    return MappingProxyType({
        "source_commit": source_commit,
        "transition_id": "PINNED_ACTIVATION:" + source_commit,
        "execution_authorized": False,
    })


def _load_committed_authorization(root: Path) -> Mapping[str, object]:
    root = Path(root).resolve()
    receipt_path = root / ACTIVE_AUTHORIZATION_RELATIVE
    gate_path = root / INDEPENDENT_GATE_RELATIVE
    if not receipt_path.is_file():
        raise G08Error("G08_AUTHORIZATION_RECEIPT_MISSING")
    if not gate_path.is_file():
        raise G08Error("G08_INDEPENDENT_ACCEPTANCE_MISSING")
    if _git(root, "status", "--porcelain"):
        raise G08Error("G08_AUTHORIZATION_REQUIRES_CLEAN_TREE")
    receipt_bytes = _tracked_bytes(root, ACTIVE_AUTHORIZATION_RELATIVE)
    gate_bytes = _tracked_bytes(root, INDEPENDENT_GATE_RELATIVE)
    committed = validate_committed_activation(root, _git(root, "rev-parse", "HEAD"))
    if receipt_bytes != _git_bytes(
        root, "show", f"HEAD:{ACTIVE_AUTHORIZATION_RELATIVE.as_posix()}"
    ) or gate_bytes != _git_bytes(
        root, "show", f"HEAD:{INDEPENDENT_GATE_RELATIVE.as_posix()}"
    ):
        raise G08Error("G08_AUTHORIZATION_NOT_COMMITTED")
    return committed


def _validate_output_collision(
    root: Path,
    request: g07.ProductionExecutionRequest,
    executable_units: Sequence[str],
    contracts: Sequence[object] | None = None,
    policy_records: Sequence[Mapping[str, object]] | None = None,
    authority_root: Path | None = None,
) -> None:
    expected_root = (Path(root).resolve() / PRODUCTION_OUTPUT_ROOT_RELATIVE).resolve()
    if Path(request.output_root).resolve() != expected_root:
        raise G08Error("G08_OUTPUT_ROOT_IDENTITY")
    expected_run_id = deterministic_unit_run_id(request.unit_id)
    if request.run_id != expected_run_id:
        raise G08Error("G08_RUN_IDENTITY")
    run_root = expected_root / request.run_id
    if run_root.exists() and not request.resume:
        raise G08Error("G08_OUTPUT_COLLISION_REQUIRES_RESUME")
    if request.resume and not run_root.exists():
        raise G08Error("G08_RESUME_TARGET_MISSING")
    if expected_root.exists():
        allowed = {deterministic_unit_run_id(unit_id) for unit_id in executable_units}
        paired_root = expected_root / SHARED_PAIRED_EVIDENCE_DIRECTORY
        if paired_root.exists():
            if contracts is None or policy_records is None:
                raise _stale_output("PAIR_AUTHORITY_REQUIRED")
            _validate_governed_shared_paired_evidence(
                Path(root).resolve(),
                Path(authority_root).resolve() if authority_root else Path(root).resolve(),
                expected_root, request.unit_id,
                contracts, policy_records,
            )
            allowed.add(SHARED_PAIRED_EVIDENCE_DIRECTORY)
        unexpected = [path.name for path in expected_root.iterdir() if path.name not in allowed]
        if unexpected:
            raise G08Error(f"G08_STALE_OUTPUT_COLLISION:{sorted(unexpected)}")


def consume_scientific_authorization(
    project_root: Path,
    request: g07.ProductionExecutionRequest | None,
) -> Mapping[str, object]:
    root = Path(project_root).resolve()
    if not isinstance(request, g07.ProductionExecutionRequest):
        raise G08Error("G08_PRODUCTION_REQUEST_REQUIRED")
    payload = _load_committed_authorization(root)
    plan, contracts = governed_plan(root)
    policies, policy_records, _ = governed_policy_universe(root, contracts)
    dependency_graph_payload(contracts, policy_records)
    executable = tuple(
        item.unit_id for item in plan
        if item.disposition is g07.DispatchDisposition.EXECUTABLE
    )
    if request.unit_id not in executable:
        raise G08Error("G08_UNIT_NOT_AUTHORIZED")
    policy_matches = [
        policy for policy, record in zip(policies, policy_records)
        if record["unit_id"] == request.unit_id
    ]
    if len(policy_matches) != 1:
        raise G08Error("G08_REQUEST_POLICY_IDENTITY")
    g07_v2.validate_policy(policy_matches[0])
    readiness = audit_real_inputs(root, plan, contracts)
    blocking = [item for item in readiness if item["status"] == "BLOCKING"]
    if blocking:
        raise G08Error("G08_REAL_INPUTS_NOT_READY")
    identity = build_parent_execution_identity(
        root, str(payload["authorization_parent_commit"]), plan, contracts
    )
    receipt = validate_authorization_payload(payload, identity)
    _validate_output_collision(
        root, request, executable, contracts=contracts, policy_records=policy_records
    )
    return receipt


__all__ = (
    "GATE_VERSION", "SCHEMA_VERSION", "EXECUTION_IDENTITY_SCHEMA_VERSION",
    "AUTHORIZATION_SCHEMA_NAME", "ACCEPTED_G07_COMMIT",
    "ACCEPTED_G07_IMPLEMENTATION_COMMIT", "INDEPENDENT_G07_ACCEPTANCE_COMMIT",
    "ACCEPTED_G07_RUNTIME_SHA256", "ACCEPTED_G07_POLICY_SHA256",
    "CORRECTION2_ACCEPTED_G08_V2_IMPLEMENTATION_COMMIT",
    "CORRECTION2_INDEPENDENT_G08_V2_ACCEPTANCE_COMMIT",
    "CORRECTION2_G08_V2_ACCEPTANCE_PATHS",
    "CORRECTION2_G08_V2_ACCEPTANCE_ARTIFACT_SHA256",
    "CORRECTION2_G08_V2_ACCEPTANCE_AGGREGATE_SHA256",
    "CORRECTION4_BASE_COMMIT", "CORRECTION4_IMPLEMENTATION_PATHS",
    "CORRECTION5_BASE_COMMIT", "CORRECTION5_IMPLEMENTATION_PATHS",
    "CORRECTION5_IMPLEMENTATION_TEST_PATH", "G08_V2_ACCEPTANCE_PATHS",
    "CORRECTION6_BASE_COMMIT", "CORRECTION6_IMPLEMENTATION_PATHS",
    "CORRECTION6_IMPLEMENTATION_TEST_PATH",
    "AUTHORITY_LINEAGE_CORRECTION_IMPLEMENTATION_COMMIT",
    "AUTHORITY_LINEAGE_CORRECTION_ACCEPTANCE_COMMIT",
    "AUTHORITY_LINEAGE_CORRECTION_ACTIVATION_COMMIT",
    "DOWNSTREAM_G06_G07_CORRECTION_COMMIT",
    "DOWNSTREAM_G06_G07_ACCEPTANCE_COMMIT",
    "DOWNSTREAM_G06_G07_CORRECTION_PATHS",
    "DOWNSTREAM_G06_G07_ACCEPTANCE_PATHS",
    "DOWNSTREAM_G06_G07_CORRECTION_SHA256",
    "DOWNSTREAM_G06_G07_ACCEPTANCE_SHA256",
    "DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_IMPLEMENTATION_PATHS",
    "DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_ACCEPTANCE_PATHS",
    "DOWNSTREAM_AUTHORITY_LINEAGE_EXTENSION_TEST_PATH",
    "GOVERNED_TRANSITION_CORRECTION_BASE_COMMIT",
    "GOVERNED_TRANSITION_REGISTRY_RELATIVE",
    "GOVERNED_TRANSITION_REGISTRY_SCHEMA",
    "GOVERNED_TRANSITION_CORRECTION_TEST_PATH",
    "GOVERNED_TRANSITION_CORRECTION_IMPLEMENTATION_PATHS",
    "GOVERNED_TRANSITION_CORRECTION_ACCEPTANCE_PATHS",
    "GOVERNED_TRANSITION_GATE_NAME",
    "GOVERNED_SUCCESSOR_SCOPE_CORRECTION_BASE_COMMIT",
    "GOVERNED_SUCCESSOR_SCOPE_CORRECTION_TEST_PATH",
    "GOVERNED_SUCCESSOR_SCOPE_CORRECTION_IMPLEMENTATION_PATHS",
    "GOVERNED_SUCCESSOR_SCOPE_CORRECTION_ACCEPTANCE_PATHS",
    "GOVERNED_SUCCESSOR_SCOPE_GATE_NAME",
    "GOVERNED_CORRECTION_LINEAGE_TEST_PATH",
    "GOVERNED_CORRECTION_LINEAGE_IMPLEMENTATION_PATHS",
    "GOVERNED_CORRECTION_LINEAGE_ACCEPTANCE_PATHS",
    "GOVERNED_CORRECTION_LINEAGE_GATE_NAME",
    "TRUSTED_IMPLEMENTATION_CONFIG_KEY", "TRUSTED_ACCEPTANCE_CONFIG_KEY",
    "REQUIRED_CORRECTION5_IMPLEMENTATION_TEST_IDS",
    "REQUIRED_CORRECTION5_INDEPENDENT_TEST_IDS",
    "REQUIRED_CORRECTION6_IMPLEMENTATION_TEST_IDS",
    "REQUIRED_CORRECTION6_INDEPENDENT_TEST_IDS",
    "ISSUE_STATUS_SEMANTICS", "ISSUE_STATUS_CLOSED_OR_RESOLVED",
    "ISSUE_STATUS_DOCUMENTED_NONBLOCKING", "ISSUE_STATUS_ALLOWLIST",
    "ISSUE_STATUS_KNOWN_BLOCKING", "ISSUE_CLOSED_ALLOWED_SEVERITIES",
    "ISSUE_NONBLOCKING_ALLOWED_SEVERITIES",
    "PRODUCTION_OUTPUT_ROOT_RELATIVE", "SUITE_RUN_ID",
    "V1_OUTPUT_ROOT_RELATIVE", "V1_SUITE_RUN_ID",
    "ACTIVE_AUTHORIZATION_RELATIVE", "INDEPENDENT_GATE_RELATIVE",
    "G08Error", "ExecutionContextIdentity", "canonical_json", "sha256_bytes",
    "sha256_file", "validate_bound_blob_bytes", "validate_g07_acceptance_payloads",
    "validate_g08_v2_acceptance_payloads",
    "correction2_g08_v2_acceptance_identity",
    "validate_correction5_implementation_test_payload",
    "correction5_implementation_test_result", "operator_g08_trust_pins",
    "validate_correction6_implementation_test_payload",
    "correction6_implementation_test_result", "classify_g08_acceptance_issue",
    "validate_current_g08_v2_acceptance_payloads",
    "validate_accepted_downstream_authority_payloads",
    "validate_accepted_downstream_authority_lineage",
    "validate_governed_downstream_transition",
    "validate_governed_downstream_transition_sequence",
    "governed_transition_correction_implementation_test_result",
    "governed_successor_scope_correction_implementation_test_result",
    "governed_correction_lineage_implementation_test_result",
    "validate_g08_implementation_lineage",
    "g08_v2_acceptance_authority", "g08_v2_acceptance_identity",
    "repository_authority", "governed_plan", "plan_summary",
    "governed_policy_universe", "validate_policy_records",
    "dependency_graph_payload", "validate_dependency_graph",
    "v2_evidence_lifecycle_identity", "validate_v2_evidence_lifecycle_identity",
    "validate_v2_namespace", "validate_execution_universe_entries",
    "real_input_aggregate_identity", "audit_real_inputs",
    "production_configuration_payload", "environment_payload",
    "output_root_readiness", "execution_universe_identity",
    "build_execution_identity", "build_parent_execution_identity",
    "PERMITTED_ACTIVATION_PATHS", "deterministic_unit_run_id",
    "expected_authorization_payload", "validate_authorization_payload",
    "validate_activation_metadata", "validate_committed_activation",
    "consume_scientific_authorization",
)
