"""Standalone archive-boundary tests; no repository or external files."""
import io
from pathlib import Path
import stat
import sys
import unittest
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "code"))
from verify_review_zip import safe_members

class PackagingTests(unittest.TestCase):
    def archive(self, name, mode=stat.S_IFREG | 0o644):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            info = zipfile.ZipInfo(name); info.external_attr = mode << 16
            z.writestr(info, b"synthetic review test")
        data.seek(0)
        return zipfile.ZipFile(data)

    def test_25_reject_traversal_and_absolute_paths(self):
        for name in ("../escape.txt", "/absolute.txt", "root/../../escape.txt", "root\\escape.txt"):
            with self.archive(name) as z, self.assertRaises(AssertionError): safe_members(z)

    def test_26_reject_symlink_and_device_members(self):
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFCHR | 0o600):
            with self.archive("root/item", mode) as z, self.assertRaises(AssertionError): safe_members(z)

    def test_27_accept_regular_member_with_valid_crc(self):
        with self.archive("root/review.txt") as z:
            self.assertEqual(safe_members(z), ["root/review.txt"])

if __name__ == "__main__": unittest.main()
