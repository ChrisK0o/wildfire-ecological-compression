"""Candidate public no-fit finalization, separate from historical G07 execution.

Historical pointers remain immutable. New candidate pointers identify this release,
not a historical producer. This entry cannot start a scientific unit or fit a model.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import time

from src import paper1_g07_runtime as g07, paper1_g08_runtime as g08
from src.paper1_control_reference import canonical, digest
from src.paper1_control_release import SelectedRelease, ReleaseError, identity, plain


class FinalizationError(RuntimeError):
    pass


class CandidateInterruption(RuntimeError):
    pass


@contextmanager
def no_new_predictions():
    """Failing sentinels, never substitute successful computation."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    from statsmodels.genmod.generalized_linear_model import GLM
    replacements = [(g07, name) for name in (
        '_fit_probabilities', '_fit_fractional_probabilities', '_tune_governed',
        '_persist_prediction', '_persist_governed_benchmark_evidence')]
    replacements += [(cls, name) for cls in (LogisticRegression, RandomForestClassifier)
                     for name in ('fit', 'predict', 'predict_proba')]
    replacements.append((GLM, 'fit'))
    originals = [(owner, name, getattr(owner, name)) for owner, name in replacements]
    def forbidden(*args, **kwargs):
        raise FinalizationError('CANDIDATE_FIT_OR_PREDICTION_FORBIDDEN')
    try:
        for owner, name, _ in originals:
            setattr(owner, name, forbidden)
        yield
    finally:
        for owner, name, value in originals:
            setattr(owner, name, value)


def verify_reference_files(reference):
    # No cached permission: every selected historical file is reopened.
    for relative in reference.records:
        reference.verify_file(reference.root / relative)


def preflight(release, unit_id, output):
    """Actual frozen contracts, policy and five-group science, without activation."""
    if not isinstance(release, SelectedRelease):
        raise ReleaseError('RELEASE_REQUIRED')
    root, output = release.root, Path(output).resolve()
    started = time.perf_counter()
    release.check(unit_id, output)
    plan, contracts = g08.governed_plan(root)
    policies, records, policy_qc = g08.governed_policy_universe(root, contracts)
    release.check(unit_id, output, contracts=contracts, policies=records)
    graph = g08.dependency_graph_payload(contracts, records)
    groups = [g for g in graph['paired_staging_groups'] if unit_id in g['unit_ids']]
    if len(groups) != 1 or set(groups[0]['unit_ids']) != set(release.payload['units']):
        raise FinalizationError('CANDIDATE_GROUP_SCOPE')
    group = groups[0]
    by_unit = {g07._unit_id(c): c for c in contracts}
    entries = {e.unit_id: e for e in plan}
    history = root / g08.PRODUCTION_OUTPUT_ROOT_RELATIVE
    reference = release.reference
    with reference.use():
        verify_reference_files(reference)
        shared = g08._validate_governed_shared_paired_evidence(
            root, root, history, unit_id, contracts, records)
        sources = []
        for member in group['unit_ids']:
            run_id = g08.deterministic_unit_run_id(member)
            run_root = history / run_id
            state = g07._reopen_production_state(run_root, root)
            if state['current_phase'] not in {'METRICS_WRITTEN', 'POSTPREDICTION_EVIDENCE_WRITTEN', 'COMPLETE'}:
                raise FinalizationError('CANDIDATE_SOURCE_NOT_READY')
            if entries[member].disposition is not g07.DispatchDisposition.EXECUTABLE:
                raise FinalizationError('CANDIDATE_SOURCE_NOT_EXECUTABLE')
            if state['identity']['unit_id'] != member:
                raise FinalizationError('CANDIDATE_SOURCE_IDENTITY')
            # Existing ordinal-30 gate is retained, parsed and authenticated in
            # addition to the staged-source and paired semantic reconstruction.
            gate_path = run_root / 'v2_publication_gate.json'
            if gate_path.exists():
                gate = json.loads(gate_path.read_bytes())
                artifacts = gate.get('artifact_records', {})
                g07.v2_policy.validate_publication_state(
                    gate, artifact_root=root, required_artifacts=tuple(artifacts),
                    expected_artifact_records=artifacts)
                for record in artifacts.values():
                    reference.verify_file(root / record['path'])
            sources.append({'unit_id': member, 'run_id': run_id,
                            'source_commit': state['source_commit'],
                            'historical_phase': state['current_phase'],
                            'historical_checkpoint_sha256': digest(run_root/'checkpoint.current.json'),
                            'prediction_sha256': digest(run_root/'predictions.csv'),
                            'metrics_sha256': digest(run_root/'metrics.json'),
                            'historical_model_fit_count': state['model_fit_count'],
                            'current_contract_sha256': by_unit[member].contract_sha256,
                            'policy_sha256': g07.v2_policy.resolve_policy(by_unit[member]).policy_sha256})
        # Live byte checks bind semantic results to unchanged bytes at consumption.
        verify_reference_files(reference)
    release.check(unit_id, output, contracts=contracts, policies=records)
    proof = {'schema': 'PAPER1_CANDIDATE_GROUP_VERIFICATION_V1',
             'release_sha256': release.sha256, 'reference_sha256': reference.selected_sha256,
             'group': plain(group), 'sources': sorted(sources, key=lambda r:r['unit_id']),
             'shared_groups': plain(shared), 'policy_universe_sha256': policy_qc['policy_universe_sha256'],
             'historical_inventory_sha256': identity(reference.payload['evidence_inventory']),
             'models_fit_this_operation': 0, 'predictions_generated_this_operation': 0}
    return proof, {'preflight_seconds': time.perf_counter()-started,
                   'plan_contract_count': len(contracts), 'source_count': len(sources),
                   'shared_group_count': shared['group_count'], 'reference_file_reads': reference.reads}


