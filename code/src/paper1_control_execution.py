"""Selected-release adapter for the retained G07 executor; no legacy activation.

TEST_ONLY selections can enter only the raising pre-handler preview. Historical
reference proofs never identify the producer of new scientific output.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict
import json
from pathlib import Path
import subprocess

from src import paper1_g07_runtime as g07, paper1_g08_runtime as g08
from src import paper1_control_integration as integration
from src.paper1_control_reference import SelectedReference, canonical, digest
from src.paper1_control_release import ReleaseError, environment, git_head, identity, source_inventory

SCHEMA = 'PAPER1_SELECTED_EXECUTOR_V1'
TEST_MODE = 'TEST_ONLY_PRE_HANDLER'
PRODUCTION_MODE = 'PRODUCTION_EXECUTION'
_operation = ContextVar('paper1_selected_execution', default=None)


def active_operation(root):
    operation = _operation.get()
    if operation is not None and operation.release.root != Path(root).resolve():
        raise ReleaseError('EXECUTOR_ROOT_MISMATCH')
    return operation


def committed_source(root):
    if subprocess.run(['git', 'status', '--porcelain', '--untracked-files=no'],
                      cwd=root, capture_output=True, check=True).stdout.strip():
        raise ReleaseError('EXECUTOR_COMMITTED_SOURCE_REQUIRED')
    tracked = set(subprocess.run(['git', 'ls-files', '-z'], cwd=root,
        capture_output=True, check=True).stdout.decode().split('\0'))
    if any(p.relative_to(root).as_posix() not in tracked for p in (root/'src').glob('*.py')):
        raise ReleaseError('EXECUTOR_UNCOMMITTED_SOURCE')


def prepare(root, reference, plan, contracts, policies, requested_units, recovery_root):
    """Review material only; an external digest must separately select it."""
    root, recovery_root = Path(root).resolve(), Path(recovery_root).resolve()
    committed_source(root)
    reference.check_selection()
    publication = json.loads((recovery_root/'publication.json').read_bytes())
    proof = publication['verification']
    producer = proof['release_sha256']
    completed = integration.consume_control(recovery_root, producer, proof)
    derived = integration.derive_next(root, reference, plan, completed)
    executable = {e.unit_id for e in plan if e.disposition is g07.DispatchDisposition.EXECUTABLE}
    if not requested_units or not set(requested_units) <= executable:
        raise ReleaseError('EXECUTOR_SCOPE')
    inputs = integration.declared_inputs(contracts)
    for path, sha in inputs.items():
        if digest(root/path) != sha:
            raise ReleaseError('EXECUTOR_INPUT')
    return dict(schema=SCHEMA, mode=TEST_MODE, repository=str(root), git_head=git_head(root),
        reference_sha256=reference.selected_sha256, sources=source_inventory(root),
        environment=environment(), numerical_runtime=integration.numerical_runtime(),
        contracts_sha256=identity(contracts), policies_sha256=identity(policies),
        plan_sha256=identity(plan), inputs=inputs, requested_units=list(requested_units),
        output=str(root/g08.PRODUCTION_OUTPUT_ROOT_RELATIVE),
        recovery=dict(root=str(recovery_root), producer=producer, proof=proof,
            files={p.relative_to(recovery_root).as_posix():digest(p)
                   for p in recovery_root.rglob('*') if p.is_file()}),
        initial_next_unit=derived['unit']['unit_id'])


class ExecutionSelection:
    def __init__(self, root, path, selected_digest, reference):
        self.root, self.path = Path(root).resolve(), Path(path).resolve()
        self.digest, self.reference = selected_digest, reference
        if not selected_digest or digest(self.path) != selected_digest:
            raise ReleaseError('EXECUTOR_SELECTION_DIGEST')
        self.payload = json.loads(self.path.read_bytes())
        p = self.payload
        if (p.get('schema') != SCHEMA or p.get('mode') not in {TEST_MODE, PRODUCTION_MODE}
                or p.get('repository') != str(self.root) or reference.root != self.root
                or not isinstance(reference, SelectedReference)
                or p.get('reference_sha256') != reference.selected_sha256):
            raise ReleaseError('EXECUTOR_SELECTION_BINDING')

    def check(self, unit, contracts=None, policies=None, plan=None):
        p = self.payload
        if digest(self.path) != self.digest or json.loads(self.path.read_bytes()) != p:
            raise ReleaseError('EXECUTOR_SELECTION_CHANGED')
        self.reference.check_selection()
        committed_source(self.root)
        if git_head(self.root) != p['git_head'] or source_inventory(self.root) != p['sources']:
            raise ReleaseError('EXECUTOR_SOURCE_CHANGED')
        if unit not in p['requested_units']:
            raise ReleaseError('EXECUTOR_UNIT_NOT_SELECTED')
        if p['output'] != str(self.root/g08.PRODUCTION_OUTPUT_ROOT_RELATIVE):
            raise ReleaseError('EXECUTOR_OUTPUT')
        if environment() != p['environment'] or integration.numerical_runtime() != p['numerical_runtime']:
            raise ReleaseError('EXECUTOR_ENVIRONMENT_CHANGED')
        for path, sha in p['inputs'].items():
            if digest(self.root/path) != sha:
                raise ReleaseError('EXECUTOR_INPUT_CHANGED')
        for label, value in [('contracts', contracts), ('policies', policies), ('plan', plan)]:
            if value is not None and identity(value) != p[label+'_sha256']:
                raise ReleaseError('EXECUTOR_'+label.upper()+'_CHANGED')
        if contracts is not None and integration.declared_inputs(contracts) != p['inputs']:
            raise ReleaseError('EXECUTOR_INPUT_SET')

    def recovered(self):
        recovery = self.payload['recovery']
        root = Path(recovery['root']).resolve()
        if not root.is_relative_to(self.root/'data/processed/propagation/paper1'):
            raise ReleaseError('EXECUTOR_RECOVERY_PATH')
        observed = {p.relative_to(root).as_posix():digest(p) for p in root.rglob('*') if p.is_file()}
        if observed != recovery['files']:
            raise ReleaseError('EXECUTOR_RECOVERY_CHANGED')
        return integration.consume_control(root, recovery['producer'], recovery['proof'])


class Operation:
    def __init__(self, release, contracts):
        self.release = release
        self.contracts = {g07._unit_id(c): c for c in contracts}

    def producer(self, source):
        if source == self.release.payload['git_head']:
            # Producer evidence only, not a capability to dispatch another unit.
            self.release.reference.check_selection()
            if (digest(self.release.path) != self.release.digest
                    or json.loads(self.release.path.read_bytes()) != self.release.payload
                    or git_head(self.release.root) != source):
                raise ReleaseError('EXECUTOR_PRODUCER_SELECTION')
            return dict(source_commit=source, transition_id='SELECTED_RELEASE:'+self.release.digest,
                        execution_authorized=False)
        return self.release.reference.producer(source)

    def _historical(self, run):
        relative=(Path(run)/'checkpoint.current.json').resolve().relative_to(self.release.root).as_posix()
        return relative in self.release.reference.records

    def _control_identity(self):
        return dict(schema=SCHEMA,source_commit=self.release.payload['git_head'],
                    release_digest=self.release.digest)

    def bind_new_state(self, run, state):
        if self._historical(run):
            raise ReleaseError('EXECUTOR_HISTORICAL_WRITE_PROHIBITED')
        expected=self._control_identity()
        if state.get('source_commit') != expected['source_commit']:
            raise ReleaseError('EXECUTOR_NEW_SOURCE_COMMIT')
        if 'execution_control' in state and state['execution_control'] != expected:
            raise ReleaseError('EXECUTOR_NEW_CONTROL_IDENTITY')
        state['execution_control']=expected

    def validate_new_state(self, run, state):
        if self._historical(run):
            return
        for path in (Path(run)/'checkpoints').glob('*.json'):
            body=json.loads(path.read_bytes())['payload']
            if (body.get('source_commit') != self.release.payload['git_head']
                    or body.get('execution_control') != self._control_identity()):
                raise ReleaseError('EXECUTOR_NEW_CONTROL_IDENTITY')
            self.validate_unit_state(Path(run).name, body)
        if state.get('execution_control') != self._control_identity():
            raise ReleaseError('EXECUTOR_NEW_CONTROL_IDENTITY')

    def validate_unit_state(self, run_id, state):
        unit=state.get('identity',{}).get('unit_id')
        contract=self.contracts.get(unit)
        if (contract is None or g07._v2_run_id(unit) != run_id
                or state['identity'].get('run_id') != run_id
                or state['identity'].get('contract_sha256') != contract.contract_sha256):
            raise ReleaseError('EXECUTOR_NEW_UNIT_BINDING')
        g07.v2_policy.validate_checkpoint_policy(state['identity'],g07.v2_policy.resolve_policy(contract))

    def awaiting_pair(self, entry, state):
        """Scheduling only: never promote staged science to terminal evidence."""
        if state['current_phase'] != 'METRICS_WRITTEN':
            return False
        self.validate_unit_state(g07._v2_run_id(entry.unit_id),state)
        contract=self.contracts[entry.unit_id]
        context=g07._DispatchContext(self.release.root,g07.ProductionExecutionRequest(
            entry.unit_id,g07._v2_run_id(entry.unit_id),Path(self.release.payload['output']),resume=True),
            entry,contract,None,g07._DISPATCH_CAPABILITY)
        members=g07._paired_group_contracts(context)
        if not members:
            return False
        for member in members:
            run=Path(self.release.payload['output'])/g07._v2_run_id(g07._unit_id(member))
            if not (run/'checkpoint.current.json').is_file():
                return True
            sibling=g07._reopen_production_state(run,self.release.root)
            if g07.PRODUCTION_PHASES.index(sibling['current_phase']) < g07.PRODUCTION_PHASES.index('METRICS_WRITTEN'):
                return True
        return False

    @contextmanager
    def use(self):
        if _operation.get() is not None:
            raise ReleaseError('EXECUTOR_NESTED_OPERATION')
        token = _operation.set(self)
        try:
            yield self
        finally:
            _operation.reset(token)

    def inheritance(self, context, policy):
        reference = self.release.reference
        unit = context.plan_entry.unit_id
        if (context.contract != self.contracts.get(unit)
                or policy != g07.v2_policy.resolve_policy(context.contract)
                or policy.mode is not g07.v2_policy.PolicyMode.INHERIT):
            raise ReleaseError('EXECUTOR_INHERIT_POLICY')
        parent = policy.inheritance_parent_unit_id
        contract = self.contracts[parent]
        run = self.release.root/g08.PRODUCTION_OUTPUT_ROOT_RELATIVE/g07._v2_run_id(parent)
        pointer_path, manifest_path = run/'checkpoint.current.json', run/'execution_manifest.json'
        with reference.use():
            reference.verify_file(pointer_path)
            reference.verify_file(manifest_path)
            state = g07._reopen_production_state(run, self.release.root)
            producer = g07._read_evidence_producer(self.release.root, contract, run,
                                                  manifest_path, 'execution_manifest')
            reference.producer(producer.source_commit)
            manifest = g07.g06.validate_execution_manifest(self.release.root, manifest_path, True).record
        if (state['current_phase'] != 'COMPLETE' or state['terminal_disposition'] != 'COMPLETE'
                or state['source_commit'] != producer.source_commit
                or state['identity']['unit_id'] != parent
                or state['identity']['run_id'] != g07._v2_run_id(parent)
                or state['identity']['contract_sha256'] != producer.contract_sha256
                or manifest.get('execution_contract_id') != producer.contract_sha256
                or manifest.get('paper1_run_id') != g07._v2_run_id(parent)
                or manifest.get('runner_source_commit') != producer.source_commit
                or manifest.get('scientific_run_git_commit') != producer.source_commit
                or manifest.get('runner_identity') != g07.SCHEMA_VERSION
                or manifest.get('terminal_status') != 'COMPLETE'):
            raise ReleaseError('EXECUTOR_INHERIT_PARENT_BINDING')
        parent_policy = g07.v2_policy.resolve_policy(contract)
        g07.v2_policy.validate_checkpoint_policy(state['identity'], parent_policy)
        selected = state.get('selected_hyperparameter')
        if (selected is None or
            (parent_policy.mode is g07.v2_policy.PolicyMode.FIXED and float(selected) != parent_policy.fixed_value) or
            (parent_policy.mode is g07.v2_policy.PolicyMode.TUNE and float(selected) not in parent_policy.candidates)):
            raise ReleaseError('EXECUTOR_INHERIT_VALUE')
        pointer = json.loads(pointer_path.read_bytes())
        return g07.v2_policy.validate_inheritance_claim(policy, parent_unit_id=parent,
            parent_policy_sha256=parent_policy.policy_sha256,
            parent_checkpoint_sha256=pointer['sha256'], parent_manifest_sha256=digest(manifest_path),
            selected_hyperparameter=float(selected))


class HandlerBoundary(RuntimeError):
    def __init__(self, context, handler, release, derived):
        self.record = dict(ordinal=derived['ordinal'], unit_id=context.request.unit_id,
            run_id=context.request.run_id, handler=handler.__module__+'.'+handler.__name__,
            registered_handler=context.plan_entry.handler_identity,
            contract_sha256=context.contract.contract_sha256,
            source_commit=context.contract.git_head, release_digest=release.digest,
            context_type=type(context).__name__, capability_valid=context.capability is g07._DISPATCH_CAPABILITY)
        super().__init__('EXECUTOR_STOP_BEFORE_HANDLER')


def _entry(release, request, preview):
    if not isinstance(release, ExecutionSelection):
        raise ReleaseError('EXECUTOR_SELECTION_REQUIRED')
    if not preview and release.payload['mode'] != PRODUCTION_MODE:
        raise ReleaseError('EXECUTOR_TEST_SELECTION_CANNOT_DISPATCH')
    if not isinstance(request,g07.ProductionExecutionRequest):
        raise ReleaseError('EXECUTOR_REQUEST_REQUIRED')
    release.check(request.unit_id)
    plan, contracts = g08.governed_plan(release.root)
    _, policies, _ = g08.governed_policy_universe(release.root, contracts)
    release.check(request.unit_id, contracts, policies, plan)
    operation = Operation(release, contracts)
    completed = release.recovered()
    with operation.use():
        derived = integration.derive_next(release.root, release.reference, plan, completed)
    if derived['unit']['unit_id'] != request.unit_id:
        raise ReleaseError('EXECUTOR_NOT_NEXT_UNIT')
    run=Path(request.output_root)/request.run_id
    if request.resume != run.exists() or operation._historical(run):
        raise ReleaseError('EXECUTOR_RESUME_STATE_MISMATCH')
    receipt = dict(schema=SCHEMA, source_commit=release.payload['git_head'], release_digest=release.digest)
    def boundary(context, handler):
        release.check(request.unit_id)
        release.recovered()
        if context.contract.git_head != release.payload['git_head']:
            raise ReleaseError('EXECUTOR_CONTRACT_SOURCE')
        if preview:
            raise HandlerBoundary(context, handler, release, derived)
    with operation.use():
        return g07._run_authorized_scientific(release.root, request, receipt, before_handler=boundary)


def preview_selected(release, request):
    """Fixed raising sentinel at the real registered handler boundary."""
    with integration.final.no_new_predictions():
        return _entry(release, request, True)


def execute_selected(release, request):
    """Requires a separately selected production release; never selected in tests."""
    return _entry(release, request, False)
