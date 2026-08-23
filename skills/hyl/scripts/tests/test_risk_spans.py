"""The risk-span suite IS offline proof that v2 targets structure, not vocabulary.

Synthetic run directories only, no network. Covers each signal family (S1 boundaries,
S2 self-labels, S3 transcript quality, S4 compression), the per-window budgets, and a
negative control that must stay quiet. Run:
    python test_risk_spans.py
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import risk_spans
from risk_spans import edge_seconds

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "risk_spans.py"
BASE = pathlib.Path(__file__).resolve().parent / "fixtures" / "base"

HEAD = "### WINDOW {k}/{n} -- LOG RANGE [{start} - {end})"
CONTENT = "### WINDOW CONTENT -- log ALL of this"


def ascii_safe(s):
    """The ascii-safe form IS the string with every non-ASCII character escaped."""
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def hms(s):
    """The hms form IS a floored second count as hh:mm:ss."""
    return "%02d:%02d:%02d" % (s // 3600, (s % 3600) // 60, s % 60)


def parse(stamp):
    """The seconds IS an hh:mm:ss string as an integer."""
    h, m, s = stamp.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def write(path, text):
    """A written artifact IS UTF-8 text with LF line endings."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def build(root, name, duration, bounds, rows, parts=None, language="ko"):
    """A synthetic run dir IS meta, index, window files and optional part files."""
    rundir = pathlib.Path(root) / name
    (rundir / "windows").mkdir(parents=True)
    index = [{"k": k, "file": "windows/window_%02d.txt" % k, "start_s": lo, "end_s": hi,
              "start_hms": hms(lo), "end_hms": hms(hi), "transcript_lines": 0}
             for k, (lo, hi) in enumerate(bounds, 1)]
    write(rundir / "meta.json", json.dumps({
        "id": "SYNTH00TEST", "url": "", "title": name, "duration_s": duration,
        "language": language, "track": {"lang": language, "kind": "auto"}, "chapters": [],
        "n_windows": len(bounds), "window_min": 30, "fetched_at": "2026-08-24T00:00:00"}))
    write(rundir / "windows" / "index.json", json.dumps({"windows": index}))
    for k, (lo, hi) in enumerate(bounds, 1):
        body = [HEAD.format(k=k, n=len(bounds), start=hms(lo), end=hms(hi)), CONTENT]
        body += ["[%s] %s" % (hms(t), text) for t, text in rows.get(k, [])]
        write(rundir / "windows" / ("window_%02d.txt" % k), "\n".join(body) + "\n")
    for k, lines in (parts or {}).items():
        (rundir / "parts").mkdir(exist_ok=True)
        write(rundir / "parts" / ("part_%02d.md" % k), "\n".join(lines) + "\n")
    return rundir


def score(rundir, window=1):
    """The scoring IS one window's risk payload after running the script on it."""
    got = subprocess.run([sys.executable, str(SCRIPT), "--rundir", str(rundir),
                          "--window", "%02d" % window],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=180)
    assert got.returncode == 0, "exit %d: %s" % (got.returncode, ascii_safe(got.stderr[:200]))
    assert got.stdout.isascii(), "stdout not ASCII: %s" % ascii_safe(got.stdout)
    risk = json.loads((rundir / "risk.json").read_text(encoding="utf-8"))
    return risk["windows"]["%02d" % window]


def reasons(payload):
    """The reasons ARE every distinct signal name across a window's spans."""
    return {reason.split("(")[0]
            for span in payload["spans"] for reason in span["why"].split(" | ")[0].split(",")}


def covering(payload, second):
    """The covering spans ARE those containing a second."""
    return [s for s in payload["spans"]
            if parse(s["start_hms"]) <= second <= parse(s["end_hms"])]


def check_adaptive_edges(root):
    """A short video IS edged proportionately, not swallowed whole."""
    assert edge_seconds(150) == 20, "150 s video edge = %d, want 20" % edge_seconds(150)
    assert edge_seconds(8281) == 90, "a long video's edge should cap at 90"
    assert edge_seconds(480) == 60, "a mid-length video's edge should scale"
    rundir = build(root, "edges", 150, [(0, 150)],
                   {1: [(t, "정상적인 강의 문장이 이어집니다") for t in range(5, 150, 10)]})
    payload = score(rundir)
    assert any("S1:video-start" in s["why"] for s in covering(payload, 5)), "no video-start zone"
    assert any("S1:video-end" in s["why"] for s in covering(payload, 145)), "no video-end zone"
    assert all(parse(s["end_hms"]) - parse(s["start_hms"]) <= 60 for s in payload["spans"]), \
        "a 150 s video was swallowed whole: %s" % ascii_safe(payload["spans"])
    return "S1 edges: a 150 s video uses EDGE_S=20 at both rims, never the whole video"


