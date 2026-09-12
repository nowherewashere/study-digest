"""Rutube: старый, но живой API. Токен — DRF TokenAuthentication, бессрочный."""
import getpass
import os

from . import net
from .config import StudyError

BASE = "https://rutube.ru/api"


class Rutube:
    source = "rutube"

    def __init__(self, cfg):
        self.cfg = cfg

    def _token_path(self):
        return self.cfg.path_of("RUTUBE_TOKEN_FILE")

    def login(self, email=None, password=None):
        """Пароль спрашивается скрыто и на диск не попадает — сохраняется только токен."""
        email = email or input("Rutube email: ").strip()
        password = password or getpass.getpass("Rutube пароль: ")
        out = net.request(BASE + "/accounts/token_auth/", self.source,
                          json_body={"username": email, "password": password},
                          where="token_auth") or {}
        token = out.get("token") if isinstance(out, dict) else None
        if not token:
            raise StudyError(self.source, f"токен не получен: {out}", code="auth")
        path = self._token_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        path.write_text(token + "\n")
        os.chmod(path, 0o600)
        return {"token_file": str(path), "ok": True}

    def api(self, path, **kw):
        head = {"Authorization": "Token " + self.cfg.token("RUTUBE_TOKEN_FILE")}
        return net.request(BASE + path, self.source, headers=head, where=path, **kw)

    def me(self):
        """Проверка токена: список своих видео, первая страница."""
        out = self.api("/video/person/?limit=5") or {}
        rows = out.get("results", []) if isinstance(out, dict) else []
        return [{"id": v.get("id"), "title": v.get("title"), "url": v.get("video_url"),
                 "hidden": v.get("is_hidden")} for v in rows]
