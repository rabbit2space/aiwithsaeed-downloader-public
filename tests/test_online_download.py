from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import tempfile
import threading
import unittest
import urllib.request

from online_download import (
    DownloadCancelled, DownloadProblem, SecureRedirect, cache_lock, check_connection,
    download_payload, validate_config,
)


class PayloadHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.requests.append(self.headers.get("Range"))
        mode = self.server.mode
        if mode == "missing":
            self.send_error(404)
            return
        payload = self.server.payload
        start, end = 0, len(payload) - 1
        requested = self.headers.get("Range")
        partial = requested is not None and mode != "ignore-range"
        if partial:
            match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
            start = int(match[1])
            end = int(match[2]) if match[2] else end
        body = payload[start:end + 1]
        self.send_response(206 if partial else 200)
        self.send_header("Content-Length", str(len(body)))
        if mode == "html":
            self.send_header("Content-Type", "text/html")
        if partial:
            first = start + 1 if mode == "bad-range" else start
            self.send_header("Content-Range", f"bytes {first}-{end}/{len(payload)}")
        self.end_headers()
        if mode == "truncate":
            body = body[:len(body) // 2]
        if mode == "tamper":
            body = b"!" * len(body)
        try:
            self.wfile.write(body)
        except (ConnectionResetError, BrokenPipeError):
            pass


class OnlineDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), PayloadHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.data = b"payload test bytes\x00\x01\x02" * 40000
        self.server.payload = self.data
        self.server.mode = "normal"
        self.server.requests = []
        self.config = {"url": "https://example.invalid/payload.zip", "version": "test",
                       "size": len(self.data), "sha256": hashlib.sha256(self.data).hexdigest()}

    def tearDown(self):
        self.temp.cleanup()

    def opener(self, request, timeout):
        # Only this injected test adapter uses loopback HTTP; production config requires HTTPS.
        local = urllib.request.Request(f"http://127.0.0.1:{self.server.server_port}/payload.zip",
                                       headers=dict(request.header_items()))
        return urllib.request.urlopen(local, timeout=timeout)

    def partial(self, size=1000):
        path = self.root / self.config["sha256"] / "payload.part"
        path.parent.mkdir(parents=True)
        path.write_bytes(self.data[:size])
        return path

    def download(self, cancel=None, progress=None):
        return download_payload(self.config, self.root, progress or (lambda value: None),
                                lambda value: None, cancel=cancel, opener=self.opener)

    def test_production_config_requires_https_and_valid_hash(self):
        for replacement in ({"url": "http://example.org/file"}, {"sha256": "bad"},
                            {"size": -1}, {"size": True}, {"url": "https://user:password@example.org/f"}):
            with self.subTest(replacement=replacement), self.assertRaises(DownloadProblem):
                validate_config(dict(self.config, **replacement))

    def test_connection_checks_real_payload_and_reports_current_connection(self):
        message = check_connection(self.config, opener=self.opener)
        self.assertIn("اتصال فعلی", message)
        self.assertEqual(self.server.requests, ["bytes=0-0"])

    def test_download_integrity_and_cache_reuse(self):
        complete = self.download()
        self.assertEqual(complete.read_bytes(), self.data)
        self.download()
        self.assertEqual(len(self.server.requests), 1)

    def test_resume_from_partial_bytes(self):
        self.partial()
        self.assertEqual(self.download().read_bytes(), self.data)
        self.assertEqual(self.server.requests, ["bytes=1000-"])

    def test_server_ignoring_range_restarts_safely(self):
        self.partial()
        self.server.mode = "ignore-range"
        self.assertEqual(self.download().read_bytes(), self.data)

    def test_interrupted_transfer_is_preserved_and_resumed(self):
        self.server.mode = "truncate"
        with self.assertRaises(DownloadProblem):
            self.download()
        partial = self.root / self.config["sha256"] / "payload.part"
        saved = partial.stat().st_size
        self.assertGreater(saved, 0)
        self.server.mode = "normal"
        self.assertEqual(self.download().read_bytes(), self.data)
        self.assertEqual(self.server.requests[-1], f"bytes={saved}-")

    def test_corrupt_data_never_becomes_installable_payload(self):
        self.server.mode = "tamper"
        with self.assertRaises(DownloadProblem):
            self.download()
        folder = self.root / self.config["sha256"]
        self.assertFalse((folder / "payload.zip").exists())
        self.assertFalse((folder / "payload.part").exists())

    def test_wrong_content_range_is_rejected(self):
        self.partial()
        self.server.mode = "bad-range"
        with self.assertRaises(DownloadProblem):
            self.download()

    def test_cancel_preserves_partial_and_retry_resumes(self):
        cancel = threading.Event()
        with self.assertRaises(DownloadCancelled):
            self.download(cancel=cancel, progress=lambda value: cancel.set())
        cancel.clear()
        self.assertEqual(self.download(cancel=cancel).read_bytes(), self.data)
        self.assertIsNotNone(self.server.requests[-1])

    def test_missing_release_reports_server_problem_not_vpn_requirement(self):
        self.server.mode = "missing"
        with self.assertRaisesRegex(DownloadProblem, "انتشار"):
            check_connection(self.config, opener=self.opener)

    def test_insecure_redirect_is_rejected(self):
        with self.assertRaises(DownloadProblem):
            SecureRedirect().redirect_request(None, None, 302, "redirect", {}, "http://example.org/file")

    def test_html_challenge_is_not_treated_as_installer_payload(self):
        self.server.mode = "html"
        with self.assertRaisesRegex(DownloadProblem, "صفحه وب"):
            self.download()

    def test_concurrent_download_cannot_share_partial_file(self):
        folder = self.root / "locked"
        with cache_lock(folder):
            with self.assertRaises(DownloadProblem):
                with cache_lock(folder):
                    self.fail("Second writer should not acquire the cache lock")


if __name__ == "__main__":
    unittest.main()