def check_window_seams(root):
    """A middle window IS suspect at both of its seams."""
    bounds = [(0, 600), (600, 1200), (1200, 1800)]
    rows = {k: [(t, "문장이 계속 이어지는 중입니다") for t in range(lo + 5, hi, 120)]
            for k, (lo, hi) in enumerate(bounds, 1)}
    payload = score(build(root, "seams", 1800, bounds, rows), 2)
    assert covering(payload, 610), "no zone at the opening seam of window 2"
    assert covering(payload, 1190), "no zone at the closing seam of window 2"
    assert "S1:window-boundary" in reasons(payload), "the seams are not labelled"
    return "S1 seams: window 2 carries boundary zones at both of its edges"


def check_silence(root):
    """A silence IS suspect at both of its rims."""
    rows = {1: [(t, "이어지는 문장입니다") for t in [100, 110, 120, 160, 170, 180]]}
    payload = score(build(root, "silence", 600, [(0, 600)], rows))
    assert covering(payload, 120) and covering(payload, 160), "the silence rims are uncovered"
    assert "S1:silence-edge" in reasons(payload), "the 40 s gap produced no silence-edge"
    return "S1 silence: a 40 s gap raises zones at both of its rims"


def check_self_labels(root):
    """The lines list IS the log's own evidence labels, addressed by part line."""
    part = ["* [00:00:05] **머리말**",
            "  * [00:00:10] 내용이 흐릿함(불명확: 어떤 말) 「어떤 말이 들립니다」",
            "  * [00:00:20] 인용만 있는 줄 「정확한 인용입니다」",
            "  * [00:00:30] 숫자 300개가 나오지만 인용은 없음",
            "  * [00:00:40] 평범한 서술"]
    rows = {1: [(t, "말이 이어집니다") for t in range(5, 300, 10)]}
    payload = score(build(root, "labels", 600, [(0, 600)], rows, {1: part}))
    kinds = {ln["part_line"]: ln["kind"] for ln in payload["lines"]}
    assert kinds == {2: "marker", 3: "anchor", 4: "unanchored-number"}, "labels wrong: %s" % kinds
    assert payload["signals"]["markers"] == 1 and payload["signals"]["anchors"] == 2, \
        "signal tallies wrong: %s" % payload["signals"]
    assert payload["signals"]["no_part"] is False, "no_part should be false"
    return "S2 labels: marker, anchor and unanchored-number land on the right part lines"


def check_no_part(root):
    """A window logged but not yet written IS still scored transcript-side."""
    rows = {1: [(t, "숫자 5개가 언급됩니다") for t in range(5, 400, 10)]}
    payload = score(build(root, "nopart", 600, [(0, 600)], rows))
    assert payload["signals"]["no_part"] is True, "no_part not set"
    assert payload["lines"] == [], "lines should be empty without a part file"
    assert payload["spans"], "transcript-side spans must still be emitted"
    assert "S4:compression" not in reasons(payload), "compression cannot exist without a part"
    return "S2 no_part: a partless window still yields S1/S3 spans and an empty lines list"


def check_quality(root):
    """The transcript's own weak spots ARE zones, each for its own reason."""
    rows = {1: [(50, "어 우리 당에서 어 가방이 아당"),
                (150, "있습니다."),
                (250, "예산은 5,억 원 규모입니다"),
                (350, "the entire sentence switches script here"),
                (450, "평범하고 충분히 긴 한국어 문장이 이어집니다")]}
    payload = score(build(root, "quality", 600, [(0, 600)], rows))
    found = reasons(payload)
    for second, reason in ((50, "S3:filler"), (150, "S3:interjection"),
                           (250, "S3:garble"), (350, "S3:script-switch")):
        assert reason in found, "%s missing: %s" % (reason, ascii_safe(sorted(found)))
        assert covering(payload, second), "%s is not covered by a span" % reason
    return "S3 quality: filler, interjection, garble and script-switch each raise their zone"


