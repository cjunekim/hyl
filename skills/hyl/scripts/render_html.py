"""A merged log plus its meta ARE one self-contained, deep-linking HTML page.

Usage: python render_html.py --rundir <DIR>

Reads log.md, meta.json and ../assets/template.html; writes <slug>.html into the
rundir. Exit 0 ok, 1 on an unrenderable log or a self-check failure, 4 on bad
args. Stdlib only; stdout is ASCII; the page is UTF-8.
"""
import argparse
import datetime
import html
import json
import pathlib
import re
import sys

LINE_RE = re.compile(r"^( *)\* \[(\d{2}):([0-5]\d):([0-5]\d)\] (.+)$")
BOLD_RE = re.compile(r"^\*\*(.+)\*\*$")
LANG_RE = re.compile(r"[a-z]{2,3}")
UNSAFE_RE = re.compile(r"""[<>:"/\\|?*\x00-\x1f'`]""")
RESERVED_RE = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)
TS_LINK_RE = re.compile(r'<a class="ts" href="[^"]*&t=(\d+)s"[^>]*>\[(\d{2}:\d{2}:\d{2})\]</a>')
TOC_HREF_RE = re.compile(r'<a href="#(s-\d+)">')
SECTION_ID_RE = re.compile(r'id="(s-\d+)"')

SILENCE = "<Silence / Musical Interlude>"
SLUG_MAX = 48
MANIFEST = ".hyl_outputs"
TOKENS = ("__LANG__", "__TITLE__", "__VIDEO_URL__", "__META_LINE__",
          "__TOC_ITEMS__", "__SECTIONS__", "__GENERATED__", "__BANNER__")


class RenderFailure(Exception):
    """A RenderFailure IS an unrenderable run directory or a failed self-check."""


class ArgParser(argparse.ArgumentParser):
    """An ArgParser IS an argparse parser whose usage errors exit 4."""

    def error(self, message):
        sys.stderr.write("BAD_ARGS %s\n" % ascii_safe(message))
        raise SystemExit(4)


def ascii_safe(s):
    """The ascii-safe form IS the string with every non-ASCII character escaped."""
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def hms(s):
    """The hms form IS a floored second count as hh:mm:ss."""
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def safe_name(text):
    """A safe name IS text reduced to a contained, non-reserved filename stem, or empty.

    Quotes and backticks go because the skill hands this path to PowerShell's
    `Invoke-Item '...'`; separators and dot-runs go so no value can climb out of
    the run directory; a Windows reserved device name cannot be a filename at all.
    """
    collapsed = "_".join(UNSAFE_RE.sub("", text or "").split())
    stem = collapsed.strip(" ._")[:SLUG_MAX].strip(" ._")
    return "" if not stem or RESERVED_RE.match(stem.split(".")[0]) else stem


def slug_of(title, vid):
    """The slug IS the title made filename-safe, with the video id as fallback.

    The fallback is sanitised by the same rules as the title, so a hostile id
    cannot become a path of its own.
    """
    slug = safe_name(title) or safe_name(vid)
    if not slug:
        return "hyl"
    return slug


def parsed(text):
    """The parsed lines ARE log.md's non-blank lines as render records.

    A record IS its level (indented by two per level, never jumping more than one
    past its predecessor), its second, its escaped text, and whether it is a bold
    section header or the silence marker.
    """
    raw_lines = [raw for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
                 if raw.strip()]
    records, previous = [], -1
    for n, raw in enumerate(raw_lines, 1):
        m = LINE_RE.match(raw)
        if not m:
            raise RenderFailure("log.md line %d is not a log line: %s" % (n, ascii_safe(raw)[:80]))
        level = min(len(m.group(1)) // 2, previous + 1)
        bold = BOLD_RE.match(m.group(5))
        records.append({
            "level": level,
            "ts": int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4)),
            "text": html.escape(bold.group(1) if bold and level == 0 else m.group(5)),
            "header": bool(bold) and level == 0,
            "silence": level == 0 and m.group(5) == SILENCE,
        })
        previous = level
    return records


