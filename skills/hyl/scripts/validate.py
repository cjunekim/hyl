"""Part files plus a transcript ARE a merged log.md and its validation report.

Usage: python validate.py --rundir <DIR>

Always writes log.md (the parts in k order, blank-trimmed, newline-joined) and
validation.json. Exit 0 ok, 1 when any ERROR is reported, 2 when the rundir
cannot be loaded, 4 on bad args. Stdlib only; stdout is ASCII; artifacts are UTF-8.
"""
import argparse
import json
import pathlib
import re
import sys

LINE_RE = re.compile(r"^( *)\* \[(\d{2}):([0-5]\d):([0-5]\d)\] (.+)$")
EVENT_RE = re.compile(r"^\[(\d{2}):([0-5]\d):([0-5]\d)\] (.+)$")
BOLD_RE = re.compile(r"^\*\*(.+)\*\*$")
LETTER_RE = re.compile(r"[A-Za-z가-힣]")
HANGUL_RE = re.compile(r"[가-힣]")
QUOTE_RE = re.compile(r"「([^」]+)」")

SILENCE = "<Silence / Musical Interlude>"
INDENTS = (0, 2, 4)
GRID_S = 30
GAP_MARGIN_S = 5
BOUNDS_SLACK_S = 3
DURATION_SLACK_S = 2
EDGE_WARN_SLACK_S = 45
EDGE_SLACK_S = 60
NEAR_S = 2
MIN_LETTERS = 20
MIN_PART_LINES = 2
KO_MIN = 0.40
EN_MAX = 0.05


class LoadFailure(Exception):
    """A LoadFailure IS an unreadable rundir."""


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


def excerpt(s, n=80):
    """An excerpt IS a single-line, length-capped copy of a log line."""
    flat = " ".join(str(s).split())
    return flat if len(flat) <= n else flat[:n] + "..."


def trimmed(text):
    """A trimmed part IS its text without leading or trailing blank lines."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    first = next((i for i, ln in enumerate(lines) if ln.strip()), len(lines))
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), -1)
    return "\n".join(lines[first:last + 1])


def silence(line):
    """A line IS a silence marker when it is level-0 with the exact marker text."""
    return line["level"] == 0 and line["text"] == SILENCE


def header(line):
    """A line IS a section header when it is level-0 and wholly bold."""
    return line["level"] == 0 and bool(BOLD_RE.match(line["text"]))


def part_line_of(k, n, spans):
    """A part line IS a merged line number expressed within its own part file."""
    span = spans.get(k)
    return max(1, n - span[0] + 1) if span and span[2] and span[3] else 1


def collapse(text):
    """A collapsed string IS its words joined by single spaces."""
    return " ".join(str(text).split())


def transcript_rows(path):
    """The transcript rows ARE the (second, text) pair of every `[hh:mm:ss] text` line.

    The transcript is machine-generated, so a line that does not parse is a harness
    fault, not content: it fails the load rather than being silently skipped, which
    would quietly shrink the event set every coverage rule is measured against.
    """
    lines = [ln for ln in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
             if ln.strip()]
    rows = [(i, ln, EVENT_RE.match(ln)) for i, ln in enumerate(lines, 1)]
    unparsed = [(i, ln) for i, ln, m in rows if not m]
    if unparsed:
        raise LoadFailure("transcript.txt line %d is not an event line: %s"
                          % (unparsed[0][0], excerpt(unparsed[0][1])))
    if not rows:
        raise LoadFailure("transcript has no parseable events")
    return [(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), m.group(4))
            for _, _, m in rows]


def quote_haystack(rows):
    """The haystack IS every transcript text joined and whitespace-collapsed.

    Joining before matching is what lets a quote span adjacent caption fragments,
    which real speech routinely does — a sentence is rarely one caption event.
    """
    return collapse(" ".join(text for _, text in rows))


def merged(index, rundir):
    """The merge IS (rows, spans) for the indexed parts in k order.

    A row IS (k, 1-based merged line number, raw text); a span IS
    (first line number, last line number, file exists, non-blank count).
    """
    rows, spans, n = [], {}, 0
    for entry in sorted(index, key=lambda e: e["k"]):
        path = rundir / "parts" / ("part_%02d.md" % entry["k"])
        exists = path.exists()
        try:
            text = trimmed(path.read_text(encoding="utf-8-sig",
                                          errors="replace")) if exists else ""
        except OSError as exc:
            raise LoadFailure("part_%02d.md unreadable: %s" % (entry["k"], exc))
        part = text.split("\n") if text else []
        spans[entry["k"]] = (n + 1, n + len(part), exists, len([r for r in part if r.strip()]))
        rows.extend((entry["k"], n + i + 1, raw) for i, raw in enumerate(part))
        n += len(part)
    return rows, spans


def decoded(rows):
    """The decoded lines ARE the non-blank rows as line records."""
    matches = [(k, n, raw, LINE_RE.match(raw)) for k, n, raw in rows if raw.strip()]
    return [{"k": k, "n": n, "raw": raw,
             "indent": len(m.group(1)) if m else None,
             "level": len(m.group(1)) // 2 if m else None,
             "ts": (int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))) if m else None,
             "text": m.group(5) if m else raw.strip(),
             "ok": bool(m) and len(m.group(1)) in INDENTS}
            for k, n, raw, m in matches]


def findings_format(lines):
    """V1 findings ARE errors for lines breaking the line grammar or the indent set."""
    return [("error", ln["k"], "V1_LINE_FORMAT", ln["n"],
             "indent %s: %s" % (ln["indent"], excerpt(ln["raw"])))
            for ln in lines if not ln["ok"]]


def findings_monotonic(timed):
    """V2 findings ARE errors where a line's timestamp precedes its predecessor's."""
    return [("error", nxt["k"], "V2_MONOTONIC", nxt["n"],
             "%s follows %s" % (hms(nxt["ts"]), hms(cur["ts"])))
            for cur, nxt in zip(timed, timed[1:]) if nxt["ts"] < cur["ts"]]


def findings_bounds(timed, windows):
    """V3 findings ARE errors for lines outside their window's +/-3s range."""
    return [("error", ln["k"], "V3_BOUNDS", ln["n"],
             "ts %s outside window %d [%s - %s) +/-%ds"
             % (hms(ln["ts"]), ln["k"], windows[ln["k"]]["start_hms"],
                windows[ln["k"]]["end_hms"], BOUNDS_SLACK_S))
            for ln in timed
            if not (windows[ln["k"]]["start_s"] - BOUNDS_SLACK_S
                    <= ln["ts"] < windows[ln["k"]]["end_s"] + BOUNDS_SLACK_S)]