def check_interjection_needs_hangul(root):
    """An English transcript IS not one long interjection."""
    rows = {1: [(t, "a normal english sentence of some length") for t in range(5, 400, 10)]}
    payload = score(build(root, "english", 600, [(0, 600)], rows, language="en"))
    assert "S3:interjection" not in reasons(payload), \
        "English lines scored as Korean interjections: %s" % ascii_safe(payload["spans"])
    assert "S3:script-switch" not in reasons(payload), "script-switch fired outside a ko window"
    return "S3 guard: a zero-Hangul line is no interjection, so an English run stays quiet"


def check_compression(root):
    """A log line that swallowed a crowd of source lines IS suspect."""
    dense = [(t, "x" * 50) for t in range(100, 200, 5)]
    sparse = [(t, "짧음") for t in range(200, 600, 50)]
    part = ["* [00:00:00] **시작**"] + \
           ["  * [%s] 요약 줄" % hms(t) for t in (100, 200, 250, 300, 350, 400, 450, 500, 550)]
    payload = score(build(root, "compress", 600, [(0, 600)], {1: dense + sparse}, {1: part}))
    assert "S4:compression" in reasons(payload), "a 1000-char reach raised no compression zone"
    assert covering(payload, 150), "the dense reach is not covered"
    return "S4 compression: the log line absorbing 1000 chars is flagged, sparse ones are not"


def check_span_budget(root):
    """A window richer than its budget IS capped, and says so."""
    rows = {1: [(t, "value %d recorded" % t) for t in range(200, 2000, 200)]}
    payload = score(build(root, "spanbudget", 2000, [(0, 2000)], rows, language="en"))
    assert len(payload["spans"]) == risk_spans.MAX_SPANS, \
        "want %d spans, got %d" % (risk_spans.MAX_SPANS, len(payload["spans"]))
    assert "capped:" in payload["spans"][-1]["why"], \
        "the cap is silent: %s" % ascii_safe(payload["spans"][-1])
    total = sum(parse(s["end_hms"]) - parse(s["start_hms"]) for s in payload["spans"])
    assert total <= risk_spans.MAX_TOTAL_S, "budget overrun: %d s" % total
    return "budget: raw zones reduced to %d spans with the drop recorded" % risk_spans.MAX_SPANS


def check_lines_budget(root):
    """A log with more anchors than budget IS sampled evenly, and says so."""
    part = ["* [00:00:00] **시작**"] + \
           ["  * [%s] 인용 줄 「%d 번째 인용」" % (hms(t), t) for t in range(1, 101)]
    rows = {1: [(t, "말이 이어집니다") for t in range(1, 200, 5)]}
    payload = score(build(root, "linesbudget", 600, [(0, 600)], rows, {1: part}))
    assert payload["lines_capped"] is True, "100 anchors should cap the lines list"
    assert len(payload["lines"]) == risk_spans.MAX_LINES, \
        "want %d lines, got %d" % (risk_spans.MAX_LINES, len(payload["lines"]))
    numbers = [ln["part_line"] for ln in payload["lines"]]
    assert numbers == sorted(numbers), "the sample is not in part order"
    assert numbers[-1] - numbers[0] > risk_spans.MAX_LINES, \
        "the sample bunched instead of spanning the log: %s" % numbers[:5]
    return "budget: 100 anchors sampled evenly to %d lines, lines_capped set" % risk_spans.MAX_LINES


def check_negative_control(root):
    """The base fixture IS quiet: boundary zones only, nothing invented."""
    rundir = pathlib.Path(root) / "control"
    shutil.copytree(BASE, rundir)
    transcript = (rundir / "transcript.txt").read_text(encoding="utf-8").splitlines()
    body = ["### WINDOW 1/1 -- LOG RANGE [00:00:00 - 00:02:30)", CONTENT] + transcript
    write(rundir / "windows" / "window_01.txt", "\n".join(body) + "\n")
    payload = score(rundir)
    assert reasons(payload) <= {"S1:video-start", "S1:video-end"}, \
        "the control raised content signals: %s" % ascii_safe(sorted(reasons(payload)))
    assert payload["lines"] == [], "the control log carries no evidence labels"
    assert payload["signals"]["numbers"] == 0 and payload["signals"]["fillers"] == 0, \
        "control signals are not zero: %s" % payload["signals"]
    return "control: the base fixture yields S1 edges only, no content signals at all"


def main():
    root = tempfile.mkdtemp(prefix="hyl_riskv2_")
    try:
        for check in (check_adaptive_edges, check_window_seams, check_silence,
                      check_self_labels, check_no_part, check_quality,
                      check_interjection_needs_hangul, check_compression,
                      check_span_budget, check_lines_budget, check_negative_control):
            print("  %s" % check(root))
        print("RISK SPANS OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
