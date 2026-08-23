"""Grammar sync IS validate.py and render_html.py agreeing on the log-line grammar.

The two scripts parse log.md independently, so a regex edited in one and not the
other makes the validator and the renderer silently disagree about what a log
line is. This turns that drift into a red test. Run:
    python test_grammar_sync.py
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import render_html
import validate

SHARED = [
    ("LINE_RE", lambda module: module.LINE_RE.pattern),
    ("BOLD_RE", lambda module: module.BOLD_RE.pattern),
    ("SILENCE", lambda module: module.SILENCE),
]


def main():
    for name, read in SHARED:
        mine, theirs = read(validate), read(render_html)
        assert mine == theirs, "%s drifted: validate %r vs render_html %r" % (name, mine, theirs)
        print("  %-8s in sync" % name)
    print("GRAMMAR SYNC OK")


if __name__ == "__main__":
    main()
