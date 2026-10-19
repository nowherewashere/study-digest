from kit.cli import add, dump, main, parser, pipe, read_text, table
from kit.config import Env
from kit.git import find_repo

from .client import HOSTS


def releases_text(rows, args):
    return table([[r["tag"] or "—", r.get("name") or "", str(len(r["assets"])),
                   r.get("status") or ""] for r in rows],
                 ["тег", "название", "файлов", "статус"]) or "релизов нет"


def build_parser(source):
    cls = HOSTS[source]

    def client(cfg, args):
        return cls(cfg, path=find_repo())

    p = parser(source, f"{cls.host}: релизы и файлы релизов. Репозиторий — из remote "
                       f"{cls.remote} текущего каталога или {cls.repo_key} в config.env.")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="команда")
    add(sub, "releases", "список релизов", pipe(client, lambda c, _: c.releases(), releases_text))
    s = add(sub, "release", "создать релиз", pipe(
        client, lambda c, a: c.release(a.tag, a.title, read_text(a.notes), sha=a.sha),
        lambda o, _: "Релиз {} создан: {}".format(o["tag"], o["url"])))
    s.add_argument("tag")
    s.add_argument("--title", required=True)
    s.add_argument("--notes", required=True, help="файл с описанием")
    s.add_argument("--sha", help="GitVerse: полный SHA; по умолчанию из тега")
    s = add(sub, "update", "изменить название или описание релиза", pipe(
        client, lambda c, a: c.update(a.tag, title=a.title, notes=read_text(a.notes)),
        lambda o, _: "Релиз {} обновлён: {}".format(o["tag"], o["url"])))
    s.add_argument("tag")
    s.add_argument("--title")
    s.add_argument("--notes", help="файл с описанием")
    s = add(sub, "asset", "загрузить файл в релиз", pipe(
        client, lambda c, a: c.asset(a.release, a.file, a.name),
        lambda o, _: "Загружено: " + o["name"]))
    s.add_argument("release", help="GitVerse: id релиза, SourceCraft: тег")
    s.add_argument("file")
    s.add_argument("--name", help="имя файла в релизе")
    s = add(sub, "api", "произвольный запрос", pipe(client, lambda c, a: c.api(a.path), dump))
    s.add_argument("path", help="например /repos/owner/repo/releases")
    return p


def gitverse(argv=None):
    return main(build_parser("gitverse"), Env, argv)


def sourcecraft(argv=None):
    return main(build_parser("sourcecraft"), Env, argv)
