import io
import ssl
import unittest
import urllib.error
import urllib.request

from study import local, net
from study.cli import kv
from study.config import Config, StudyError
from study.hosting import GitVerse, SourceCraft
from tests.fakes import patch


class LocalTest(unittest.TestCase):
    def test_repo_slug(self):
        for url in ("ssh://git@gitverse.ru:2222/owner/repo.git", "ssh://ssh.sourcecraft.dev/owner/repo.git",
                    "git@github.com:owner/repo.git", "https://github.com/owner/repo", ""):
            self.assertEqual(local.repo_slug(url), "owner/repo" if url else "")

    def test_lab_id(self):
        self.assertEqual(local.lab_id("1"), "01")
        self.assertEqual(local.lab_id(" LAB02 "), "02")
        for bad in ("hw1", "123", "x", ""):   # домашних у study answer нет: только labNN
            with self.assertRaises(StudyError):
                local.lab_id(bad)

    def test_video_keys(self):
        self.assertEqual(local.VIDEO_KEYS[:2], ["RUTUBE_PLAYLIST", "RUTUBE_LAB"])
        self.assertEqual(len(local.VIDEO_KEYS), 10)


class NetTest(unittest.TestCase):
    def test_certificate_and_connection_errors(self):
        def fail(reason):
            def urlopen(*_, **__):
                raise urllib.error.URLError(reason)
            return urlopen

        cert = ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED")
        patch(self, urllib.request, "urlopen", fail(cert))
        with self.assertRaises(StudyError) as e:
            net.send("https://x.example/", "moodle")
        self.assertEqual(e.exception.code, "certificate")
        self.assertIn("Install Certificates.command", e.exception.hint())
        patch(self, urllib.request, "urlopen", fail(OSError("refused")))
        with self.assertRaises(StudyError) as e:
            net.send("https://x.example/", "moodle")
        self.assertEqual((e.exception.code, e.exception.hint()), (None, None))
        self.assertIn("нет связи", e.exception.message)

    def test_retries(self):
        """Повторы: 502–504 и обрыв — до retries раз с паузой; 4xx, сертификат — сразу."""
        class Reply:
            status, headers = 200, {}

            def read(self):
                return b"ok"

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fails(*errors):
            queue = list(errors)

            def urlopen(*_, **__):
                e = queue.pop(0)
                if e is None:
                    return Reply()
                raise e
            return urlopen

        def http(code):
            # fp обязателен: в 3.8 без него read() падает, а настоящий urlopen его даёт всегда
            return urllib.error.HTTPError("https://x.example/", code, "err", {}, io.BytesIO())

        naps = []
        patch(self, net.time, "sleep", naps.append)
        patch(self, urllib.request, "urlopen", fails(http(502), OSError("reset"), None))
        self.assertEqual(net.send("https://x.example/", "moodle", retries=2)[2], b"ok")
        self.assertEqual(naps, [net.RETRY_PAUSE, net.RETRY_PAUSE])
        cert = urllib.error.URLError(ssl.SSLCertVerificationError(1, "CERTIFICATE_VERIFY_FAILED"))
        for bad, tries in ((http(502), 3), (http(400), 1), (cert, 1)):
            naps.clear()
            patch(self, urllib.request, "urlopen", fails(bad, bad, bad, None))
            with self.assertRaises(StudyError) as e:
                net.send("https://x.example/", "moodle", retries=2)
            self.assertEqual(len(naps), tries - 1, bad)
        self.assertEqual(e.exception.code, "certificate")
        patch(self, urllib.request, "urlopen", fails(http(503), None))
        with self.assertRaises(StudyError) as e:   # по умолчанию повторов нет
            net.send("https://x.example/", "moodle")
        self.assertIn("HTTP 503", e.exception.message)

    def test_multipart(self):
        body, ctype = net.multipart({"a": "1"},
                                    [("f", "x.bin", b"\x00\xff", "application/octet-stream")])
        boundary = ctype.split("boundary=")[1]
        self.assertIn(f'--{boundary}\r\nContent-Disposition: form-data; name="a"\r\n\r\n1\r\n'
                      .encode(), body)
        self.assertIn(b'filename="x.bin"\r\nContent-Type: application/octet-stream'
                      b'\r\n\r\n\x00\xff\r\n', body)
        self.assertTrue(body.endswith(f"--{boundary}--\r\n".encode()))


class CliTest(unittest.TestCase):
    def test_kv(self):
        self.assertEqual(kv(["a=1", "b=x=y", "a=2", "a=3"]), {"a": ["1", "2", "3"], "b": "x=y"})


class HostingTest(unittest.TestCase):
    def test_urls(self):
        cfg = Config("/nonexistent/config.env")
        gv, sc = GitVerse(cfg, repo="o/r"), SourceCraft(cfg, repo="org/r")
        self.assertEqual(gv.web_url("v1"), "https://gitverse.ru/o/r/releases/tag/v1")
        self.assertEqual(sc.web_url("v1"), "https://sourcecraft.dev/org/r/releases/v1")
        self.assertEqual(sc.localize("see https://gitverse.ru/o/r/commit/abc"),
                         "see https://gitverse.ru/o/r/commit/abc")   # без path — нечего подменять


if __name__ == "__main__":
    unittest.main()
