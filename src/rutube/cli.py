import argparse
import pathlib

from kit.cli import add, confirm_gate, dump, main, parser, pipe, read_text, table
from kit.config import Env, ToolError

from .client import DEFAULT_CATEGORY, Rutube

MODE = argparse.ArgumentParser(add_help=False)
MODE.add_argument("--mode", choices=["auto", "jwt", "token"], default="auto",
                  help="какой вход Rutube использовать (по умолчанию auto)")
SLOTS = ["playlist", "lab", "report", "presentation", "defense"]


def rt(cfg, args):
    return Rutube(cfg, mode=args.mode)


def anon(cfg, args):
    return Rutube(cfg)


def videos_table(rows):
    return table([[str(v["id"]), v["title"] or "", "скрыто" if v["hidden"] else "", v["url"] or ""]
                  for v in rows], ["id", "название", "", "ссылка"])


def dated_videos_table(rows):
    return table([[str(v["id"]), v["title"] or "", (v.get("created") or "")[:10], v["url"] or ""]
                  for v in rows], ["id", "название", "создано", "ссылка"])


def video_text(v, args):
    keys = [("id", "id"), ("title", "название"), ("is_hidden", "скрыто"),
            ("video_url", "ссылка"), ("duration", "длительность")]
    cat = (v.get("category") or {}).get("name")
    return "\n".join([f"{label}: {v.get(k)}" for k, label in keys] + [f"категория: {cat}"])


def edit_video(r, args):
    fields = {"title": args.title, "category": args.category, "age": args.age,
              "description": read_text(args.desc)}
    if args.hidden or args.visible:
        fields["is_hidden"] = not args.visible
    return r.edit(args.video_id, **fields)


def record(args, url):
    if not args.slot:
        return ""
    key = f"RUTUBE_{args.slot.upper()}"
    if args.env:
        Env(args.env).put(key, url)
        return f"\n{key} записан в {args.env}"
    return f"\n{key}={url}"


def cmd_playlist_create(cfg, args):
    p = rt(cfg, args).playlist_create(args.title, args.hidden)
    text = f"плейлист создан: {p['id']} {p['url'] or ''}".rstrip()
    return p, text + (record(args, p["url"]) if p["url"] else "")


def cmd_upload(cfg, args):
    if bool(args.file) == bool(args.url):
        raise ToolError("rutube", "укажи либо файл, либо --url (одно из двух)", code="usage")
    if args.env and not args.slot:
        raise ToolError("rutube", "--env пишет ссылку в строку RUTUBE_<SLOT>: нужен --slot",
                        code="usage")
    title = args.title or (pathlib.Path(args.file).stem if args.file else None)
    category = args.category or DEFAULT_CATEGORY
    age = 0 if args.age is None else args.age
    plan = {"source": args.url or args.file, "title": title, "category": category, "age": age,
            "hidden": args.hidden, "playlist": args.playlist, "env": args.env,
            "confirmed": bool(args.confirm)}
    lines = []
    if not args.confirm:
        size = f" ({pathlib.Path(args.file).stat().st_size} байт)" if args.file else ""
        lines = ["Что будет загружено на Rutube:",
                 f"  источник: {('URL ' + args.url) if args.url else args.file + size}",
                 f"  название: {title or '?'}",
                 f"  категория: {category}   возраст: {age}+",
                 f"  видимость: {'скрыто' if args.hidden else 'публично'}",
                 f"  плейлист: {args.playlist or 'нет'}",
                 "  ссылка: " + (f"RUTUBE_{args.slot.upper()} в {args.env}" if args.env
                                 else "только в выводе")]
    gate = confirm_gate(plan, lines, args,
                        "Загрузка публикует видео в твой аккаунт. Повтори с --confirm.")
    if gate:
        return gate
    r = rt(cfg, args)
    up = r.upload_url if args.url else r.upload_file
    v = up(args.url or args.file, title=title, description=read_text(args.desc),
           category=category, hidden=args.hidden, age=age)
    text = f"загружено: {v['id']} {v['url']}" + (" (скрыто)" if v["hidden"] else "")
    text += record(args, v["url"])
    if args.playlist:
        try:
            r.playlist_add(args.playlist, v["id"])
        except ToolError as e:
            v = {**v, "playlist_error": e.message}
            text += (f"\nв плейлист {args.playlist} не добавлено ({e.message}); видео ещё "
                     f"обрабатывается — через несколько минут: "
                     f"rutube playlist add {args.playlist} {v['id']}")
    return v, text


def slot_args(s, slots):
    s.add_argument("--slot", choices=slots, help="строка RUTUBE_<SLOT>= для tuis/labNN.env")
    s.add_argument("--env", help="файл tuis/labNN.env: записать туда ссылку (нужен --slot)")


