"""Risk spans ARE where a log is structurally most likely to be wrong.

Usage: python risk_spans.py --rundir <DIR> --window NN

v2 scores STRUCTURE, not vocabulary: risk is evidence weakness times assertion
strength, and both are computable for any subject. A domain word list was tried and
retired -- the one fabrication it ever had to catch (a sentence completed past the
end of the video) happened in a recording where that list scored nothing at all.

Four signal families, all deterministic:
  S1  boundary zones      -- video edges, window seams, the rims of silence
  S2  logger self-labels  -- the log's own uncertainty markers, quotes and bare numbers
  S3  transcript quality  -- fillers, interjections, digits, garbles, script switches
  S4  compression         -- log lines that absorbed an outsized amount of source

S1/S3/S4 become time `spans`; S2 becomes a `lines` list the verifier reads line by
line. Merged into `RUN_DIR\\risk.json`. Exit 0 whenever the window is readable (no
spans is a normal answer), 2 when it is not, 4 on bad args. Stdout is ASCII.
"""
import argparse
import json
import pathlib
import re
import sys

STAMP_RE = re.compile(r"\[(\d{2}):([0-5]\d):([0-5]\d)\]\s*(.*)$")
HANGUL_RE = re.compile(r"[가-힣]")
LETTER_RE = re.compile(r"[A-Za-z가-힣]")
DIGIT_RE = re.compile(r"\d")
GARBLE_RE = re.compile(r"\d,\s*[가-힣]")
CONTENT = "### WINDOW CONTENT -- log ALL of this"
MARGIN_AFTER = "### CONTEXT MARGIN (after) -- context only, do NOT log"

MARKER = "(불명확"
ANCHOR = "「"

EDGE_MAX_S = 90
EDGE_MIN_S = 20
WBOUND_S = 60
SIL_GAP_S = 30
SIL_EDGE_S = 30
FILLER_PAD_S = 20
SHORT_PAD_S = 15
INTERJECTION_PAD_S = 10
DENSITY_FLOOR_S = 30
COMPRESS_PAD_S = 20
COMPRESS_MIN_CHARS = 300
COMPRESS_DECILE = 0.9

MAX_SPANS = 8
MAX_TOTAL_S = 10 * 60
MAX_LINES = 80
AUTO_KEEP_MIN_REASONS = 3
AUTO_KEEP_MAX = 4
KIND_ORDER = ("marker", "unanchored-number", "anchor")

# Filler tokens count only as standalone words, so they never match inside a real
# word; two or more in one caption line is the signal, never a single one.
FILLERS = {"어", "음", "그", "저", "뭐", "아", "uh", "um", "ah"}
MIN_FILLERS = 2
# An interjection is a short standalone RESPONSE, not any short caption fragment.
# It needs at least one Hangul character (without that floor every line of an English
# transcript qualifies) AND a sentence-final ending: "있습니다." and a bare "네" count,
# a mid-sentence fragment like "중단하기로" does not. Auto-captions routinely drop the
# full stop, so the ending letter alone is enough.
INTERJECTION_MAX_HANGUL = 6
SENTENCE_FINAL_RE = re.compile(r"[다요까죠네예][.?]?$")
SCRIPT_SWITCH_RATIO = 0.3
SCRIPT_SWITCH_MIN_LETTERS = 4


class RiskFailure(Exception):
    """A RiskFailure IS a window that cannot be read."""


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


def content_of(text):
    """The content lines ARE a window's log range, without its context margins."""
    lines = text.replace("\r\n", "\n").split("\n")
    if CONTENT not in lines:
        return [ln for ln in lines if not ln.startswith("###")]
    end = lines.index(MARGIN_AFTER) if MARGIN_AFTER in lines else len(lines)
    return lines[lines.index(CONTENT) + 1:end]


def rows_of(lines):
    """The rows ARE the (second, text) pair of every timestamped line."""
    stamped = [STAMP_RE.search(ln) for ln in lines if ln.strip()]
    return [(int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)), m.group(4))
            for m in stamped if m]


