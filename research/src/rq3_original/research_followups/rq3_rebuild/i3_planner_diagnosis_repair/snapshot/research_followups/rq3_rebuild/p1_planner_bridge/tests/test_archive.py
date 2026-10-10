import io,json,stat,unittest,zipfile
from archive import make_archive,verify,ARCHIVE_ROOT

class ArchiveTests(unittest.TestCase):
    def test_valid_full_expected_byte_readback(self):
        blob,expected=make_archive({'START_HERE.md':b'Owned review entry'})
        self.assertEqual(verify(blob,expected)['file_count'],2)
    def test_extra_missing_and_hash_changes_rejected(self):
        blob,_=make_archive({'START_HERE.md':b'Entry'})
        for mode in ('extra','missing','changed'):
            stream=io.BytesIO()
            with zipfile.ZipFile(io.BytesIO(blob)) as old,zipfile.ZipFile(stream,'w') as new:
                for info in old.infolist():
                    if mode=='missing' and info.filename.endswith('START_HERE.md'):continue
                    data=old.read(info)
                    if mode=='changed' and info.filename.endswith('START_HERE.md'):data=b'altered'
                    new.writestr(info,data)
                if mode=='extra':new.writestr(ARCHIVE_ROOT+'/extra.txt','extra')
            with self.assertRaises(ValueError):verify(stream.getvalue())
    def test_duplicate_and_unsafe_paths_rejected(self):
        for name,symlink in (('../escape',False),(ARCHIVE_ROOT+'/link',True),(ARCHIVE_ROOT+'/duplicate',False)):
            b=io.BytesIO()
            with zipfile.ZipFile(b,'w') as z:
                info=zipfile.ZipInfo(name);info.create_system=3
                info.external_attr=((stat.S_IFLNK if symlink else stat.S_IFREG)|0o644)<<16
                z.writestr(info,b'x')
                if name.endswith('duplicate'):
                    import warnings
                    with warnings.catch_warnings():warnings.simplefilter('ignore');z.writestr(info,b'x')
            with self.assertRaises(ValueError):verify(b.getvalue())