def expected_outputs(release, proof):
    """Deterministic semantic claims, not acceptance of stored status strings."""
    publication = {'schema': 'PAPER1_CANDIDATE_PUBLICATION_V1',
                   'producer_release_sha256': release.sha256, 'test_only': True,
                   'verification': proof, 'publication_state': 'VALIDATED_READY_FOR_TERMINAL'}
    files = {'publication.json': canonical(publication) + b'\n'}
    pointers = {}
    for source in proof['sources']:
        prior = None
        run = source['run_id']
        for sequence, phase in enumerate(('PUBLICATION_VALIDATED', 'COMPLETE'), 1):
            relative = f'{run}/checkpoints/{sequence:02d}_{phase}.json'
            payload = {'schema': 'PAPER1_CANDIDATE_FINALIZATION_CHECKPOINT_V1',
                       'producer_release_sha256': release.sha256, 'test_only': True,
                       'unit_id': source['unit_id'], 'run_id': run, 'phase': phase,
                       'sequence': sequence, 'previous_checkpoint': prior,
                       'publication_sha256': identity(publication),
                       'historical_source': source,
                       'model_fits_this_operation': 0, 'predictions_generated_this_operation': 0}
            raw = canonical(payload) + b'\n'
            files[relative] = raw
            prior = {'path': relative, 'sha256': g07.sha256_bytes(raw)}
            pointers[(run, phase)] = canonical(prior) + b'\n'
    return files, pointers


