from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from official_resources import RESOURCES, extract_tools, load_resources
from online_download import DownloadProblem


class OfficialResourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def config(self, resources):
        (self.root / "official-resources.json").write_text(json.dumps({
            "mode": "official-resources", "resources": resources,
        }), encoding="utf-8")

    def test_official_pinned_sources_load_without_our_website(self):
        self.config(RESOURCES)
        loaded = load_resources(self.root)
        self.assertEqual(len(loaded), 2)
        self.assertTrue(loaded[0]["url"].startswith("https://nodejs.org/"))
        self.assertTrue(loaded[1]["url"].startswith("https://www.gyan.dev/"))
        self.assertNotIn("aiwithsaeed.com", json.dumps(loaded))

    def test_source_destination_hash_or_size_cannot_be_replaced(self):
        for field, replacement in (("url", "https://example.org/tool.zip"), ("sha256", "a" * 64),
                                   ("size", 100), ("members", {"node.exe": "../escape.exe"})):
            resources = deepcopy(RESOURCES)
            resources[0][field] = replacement
            self.config(resources)
            with self.subTest(field=field), self.assertRaises(DownloadProblem):
                load_resources(self.root)

    def test_only_required_binaries_and_notices_are_extracted(self):
        archives = {}
        for resource in RESOURCES:
            archive = self.root / f"{resource['id']}.zip"
            with zipfile.ZipFile(archive, "w") as stream:
                for name in resource["members"]:
                    stream.writestr(name, b"test file")
                stream.writestr("unneeded/ffplay.exe", b"not required")
                stream.writestr("../escape.exe", b"must not extract")
            archives[resource["id"]] = archive
        destination = self.root / "app"
        destination.mkdir()
        extract_tools(RESOURCES, archives, destination)
        self.assertEqual((destination / "_internal/tools/node.exe").read_bytes(), b"test file")
        self.assertTrue((destination / "_internal/tools/ffmpeg.exe").is_file())
        self.assertTrue((destination / "_internal/tools/ffprobe.exe").is_file())
        self.assertFalse((self.root / "escape.exe").exists())
        self.assertFalse((destination / "unneeded").exists())

    def test_missing_required_executable_stops_installation(self):
        archive = self.root / "empty.zip"
        with zipfile.ZipFile(archive, "w"):
            pass
        with self.assertRaises(DownloadProblem):
            extract_tools([RESOURCES[0]], {"node": archive}, self.root / "app")
