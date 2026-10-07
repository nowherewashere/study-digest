import base64
import json
import os
import time
import unittest

from study.config import StudyError
from study.rutube import ACCESS_MARGIN, BASE, REFRESH_URL, UPLOAD_URL, Rutube, _extract_refresh
from tests.fakes import FakeNet, config, tmpdir


def jwt(**payload):
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{body}.sig"


def b64(s):
    return base64.b64encode(str(s).encode()).decode()


FRESH = jwt(exp=int(time.time()) + 3600, user_id=42)
STALE = jwt(exp=int(time.time()) + ACCESS_MARGIN - 10, user_id=42)


class RutubeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tmpdir(self)
        self.net = FakeNet().install(self)
        self.cfg = config(self.tmp)
        self.refresh, self.access, self.token = (self.tmp / n for n in
                                                 ("rt-refresh", "rt-access", "rt-token"))

    def rt(self, mode="auto"):
        return Rutube(self.cfg, mode=mode)


class AuthTest(RutubeCase):
    def test_auto_prefers_jwt_then_token(self):
        with self.assertRaises(StudyError) as e:
            self.rt()._auth_header()
        self.assertEqual(e.exception.code, "notoken")
        self.token.write_text("T0\n", encoding="utf-8")
        self.assertEqual(self.rt()._auth_header(), {"Authorization": "Token T0"})
        self.refresh.write_text("R1\n", encoding="utf-8")
        self.access.write_text(FRESH + "\n", encoding="utf-8")
        self.assertEqual(self.rt()._auth_header(), {"Authorization": "Bearer " + FRESH})
        self.assertEqual(self.rt("token")._auth_header(), {"Authorization": "Token T0"})
        self.assertEqual(self.rt("jwt")._auth_header(), {"Authorization": "Bearer " + FRESH})
        with self.assertRaises(StudyError) as e:
            self.rt("bogus")._auth_header()
        self.assertEqual(e.exception.code, "config")
        self.assertEqual(self.net.sent, [])

    def test_mint_cache_and_rotation(self):
        self.refresh.write_text("R1\n", encoding="utf-8")
        self.access.write_text(STALE + "\n", encoding="utf-8")
        self.net.reply("POST", REFRESH_URL, {"access_token": FRESH, "refresh_token": "R2"})
        r = self.rt("jwt")
        self.assertEqual(r._mint(), FRESH)
        req = self.net.sent[0]
        self.assertEqual((req["headers"]["Cookie"], req["data"]), ("refreshToken=R1", None))
        self.assertEqual(self.refresh.read_text(encoding="utf-8"), "R2\n")
        self.assertEqual(self.access.read_text(encoding="utf-8"), FRESH + "\n")
        if os.name == "posix":
            self.assertEqual(oct(self.access.stat().st_mode)[-3:], "600")
        self.assertEqual(r._mint(), FRESH)
        self.assertEqual(self.rt("jwt")._mint(), FRESH)
        self.assertEqual(len(self.net.sent), 1)

    def test_mint_keeps_refresh_without_rotation(self):
        self.refresh.write_text("R1\n", encoding="utf-8")
        self.net.reply("POST", REFRESH_URL, {"access_token": FRESH})
        self.rt("jwt")._mint()
        self.assertEqual(self.refresh.read_text(encoding="utf-8"), "R1\n")
        self.access.unlink()
        self.net.reply("POST", REFRESH_URL, {"detail": "invalid"})
        with self.assertRaises(StudyError) as e:
            self.rt("jwt")._mint()
        self.assertEqual(e.exception.code, "auth")
        self.refresh.unlink()
        with self.assertRaises(StudyError) as e:
            self.rt("jwt")._mint()
        self.assertEqual(e.exception.code, "notoken")

    def test_save_refresh_checks_before_writing(self):
        self.refresh.write_text("OLD\n", encoding="utf-8")
        self.net.reply("POST", REFRESH_URL, {"error": "x"})
        with self.assertRaises(StudyError):
            self.rt().save_refresh("refreshToken=BAD; ym_uid=1")
        self.assertEqual(self.refresh.read_text(encoding="utf-8"), "OLD\n")
        self.net.reply("POST", REFRESH_URL, {"access_token": FRESH, "refresh_token": "R2"})
        out = self.rt().save_refresh("refreshToken=R1; ym_uid=1")
        self.assertEqual(out, {"refresh_file": str(self.refresh), "ok": True})
        self.assertEqual(self.net.sent[1]["headers"]["Cookie"], "refreshToken=R1")
        self.assertEqual((self.refresh.read_text(encoding="utf-8"),
                          self.access.read_text(encoding="utf-8")), ("R2\n", FRESH + "\n"))
        self.assertEqual(_extract_refresh(" R9 "), "R9")
        with self.assertRaises(StudyError):
            self.rt().save_refresh("refreshToken=")

    def test_login_token_mode(self):
        self.net.reply("POST", BASE + "/accounts/token_auth/", {"token": "T1"})
        self.assertEqual(self.rt().login("a@b.c", "pw"),
                         {"token_file": str(self.token), "ok": True})
        self.assertEqual(self.net.sent[0]["json_body"], {"username": "a@b.c", "password": "pw"})
        self.assertNotIn("Authorization", self.net.sent[0]["headers"])
        self.assertEqual(self.token.read_text(encoding="utf-8"), "T1\n")
        self.net.reply("POST", "/accounts/token_auth/", {"non_field_errors": ["bad"]})
        with self.assertRaises(StudyError):
            self.rt().login("a@b.c", "pw")

    def test_channel_id(self):
        self.refresh.write_text("R1\n", encoding="utf-8")
        self.access.write_text(FRESH + "\n", encoding="utf-8")
        self.assertEqual(self.rt("jwt")._channel_id(), 42)
        self.access.write_text(jwt(exp=int(time.time()) + 3600,
                                   data={"user_info": {"id": 7}}) + "\n", encoding="utf-8")
        self.assertEqual(self.rt("jwt")._channel_id(), 7)
        self.access.write_text(jwt(exp=int(time.time()) + 3600) + "\n", encoding="utf-8")
        with self.assertRaises(StudyError) as e:
            self.rt("jwt")._channel_id()
        self.assertEqual(e.exception.code, "auth")
        self.assertEqual(Rutube._jwt_payload("not-a-jwt"), {})


