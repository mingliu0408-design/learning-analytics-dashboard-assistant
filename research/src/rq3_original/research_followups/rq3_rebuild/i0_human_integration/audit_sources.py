"""Read exact E1/E0 locators only. Export hashes/headers, never private rows."""
import csv
import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from utils.c4_rebuild.sources import source_template


def main():
    old = json.loads((HERE.parent/'e1_five_page/DATA_COVERAGE_PROFILE.json').read_text())
    legacy = Path('/Users/liuming/Downloads/duteaiapp_cfull_semantic_integrated_v1_副本3')
    rows = []
    for r in old['sources']:
        if r.get('location') != 'known_legacy':
            continue
        p = Path(r['path'])
        assert p.is_relative_to(legacy) and not p.is_symlink()
        row = dict(source_id=r['binding_field'], locator=str(p), exists=p.is_file(),
                   current_checkout_exists=(ROOT/p.relative_to(legacy)).is_file(),
                   permission='UNKNOWN', authenticated_binding='UNKNOWN', rows_exported=0)
        if p.is_file():
            row['bytes'] = p.stat().st_size
            row['sha256'] = hashlib.sha256(p.read_bytes()).hexdigest()
            row['matches_E1'] = row['sha256'] == r.get('sha256')
            if p.suffix == '.csv':
                with p.open(encoding='utf-8-sig', newline='') as f:
                    row['headers'] = next(csv.reader(f))
                row['readiness'] = 'PARTIAL'
            elif p.suffix == '.xlsx':
                # Only first-row cells and the referenced shared strings are reported.
                ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
                with ZipFile(p) as z:
                    first = ET.fromstring(z.read('xl/worksheets/sheet1.xml')).find('s:sheetData/s:row', ns)
                    strings = ET.fromstring(z.read('xl/sharedStrings.xml')).findall('s:si', ns)
                    headers = []
                    for c in first.findall('s:c', ns):
                        v = c.find('s:v', ns)
                        if v is not None and c.get('t') == 's':
                            headers.append(''.join(strings[int(v.text)].itertext()))
                    row['headers'] = headers
                row['readiness'] = 'PARTIAL'
            else:
                row.update(readiness='UNKNOWN', read_status='BINARY_NOT_DESERIALISED')
        else:
            row['readiness'] = 'UNKNOWN'
        row['temporal_semantics'] = r.get('temporal_semantics', 'Identity table is not authenticated enrolment or a calendar')
        rows.append(row)
    for name in ('goals', 'reflections'):
        rows.append(dict(source_id=name, readiness='UNKNOWN', reason='NO_STANDARD_SOURCE_BINDING', rows_exported=0))
    docs = []
    for rel in ('PRIVATE_DATA_NOTICE.md', 'project_manifest_v1.json', 'utils/c4_dashboard_scoped/scope.py',
                'utils/c4_dashboard_scoped/loader.py'):
        p = ROOT/rel
        docs.append(dict(path=rel, sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
    output = dict(source_origin='REAL_LOCAL_METADATA_ONLY', sources=rows, inspected_source_documents=docs,
                  result='PARTIAL_REAL_BINDING_NOT_AUTHORISED',
                  boundary='Private-copy notice permits owner local work; it does not establish new participant consent, course enrolment, observation windows, metric coverage or live-use permission.',
                  real_rows_aggregated=0, private_rows_exported=0, pickle_loads=0, sibling_worktrees_read=False)
    (HERE/'receipts/REAL_SOURCE_METADATA.json').write_text(json.dumps(output, indent=2, ensure_ascii=False)+'\n')
    (HERE/'REAL_SOURCE_MANIFEST_TEMPLATE.json').write_text(json.dumps([source_template(r['source_id']) for r in rows], indent=2)+'\n')
    print(json.dumps(dict(source_count=len(rows), headers_verified=sum('headers' in r for r in rows),
                          unchanged_hashes=sum(r.get('matches_E1', False) for r in rows), private_rows_exported=0)))


if __name__ == '__main__':
    main()