def edge_seconds(duration):
    """The edge reach IS a share of the video, floored and capped.

    A fixed 90 s would swallow a three-minute video whole and tell the verifier
    nothing; a share keeps the zone proportionate at both extremes.
    """
    return min(EDGE_MAX_S, max(EDGE_MIN_S, duration // 8))


def zones_boundary(k, first_k, last_k, start, end, duration):
    """S1 zones ARE the video's rims and the seams between windows."""
    edge = edge_seconds(duration)
    out = []
    if k == first_k:
        out.append((0, edge, "S1:video-start"))
    if k == last_k:
        out.append((duration - edge, duration, "S1:video-end"))
    if k != first_k:
        out.append((start, start + WBOUND_S, "S1:window-boundary"))
    if k != last_k:
        out.append((end - WBOUND_S, end, "S1:window-boundary"))
    return out


def zones_silence(rows):
    """S1 zones ARE the rims of every silence, where a sentence can vanish."""
    return [zone
            for before, after in zip(rows, rows[1:]) if after[0] - before[0] > SIL_GAP_S
            for zone in ((before[0] - SIL_EDGE_S, before[0], "S1:silence-edge"),
                         (after[0], after[0] + SIL_EDGE_S, "S1:silence-edge"))]


def hangul_share(text):
    """The share IS (Hangul fraction of a line's letters, letter count)."""
    letters = LETTER_RE.findall(text)
    return (len(HANGUL_RE.findall(text)) / len(letters) if letters else 0.0), len(letters)


def zones_quality(rows, korean_window):
    """S3 zones ARE the places the transcript itself is least trustworthy."""
    out = []
    for second, text in rows:
        hangul = len(HANGUL_RE.findall(text))
        ratio, letters = hangul_share(text)
        if len([w for w in text.split() if w in FILLERS]) >= MIN_FILLERS:
            out.append((second - FILLER_PAD_S, second + FILLER_PAD_S, "S3:filler"))
        if 1 <= hangul <= INTERJECTION_MAX_HANGUL and SENTENCE_FINAL_RE.search(text.strip()):
            out.append((second - INTERJECTION_PAD_S, second + INTERJECTION_PAD_S,
                        "S3:interjection"))
        if DIGIT_RE.search(text):
            out.append((second - SHORT_PAD_S, second + SHORT_PAD_S, "S3:number"))
        if GARBLE_RE.search(text):
            out.append((second - SHORT_PAD_S, second + SHORT_PAD_S, "S3:garble"))
        if korean_window and letters >= SCRIPT_SWITCH_MIN_LETTERS and ratio < SCRIPT_SWITCH_RATIO:
            out.append((second - SHORT_PAD_S, second + SHORT_PAD_S, "S3:script-switch"))
    return out


def zones_compression(log_rows, rows, end):
    """S4 zones ARE log lines that swallowed far more source than their neighbours."""
    if not log_rows:
        return []
    reaches = list(zip([ts for ts, _ in log_rows],
                       [ts for ts, _ in log_rows[1:]] + [end]))
    absorbed = [(ts, nxt, sum(len(text) for second, text in rows if ts <= second < nxt))
                for ts, nxt in reaches]
    ranked = sorted(size for _, _, size in absorbed)
    cutoff = ranked[min(int(COMPRESS_DECILE * len(ranked)), len(ranked) - 1)]
    return [(ts - COMPRESS_PAD_S, nxt + COMPRESS_PAD_S, "S4:compression")
            for ts, nxt, size in absorbed if size >= max(cutoff, COMPRESS_MIN_CHARS)]


def clipped(zones, start, end):
    """The clipped zones ARE those trimmed to the window's content range."""
    return [(max(start, low), min(end, high), reason) for low, high, reason in zones
            if min(end, high) > max(start, low)]


def merged_zones(zones):
    """The spans ARE overlapping zones fused, each keeping a tally of its reasons."""
    out = []
    for low, high, reason in sorted(zones):
        if out and low <= out[-1]["end_s"]:
            out[-1]["end_s"] = max(out[-1]["end_s"], high)
            out[-1]["tally"][reason] = out[-1]["tally"].get(reason, 0) + 1
        else:
            out.append({"start_s": low, "end_s": high, "tally": {reason: 1}})
    return out


def why_of(tally):
    """The reason IS the distinct signals behind a span; only counted ones carry counts.

    A boundary zone exists once by construction, so a count there would be noise; an
    S3 or S4 reason earns its count because it says how many lines drove it.
    """
    return ",".join(reason if reason.startswith("S1:") else "%s(%d)" % (reason, count)
                    for reason, count in sorted(tally.items()))


def hits_of(span):
    """A span's hits ARE every S3/S4 occurrence plus one per distinct S1 zone type.

    S1 zones are structural and carry no occurrences of their own. Counting each as one
    keeps a purely structural span — the video's last minute, say — from scoring zero
    and vanishing, and that is the exact span that caught a truncated closing sentence.
    """
    return sum(1 if reason.startswith("S1:") else count
               for reason, count in span["tally"].items())


def score_of(span):
    """A span's score IS its hits per second, floored at 30 s.

    Hits rather than distinct reasons: intensity is what marks a stretch worth reading.
    Dividing by length stops a sprawling blob eating the budget; the floor stops the
    metric fetishizing five-second slivers.
    """
    return hits_of(span) / float(max(span["end_s"] - span["start_s"], DENSITY_FLOOR_S))


def budgeted(spans):
    """The kept spans ARE the auto-kept confluences plus the densest that still fit.

    A stretch where three or more DIFFERENT signals coincide is qualitatively different
    evidence from one signal repeated, so a few of those are kept outright instead of
    competing on score. They still spend from both budgets.
    """
    ranked = sorted(spans, key=lambda s: (-score_of(s), -hits_of(s), -len(s["tally"]),
                                          s["start_s"]))
    kept = [s for s in ranked if len(s["tally"]) >= AUTO_KEEP_MIN_REASONS][:AUTO_KEEP_MAX]
    chosen = {id(s) for s in kept}
    total = sum(s["end_s"] - s["start_s"] for s in kept)
    for span in ranked:
        length = span["end_s"] - span["start_s"]
        if id(span) in chosen:
            continue
        if len(kept) < MAX_SPANS and total + length <= MAX_TOTAL_S:
            kept.append(span)
            chosen.add(id(span))
            total += length
    return sorted(kept, key=lambda s: s["start_s"]), len(spans) - len(kept)


def span_records(spans, dropped):
    """The span records ARE the emitted spans, the last noting any cap."""
    records = [{"start_hms": hms(span["start_s"]), "end_hms": hms(span["end_s"]),
                "why": why_of(span["tally"])} for span in spans]
    if dropped and records:
        records[-1]["why"] += " | capped: %d dropped" % dropped
    return records


def kind_of(said):
    """A log line's kind IS what the logger's own protocol says about its evidence.

    Judged on the text AFTER the timestamp: every line carries digits in its own
    `[hh:mm:ss]`, so testing the whole line would label the entire log a number.
    """
    if MARKER in said:
        return "marker"
    if ANCHOR in said:
        return "anchor"
    return "unanchored-number" if DIGIT_RE.search(said) else ""


def self_labels(part_lines):
    """S2 lines ARE the log's own claims about its evidence, one record per line."""
    stamped = [(number, STAMP_RE.search(text)) for number, text in enumerate(part_lines, 1)]
    labelled = [(number, stamp, kind_of(stamp.group(4))) for number, stamp in stamped if stamp]
    return [{"part_line": number, "ts": "%s:%s:%s" % stamp.groups()[:3], "kind": kind}
            for number, stamp, kind in labelled if kind]


def sampled(lines):
    """The kept lines ARE all of them, or an evenly spaced sample within budget.

    Markers and bare numbers are kept whole — they are exactly what a verifier must
    read. Anchors are the compressible class, so an overflow thins them evenly rather
    than truncating the tail and leaving the end of a long log unexamined.
    """
    if len(lines) <= MAX_LINES:
        return lines, False
    ranked = {kind: [ln for ln in lines if ln["kind"] == kind] for kind in KIND_ORDER}
    kept = (ranked["marker"] + ranked["unanchored-number"])[:MAX_LINES]
    anchors, room = ranked["anchor"], MAX_LINES - len(kept)
    if room > 0 and anchors:
        step = len(anchors) / float(room)
        kept = kept + [anchors[min(int(i * step), len(anchors) - 1)] for i in range(room)]
    return sorted(kept, key=lambda ln: ln["part_line"]), True


def merged_risk(rundir, window, payload):
    """The risk file IS every scored window, with this one replaced."""
    path = rundir / "risk.json"
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError):
        current = {}
    scored = current.get("windows") if isinstance(current, dict) else {}
    scored = scored if isinstance(scored, dict) else {}
    scored[window] = payload
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps({"windows": scored}, ensure_ascii=False, indent=1) + "\n")