def blocks_of(records):
    """The blocks ARE the log's sections, silence markers, and section-less bullets.

    A silence marker closes the section it follows, so the bullets after it open a
    new section-less block rather than rejoining the section above.
    """
    blocks = []
    for record in records:
        if record["header"]:
            blocks.append(["section", record, []])
        elif record["silence"]:
            blocks.append(["silence", record, []])
        else:
            if not blocks or blocks[-1][0] == "silence":
                blocks.append(["loose", None, []])
            blocks[-1][2].append(record)
    return blocks


def anchor(record, url):
    """An anchor IS the record's timestamp as a deep link into the video."""
    return ('<a class="ts" href="%s&t=%ds" target="_blank" rel="noopener">[%s]</a>'
            % (url, record["ts"], hms(record["ts"])))


def bullets(records, url):
    """The bullet html IS the records as properly nested <ul>/<li> levels."""
    out, depth, filled = [], 0, []
    for record in records:
        level = max(record["level"], 1)
        while depth < level:
            out.append("<ul>")
            filled.append(False)
            depth += 1
        while depth > level:
            out.append("</li>" if filled[depth - 1] else "")
            out.append("</ul>")
            filled.pop()
            depth -= 1
        if filled[depth - 1]:
            out.append("</li>")
        out.append("<li>%s %s" % (anchor(record, url), record["text"]))
        filled[depth - 1] = True
    while depth > 0:
        out.append("</li>" if filled[depth - 1] else "")
        out.append("</ul>")
        filled.pop()
        depth -= 1
    return [chunk for chunk in out if chunk]


def sections_html(blocks, url):
    """The sections html IS every block rendered, sections numbered from one."""
    out, index = [], 0
    for kind, record, children in blocks:
        if kind == "section":
            index += 1
            out.append('<details class="sec" id="s-%d" open><summary>%s <span class="hdr">%s</span></summary>'
                       % (index, anchor(record, url), record["text"]))
            out.extend(bullets(children, url))
            out.append("</details>")
        elif kind == "silence":
            out.append('<p class="silence">%s %s</p>' % (anchor(record, url), record["text"]))
        else:
            out.extend(bullets(children, url))
    return "\n".join(out)


def toc_html(blocks):
    """The toc html IS one linked entry per section, in document order."""
    headers = [record for kind, record, _ in blocks if kind == "section"]
    return "\n".join(
        '      <li><a href="#s-%d"><span class="toc-ts">[%s]</span> %s</a></li>'
        % (i, hms(record["ts"]), record["text"])
        for i, record in enumerate(headers, 1))


def self_checked(page, n_lines):
    """The checked page IS the rendering whose links, labels and anchors all agree."""
    links = TS_LINK_RE.findall(page)
    declared = page.count('class="ts"')
    mismatched = [(sec, label) for sec, label in links if hms(int(sec)) != label]
    dangling = sorted(set(TOC_HREF_RE.findall(page)) - set(SECTION_ID_RE.findall(page)))
    if not page.strip():
        raise RenderFailure("rendered page is empty")
    if mismatched:
        raise RenderFailure("%d deep links disagree with their label, first %s"
                            % (len(mismatched), mismatched[0]))
    if len(links) != declared:
        raise RenderFailure("%d well-formed ts links but %d ts spans" % (len(links), declared))
    if declared != n_lines:
        raise RenderFailure("%d ts links for %d non-blank log lines" % (declared, n_lines))
    if dangling:
        raise RenderFailure("toc anchors without a section: %s" % ", ".join(dangling))
    return page


def banner_of(rundir):
    """The banner IS a visible alert when the mechanical validation failed, else empty.

    Render still succeeds on a failing log — the gate is visibility, not refusal —
    so the page itself has to say so rather than looking like a clean result.
    """
    path = rundir / "validation.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        return ""
    if report.get("status") != "fail":
        return ""
    return ('<div class="hyl-degraded" role="alert">VALIDATION FAILED - %d error(s). '
            'This log is incomplete or malformed; see validation.json.</div>'
            % len(report.get("errors") or []))


