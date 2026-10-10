import hashlib
import io
import json
import stat
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from verify_review_package import verify,PREFIX,MANIFEST,validate_info

class PackagingTests(unittest.TestCase):
    def fixture(self,change=None):
        data=b'synthetic review payload\n';name=PREFIX+'/START_HERE.md'
        members={name:data}
        manifest={'members':[{'path':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}],
                  'self_reference_exclusions':[MANIFEST]}
        if change:change(members,manifest)
        members[MANIFEST]=json.dumps(manifest).encode()
        f=tempfile.NamedTemporaryFile(suffix='.zip',delete=False);f.close();self.addCleanup(Path(f.name).unlink)
        with zipfile.ZipFile(f.name,'w') as z:
            for n,b in members.items():z.writestr(n,b)
        return f.name
    def test_valid_archive_member_hashes_crc_and_exact_set(self):
        self.assertEqual(verify(self.fixture())['member_count'],2)
    def test_extra_member_rejected(self):
        with self.assertRaisesRegex(ValueError,'MISSING_OR_EXTRA'):
            verify(self.fixture(lambda m,x:m.update({PREFIX+'/extra.txt':b'extra'})))
    def test_missing_member_rejected(self):
        with self.assertRaisesRegex(ValueError,'MISSING_OR_EXTRA'):
            verify(self.fixture(lambda m,x:m.clear()))
    def test_wrong_payload_hash_rejected(self):
        with self.assertRaisesRegex(ValueError,'MEMBER_BYTES_OR_HASH'):
            verify(self.fixture(lambda m,x:x['members'][0].update(sha256='0'*64)))
    def test_traversal_absolute_windows_and_noncanonical_names_rejected(self):
        for name in ('/absolute','../outside',PREFIX+'/../escape',PREFIX+'/a/./b',PREFIX+'//file',PREFIX+'/C:bad',PREFIX+'/a\\b'):
            with self.subTest(name=name),self.assertRaises(ValueError):validate_info(zipfile.ZipInfo(name))
    def test_symlink_and_device_rejected(self):
        for mode in (stat.S_IFLNK,stat.S_IFCHR):
            i=zipfile.ZipInfo(PREFIX+'/special');i.create_system=3;i.external_attr=(mode|0o644)<<16
            with self.assertRaisesRegex(ValueError,'NONREGULAR'):validate_info(i)
    def test_duplicate_names_rejected(self):
        p=self.fixture()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with zipfile.ZipFile(p,'a') as z:z.writestr(MANIFEST,b'{}')
        with self.assertRaisesRegex(ValueError,'DUPLICATE_MEMBER'):verify(p)
