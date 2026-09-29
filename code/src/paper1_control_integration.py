"""Selected future-execution descriptor and explicit no-dispatch control consumer.

This candidate interface has no activation or scientific handler invocation. A
future production selection needs separate review and adoption; a dry selection
cannot grant that authority. Old control producers retain their exact identities.
"""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from types import SimpleNamespace

from src import paper1_g07_runtime as g07, paper1_g08_runtime as g08
from src import paper1_control_finalization as final
from src.paper1_control_reference import canonical, digest
from src.paper1_control_release import (
    SelectedRelease, ReleaseError, environment, git_head, identity, plain,
    prepare_release, relative_file, source_inventory,
)

SCHEMA = 'PAPER1_EXECUTION_RELEASE_V1'
DRY_MODE = 'DRY_RUN_NO_DISPATCH'
THREAD_ENV = (
    'OMP_NUM_THREADS', 'OMP_THREAD_LIMIT', 'OMP_DYNAMIC', 'OMP_MAX_ACTIVE_LEVELS',
    'OPENBLAS_NUM_THREADS', 'OPENBLAS_CORETYPE', 'GOTO_NUM_THREADS',
    'MKL_NUM_THREADS', 'MKL_DYNAMIC', 'MKL_CBWR', 'BLIS_NUM_THREADS',
    'VECLIB_MAXIMUM_THREADS', 'NPY_DISABLE_CPU_FEATURES', 'KMP_DUPLICATE_LIB_OK',
)


class IntegrationError(RuntimeError):
    pass


class DispatchBoundaryReached(RuntimeError):
    """Intent recorded; raised before any scientific handler/model construction."""
    def __init__(self, record):
        self.record = record
        super().__init__('DRY_RUN_STOP_BEFORE_SCIENTIFIC_DISPATCH')


def numerical_runtime():
    # Import the actual fit-path libraries, but never construct or fit a model.
    import scipy.linalg  # noqa: F401
    import sklearn.ensemble  # noqa: F401
    import statsmodels.api  # noqa: F401
    from threadpoolctl import threadpool_info
    previous = None
    for _ in range(4):
        current = sorted(threadpool_info(), key=lambda p: p['filepath'])
        if current == previous:
            break
        previous = current
    else:
        raise ReleaseError('RELEASE_NUMERICAL_DISCOVERY_UNSTABLE')
    # MKL introspection can itself load OpenMP. Bind the stabilized full set,
    # not the incomplete first enumeration; never omit a discovered library.
    pools = []
    for pool in current:
        record = dict(pool)
        record['library_sha256'] = digest(Path(record['filepath']))
        pools.append(record)
    return {'thread_control_environment': {k: os.environ.get(k) for k in THREAD_ENV},
            'loaded_pools': sorted(pools, key=lambda p: p['filepath']),
            'fit_configuration': plain(g07.SCIENTIFIC_CONFIGURATION)}


def declared_inputs(contracts):
    result = {}
    for c in contracts:
        for field in ('predictor', 'response', 'support'):
            path, sha = getattr(c, field + '_path'), getattr(c, field + '_sha256')
            if not path and not sha and c.execution_enabled is False and c.model_family == 'DISABLED':
                continue
            if not path or not sha or (path in result and result[path] != sha):
                raise ReleaseError('EXECUTION_INPUT_SCHEMA')
            result[path] = sha
    return result


def prepare_execution_release(root, output, reference, units, contracts, policies,
                              plan, requested_units, prior_release_path,
                              prior_release_digest, prior_control_root):
    """Reviewable production-capable descriptor; creation is NOT selection."""
    root, output = Path(root).resolve(), Path(output).resolve()
    legacy_output = root / 'data/processed/propagation/paper1/candidate_control_finalization'
    payload = prepare_release(root, legacy_output, reference, units, contracts, policies)
    if output == legacy_output or not output.is_relative_to(root / 'data/processed/propagation/paper1'):
        raise ReleaseError('EXECUTION_CONTROL_DESTINATION')
    prior_path = Path(prior_release_path).resolve()
    if digest(prior_path) != prior_release_digest:
        raise ReleaseError('EXECUTION_PRIOR_SELECTION')
    prior = json.loads(prior_path.read_bytes())
    if (prior.get('mode') != 'TEST_ONLY_NO_FIT' or prior.get('reference_sha256') != reference.selected_sha256
            or set(prior.get('units', ())) != set(units)
            or prior.get('contracts_sha256') != identity(contracts)
            or prior.get('policies_sha256') != identity(policies)):
        raise ReleaseError('EXECUTION_PRIOR_PRODUCER_BINDING')
    requested_units = list(requested_units)
    known = {e.unit_id for e in plan if e.disposition is g07.DispatchDisposition.EXECUTABLE}
    if not requested_units or len(set(requested_units)) != len(requested_units) or not set(requested_units) <= known:
        raise ReleaseError('EXECUTION_REQUEST_SCOPE')
    payload.update(schema=SCHEMA, mode=DRY_MODE, output=str(output),
                   production_output=str(root / g08.PRODUCTION_OUTPUT_ROOT_RELATIVE),
                   requested_units=requested_units, plan_sha256=identity(plan),
                   numerical_runtime=numerical_runtime(),
                   prior_control_producer={'release_path': str(prior_path),
                                           'release_sha256': prior_release_digest,
                                           'control_root': str(Path(prior_control_root).resolve())})
    return payload