def read_text(path):
    """The text IS a file's UTF-8 content, a byte-order mark tolerated."""
    return path.read_text(encoding="utf-8-sig", errors="replace")


def run(args):
    """The run IS one window scored into the run's risk file."""
    rundir = pathlib.Path(args.rundir)
    window = args.window.zfill(2) if args.window.isdigit() else args.window
    try:
        meta = json.loads(read_text(rundir / "meta.json"))
        index = json.loads(read_text(rundir / "windows" / "index.json"))["windows"]
        window_text = read_text(rundir / "windows" / ("window_%s.txt" % window))
    except (OSError, ValueError, KeyError) as exc:
        raise RiskFailure("window %s is unreadable: %s" % (window, exc))

    entry = next((w for w in index if "%02d" % w["k"] == window), None)
    if entry is None:
        raise RiskFailure("window %s is not in the index" % window)
    duration = int(meta.get("duration_s") or 0)
    first_k, last_k = min(w["k"] for w in index), max(w["k"] for w in index)
    start, end = entry["start_s"], entry["end_s"]

    rows = rows_of(content_of(window_text))
    korean_window = str(meta.get("language") or "").startswith("ko")
    part_path = rundir / "parts" / ("part_%s.md" % window)
    no_part = not part_path.exists()
    part_lines = [] if no_part else read_text(part_path).split("\n")
    log_rows = rows_of(part_lines)

    zones = (zones_boundary(entry["k"], first_k, last_k, start, end, duration)
             + zones_silence(rows) + zones_quality(rows, korean_window)
             + zones_compression(log_rows, rows, end))
    spans, dropped = budgeted(merged_zones(clipped(zones, start, end)))
    lines, lines_capped = sampled(self_labels(part_lines))

    payload = {
        "spans": span_records(spans, dropped),
        "lines": lines,
        "signals": {
            "anchors": len([t for t in part_lines if ANCHOR in t]),
            "markers": len([t for t in part_lines if MARKER in t]),
            "fillers": len([1 for _, text in rows
                            if len([w for w in text.split() if w in FILLERS]) >= MIN_FILLERS]),
            "numbers": len([1 for _, text in rows if DIGIT_RE.search(text)]),
            "no_part": no_part,
        },
        "lines_capped": lines_capped,
    }
    merged_risk(rundir, window, payload)
    return "RISK window=%s spans=%d lines=%d" % (window, len(payload["spans"]), len(lines))


def parser():
    """The parser IS the CLI contract; usage errors exit 4."""
    cli = ArgParser(description="Score one window for structural fabrication risk.")
    cli.add_argument("--rundir", required=True)
    cli.add_argument("--window", required=True)
    return cli


def main():
    try:
        print(run(parser().parse_args()))
    except RiskFailure as exc:
        sys.stderr.write("RISK_FAILED %s\n" % ascii_safe(exc))
        raise SystemExit(2)
    except Exception as exc:
        sys.stderr.write("RISK_FAILED %s\n" % ascii_safe(repr(exc)))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