class ApiTest(RutubeCase):
    def setUp(self):
        super().setUp()
        self.refresh.write_text("R1\n", encoding="utf-8")
        self.access.write_text(FRESH + "\n", encoding="utf-8")
        self.r = self.rt()

    def test_me_and_categories(self):
        self.net.reply("GET", BASE + "/video/person/?limit=5",
                       {"results": [{"id": "v1", "title": "ЛР 1", "video_url": "https://rutube.ru/video/v1/",
                                     "is_hidden": True}]})
        self.assertEqual(self.r.me(), [{"id": "v1", "title": "ЛР 1", "url": "https://rutube.ru/video/v1/",
                                        "hidden": True}])
        self.assertEqual(self.net.sent[0]["headers"], {"Authorization": "Bearer " + FRESH})
        self.net.reply("GET", "/video/category/",
                       [{"id": 13, "short_name": "misc", "name": "Разное"}])
        self.assertEqual(self.r.categories(), [{"id": 13, "short": "misc", "name": "Разное"}])
        self.assertNotIn("Authorization", self.net.sent[1]["headers"])

    def test_edit_fields(self):
        self.net.reply("PATCH", "/v2/video/v1/?client=vulp", {"title": "Новое"})
        self.r.edit("v1", title="Новое", description=None, category=13, age=16, is_hidden=False)
        self.assertEqual(self.net.sent[0]["json_body"],
                         {"title": "Новое", "category": 13, "is_hidden": False,
                          "age_restriction": 4})
        with self.assertRaises(StudyError) as e:
            self.r.edit("v1", title=None)
        self.assertEqual(e.exception.code, "usage")

    def test_playlists(self):
        self.net.reply("POST", "/playlist/custom/", {"id": 55, "title": "Лабы", "is_hidden": True})
        self.assertEqual(self.r.playlist_create("Лабы", hidden=True),
                         {"id": 55, "title": "Лабы", "hidden": True, "url": "https://rutube.ru/plst/55/"})
        self.assertEqual(self.net.sent[0]["json_body"], {"title": "Лабы", "is_hidden": True})
        self.net.reply("POST", "/playlist/custom/", None)
        self.assertIsNone(self.r.playlist_create("x")["url"])
        self.net.reply("GET", "/playlist/user/42/", {"results": [{"id": 55, "title": "Лабы",
                                                                   "videos_count": 2}]})
        self.assertEqual(self.r.playlists()[0]["url"], "https://rutube.ru/plst/55/")
        self.net.reply("POST", "/playlist/custom/update/v1/", {})
        self.r.playlist_add("55", "v1")
        self.assertEqual(self.net.sent[-1]["json_body"], {"include": [55], "exclude": []})

    def test_upload_url(self):
        self.net.reply("POST", BASE + "/video/", {"video_id": "v9"})
        self.net.reply("PATCH", "/v2/video/v9/?client=vulp", {})
        out = self.r.upload_url("https://example.org/a.mp4", title="ЛР 1", hidden=True, age=0)
        self.assertEqual(out, {"id": "v9", "url": "https://rutube.ru/video/v9/", "title": "ЛР 1",
                               "hidden": True})
        self.assertEqual(self.net.sent[0]["json_body"],
                         {"url": "https://example.org/a.mp4", "category_id": 13})
        self.assertEqual(self.net.sent[1]["json_body"],
                         {"title": "ЛР 1", "is_hidden": True, "age_restriction": 1})
        self.net.reply("POST", "/video/", {"detail": "quota"})
        with self.assertRaises(StudyError) as e:
            self.r.upload_url("https://example.org/b.mp4")
        self.assertEqual(e.exception.code, "upload")

    def test_upload_file_tus(self):
        f = self.tmp / "lab01.mp4"
        f.write_bytes(b"MOVIE")
        self.net.reply("POST", "/uploader/upload_session/?client=vulp&batch_id=",
                       {"sid": "S1", "video": "v7"})
        self.net.reply("PATCH", "/v2/video/v7/?client=vulp", {})
        self.net.reply("POST", UPLOAD_URL + "S1", b"", headers={"Upload-Offset": "5"})
        out = self.r.upload_file(f, category=13)
        self.assertEqual(out["title"], "lab01")
        sess, edit, tus = self.net.sent
        self.assertEqual(sess["json_body"], {"title": "lab01"})
        self.assertEqual(edit["json_body"], {"title": "lab01", "is_hidden": False, "category": 13})
        self.assertEqual(tus["data"], b"MOVIE")
        head = tus["headers"]
        self.assertEqual((head["Tus-Resumable"], head["Upload-Length"], head["Content-Type"],
                          head["Origin"]),
                         ("1.0.0", "5", "application/offset+octet-stream", "https://studio.rutube.ru"))
        self.assertEqual(head["Upload-Metadata"],
                         f"sessionId {b64('S1')},videoId {b64('v7')},userId {b64(42)}")
        self.assertNotIn("Authorization", head)

    def test_upload_file_errors(self):
        f = self.tmp / "a.mp4"
        f.write_bytes(b"MOVIE")
        self.net.reply("POST", "/uploader/upload_session/", {"sid": "S1"})
        with self.assertRaises(StudyError) as e:
            self.r.upload_file(f)
        self.assertIn("upload_session", e.exception.message)
        self.net.reply("POST", "/uploader/upload_session/", {"sid": "S2", "video": "v8"})
        self.net.reply("PATCH", "/v2/video/v8/", {})
        self.net.reply("POST", UPLOAD_URL + "S2", b"", headers={"Upload-Offset": "3"})
        with self.assertRaises(StudyError) as e:
            self.r.upload_file(f)
        self.assertEqual(e.exception.message, "загружено 3 из 5 байт")
