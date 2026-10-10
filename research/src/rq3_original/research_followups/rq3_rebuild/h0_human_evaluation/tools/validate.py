"""Read-only offline validation; does not create ratings or grant execution approval."""
import argparse
import json
import sys
from pathlib import Path
from h0 import ROOT, CRITERIA, digest, read_json, schema_errors, validate_task, validate_collection, validate_ratings, packet_errors, load_ratings_csv, validate_condition_parity


def artifacts():
    errors = []
    manifest = read_json(ROOT / 'input/MANIFEST.json')
    for entry in manifest['members']:
        data = (ROOT / 'input' / entry['path']).read_bytes()
        if len(data) != entry['bytes'] or digest(data) != entry['sha256']:
            errors.append('input integrity: ' + entry['path'])
    for entry in read_json(ROOT / 'SOURCE_LINEAGE.json')['completed_sources']:
        if 'snapshot' in entry:
            data = (ROOT / entry['snapshot']).read_bytes()
            if len(data) != entry['bytes'] or digest(data) != entry['sha256']:
                errors.append('completed source integrity: ' + entry['snapshot'])
    rubric = read_json(ROOT / 'rubric.json')
    original = read_json(ROOT / 'input/REFERENCES/SOURCE_RUBRIC_TRANSCRIPTION.json')
    page = ' '.join((ROOT / 'evidence/SOURCE_PAPER_PAGE_07.txt').read_text().split())
    if [c['id'] for c in rubric['criteria']] != list(CRITERIA) or rubric['scale'] != original['scale']:
        errors.append('rubric criteria/scale drift')
    for c, o in zip(rubric['criteria'], original['criteria']):
        if any(c[k] != o[k] for k in ('id', 'name', 'source_description')):
            errors.append('source description drift: ' + c['id'])
        if ' '.join(c['source_description'].split()) not in page:
            # Layout text includes the Theory column interleaved on the Personalisation line;
            # visual inspection is authoritative; read ordinary PDF text for column-free matching.
            plain = ' '.join((ROOT / 'evidence/SOURCE_TABLE_DESCRIPTION_TEXT.txt').read_text().split())
            if ' '.join(c['source_description'].split()) not in plain:
                errors.append('source text extraction mismatch: ' + c['id'])
        if c['anchor_status'] != 'LOCAL_OPERATIONALISATION_PENDING_HUMAN_CALIBRATION' or set(c['proposed_anchors']) != {'1','2','3','4','5'}:
            errors.append('local anchor attribution mismatch')
    for name, schema in [('task_template','task'),('source_span_template','source_span'),('source_annotation_template','source_annotation'),('runtime_capture_template','runtime_capture'),('writer_template','writer'),('reviewer_template','reviewer'),('rater_template','rater')]:
        errors.extend(schema_errors(read_json(ROOT / f'templates/{name}.json'), read_json(ROOT / f'schemas/{schema}.schema.json')))
    for name in ('writer', 'reviewer', 'rater'):
        if any(value is not None and value != '' for key, value in read_json(ROOT / f'templates/{name}_template.json').items() if key != 'status'):
            errors.append('human identity/check/attestation must be blank: ' + name)
    blank_task = read_json(ROOT / 'templates/task_template.json')
    errors.extend(validate_task(blank_task))
    if not validate_task(blank_task, ready=True):
        errors.append('blank template incorrectly accepted as ready')
    packet = read_json(ROOT / 'blank_packet/human/human_packet.json')
    errors.extend(packet_errors(packet))
    errors.extend(validate_condition_parity(packet['items'], read_json(ROOT / 'blank_packet/restricted/mode_mapping.json')))
    if packet['items'] or read_json(ROOT / 'blank_packet/restricted/mode_mapping.json'):
        errors.append('default H0 package unexpectedly contains task slots/mapping')
    for name in ('ratings.json', 'ratings.csv'):
        path = ROOT / 'blank_packet/human' / name
        rows = load_ratings_csv(path) if path.suffix == '.csv' else read_json(path)
        errors.extend(validate_ratings(rows, [packet['item_template']], blank_only=True))
    for name in ('index.html', 'app.js', 'style.css'):
        if (ROOT / 'ui' / name).read_bytes() != (ROOT / 'blank_packet/human' / name).read_bytes():
            errors.append('UI copy drift: ' + name)
    required = ['SUPERVISOR_RUBRIC_SOURCE_AUDIT.md','HUMAN_RUBRIC_GUIDE_DRAFT.md','COMMON_REFERENCE_AND_APPLICABILITY_PROTOCOL_DRAFT.md','TASK_AUTHORING_KIT.md','SIX_MODE_DESIGN_AND_WORKLOAD_OPTIONS.md','HUMAN_ANALYSIS_PLAN_DRAFT.md','AUTHOR_DECISIONS_NEEDED.md','THESIS_FUTURE_DELTA_PROPOSAL.md','START_HERE.md']
    for name in required:
        if not (ROOT / name).is_file() or not (ROOT / name).stat().st_size:
            errors.append('missing deliverable ' + name)
    return errors


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind', choices=['all', 'task', 'collection', 'ratings', 'bundle'])
    p.add_argument('file', nargs='?')
    p.add_argument('--ready', action='store_true')
    p.add_argument('--packet')
    p.add_argument('--complete', action='store_true')
    a = p.parse_args()
    try:
        if a.kind == 'all':
            errors = artifacts()
        elif a.kind == 'task':
            errors = validate_task(read_json(a.file), a.ready)
        elif a.kind == 'collection':
            errors = validate_collection(read_json(a.file), a.ready)
        elif a.kind == 'bundle':
            bundle = Path(a.file)
            packet = read_json(bundle / 'human/human_packet.json')
            errors = packet_errors(packet)
            errors += validate_condition_parity(packet['items'], read_json(bundle / 'restricted/mode_mapping.json'))
            errors += validate_ratings(read_json(bundle / 'human/ratings.json'), packet['items'] or [packet['item_template']], blank_only=True)
        else:
            packet = read_json(a.packet)
            rows = load_ratings_csv(a.file) if Path(a.file).suffix == '.csv' else read_json(a.file)
            errors = packet_errors(packet, preparation=not a.complete)
            errors += validate_ratings(rows, packet['items'] or [packet['item_template']], complete=a.complete, blank_only=packet['stage']=='H0_RESPONSE_FREE_PREPARATION')
        print(json.dumps({'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'scope': a.kind, 'scientific_execution_authorized': False}, indent=2))
        sys.exit(bool(errors))
    except (ValueError, TypeError, OSError, KeyError) as exc:
        print(json.dumps({'status':'FAIL','error':str(exc)}))
        sys.exit(1)