class ExecutionRelease(SelectedRelease):
    """Separately selected descriptor; not a generic authorization capability."""
    def __init__(self, root, path, selected_sha256, reference):
        self.root, self.path = Path(root).resolve(), Path(path).resolve()
        self.reference, self.sha256 = reference, selected_sha256
        if not selected_sha256 or digest(self.path) != selected_sha256:
            raise ReleaseError('RELEASE_SELECTION_MISMATCH')
        self.payload = json.loads(self.path.read_bytes())
        if (self.payload.get('schema') != SCHEMA
                or self.payload.get('mode') not in {DRY_MODE, 'FUTURE_PRODUCTION_RELEASE'}
                or self.payload.get('repository') != str(self.root)
                or self.payload.get('reference_sha256') != reference.selected_sha256
                or reference.root != self.root):
            raise ReleaseError('RELEASE_SELECTION_BINDING')

    def check(self, unit, output, *, contracts=None, policies=None, plan=None):
        if digest(self.path) != self.sha256:
            raise ReleaseError('RELEASE_CHANGED')
        if json.loads(self.path.read_bytes()) != self.payload:
            raise ReleaseError('RELEASE_IN_MEMORY_CHANGED')
        p = self.payload
        self.reference.check_selection()
        if git_head(self.root) != p['git_head']:
            raise ReleaseError('RELEASE_HEAD_CHANGED')
        if unit not in p['units'] and unit not in p['requested_units']:
            raise ReleaseError('RELEASE_UNIT_NOT_SELECTED')
        output = Path(output).resolve()
        if (str(output) != p['output'] or not output.is_relative_to(self.root / 'data/processed/propagation/paper1')
                or str(self.root / g08.PRODUCTION_OUTPUT_ROOT_RELATIVE) != p['production_output']
                or output == Path(p['production_output'])):
            raise ReleaseError('RELEASE_OUTPUT_SCOPE')
        if source_inventory(self.root) != p['sources']:
            raise ReleaseError('RELEASE_CODE_CONFIG_CHANGED')
        if environment() != p['environment']:
            raise ReleaseError('RELEASE_ENVIRONMENT_CHANGED')
        if numerical_runtime() != p['numerical_runtime']:
            raise ReleaseError('RELEASE_NUMERICAL_RUNTIME_CHANGED')
        for path, expected in p['inputs'].items():
            if digest(relative_file(self.root, path)) != expected:
                raise ReleaseError('RELEASE_INPUT_CHANGED:' + path)
        if contracts is not None and (identity(contracts) != p['contracts_sha256']
                                      or declared_inputs(contracts) != p['inputs']):
            raise ReleaseError('RELEASE_CONTRACT_CHANGED')
        if policies is not None and identity(policies) != p['policies_sha256']:
            raise ReleaseError('RELEASE_POLICY_CHANGED')
        if plan is not None and identity(plan) != p['plan_sha256']:
            raise ReleaseError('RELEASE_PLAN_CHANGED')
        old = p['prior_control_producer']
        if digest(Path(old['release_path'])) != old['release_sha256']:
            raise ReleaseError('EXECUTION_PRIOR_SELECTION')
        return {'release_sha256': self.sha256, 'mode': p['mode']}


def consume_control(output, producer_sha256, proof):
    """New control format ONLY. Partial writes are recoverable, not completed."""
    output = Path(output).resolve()
    expected = deepcopy(proof)
    expected['release_sha256'] = producer_sha256
    files, pointers = final.expected_outputs(SimpleNamespace(sha256=producer_sha256), expected)
    final.verify_existing(output, files, pointers)
    for relative, raw in files.items():
        path = output / relative
        if not path.is_file() or path.read_bytes() != raw:
            raise IntegrationError('CONTROL_MISSING_OR_INVALID_CHECKPOINT')
    completed = {}
    for source in expected['sources']:
        pointer = output / source['run_id'] / 'checkpoint.current.json'
        if not pointer.is_file():
            raise IntegrationError('CONTROL_POINTER_MISSING_RECOVERY_REQUIRED')
        if pointer.read_bytes() != pointers[(source['run_id'], 'COMPLETE')]:
            raise IntegrationError('CONTROL_POINTER_REGRESSED_OR_PARTIAL')
        completed[source['unit_id']] = {'format': 'PAPER1_CANDIDATE_FINALIZATION_CHECKPOINT_V1',
                                      'producer_release_sha256': producer_sha256,
                                      'pointer_sha256': digest(pointer)}
    return completed


