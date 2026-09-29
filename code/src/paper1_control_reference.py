"""Explicit historical reference preparation and selection, independent of releases.

This is candidate governance, not G08 activation. Preparation reuses the retained
legacy proof algorithms under an explicit historic anchor set. Runtime selection
requires a separately supplied bundle digest, never the bundle's own assertion.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time


class ReferenceError(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@dataclass
class Preparation:
    root: Path
    anchors: dict
    cache: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    hits: int = 0

    def query(self, root, args, binary):
        if Path(root).resolve() != self.root:
            raise ReferenceError('REFERENCE_REPOSITORY_MISMATCH')
        # This preparation context cannot be used to issue mutable commands.
        if args[0] not in {'rev-parse', 'rev-list', 'merge-base', 'diff-tree', 'show', 'ls-tree', 'cat-file', 'diff'}:
            raise ReferenceError('REFERENCE_NONIMMUTABLE_QUERY')
        if args[0] == 'diff' and (len(args) != 6 or args[1:4] != ('--no-renames', '--name-only', '-z')
                                  or any(not re.fullmatch('[0-9a-f]{40}', a) for a in args[4:])):
            raise ReferenceError('REFERENCE_NONIMMUTABLE_DIFF')
        args = tuple(arg.replace('HEAD', self.anchors['head']) for arg in args)
        key = (args, binary)
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        self.calls[args[0]] = self.calls.get(args[0], 0) + 1
        result = subprocess.run(['git', *args], cwd=self.root, capture_output=True)
        if result.returncode:
            raise ReferenceError('REFERENCE_GIT_QUERY_REJECTED:' + repr(args))
        value = result.stdout if binary else result.stdout.decode('utf-8').strip()
        self.cache[key] = value
        return value


_preparation = ContextVar('paper1_reference_preparation', default=None)
_selection = ContextVar('paper1_reference_selection', default=None)


def preparation(root):
    item = _preparation.get()
    if item is not None and Path(root).resolve() != item.root:
        raise ReferenceError('REFERENCE_REPOSITORY_MISMATCH')
    return item


def selected(root):
    item = _selection.get()
    if item is not None and Path(root).resolve() != item.root:
        raise ReferenceError('REFERENCE_REPOSITORY_MISMATCH')
    return item


def prepare_reference(root, anchors, evidence_inventory):
    """Produce a review bundle; this does not select or independently accept it."""
    from src import paper1_g07_runtime as g07, paper1_g08_runtime as g08
    root = Path(root).resolve()
    if set(anchors) != {'head', 'implementation', 'acceptance', 'bridge'} or any(
        not re.fullmatch('[0-9a-f]{40}', str(x)) for x in anchors.values()
    ):
        raise ReferenceError('REFERENCE_ANCHOR_SCHEMA')
    if _preparation.get() or _selection.get():
        raise ReferenceError('REFERENCE_NESTED_PREPARATION')
    started = time.perf_counter()
    prep = Preparation(root, dict(anchors))
    token = _preparation.set(prep)
    try:
        if prep.query(root, ('rev-parse', anchors['head'] + '^{commit}'), False) != anchors['head']:
            raise ReferenceError('REFERENCE_HEAD')
        producers, edges = set(), set()
        for record in evidence_inventory:
            path = root / record['path']
            if path.resolve().is_relative_to(root) is False or digest(path) != record['sha256']:
                raise ReferenceError('REFERENCE_INPUT_IDENTITY')
            if path.parent.name != 'checkpoints' or path.parent.parent.parent.name != 'g07_scientific_execution_v2':
                continue
            payload = json.loads(path.read_bytes())['payload']
            producers.add(payload['source_commit'])
            migration = payload.get('resume_identity_migration')
            if migration:
                edges.add((migration['historical_source_commit'], migration['current_source_commit']))
        proofs = {p: dict(g08.validate_evidence_producer_activation(root, p)) for p in sorted(producers)}
        migrations = {'|'.join(edge): dict(g07._read_migration_authority(root, *edge))
                      for edge in sorted(edges)}
        # Every persisted occurrence must equal the reconstructed edge, not its own hash.
        for record in evidence_inventory:
            path = root / record['path']
            if path.parent.name == 'checkpoints' and path.parent.parent.parent.name == 'g07_scientific_execution_v2':
                body = json.loads((root / record['path']).read_bytes())['payload']
                migration = body.get('resume_identity_migration')
                if migration and migration['authority_transition'] != migrations['|'.join((
                    migration['historical_source_commit'], migration['current_source_commit']))]:
                    raise ReferenceError('REFERENCE_PERSISTED_MIGRATION_MISMATCH')
        return {'schema': 'PAPER1_SELECTED_HISTORICAL_REFERENCE_V1', 'anchors': dict(anchors),
                'producer_proofs': proofs, 'migration_proofs': migrations,
                'evidence_inventory': evidence_inventory,
                'preparation': {'elapsed_seconds': time.perf_counter() - started,
                                'git_calls': prep.calls, 'query_cache_hits': prep.hits,
                                'proof_basis': 'Retained G08 producer and G07 migration reconstruction under explicit historical anchors'}}
    finally:
        _preparation.reset(token)


class SelectedReference:
    def __init__(self, root, path, selected_sha256):
        self.root, self.path = Path(root).resolve(), Path(path).resolve()
        if not selected_sha256 or digest(self.path) != selected_sha256:
            raise ReferenceError('REFERENCE_SELECTION_MISMATCH')
        self.selected_sha256 = selected_sha256
        self.payload = json.loads(self.path.read_bytes())
        if self.payload.get('schema') != 'PAPER1_SELECTED_HISTORICAL_REFERENCE_V1':
            raise ReferenceError('REFERENCE_SCHEMA')
        records = self.payload['evidence_inventory']
        self.records = {r['path']: r for r in records}
        if len(self.records) != len(records):
            raise ReferenceError('REFERENCE_DUPLICATE_PATH')
        self.reads = 0

    def check_selection(self):
        if digest(self.path) != self.selected_sha256:
            raise ReferenceError('REFERENCE_CHANGED')
        original = json.loads(self.path.read_bytes())
        if original != self.payload or self.records != {r['path']: r for r in original['evidence_inventory']}:
            raise ReferenceError('REFERENCE_IN_MEMORY_CHANGED')

    def verify_file(self, path):
        self.check_selection()
        resolved = Path(path).resolve()
        if not resolved.is_relative_to(self.root) or Path(path).is_symlink():
            raise ReferenceError('REFERENCE_PATH_ESCAPE')
        relative = resolved.relative_to(self.root).as_posix()
        record = self.records.get(relative)
        self.reads += 1
        if record is None or resolved.stat().st_size != record['size'] or digest(resolved) != record['sha256']:
            raise ReferenceError('REFERENCE_EVIDENCE_MISMATCH:' + relative)

    def producer(self, source):
        self.check_selection()
        if source not in self.payload['producer_proofs']:
            raise ReferenceError('REFERENCE_PRODUCER_NOT_SELECTED')
        proof = self.payload['producer_proofs'][source]
        if proof.get('source_commit') != source or proof.get('execution_authorized') is not False:
            raise ReferenceError('REFERENCE_PRODUCER_CLAIM')
        return deepcopy(proof)

    def migration(self, old, new):
        self.producer(old)
        self.producer(new)
        key = old + '|' + new
        if key not in self.payload['migration_proofs']:
            raise ReferenceError('REFERENCE_MIGRATION_NOT_SELECTED')
        return deepcopy(self.payload['migration_proofs'][key])

    @contextmanager
    def use(self):
        if _selection.get() or _preparation.get():
            raise ReferenceError('REFERENCE_NESTED_SELECTION')
        self.check_selection()
        token = _selection.set(self)
        try:
            yield self
        finally:
            _selection.reset(token)
