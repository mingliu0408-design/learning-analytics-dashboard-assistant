"""Bounded preparation manifests; author declarations remain explicit unknowns."""
from pathlib import Path
from hashlib import sha256
from utils.c4_dashboard_scoped.scope import instant

FIELDS = ('source_id', 'path', 'sha256', 'format', 'learner_binding', 'course_id',
          'permission_ref', 'snapshot_version', 'observation', 'window',
          'timezone', 'calendar_ref', 'coverage_ref', 'metric_semantics',
          'safe_export_provenance', 'item_identity_ref')


def source_template(source_id):
    return {k: source_id if k == 'source_id' else None for k in FIELDS}


def check_source(manifest, source_root, *, weekly=True):
    if set(manifest) != set(FIELDS):
        raise ValueError('Source manifest fields differ from I0 contract')
    root = Path(source_root).resolve()
    m = manifest
    gaps = []
    for key in ('learner_binding', 'course_id', 'permission_ref', 'snapshot_version',
                'coverage_ref', 'metric_semantics'):
        if not m[key]:
            gaps.append(key.upper() + '_UNKNOWN')
    p = None
    if not m['path']:
        gaps.append('SOURCE_FILE_UNBOUND')
    else:
        supplied = root / m['path']
        p = supplied.resolve()
        if not p.is_relative_to(root) or supplied.is_symlink():
            raise ValueError('Source path outside authorised root or symlink')
        if not p.is_file():
            gaps.append('SOURCE_FILE_UNAVAILABLE')
        elif m['format'] != 'csv' or p.suffix.lower() != '.csv':
            gaps.append('SAFE_CSV_EXPORT_REQUIRED')
        elif not m['sha256'] or sha256(p.read_bytes()).hexdigest() != m['sha256']:
            gaps.append('SOURCE_HASH_UNVERIFIED')
    if m['source_id'] == 'gdocs' and not m['safe_export_provenance']:
        gaps.append('TRUSTED_REFLECTION_EXPORT_REQUIRED')
    if m['source_id'] == 'echo' and not m['item_identity_ref']:
        gaps.append('STABLE_RECORDING_ID_REQUIRED')
    if weekly:
        if m['observation'] not in ('timestamp', 'week', 'interval'):
            gaps.append('WEEKLY_OBSERVATION_UNSUPPORTED')
        for key in ('window', 'timezone', 'calendar_ref'):
            if not m[key]:
                gaps.append(key.upper() + '_UNKNOWN')
    elif m['observation'] == 'cumulative' and not m['window']:
        # A real cumulative snapshot still needs a stated cut-off/collection basis.
        gaps.append('CUMULATIVE_SNAPSHOT_WINDOW_UNKNOWN')
    if m['window']:
        try:
            a, b = m['window']
            if instant(a) >= instant(b):
                raise ValueError('empty window')
        except (ValueError, TypeError):
            gaps.append('INVALID_OBSERVATION_WINDOW')
    return dict(source_id=m['source_id'], status='READY' if not gaps else 'PARTIAL' if p and p.is_file() else 'UNKNOWN',
                ready=not gaps, gaps=gaps, weekly=weekly,
                authority='CALLER_DECLARATIONS_NOT_AUTHENTICATED_BY_THIS_CHECKER')