def verify_existing(output, files, pointers):
    """Unknown or mutated partial output is a rejection, never a terminal success."""
    if not output.exists():
        return
    allowed_pointers = {f'{run}/checkpoint.current.json' for run, _ in pointers}
    for path in output.rglob('*'):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise FinalizationError('CANDIDATE_OUTPUT_LINK')
        if not path.is_file():
            continue
        relative = path.relative_to(output).as_posix()
        raw = path.read_bytes()
        if relative in files:
            if raw != files[relative]:
                raise FinalizationError('CANDIDATE_OUTPUT_COLLISION:' + relative)
            if '/checkpoints/' in relative:
                previous = json.loads(raw)['previous_checkpoint']
                if previous and (not (output/previous['path']).is_file()
                                 or (output/previous['path']).read_bytes() != files[previous['path']]):
                    raise FinalizationError('CANDIDATE_CHECKPOINT_LINEAGE_GAP')
        elif relative in allowed_pointers:
            run = relative.split('/')[0]
            if raw not in (pointers[(run, 'PUBLICATION_VALIDATED')], pointers[(run, 'COMPLETE')]):
                raise FinalizationError('CANDIDATE_POINTER_CLAIM')
            pointer = json.loads(raw)
            checkpoint = output / pointer['path']
            if not checkpoint.is_file() or checkpoint.read_bytes() != files[pointer['path']]:
                raise FinalizationError('CANDIDATE_POINTER_WITHOUT_CHECKPOINT')
            if not (output/'publication.json').is_file():
                raise FinalizationError('CANDIDATE_PREMATURE_COMPLETE')
        else:
            raise FinalizationError('CANDIDATE_UNEXPECTED_OUTPUT:' + relative)


def finalize(release, unit_id, output, *, interrupt_after=None, read_only=False):
    """Public candidate entry; only verified existing predictions may finalize.

    Test interruption uses named write boundaries, never a success mock. No old
    G07 checkpoint is advanced or rewritten: candidate pointers own the new state.
    """
    output = Path(output).resolve()
    started = time.perf_counter()
    with no_new_predictions():
        proof, timings = preflight(release, unit_id, output)
        files, pointers = expected_outputs(release, proof)
        verify_existing(output, files, pointers)
        if read_only:
            return {'verification': proof, 'timings': timings, 'write_count': 0}
        # Binding is re-read at the write boundary, not cached authorization.
        release.check(unit_id, output)
        verify_reference_files(release.reference)
        written = 0
        for relative, raw in files.items():
            path = output / relative
            if not path.exists():
                g07._write_once(path, raw)
                written += 1
            elif path.read_bytes() != raw:
                raise FinalizationError('CANDIDATE_LIVE_OUTPUT_COLLISION')
            if relative == 'publication.json' and interrupt_after == 'PUBLICATION_WRITTEN':
                raise CandidateInterruption('CANDIDATE_INTERRUPTED_AFTER_PUBLICATION')
            if relative.endswith('.json') and '/checkpoints/' in relative:
                if interrupt_after == 'CHECKPOINT_BEFORE_POINTER':
                    raise CandidateInterruption('CANDIDATE_INTERRUPTED_CHECKPOINT_BEFORE_POINTER')
                run = relative.split('/')[0]
                phase = json.loads(raw)['phase']
                pointer = output / run / 'checkpoint.current.json'
                wanted = pointers[(run, phase)]
                release.check(unit_id, output)
                verify_reference_files(release.reference)
                verify_existing(output, files, pointers)
                # Reentry must never regress a COMPLETE pointer.
                if pointer.exists() and pointer.read_bytes() == pointers[(run, 'COMPLETE')]:
                    continue
                if not pointer.exists() or pointer.read_bytes() != wanted:
                    g07._atomic_bytes(pointer, wanted)
                    written += 1
                if phase == 'COMPLETE' and interrupt_after == 'FIRST_COMPLETE':
                    raise CandidateInterruption('CANDIDATE_INTERRUPTED_AFTER_FIRST_COMPLETE')
        verify_existing(output, files, pointers)
        for run, phase in pointers:
            if phase == 'COMPLETE' and (output/run/'checkpoint.current.json').read_bytes() != pointers[(run, phase)]:
                raise FinalizationError('CANDIDATE_INCOMPLETE_GROUP')
    timings['total_seconds'] = time.perf_counter()-started
    return {'verification': proof, 'timings': timings, 'write_count': written,
            'candidate_group_state': 'COMPLETE', 'historical_checkpoints_modified': False}
