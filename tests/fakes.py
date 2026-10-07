import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from unittest import mock

from study import net
from study.config import Config

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
NOW = 1789538400
DAY = 86400
ENV = re.compile(r"^(TUIS_|GITVERSE_|SOURCECRAFT_|DIGEST_|RUTUBE_|GV_REPO$|SC_REPO$)")


def fixture(name):
    p = FIXTURES / name
    if p.suffix:
        return p.read_text(encoding="utf-8")
    return json.loads(p.with_suffix(".json").read_text(encoding="utf-8"))


def patch(case, obj, attr, value):
    p = mock.patch.object(obj, attr, value)
    p.start()
    case.addCleanup(p.stop)


def passed(case):
    o = getattr(case, "_outcome", None)
    if o is None:
        return True
    if hasattr(o, "errors"):
        return not any(exc for _, exc in o.errors)
    return not any(t is case for t, _ in o.result.failures + o.result.errors)


def tmpdir(case):
    d = pathlib.Path(tempfile.mkdtemp()).resolve()
    case.addCleanup(shutil.rmtree, d, True)
    (d / "gitconfig").write_text("", encoding="utf-8")
    clean = {k: v for k, v in os.environ.items() if not ENV.match(k)}
    clean.update({"GIT_CONFIG_GLOBAL": str(d / "gitconfig"), "GIT_CONFIG_NOSYSTEM": "1"})
    p = mock.patch.dict(os.environ, clean, clear=True)
    p.start()
    case.addCleanup(p.stop)
    return d


def config(tmp, extra=""):
    p = tmp / "config.env"
    p.write_text("TUIS_URL=https://tuis.example\nTUIS_TOKEN=test-token\n"
                 "GITVERSE_TOKEN=gv-token\nSOURCECRAFT_TOKEN=sc-token\n"
                 f"DIGEST_STATE={tmp / '.state.json'}\n"
                 f"RUTUBE_TOKEN_FILE={tmp / 'rt-token'}\n"
                 f"RUTUBE_REFRESH_FILE={tmp / 'rt-refresh'}\n"
                 f"RUTUBE_ACCESS_FILE={tmp / 'rt-access'}\n" + extra, encoding="utf-8")
    return Config(p)



GIT = ["git", "-c", "user.name=study", "-c", "user.email=study@example.org",
       "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "init.defaultBranch=master"]


def git(path, *args):
    return subprocess.run([*GIT, "-C", str(path), *args], capture_output=True, encoding="utf-8",
                          check=True).stdout.strip()


def repo(path, remotes=None, tag=None):
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q")
    for name, url in (remotes or {}).items():
        git(path, "remote", "add", name, url)
    git(path, "commit", "-q", "--allow-empty", "-m", "chore: init")
    if tag:
        git(path, "tag", "-a", tag, "-m", tag)
    return path



def decode(headers, data):
    out = {"form": None, "json_body": None, "fields": None, "files": None}
    ctype = (headers or {}).get("Content-Type", "")
    if data is None:
        return out
    if ctype.startswith("application/x-www-form-urlencoded"):
        out["form"] = dict(urllib.parse.parse_qsl(data.decode(), keep_blank_values=True))
    elif ctype.startswith("application/json"):
        out["json_body"] = json.loads(data)
    elif ctype.startswith("multipart/form-data"):
        out["fields"], out["files"] = {}, {}
        boundary = ("--" + ctype.split("boundary=")[1]).encode()
        for part in data.split(boundary)[1:-1]:
            head, _, body = part[2:].partition(b"\r\n\r\n")
            head, body = head.decode(), body[:-2]
            name = re.search(r'(?<!file)name="([^"]*)"', head).group(1)
            fname = re.search(r'filename="([^"]*)"', head)
            if fname:
                ct = re.search(r"Content-Type: (.*)", head).group(1)
                out["files"][name] = (fname.group(1), body, ct)
            else:
                out["fields"][name] = body.decode()
    return out


def encode(body):
    if body is None:
        return b""
    return body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()


class FakeNet:
    def __init__(self):
        self.queue = []
        self.sent = []

    def install(self, case):
        patch(case, net, "send", self.send)
        case.addCleanup(lambda: passed(case) and self.done())
        return self

    def reply(self, method, what, body=None, headers=None):
        what = (what,) if isinstance(what, str) else tuple(what)
        self.queue.append((method.upper(), what, body, headers or {}))

    def drop(self, *what):
        self.queue = [q for q in self.queue if not set(what) <= set(q[1])]

    def done(self):
        left = [(m, " ".join(w)) for m, w, _, _ in self.queue]
        if left:
            raise AssertionError(f"ответы остались невостребованными: {left}")

    def calls(self, fn):
        return [r["form"] for r in self.sent if r["form"] and r["form"].get("wsfunction") == fn]

    def send(self, url, source, *, method=None, headers=None, data=None, timeout=600,
             where=None, retries=0):
        method = method or ("POST" if data is not None else "GET")
        rec = {"method": method, "url": url, "source": source, "where": where,
               "timeout": timeout, "retries": retries, "headers": dict(headers or {}),
               "data": data, **decode(headers, data)}
        self.sent.append(rec)
        head = f"{method} {url}"
        pairs = [f"{k}={v}" for k, v in (rec["form"] or {}).items()]
        tokens = set(pairs) | set((rec["form"] or {}).values())
        for i, (m, what, body, hd) in enumerate(self.queue):
            if m == method and all(w in head or w in tokens for w in what):
                del self.queue[i]
                if isinstance(body, Exception):
                    raise body
                return 200, hd, encode(body)
        raise AssertionError(f"нет ответа для {head} {' '.join(pairs)}")
