import ast
import io
import pathlib
import re
import tokenize
import unittest

DOCABLE = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
HERE = pathlib.Path(__file__).resolve().parents[1]
CALL = re.compile(r"(\.read_text|\.write_text|(?<![\w.])open)\($")


def calls(path):
    with tokenize.open(path) as f:
        tokens = list(tokenize.generate_tokens(f.readline))
    depth, start, args, out = 0, None, [], []
    for i, tok in enumerate(tokens):
        if start is None:
            if tok.string == "(" and CALL.search("".join(t.string for t in tokens[i - 2:i + 1])):
                start, depth, args = tok.start[0], 1, []
            continue
        depth += {"(": 1, ")": -1}.get(tok.string, 0)
        if depth == 0:
            out.append((start, args))
            start = None
        elif tok.type == tokenize.NAME:
            args.append(tok.string)
    return out


class EncodingTest(unittest.TestCase):
    def test_every_text_io_names_encoding(self):
        files = [*HERE.glob("src/study/*.py"), *HERE.glob("tests/*.py"), HERE / "study",
                 HERE / "install.py"]
        bad = [f"{f.relative_to(HERE)}:{line}" for f in files if f.exists()
               for line, args in calls(f) if "encoding" not in args]
        self.assertEqual(bad, [])


class NoCommentsTest(unittest.TestCase):
    def test_no_comments_or_docstrings(self):
        bad = []
        for f in [*HERE.glob("src/study/*.py"), *HERE.glob("tests/*.py"), HERE / "study",
                  HERE / "install.py"]:
            if not f.exists():
                continue
            name = f.relative_to(HERE)
            with tokenize.open(f) as fh:
                src = fh.read()
            for t in tokenize.generate_tokens(io.StringIO(src).readline):
                if t.type == tokenize.COMMENT and not t.string.startswith("# noqa") \
                        and not (t.start[0] == 1 and t.string.startswith("#!")):
                    bad.append(f"{name}:{t.start[0]}")
            for n in ast.walk(ast.parse(src)):
                if isinstance(n, DOCABLE) \
                        and ast.get_docstring(n, clean=False) is not None:
                    bad.append(f"{name}:{getattr(n, 'lineno', 1)}")
        self.assertEqual(bad, [])