def whole_number(value):
    """A whole number IS an integer reading of a report field, zero when it is not one."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def verify_of(rundir):
    """The verification status IS (banner html, footer suffix) read from verify.json.

    Absent, unreadable and malformed all mean the same thing — nobody has checked
    this log — so they all raise the amber banner rather than crashing or, worse,
    silently rendering a page that looks verified.
    """
    path = rundir / "verify.json"
    try:
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        report = {}
    report = report if isinstance(report, dict) else {}
    status = str(report.get("status") or "none")
    if status in ("clean", "repaired_clean"):
        return "", " · verified %s, %d spans, %s" % (
            str(report.get("mode") or "unknown"), whole_number(report.get("spans_checked")),
            "clean" if status == "clean" else "repaired-clean")
    if status == "findings_open":
        return ('<div class="hyl-unverified" role="alert">VERIFICATION FOUND UNRESOLVED '
                'ISSUES (%d) - see verify.md.</div>' % whole_number(report.get("findings"))), ""
    return ('<div class="hyl-unverified" role="alert">UNVERIFIED - semantic fidelity has '
            'not been checked for this log.</div>'), ""


def rendered(rundir, template):
    """The rendering IS (slug, page, link count, section count) for a run directory."""
    try:
        meta = json.loads((rundir / "meta.json").read_text(encoding="utf-8"))
        records = parsed((rundir / "log.md").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise RenderFailure("%s: %s" % (type(exc).__name__, exc))
    if not records:
        raise RenderFailure("log.md has no log lines")

    vid = meta.get("id") or ""
    language = str(meta.get("language") or "")
    language = language if LANG_RE.fullmatch(language) else "ko"
    url = "https://www.youtube.com/watch?v=%s" % html.escape(vid, quote=True)
    blocks = blocks_of(records)
    n_sections = len([1 for kind, _, _ in blocks if kind == "section"])
    verify_banner, verified = verify_of(rundir)
    values = {
        "__LANG__": html.escape(language, quote=True),
        "__TITLE__": html.escape(str(meta.get("title") or vid), quote=True),
        "__VIDEO_URL__": url,
        "__META_LINE__": html.escape("%s · %s · %d windows · %d lines" % (
            hms(int(meta.get("duration_s") or 0)), language,
            int(meta.get("n_windows") or 0), len(records)), quote=True),
        "__TOC_ITEMS__": toc_html(blocks),
        "__SECTIONS__": sections_html(blocks, url),
        "__GENERATED__": html.escape(
            "generated %s · hyl%s" % (datetime.date.today().isoformat(), verified),
            quote=True),
        "__BANNER__": banner_of(rundir) + verify_banner,
    }
    page = re.sub("|".join(map(re.escape, TOKENS)), lambda m: values[m.group(0)], template)
    return slug_of(meta.get("title"), vid), self_checked(page, len(records)), len(records), n_sections


def parser():
    """The parser IS the CLI contract."""
    cli = ArgParser(description="Render a validated hyl log as HTML.")
    cli.add_argument("--rundir", required=True)
    return cli


def main():
    rundir = pathlib.Path(parser().parse_args().rundir)
    template = pathlib.Path(__file__).resolve().parent.parent / "assets" / "template.html"
    try:
        slug, page, links, sections = rendered(rundir, template.read_text(encoding="utf-8"))
        out = rundir / ("%s.html" % slug)
        if rundir.resolve() not in out.resolve().parents:
            raise RenderFailure("output escapes the run directory: %s" % ascii_safe(out))
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(page)
        if not out.exists():
            raise RenderFailure("nothing written to %s: a Windows device name swallows the "
                                "write and still reports success" % ascii_safe(out))
        with open(rundir / MANIFEST, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out.name + "\n")
    except (RenderFailure, OSError) as exc:
        sys.stderr.write("RENDER_FAILED %s\n" % ascii_safe(exc))
        raise SystemExit(1)
    except Exception as exc:
        sys.stderr.write("RENDER_FAILED %s\n" % ascii_safe(repr(exc)))
        raise SystemExit(1)
    print("RENDER out=%s links=%d sections=%d" % (ascii_safe(out), links, sections))


if __name__ == "__main__":
    main()
