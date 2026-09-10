"""HTTP поверх stdlib: form, json, multipart. Все ошибки — StudyError.

Отличия от curl, из-за которых здесь явные заголовки: urllib по умолчанию представляется
`Python-urllib/3.12`. При ошибке обязательно читаем тело — GitVerse отвечает 400/422
с пустым телом, и без чтения пользователь увидит меньше, чем видел с curl.
"""
import json as jsonlib
import urllib.error
import urllib.parse
import urllib.request
import uuid

from .config import StudyError

UA = "study/1"


def multipart(fields, files):
    """fields: {имя: значение}, files: [(поле, имя файла, байты, тип)] → (тело, content-type)."""
    b = uuid.uuid4().hex
    out = bytearray()
    for key, value in (fields or {}).items():
        out += f'--{b}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
    for key, name, data, ctype in files or []:
        out += (f'--{b}\r\nContent-Disposition: form-data; name="{key}"; filename="{name}"\r\n'
                f'Content-Type: {ctype}\r\n\r\n').encode()
        out += data + b"\r\n"
    out += f"--{b}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={b}"


def _open(req, source, where, timeout):
    """Один поход в сеть. Тело ошибки читается обязательно: GitVerse отвечает 400/422
    с пустым телом, и без чтения пользователь увидит меньше, чем видел с curl."""
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        detail = (e.read() or b"")[:200].decode("utf-8", "replace").strip()
        raise StudyError(source, f"HTTP {e.code}" + (f": {detail}" if detail else " (пустой ответ)"),
                         where=where) from None
    except urllib.error.URLError as e:
        raise StudyError(source, f"нет связи: {e.reason}", where=where) from None


def raw(url, source, *, headers=None, timeout=600, where=None):
    """GET, отдающий байты: файлы курсов приходят не JSON."""
    head = {"User-Agent": UA}
    head.update(headers or {})
    return _open(urllib.request.Request(url, headers=head), source, where, timeout)


def request(url, source, *, method=None, headers=None, form=None, json_body=None,
            files=None, fields=None, timeout=120, where=None):
    """Один запрос. Возвращает разобранный JSON, либо текст, если это не JSON."""
    head = {"User-Agent": UA}
    head.update(headers or {})
    data = None

    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        head.setdefault("Content-Type", "application/x-www-form-urlencoded")
    elif json_body is not None:
        # Тело сериализуется как есть: GitVerse отвергает хвостовой перевод строки (422).
        data = jsonlib.dumps(json_body, ensure_ascii=False).encode()
        head["Content-Type"] = "application/json"
    elif files is not None:
        data, ctype = multipart(fields, files)
        head["Content-Type"] = ctype

    req = urllib.request.Request(url, data=data, headers=head,
                                 method=method or ("POST" if data is not None else "GET"))
    body = _open(req, source, where, timeout)

    if not body:
        return None
    try:
        return jsonlib.loads(body)
    except ValueError:
        return body.decode("utf-8", "replace")


def http_code(url, source, **kw):
    """Как request, но возвращает код ответа — для загрузок, где тело неинтересно."""
    try:
        request(url, source, **kw)
        return 201
    except StudyError as e:
        raise e
