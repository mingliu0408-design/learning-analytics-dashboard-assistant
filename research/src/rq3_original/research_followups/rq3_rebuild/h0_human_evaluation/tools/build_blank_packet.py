"""Build response-free materials only. Does not load/generate candidate answers."""
import argparse
import copy
import csv
import shutil
import uuid
from pathlib import Path
from h0 import ROOT, CRITERIA, MODES, RATING_FIELDS, canonical_bytes, digest, read_json, write_json, validate_collection, packet_errors, validate_ratings, validate_condition_parity

INSTRUCTIONS = ('请先阅读共同问题、可见情境、来源与任务固定适用性，再独立评价原八个项目。'
                '1=Poor，5=Excellent；NA 仅用于任务预定不适用。空白不是分数。'
                '没有待评回答时不得评分。不要推测系统身份或查看其他评分者记录。'
                '行为锚点为本研究待校准草案。')


def build(output, tasks=None):
    output = Path(output)
    if output.exists():
        raise ValueError('refuse to overwrite existing packet directory')
    tasks = [] if tasks is None else tasks
    errors = validate_collection(tasks)
    if errors:
        raise ValueError('; '.join(errors))
    raw = read_json(ROOT / 'rubric.json')
    rubric = {k: raw[k] for k in ('rubric_version', 'paper_title', 'source_version', 'source_pdf_sha256', 'scale', 'criteria')}
    blank = read_json(ROOT / 'templates/task_template.json')

    def item(task, item_id):
        return {'item_id': item_id, 'query': task['task']['target_utterance'],
                'visible_context': copy.deepcopy(task['visible_context']),
                'evidence_dossier': copy.deepcopy(task['evaluator_reference']),
                'response': None, 'applicability': copy.deepcopy(task['applicability']),
                'instructions': INSTRUCTIONS, 'rubric_sha256': digest(canonical_bytes(rubric)),
                'observability': copy.deepcopy(task['observability'])}

    packet = {'schema_version': 'H0_HUMAN_PACKET_V1', 'stage': 'H0_RESPONSE_FREE_PREPARATION',
              'packet_id': uuid.uuid4().hex, 'protocol_approval_reference': '',
              'rubric': rubric, 'items': [], 'item_template': item(blank, '')}
    mapping, rows = [], []
    for task in tasks:
        for mode in MODES:
            oid = uuid.uuid4().hex
            packet['items'].append(item(task, oid))
            mapping.append({'item_id': oid, 'task_id': task['task_id'], 'family_id': task['family_id'], 'mode': mode})
    # No planned slots are created from the empty task collection.
    for entry in packet['items'] or [packet['item_template']]:
        for c in CRITERIA:
            rows.append({'item_id': entry['item_id'], 'rater_id': '', 'criterion_id': c,
                         'score': None, 'note': '', 'applicability_dispute': '', 'recorded_at': ''})
    errors = packet_errors(packet) + validate_ratings(rows, packet['items'] or [packet['item_template']], blank_only=True) + validate_condition_parity(packet['items'], mapping)
    if errors:
        raise ValueError('; '.join(errors))
    (output / 'human').mkdir(parents=True)
    (output / 'restricted').mkdir()
    (output / 'restricted').chmod(0o700)
    write_json(output / 'human/human_packet.json', packet)
    write_json(output / 'human/ratings.json', rows)
    with (output / 'human/ratings.csv').open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=RATING_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    write_json(output / 'restricted/mode_mapping.json', mapping)
    (output / 'restricted/mode_mapping.json').chmod(0o600)
    for name in ('index.html', 'app.js', 'style.css'):
        shutil.copyfile(ROOT / 'ui' / name, output / 'human' / name)
    (output / 'README.md').write_text('# H0 空白人工包\n\n只把 human 目录给评分者。restricted 映射始终由协调者另存；此默认包映射为空。没有真实任务或回答；分数、NA、理由、身份都未填。仅本地显式 JSON 导入/导出，无网络或自动缓存。未来填写包需要独立批准和新数据交接。\n', encoding='utf-8')
    return {'items': len(packet['items']), 'blank_rating_rows': len(rows), 'mapping_rows': len(mapping), 'response_count': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--tasks', help='Optional response-free task collection; never candidate responses')
    args = parser.parse_args()
    print(build(args.output, read_json(args.tasks) if args.tasks else None))
