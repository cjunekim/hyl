"""G5 IS proof that every skill script imports nothing outside the stdlib allowlist.

Usage: python check_stdlib_only.py
Parses each .py file under scripts/ and compares its import roots against the
allowlist. Exit 0 and `G5 PASS` when clean; AssertionError otherwise.
"""
import ast
import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[1]
ALLOWED = {"sys", "os", "re", "json", "argparse", "subprocess", "shutil", "pathlib",
           "html", "datetime", "time", "math", "io", "tempfile", "ast", "glob",
           "unicodedata", "hashlib"}
LOCAL = {"fetch_transcript", "validate", "render_html", "risk_spans"}


def ascii_safe(s):
    """The ascii-safe form IS the string with every non-ASCII character escaped."""
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def roots(tree):
    """The import roots ARE the first dotted component of every module a file imports."""
    plain = {alias.name.split(".")[0]
             for node in ast.walk(tree) if isinstance(node, ast.Import)
             for alias in node.names}
    froms = {(node.module or "").split(".")[0]
             for node in ast.walk(tree)
             if isinstance(node, ast.ImportFrom) and not node.level}
    return (plain | froms) - {""}


def main():
    files = sorted(SCRIPTS.rglob("*.py"))
    used = {path: roots(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
            for path in files}
    offenders = {path: sorted(names - ALLOWED - LOCAL)
                 for path, names in used.items() if names - ALLOWED - LOCAL}
    for path, names in used.items():
        print("  %-28s %s" % (ascii_safe(path.relative_to(SCRIPTS).as_posix()),
                              " ".join(sorted(names))))
    assert not offenders, "non-stdlib imports: %s" % ascii_safe(
        {path.name: names for path, names in offenders.items()})
    print("G5 PASS files=%d" % len(files))


if __name__ == "__main__":
    main()
