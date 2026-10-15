from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
import zipfile

import windows_installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.target = self.root / "installed"
        self.kernel = mock.MagicMock()
        self.kernel.OpenMutexW.return_value = 0
        self.patches = [
            mock.patch.object(windows_installer, "ROOT", self.root),
            mock.patch.object(windows_installer.ctypes, "WinDLL", return_value=self.kernel, create=True),
        ]
        for patch in self.patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.folder.cleanup()

    def payload(self, unsafe=False):
        path = self.root / "payload.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("AIwithSaeed-Downloader.exe", b"test-executable")
            archive.writestr("installation.json", json.dumps({
                "product": windows_installer.PRODUCT_ID, "version": "test",
            }))
            if unsafe:
                archive.writestr("../outside.txt", "must not escape")
        (self.root / "payload.sha256").write_text(hashlib.sha256(path.read_bytes()).hexdigest(), encoding="ascii")

    def test_refuses_unrelated_destination_without_changing_it(self):
        self.target.mkdir()
        sentinel = self.target / "personal.txt"
        sentinel.write_text("keep me", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unrelated files"):
            windows_installer.install(self.target, lambda value: None, register=False)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep me")

    def test_corrupt_payload_fails_before_installing(self):
        self.payload()
        (self.root / "payload.sha256").write_text("incorrect", encoding="ascii")
        with self.assertRaisesRegex(RuntimeError, "damaged"):
            windows_installer.install(self.target, lambda value: None, register=False)
        self.assertFalse(self.target.exists())

    def test_rejects_zip_path_traversal(self):
        self.payload(unsafe=True)
        with self.assertRaisesRegex(RuntimeError, "Unsafe path"):
            windows_installer.install(self.target, lambda value: None, register=False)
        self.assertFalse((self.root / "outside.txt").exists())
        self.assertFalse(self.target.exists())

    def test_install_and_upgrade_preserve_data_outside_program_folder(self):
        self.payload()
        user_data = self.root / "personal-download.mp4"
        user_data.write_bytes(b"keep this download")
        progress = []
        windows_installer.install(self.target, progress.append, register=False)
        self.assertEqual(progress[-1], 100)
        self.assertTrue((self.target / "Uninstall.ps1").is_file())
        windows_installer.install(self.target, progress.append, register=False)
        self.assertEqual(user_data.read_bytes(), b"keep this download")
        self.assertEqual((self.target / "AIwithSaeed-Downloader.exe").read_bytes(), b"test-executable")

    def test_running_application_blocks_update(self):
        self.payload()
        self.kernel.OpenMutexW.return_value = 123
        with self.assertRaisesRegex(RuntimeError, "Close AIwithSaeed"):
            windows_installer.install(self.target, lambda value: None, register=False)
        self.kernel.CloseHandle.assert_called_once_with(123)


if __name__ == "__main__":
    unittest.main()