def owner_of(second, windows, fallback):
    """The owning window IS the one whose content range contains a transcript second."""
    return next((w["k"] for w in windows.values()
                 if w["start_s"] <= second < w["end_s"]), fallback)


def findings_grid(timed, events, windows):
    """V4 findings ARE errors for skipped transcript content and warnings for
    unmarked silence, wherever consecutive log timestamps sit more than 30s apart.

    A gap straddling a part boundary belongs to the window that OWNS the first
    uncovered event: the later window cannot log content below its own start.
    """
    out = []
    for cur, nxt in zip(timed, timed[1:]):
        gap = nxt["ts"] - cur["ts"]
        inside = [t for t in events if cur["ts"] + GAP_MARGIN_S < t < nxt["ts"] - GAP_MARGIN_S]
        if gap <= GRID_S:
            continue
        if inside:
            owner = nxt["k"] if cur["k"] == nxt["k"] else owner_of(inside[0], windows, nxt["k"])
            out.append(("error", owner, "V4_GRID_GAP", nxt["n"],
                        "gap %ds %s->%s, %d transcript events inside"
                        % (gap, hms(cur["ts"]), hms(nxt["ts"]), len(inside))))
        elif not (silence(cur) or silence(nxt)):
            out.append(("warning", nxt["k"], "V4_SILENCE_UNMARKED", nxt["n"],
                        "gap %ds %s->%s, no transcript content, no silence marker"
                        % (gap, hms(cur["ts"]), hms(nxt["ts"]))))
    return out


def findings_edge_uncovered(by_part, windows, events):
    """V4 findings ARE errors for transcript content the log never reaches at the two
    edges no cross-window gap can cover: the first window's head, the last window's tail.

    Interior under-coverage always sits between two consecutive log lines, so it is
    already reported as V4_GRID_GAP against the window that owns it. Only the video's
    opening and its ending have no neighbouring log line to form that gap, which is why
    the head arm is scoped to the first window and the tail arm to the last. On a
    single-window video both arms apply to it.
    """
    first_k, last_k = min(windows), max(windows)
    out = []
    for k, part in by_part.items():
        timed = [ln for ln in part if ln["ts"] is not None]
        if not timed:
            continue
        first_log = min(ln["ts"] for ln in timed)
        last_log = max(ln["ts"] for ln in timed)
        head = ([t for t in events if windows[k]["start_s"] <= t < first_log - EDGE_SLACK_S]
                if k == first_k else [])
        tail = ([t for t in events if last_log + EDGE_SLACK_S < t < windows[k]["end_s"]]
                if k == last_k else [])
        if head:
            out.append(("error", k, "V4_EDGE_UNCOVERED", part[0]["n"],
                        "head of window %d uncovered: %d transcript events between %s and %s "
                        "(first log line %s)"
                        % (k, len(head), hms(head[0]), hms(head[-1]), hms(first_log))))
        if tail:
            out.append(("error", k, "V4_EDGE_UNCOVERED", part[-1]["n"],
                        "tail of window %d uncovered: %d transcript events between %s and %s "
                        "(last log line %s)"
                        % (k, len(tail), hms(tail[0]), hms(tail[-1]), hms(last_log))))
    return out