def playlist_parsers(sub):
    p = sub.add_parser("playlist", help="плейлисты: list/create/add/remove/videos")
    ps = p.add_subparsers(dest="plcmd", required=True, metavar="действие")
    add(ps, "list", "свои плейлисты", pipe(
        rt, lambda r, _: r.playlists(), lambda o, _: videos_table(o) or "плейлистов нет"), MODE)
    s = add(ps, "create", "создать плейлист", cmd_playlist_create, MODE)
    s.add_argument("--title", required=True)
    s.add_argument("--hidden", action="store_true", help="скрытый плейлист")
    slot_args(s, ["playlist"])
    s = add(ps, "add", "добавить видео в плейлист", pipe(
        rt, lambda r, a: r.playlist_add(a.playlist_id, a.video_id),
        lambda _, a: f"видео {a.video_id} → плейлист {a.playlist_id}"), MODE)
    s.add_argument("playlist_id")
    s.add_argument("video_id")
    s = add(ps, "remove", "убрать видео из плейлиста", pipe(
        rt, lambda r, a: r.playlist_remove(a.playlist_id, a.video_id),
        lambda _, a: f"видео {a.video_id} убрано из плейлиста {a.playlist_id}"), MODE)
    s.add_argument("playlist_id")
    s.add_argument("video_id")
    s = add(ps, "videos", "состав плейлиста", pipe(
        rt, lambda r, a: r.playlist_videos(a.playlist_id),
        lambda o, _: dated_videos_table(o) or "плейлист пуст"), MODE)
    s.add_argument("playlist_id")


def build_parser():
    p = parser("rutube", "Rutube: вход, свои видео, плейлисты, загрузка.")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="команда")
    s = add(sub, "login", "режим token: вход по email и паролю (пароль не хранится); "
            "только для аккаунтов с паролем", pipe(
                anon, lambda r, a: r.login(a.email),
                lambda o, _: "Rutube: сохранён token (режим token): " + o["token_file"]))
    s.add_argument("--email")
    s = add(sub, "jwt", "режим jwt: сохранить refreshToken из cookie браузера (VK ID / Gazprom ID)",
            pipe(anon, lambda r, a: r.save_refresh(a.refresh),
                 lambda o, _: "Rutube: сохранён refresh_token (режим jwt): " + o["refresh_file"]))
    s.add_argument("--refresh", help="сам refreshToken или строка cookie; без флага спросит скрыто")
    add(sub, "me", "проверить вход: мои видео",
        pipe(rt, lambda r, _: r.me(),
             lambda o, _: videos_table(o) or "вход работает, видео пока нет"),
        MODE)
    s = add(sub, "api", "произвольный GET к rutube.ru/api",
            pipe(rt, lambda r, a: r.api(a.path), dump), MODE)
    s.add_argument("path", help="например /video/person/")
    add(sub, "categories", "список категорий Rutube (id для --category)", pipe(
        anon, lambda r, _: r.categories(),
        lambda o, _: table([[str(c["id"]), c["short"] or "", c["name"] or ""] for c in o],
                           ["id", "код", "название"])))
    s = add(sub, "video", "метаданные и состояние своего видео",
            pipe(rt, lambda r, a: r.video(a.video_id), video_text), MODE)
    s.add_argument("video_id")
    s = add(sub, "edit", "правка названия/описания/категории/видимости", pipe(
        rt, edit_video, lambda o, a: "готово: " + (o.get("title") or a.video_id)), MODE)
    s.add_argument("video_id")
    s.add_argument("--title")
    s.add_argument("--desc", help="файл с описанием")
    s.add_argument("--category", type=int, help="id категории (см. rutube categories)")
    s.add_argument("--age", type=int, choices=[0, 6, 12, 14, 16, 18], help="возрастное ограничение")
    s.add_argument("--hidden", action="store_true", help="сделать скрытым")
    s.add_argument("--visible", action="store_true", help="сделать публичным")
    playlist_parsers(sub)

    s = add(sub, "upload", "загрузить видео: файл (tus) или --url", cmd_upload, MODE)
    s.add_argument("file", nargs="?", help="локальный видеофайл (либо задать --url)")
    s.add_argument("--url", help="импорт по URL — Rutube скачает сам")
    s.add_argument("--title")
    s.add_argument("--desc", help="файл с описанием")
    s.add_argument("--category", type=int,
                   help=f"id категории (см. rutube categories; по умолчанию {DEFAULT_CATEGORY})")
    s.add_argument("--age", type=int, choices=[0, 6, 12, 14, 16, 18],
                   help="возраст (по умолчанию 0+)")
    s.add_argument("--hidden", action="store_true", help="загрузить скрытым")
    s.add_argument("--playlist", help="id плейлиста — сразу добавить туда")
    slot_args(s, SLOTS[1:])
    s.add_argument("--confirm", action="store_true", help="подтвердить загрузку (без него — план)")
    return p


def rutube(argv=None):
    return main(build_parser(), Env, argv)
