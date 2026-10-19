import argparse
import ctypes
import json
import pathlib
import sys

from .config import HERE, ToolError
from .git import git

JSON = argparse.ArgumentParser(add_help=False)
JSON.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                  help="машиночитаемый вывод")


def version(ref="HEAD", path=None):
    return git(path or HERE, "describe", "--tags", "--always", ref) or "?"


def table(rows, headers=None):
    rows = [[str(c) for c in r] for r in rows]
    if not rows:
        return ""
    data = ([list(headers)] if headers else []) + rows
    widths = [max(len(r[i]) for r in data) for i in range(len(data[0]))]
    out = []
    for i, r in enumerate(data):
        out.append("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
        if headers and i == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def read_text(path):
    return pathlib.Path(path).read_text(encoding="utf-8") if path else None


def dump(out, args):
    return json.dumps(out, ensure_ascii=False, indent=1)


def add(sub, name, doc, fn, *parents):
    s = sub.add_parser(name, help=doc, description=doc, parents=[JSON, *parents])
    s.set_defaults(fn=fn)
    return s


def pipe(target, call, show):
    def run(cfg, args):
        out = call(target(cfg, args), args)
        return out, show(out, args)
    return run


def confirm_gate(plan, lines, args, warning):
    if args.confirm:
        return None
    return plan, "\n".join([*lines, "", warning]), 1


class Version(argparse.Action):

    def __call__(self, parser, *_):
        print(f"{parser.prog} {version()}")
        parser.exit()


def parser(prog, description):
    p = argparse.ArgumentParser(prog=prog, description=description)
    p.add_argument("--json", action="store_true", help="машиночитаемый вывод")
    p.add_argument("--version", action=Version, nargs=0, help="версия по тегам git")
    return p


def main(p, make_cfg, argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv:
        p.print_help()
        return 0
    args = p.parse_args(argv)
    try:
        data, text, *rc = args.fn(make_cfg(), args)
        print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else text)
    except ToolError as e:
        print(e.text(), file=sys.stderr)
        if e.hint():
            print(e.hint(), file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("", file=sys.stderr)
        return 130
    return rc[0] if rc else 0


def windows_console():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    k = ctypes.windll.kernel32
    handle, mode = k.GetStdHandle(-11), ctypes.c_uint()
    if k.GetConsoleMode(handle, ctypes.byref(mode)):
        k.SetConsoleMode(handle, mode.value | 4)


def launch(entry):
    if sys.platform == "win32":
        windows_console()
    return entry()