def derive_next(root, reference, plan, completed_controls):
    """Use actual plan order and immutable historical records, never ordinal literals."""
    history = root / g08.PRODUCTION_OUTPUT_ROOT_RELATIVE
    completed, pending, staged = [], [], []
    known_runs = {g08.deterministic_unit_run_id(e.unit_id) for e in plan}
    for path in history.iterdir():
        if path.name.startswith('PAPER1_G07_') and path.name not in known_runs:
            raise IntegrationError('UNKNOWN_HISTORICAL_RUN')
    from contextlib import nullcontext
    from src.paper1_control_execution import active_operation
    operation=active_operation(root)
    # Historical pointers use their selected immutable inventory. New outputs
    # use their own committed producer/release identity, never the old bundle.
    with nullcontext():
        for ordinal, entry in enumerate(plan, 1):
            run = history / g08.deterministic_unit_run_id(entry.unit_id)
            if run.exists():
                historical=(run/'checkpoint.current.json').relative_to(root).as_posix() in reference.records
                if not historical and operation is None:
                    raise IntegrationError('UNSELECTED_NEW_OUTPUT')
                with reference.use() if historical else nullcontext():
                    state = g07._reopen_production_state(run, root)
                    if historical:
                        reference.producer(state['source_commit'])
                    else:
                        operation.producer(state['source_commit'])
                if (state['identity']['unit_id'] != entry.unit_id
                        or state['identity']['run_id'] != run.name):
                    raise IntegrationError('HISTORICAL_UNIT_IDENTITY')
                if entry.unit_id in completed_controls:
                    completed.append({'ordinal': ordinal, 'unit_id': entry.unit_id,
                                      'completion': completed_controls[entry.unit_id]})
                    continue
                if state['current_phase'] == 'COMPLETE' and state['terminal_disposition'] == 'COMPLETE':
                    completed.append({'ordinal': ordinal, 'unit_id': entry.unit_id,
                                      'completion': {'format': 'HISTORICAL_G07' if historical else 'SELECTED_RELEASE_G07',
                                                     'source_commit': state['source_commit']}})
                    continue
                if not historical:
                    if operation.awaiting_pair(entry,state):
                        staged.append({'ordinal':ordinal,'unit_id':entry.unit_id,
                                       'phase':state['current_phase'],'terminal':False})
                    else:
                        pending.append((ordinal,entry))
                    continue
                raise IntegrationError('UNRECOVERED_HISTORICAL_UNIT:' + entry.unit_id)
            if entry.unit_id in completed_controls:
                raise IntegrationError('CONTROL_WITHOUT_HISTORICAL_SOURCE')
            if entry.disposition is g07.DispatchDisposition.EXECUTABLE:
                pending.append((ordinal, entry))
            elif entry.disposition is not g07.DispatchDisposition.DISABLED:
                # Do not erase blocked/nonestimable lifecycle work ahead of execution.
                pending.append((ordinal, entry))
    if not pending:
        raise IntegrationError('NO_NEXT_REGISTERED_UNIT')
    ordinal, entry = pending[0]
    if entry.disposition is not g07.DispatchDisposition.EXECUTABLE:
        raise IntegrationError('NEXT_UNIT_REQUIRES_NONEXECUTION_LIFECYCLE')
    return {'ordinal': ordinal, 'unit': plain(entry),
            'run_id': g08.deterministic_unit_run_id(entry.unit_id),
            'completed': completed, 'staged_pending_group': staged}


def dispatch_boundary(release, derived, requested_unit):
    if requested_unit != derived['unit']['unit_id'] or requested_unit not in release.payload['requested_units']:
        raise IntegrationError('DISPATCH_NOT_DERIVED_NEXT_UNIT')
    if release.payload['mode'] != DRY_MODE:
        raise IntegrationError('REAL_ADOPTION_NOT_IMPLEMENTED_OR_AUTHORIZED')
    raise DispatchBoundaryReached(derived)


def dry_run_next(release, recovery_unit, output, requested_unit, *, interrupt_after=None):
    """Public integration entry. No fallback to run_scientific or legacy activation."""
    if not isinstance(release, ExecutionRelease) or release.payload['mode'] != DRY_MODE:
        raise IntegrationError('DRY_SELECTION_REQUIRED')
    with final.no_new_predictions():
        result = final.finalize(release, recovery_unit, output, interrupt_after=interrupt_after)
        proof = result['verification']
        old = release.payload['prior_control_producer']
        consume_control(old['control_root'], old['release_sha256'], proof)
        completed = consume_control(output, release.sha256, proof)
        plan, contracts = g08.governed_plan(release.root)
        _, policies, _ = g08.governed_policy_universe(release.root, contracts)
        release.check(requested_unit, output, contracts=contracts, policies=policies, plan=plan)
        final.verify_reference_files(release.reference)
        derived = derive_next(release.root, release.reference, plan, completed)
        derived.update(recovery=result, models_fit=0, predictions_generated=0,
                       scientific_dispatch_count=0, release_sha256=release.sha256)
        # Reopen control and science bytes at consumption, not just at recovery.
        consume_control(output, release.sha256, proof)
        final.verify_reference_files(release.reference)
        release.check(requested_unit, output)
        dispatch_boundary(release, derived, requested_unit)