def findings_first_header(by_part):
    """V5 findings ARE errors for parts that do not open with a bold section header."""
    return [("error", k, "V5_FIRST_HEADER", part[0]["n"],
             "part opens with %s" % excerpt(part[0]["raw"]))
            for k, part in by_part.items() if part and not header(part[0])]


def findings_hierarchy(leveled):
    """V5 findings ARE warnings for level jumps and for stray level-0 lines."""
    jumps = [("warning", nxt["k"], "V5_HIERARCHY", nxt["n"],
              "level %d follows level %d" % (nxt["level"] + 1, cur["level"] + 1))
             for cur, nxt in zip(leveled, leveled[1:]) if nxt["level"] > cur["level"] + 1]
    strays = [("warning", ln["k"], "V5_HIERARCHY", ln["n"],
               "top-level line is neither bold header nor silence marker: %s" % excerpt(ln["raw"]))
              for ln in leveled if ln["level"] == 0 and not header(ln) and not silence(ln)]
    return jumps + strays


def findings_language(by_part, language):
    """V6 findings ARE errors where a part's hangul share contradicts meta.language."""
    out = []
    for k, part in by_part.items():
        body = " ".join(ln["text"] for ln in part
                        if ln["ts"] is not None and not silence(ln))
        letters = LETTER_RE.findall(body)
        if not part or len(letters) < MIN_LETTERS:
            continue
        ratio = len(HANGUL_RE.findall(body)) / len(letters)
        low = language.startswith("ko") and ratio < KO_MIN
        high = language.startswith("en") and ratio > EN_MAX
        if low or high:
            out.append(("error", k, "V6_LANGUAGE", part[0]["n"],
                        "hangul ratio %.2f over %d letters %s bound %.2f for language %s"
                        % (ratio, len(letters), "below" if low else "above",
                           KO_MIN if low else EN_MAX, language)))
    return out


def findings_edge(by_part, windows, events):
    """V7 findings ARE warnings where a part's first or last log timestamp sits more
    than 45s away from the first or last transcript event of its window."""
    out = []
    for k, part in by_part.items():
        timed = [ln for ln in part if ln["ts"] is not None]
        content = [t for t in events if windows[k]["start_s"] <= t < windows[k]["end_s"]]
        if not timed or not content:
            continue
        for label, line, reference in (("start", timed[0], content[0]),
                                       ("end", timed[-1], content[-1])):
            if abs(line["ts"] - reference) > EDGE_WARN_SLACK_S:
                out.append(("warning", k, "V7_EDGE_COVERAGE", line["n"],
                            "%s slack %ds: log %s vs transcript %s"
                            % (label, abs(line["ts"] - reference), hms(line["ts"]),
                               hms(reference))))
    return out


def findings_duration(timed, duration):
    """V8 findings ARE errors for timestamps beyond the video's duration."""
    return [("error", ln["k"], "V8_DURATION", ln["n"],
             "ts %s exceeds duration %s" % (hms(ln["ts"]), hms(duration)))
            for ln in timed if ln["ts"] > duration + DURATION_SLACK_S]


def findings_empty(index, spans):
    """V9 findings ARE errors for missing or near-empty part files."""
    return [("error", entry["k"], "V9_EMPTY_PART", 1,
             "part_%02d.md %s" % (entry["k"], "is missing" if not spans[entry["k"]][2]
                                  else "has %d non-blank lines" % spans[entry["k"]][3]))
            for entry in index
            if not spans[entry["k"]][2] or spans[entry["k"]][3] < MIN_PART_LINES]


def findings_near(timed, events):
    """V10 findings ARE warnings for log timestamps with no transcript event nearby."""
    near = {t + d for t in events for d in range(-NEAR_S, NEAR_S + 1)}
    return [("warning", ln["k"], "V10_TS_NOT_IN_TRANSCRIPT", ln["n"],
             "no transcript event within +/-%ds of %s" % (NEAR_S, hms(ln["ts"])))
            for ln in timed if ln["ts"] not in near]


