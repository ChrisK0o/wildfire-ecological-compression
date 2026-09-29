"""TEST-ONLY selected release validation for the isolated structural candidate.

This proposes replacing routine approval-chain reconstruction. It does not
activate G08, change pins, authorize fits, or independently accept this candidate.
The caller supplies the selected digest separately from the release document.
"""
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from enum import Enum
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from src.paper1_control_reference import canonical, digest, SelectedReference


class ReleaseError(RuntimeError):
    pass


def plain(value):
    if is_dataclass(value):
        return plain(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, 'items'):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def identity(value):
    return hashlib.sha256(canonical(plain(value))).hexdigest()


def environment():
    return {'executable': str(Path(sys.executable).resolve()),
            'python': platform.python_version(), 'platform': platform.platform(),
            'conda_prefix': os.environ.get('CONDA_PREFIX'),
            'conda_env': os.environ.get('CONDA_DEFAULT_ENV'),
            'packages': dict(sorted((d.metadata['Name'].lower(), d.version)
                                    for d in importlib.metadata.distributions()
                                    if d.metadata.get('Name')))}


def git_head(root):
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root, check=True,
                          capture_output=True).stdout.decode().strip()


def relative_file(root, relative):
    path = root / relative
    if Path(relative).is_absolute() or '..' in Path(relative).parts or not path.resolve().is_relative_to(root):
        raise ReleaseError('RELEASE_PATH_ESCAPE')
    if path.is_symlink() or not path.is_file():
        raise ReleaseError('RELEASE_FILE_UNAVAILABLE:' + relative)
    return path


def source_inventory(root):
    paths = subprocess.run(['git', 'ls-files', '-z'], cwd=root, check=True,
                           capture_output=True).stdout.decode().split('\0')
    paths = {p for p in paths if p and not p.startswith('data/')}
    # Include new candidate source, not only files tracked by the old release.
    paths.update(p.relative_to(root).as_posix() for p in (root / 'src').glob('*.py'))
    return {p: digest(relative_file(root, p)) for p in sorted(paths)}


def prepare_release(root, output, reference, units, contracts, policies):
    """Generate a review document, not self-selection or an acceptance record."""
    root, output = Path(root).resolve(), Path(output).resolve()
    if output != root / 'data/processed/propagation/paper1/candidate_control_finalization':
        raise ReleaseError('RELEASE_OUTPUT_SCOPE')
    reference.check_selection()
    if reference.root != root or not units or len(units) != len(set(units)):
        raise ReleaseError('RELEASE_REQUEST_SCOPE')
    inputs = {}
    for contract in contracts:
        for field in ('predictor', 'response', 'support'):
            path, expected = getattr(contract, field + '_path'), getattr(contract, field + '_sha256')
            if (not path and not expected and contract.execution_enabled is False
                    and contract.model_family == 'DISABLED'):
                continue
            if digest(relative_file(root, path)) != expected:
                raise ReleaseError('RELEASE_INPUT_IDENTITY:' + path)
            inputs[path] = expected
    return {'schema': 'PAPER1_CANDIDATE_RELEASE_V1', 'mode': 'TEST_ONLY_NO_FIT',
            'repository': str(root), 'output': str(output), 'units': list(units),
            'git_head': git_head(root),
            'reference_sha256': reference.selected_sha256,
            'sources': source_inventory(root), 'inputs': inputs,
            'environment': environment(), 'contracts_sha256': identity(contracts),
            'policies_sha256': identity(policies)}


class SelectedRelease:
    def __init__(self, root, path, selected_sha256, reference):
        self.root, self.path = Path(root).resolve(), Path(path).resolve()
        if not selected_sha256 or digest(self.path) != selected_sha256:
            raise ReleaseError('RELEASE_SELECTION_MISMATCH')
        self.sha256 = selected_sha256
        self.payload = json.loads(self.path.read_bytes())
        self.reference = reference
        if (self.payload.get('schema') != 'PAPER1_CANDIDATE_RELEASE_V1'
                or self.payload.get('mode') != 'TEST_ONLY_NO_FIT'
                or self.payload.get('repository') != str(self.root)
                or self.payload.get('reference_sha256') != reference.selected_sha256
                or reference.root != self.root):
            raise ReleaseError('RELEASE_SELECTION_BINDING')

    def check(self, unit, output, *, contracts=None, policies=None):
        if digest(self.path) != self.sha256:
            raise ReleaseError('RELEASE_CHANGED')
        if json.loads(self.path.read_bytes()) != self.payload:
            raise ReleaseError('RELEASE_IN_MEMORY_CHANGED')
        if git_head(self.root) != self.payload['git_head']:
            raise ReleaseError('RELEASE_HEAD_CHANGED')
        self.reference.check_selection()
        if unit not in self.payload['units']:
            raise ReleaseError('RELEASE_UNIT_NOT_SELECTED')
        output = Path(output).resolve()
        if (str(output) != self.payload['output'] or
                output != self.root / 'data/processed/propagation/paper1/candidate_control_finalization'):
            raise ReleaseError('RELEASE_OUTPUT_SCOPE')
        if source_inventory(self.root) != self.payload['sources']:
            raise ReleaseError('RELEASE_CODE_CONFIG_CHANGED')
        if environment() != self.payload['environment']:
            raise ReleaseError('RELEASE_ENVIRONMENT_CHANGED')
        for path, expected in self.payload['inputs'].items():
            if digest(relative_file(self.root, path)) != expected:
                raise ReleaseError('RELEASE_INPUT_CHANGED:' + path)
        if contracts is not None and identity(contracts) != self.payload['contracts_sha256']:
            raise ReleaseError('RELEASE_CONTRACT_CHANGED')
        if policies is not None and identity(policies) != self.payload['policies_sha256']:
            raise ReleaseError('RELEASE_POLICY_CHANGED')
        return {'release_sha256': self.sha256, 'mode': 'TEST_ONLY_NO_FIT'}
