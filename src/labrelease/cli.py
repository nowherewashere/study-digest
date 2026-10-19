from kit.cli import add, confirm_gate, main, parser
from kit.config import Env

from . import answer, lab, publish


def cmd_publish(cfg, args):
    course = lab.current()
    p = publish.plan(cfg, course, args.num, args.tag)
    text = publish.render(p)
    if p["problems"]:
        return publish.public(p), text, 1
    gate = confirm_gate(publish.public(p), [text], args,
                        "Релиз публикуется на обоих хостингах. Повтори с --confirm.")
    if gate:
        return gate
    done = publish.apply(course, p)
    return ({**publish.public(p), "done": done},
            "\n".join(f"{d['source']}: {d['url']}" for d in done))


def cmd_answer(cfg, args):
    d = answer.build(cfg, lab.current(), args.num, args.tag)
    return d, answer.render(d), *([1] if d["blocked"] or d["created"] else [])


def build_parser():
    p = parser("labrelease", "Лаба под запись: релиз с файлами на GitVerse и SourceCraft, "
                             "ответ в ТУИС со ссылками. Запускать из репозитория курса.")
    sub = p.add_subparsers(dest="cmd", required=True, metavar="команда")
    s = add(sub, "publish", "релиз лабы на обоих хостингах: проверить, создать, догрузить файлы",
            cmd_publish)
    s.add_argument("num", help="номер лабораторной работы (NN)")
    s.add_argument("--tag", help="тег релиза; по умолчанию последний")
    s.add_argument("--confirm", action="store_true", help="выполнить (без него — план)")
    s = add(sub, "answer", "текст ответа в ТУИС: tuis/labNN.md рядом с репозиторием", cmd_answer)
    s.add_argument("num", help="номер лабораторной работы (NN)")
    s.add_argument("--tag", help="тег релиза; по умолчанию последний")
    return p


def labrelease(argv=None):
    return main(build_parser(), Env, argv)