def findings_quotes(lines, haystack):
    """V11 findings ARE errors for bracketed quotes absent from the transcript.

    ONE-DIRECTIONAL by design: an anchor that cannot be found is a fabrication
    signal worth an error, but a line carrying NO anchor is never flagged here.
    Demanding anchors mechanically would open repair rounds no logger can close —
    judging which claims need support is the verifier's job, not the grammar's.
    """
    return [("error", ln["k"], "V11_QUOTE_NOT_IN_TRANSCRIPT", ln["n"],
             "quote at %s is not in the transcript: %s"
             % (hms(ln["ts"]) if ln["ts"] is not None else "?", ascii_safe(quote)))
            for ln in lines for quote in QUOTE_RE.findall(ln["text"])
            if collapse(quote) not in haystack]


def loaded(rundir):
    """The load IS (meta, index, transcript seconds) of a run directory."""
    try:
        meta = json.loads((rundir / "meta.json").read_text(encoding="utf-8"))
        index = json.loads((rundir / "windows" / "index.json").read_text(encoding="utf-8"))["windows"]
        rows = transcript_rows(rundir / "transcript.txt")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise LoadFailure("%s: %s" % (type(exc).__name__, exc))
    if meta.get("n_windows") != len(index):
        raise LoadFailure("meta n_windows %s disagrees with %d indexed windows"
                          % (meta.get("n_windows"), len(index)))
    try:
        duration = int(meta.get("duration_s") or 0)
    except (TypeError, ValueError):
        raise LoadFailure("meta duration_s is not a number: %r" % (meta.get("duration_s"),))
    if duration <= 0:
        raise LoadFailure("meta duration_s is %d; every line would fail V8 against it"
                          % duration)
    return meta, index, [t for t, _ in rows], quote_haystack(rows)


def validation(rundir):
    """The validation IS (log text, report dict) for a run directory."""
    meta, index, events, haystack = loaded(rundir)
    windows = {entry["k"]: entry for entry in index}
    rows, spans = merged(index, rundir)
    lines = decoded(rows)
    by_part = {entry["k"]: [ln for ln in lines if ln["k"] == entry["k"]]
               for entry in sorted(index, key=lambda e: e["k"])}
    timed = [ln for ln in lines if ln["ts"] is not None]
    leveled = [ln for ln in lines if ln["level"] is not None]

    findings = (findings_format(lines)
                + findings_monotonic(timed)
                + findings_bounds(timed, windows)
                + findings_grid(timed, events, windows)
                + findings_edge_uncovered(by_part, windows, events)
                + findings_first_header(by_part)
                + findings_hierarchy(leveled)
                + findings_language(by_part, str(meta.get("language") or ""))
                + findings_edge(by_part, windows, events)
                + findings_duration(timed, int(meta.get("duration_s") or 0))
                + findings_empty(index, spans)
                + findings_near(timed, events)
                + findings_quotes(lines, haystack))
    ordered = sorted(findings, key=lambda f: (f[3], f[2], f[1]))
    entries = {level: [{"window": w, "code": c, "line": n,
                        "part_line": part_line_of(w, n, spans), "detail": d}
                       for lv, w, c, n, d in ordered if lv == level]
               for level in ("error", "warning")}
    report = {"status": "fail" if entries["error"] else "pass",
              "n_log_lines": len(lines),
              "errors": entries["error"], "warnings": entries["warning"]}
    return "\n".join(raw for _, _, raw in rows) + "\n", report


def write_text(path, text):
    """A written artifact IS UTF-8 text with LF line endings."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def parser():
    """The parser IS the CLI contract."""
    cli = ArgParser(description="Merge and validate hyl part files.")
    cli.add_argument("--rundir", required=True)
    return cli


def main():
    rundir = pathlib.Path(parser().parse_args().rundir)
    try:
        log_text, report = validation(rundir)
    except LoadFailure as exc:
        sys.stderr.write("VALIDATE_LOAD_FAILED %s\n" % ascii_safe(exc))
        raise SystemExit(2)
    except Exception as exc:
        sys.stderr.write("VALIDATE_CRASHED %s\n" % ascii_safe(repr(exc)))
        raise SystemExit(2)
    write_text(rundir / "log.md", log_text)
    write_text(rundir / "validation.json",
               json.dumps(report, ensure_ascii=False, indent=1) + "\n")
    print("VALIDATE status=%s errors=%d warnings=%d"
          % (report["status"], len(report["errors"]), len(report["warnings"])))
    raise SystemExit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
