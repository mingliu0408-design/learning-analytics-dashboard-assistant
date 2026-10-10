"""ARTIFICIAL_PROGRAM_FIXTURES_ONLY: malicious ZIP shapes in temporary files."""
import hashlib
import json
import stat
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from verify_review_zip import verify


class ArchiveTests(unittest.TestCase):
    def create(self,path,attack=None):
        files={'START_HERE.md':b'ARTIFICIAL_ARCHIVE_TEST_ONLY\n'}
        if attack=='traversal':files['../escape.txt']=b'x'
        if attack=='absolute':files['/escape.txt']=b'x'
        if attack=='backslash':files['a\\b']=b'x'
        if attack=='extra':files['unexpected.txt']=b'x'
        names=[*files,'EXPORT_ALLOWLIST.json','OUTPUT_MANIFEST.json']
        files['EXPORT_ALLOWLIST.json']=json.dumps({'members':names}).encode()
        entries=[{'path':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items() if not(attack=='extra' and n=='unexpected.txt')]
        if attack=='hash':entries[0]['sha256']='0'*64
        if attack=='length':entries[0]['bytes']+=1
        if attack=='duplicate_manifest':entries.append(entries[0])
        files['OUTPUT_MANIFEST.json']=json.dumps({'excluded_self':'OUTPUT_MANIFEST.json','members':entries}).encode()
        with zipfile.ZipFile(path,'w') as z:
            for name,data in files.items():
                info=zipfile.ZipInfo(name);info.create_system=3;info.external_attr=(stat.S_IFREG|0o644)<<16
                if attack=='symlink' and name=='START_HERE.md':info.external_attr=(stat.S_IFLNK|0o777)<<16
                z.writestr(info,data)
            if attack=='duplicate':
                with warnings.catch_warnings():warnings.simplefilter('ignore');z.writestr('START_HERE.md',b'ARTIFICIAL_DUPLICATE')
    def test_valid_archive(self):
        with tempfile.TemporaryDirectory(prefix='h0_zip_test_') as d:
            p=Path(d)/'x.zip';self.create(p);r=verify(p);self.assertEqual(r['status'],'PASS');self.assertEqual(r['members'],3)
    def test_rejects_path_identity_and_integrity_attacks(self):
        for attack in ['traversal','absolute','backslash','symlink','duplicate','duplicate_manifest','extra','hash','length']:
            with self.subTest(attack=attack),tempfile.TemporaryDirectory(prefix='h0_zip_test_') as d:
                p=Path(d)/'x.zip';self.create(p,attack)
                with self.assertRaises(ValueError):verify(p)


if __name__=='__main__':unittest.main()
