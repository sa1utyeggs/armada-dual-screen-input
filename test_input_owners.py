from pathlib import Path
import tempfile
import unittest

from native_input import input_owners


class InputOwnerTests(unittest.TestCase):
    def test_all_owners_are_returned_and_duplicate_descriptors_are_not_owners(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            wanted=Path('/dev/input/position-owned-test-node')
            for pid in ('100','200','300','non-process'):
                folder=root/pid/'fd';folder.mkdir(parents=True)
                (folder/'4').symlink_to(wanted if pid!='300' else '/dev/null')
                (folder/'5').symlink_to(wanted if pid!='300' else '/dev/null')
            self.assertEqual(input_owners(wanted,proc_root=root),{100,200})

    def test_vanished_process_or_descriptor_is_skipped_without_opening_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'100').mkdir()
            (root/'200'/'fd').mkdir(parents=True)
            (root/'200'/'fd'/'4').write_text('not a symlink')
            self.assertEqual(input_owners(Path('/dev/input/nonexistent'),proc_root=root),set())


if __name__ == '__main__': unittest.main()
