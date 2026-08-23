"""The fixture suite IS the base rundir mutated into known-bad variants and validated.

Each variant states the exact text operation applied to the copy, the exit code
validate.py must return, and the distinct ERROR codes it must report. Run:
    python run_fixture_tests.py
Prints one ASCII line per fixture, then `FIXTURES OK`.
"""
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
BASE = HERE / "fixtures" / "base"
SCRIPTS = HERE.parent
VALIDATE = SCRIPTS / "validate.py"
RENDER = SCRIPTS / "render_html.py"

PART = "parts/part_01.md"
TRANSCRIPT = "transcript.txt"

F2_FROM = "  * [00:00:16] 첫 번째 주제 소개"
F2_TO = "  * 첫 번째 주제 소개"

F3_FROM = "    * [00:00:31] 개념의 중요성 강조\n    * [00:00:46] 예시 제시\n"

F4_TRANSCRIPT_FROM = ("[00:01:01] 두 번째 주제로 넘어갑니다\n"
                      "[00:01:16] 여기서 핵심은 반복입니다\n"
                      "[00:01:31] 실습을 해 보겠습니다\n"
                      "[00:01:46] 결과를 확인해 봅시다\n")
F4_PART_FROM = ("* [00:01:01] **두 번째 주제와 실습**\n"
                "  * [00:01:01] 두 번째 주제 전환\n"
                "  * [00:01:16] 핵심은 반복\n"
                "  * [00:01:31] 실습 진행\n"
                "    * [00:01:46] 결과 확인")
F4_PART_TO = "* [00:00:46] <Silence / Musical Interlude>"

F5_FROM = "    * [00:00:31] 개념의 중요성 강조"
F5_TO = "   * [00:00:31] 개념의 중요성 강조"

F6_PART = """* [00:00:01] **Lecture opening and first topic**
  * [00:00:01] Greeting and start of the lecture
  * [00:00:16] Introduction of the first topic
    * [00:00:31] Emphasis on the importance of the concept
    * [00:00:46] An example is given
* [00:01:01] **Second topic and practice**
  * [00:01:01] Transition to the second topic
  * [00:01:16] The key point is repetition
  * [00:01:31] Hands-on practice
    * [00:01:46] Checking the results
* [00:02:01] **Wrap-up**
  * [00:02:01] Summary of today's content
  * [00:02:16] Closing remarks
"""

F7_FROM = "  * [00:01:16] 핵심은 반복\n  * [00:01:31] 실습 진행"
F7_TO = "  * [00:01:31] 핵심은 반복\n  * [00:01:16] 실습 진행"

F8_ADDED = "  * [00:03:30] 범위 밖 내용\n"

F10_FROM = "* [00:00:01] **강의 시작과 첫 번째 주제**"
F10_TO = "* [00:00:01] 강의 시작과 첫 번째 주제"

F11_TRANSCRIPT_FROM = ("[00:00:31] 이 개념은 매우 중요합니다\n"
                       "[00:00:46] 예를 들어 보겠습니다\n")

F12_FROM = ("* [00:01:01] **두 번째 주제와 실습**\n"
            "  * [00:01:01] 두 번째 주제 전환\n"
            "  * [00:01:16] 핵심은 반복\n"
            "  * [00:01:31] 실습 진행\n"
            "    * [00:01:46] 결과 확인\n"
            "* [00:02:01] **정리**\n"
            "  * [00:02:01] 내용 정리\n"
            "  * [00:02:16] 마무리 인사\n")

F15_FROM = "  * [00:00:16] 첫 번째 주제 소개"
F15_TO = "  * [00:60:00] 첫 번째 주제 소개"

F16_ADDED = "  * [00:02:16] 마무리 인사를 재확인 「다음 시간에 뵙겠습니다」\n"
F17_ADDED = "  * [00:02:16] 마무리 인사를 재확인 「존재하지 않는 인용」\n"
CROSS_ADDED = ("  * [00:02:16] 마무리 흐름 요약 "
               "「오늘 내용을 정리하겠습니다 다음 시간에 뵙겠습니다」\n")

F13_FROM = ("* [00:00:01] **강의 시작과 첫 번째 주제**\n"
            "  * [00:00:01] 인사와 강의 시작\n"
            "  * [00:00:16] 첫 번째 주제 소개\n"
            "    * [00:00:31] 개념의 중요성 강조\n"
            "    * [00:00:46] 예시 제시\n"
            "* [00:01:01] **두 번째 주제와 실습**\n"
            "  * [00:01:01] 두 번째 주제 전환\n"
            "  * [00:01:16] 핵심은 반복\n"
            "  * [00:01:31] 실습 진행\n"
            "    * [00:01:46] 결과 확인\n")

DELETE = object()


def swap(old, new):
    """An operation IS the pure replacement of one exact substring by another."""
    return lambda text: text.replace(old, new)


def append(added):
    """An operation IS the pure addition of a line at the end of the file."""
    return lambda text: text + added


def whole(new):
    """An operation IS the pure replacement of the file's entire content."""
    return lambda _text: new


def remove():
    """An operation IS the removal of the file from the run directory."""
    return lambda _text: DELETE


FIXTURES = [
    ("F1_clean", [], 0, [], []),
    ("F2_missing_ts", [(PART, swap(F2_FROM, F2_TO))], 1, ["V1_LINE_FORMAT"], []),
    ("F3_gap_content", [(PART, swap(F3_FROM, ""))], 1, ["V4_GRID_GAP"], []),
    ("F4_silence_marked", [(TRANSCRIPT, swap(F4_TRANSCRIPT_FROM, "")),
                           (PART, swap(F4_PART_FROM, F4_PART_TO))], 0, [], []),
    ("F5_bad_indent", [(PART, swap(F5_FROM, F5_TO))], 1, ["V1_LINE_FORMAT"], []),
    ("F6_wrong_language", [(PART, whole(F6_PART))], 1, ["V6_LANGUAGE"], []),
    ("F7_non_monotonic", [(PART, swap(F7_FROM, F7_TO))], 1, ["V2_MONOTONIC"], []),
    ("F8_out_of_bounds", [(PART, append(F8_ADDED))], 1, ["V3_BOUNDS", "V8_DURATION"],
     ["V10_TS_NOT_IN_TRANSCRIPT", "V4_SILENCE_UNMARKED", "V7_EDGE_COVERAGE"]),
    ("F9_empty_part", [(PART, remove())], 1, ["V9_EMPTY_PART"], []),
    ("F10_first_not_header", [(PART, swap(F10_FROM, F10_TO))], 1, ["V5_FIRST_HEADER"],
     ["V5_HIERARCHY"]),
    ("F11_unmarked_gap", [(PART, swap(F3_FROM, "")),
                          (TRANSCRIPT, swap(F11_TRANSCRIPT_FROM, ""))], 0, [],
     ["V4_SILENCE_UNMARKED"]),
    ("F12_tail_uncovered", [(PART, swap(F12_FROM, ""))], 1, ["V4_EDGE_UNCOVERED"],
     ["V7_EDGE_COVERAGE"]),
    ("F13_head_uncovered", [(PART, swap(F13_FROM, ""))], 1, ["V4_EDGE_UNCOVERED"],
     ["V7_EDGE_COVERAGE"]),
    ("F14_empty_transcript", [(TRANSCRIPT, whole(""))], 2, [], []),
    ("F15_bad_clock", [(PART, swap(F15_FROM, F15_TO))], 1, ["V1_LINE_FORMAT"], []),
    ("F16_quote_ok", [(PART, append(F16_ADDED))], 0, [], []),
    ("F17_quote_fabricated", [(PART, append(F17_ADDED))], 1,
     ["V11_QUOTE_NOT_IN_TRANSCRIPT"], []),
]

RENDERED = ("F1_clean", "F4_silence_marked")
XSS_LANGUAGE = 'ko"><script>alert(1)</script>'
CLEAN_VERIFY = {"status": "clean", "mode": "targeted", "windows": 1,
                "spans_checked": 3, "findings": 0, "repaired": 0, "date": "2026-08-23"}


def ascii_safe(s):
    """The ascii-safe form IS the string with every non-ASCII character escaped."""
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def materialized(name, operations, root):
    """A materialized fixture IS a copy of the base rundir with its operations applied."""
    rundir = pathlib.Path(root) / name
    shutil.copytree(BASE, rundir)
    for relative, operation in operations:
        target = rundir / relative
        before = target.read_text(encoding="utf-8")
        after = operation(before)
        assert after != before, "%s: operation on %s changed nothing" % (name, relative)
        if after is DELETE:
            target.unlink()
        else:
            with open(target, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(after)
    return rundir


def script_run(script, rundir):
    """A script run IS the CompletedProcess of a skill script over a rundir."""
    return subprocess.run([sys.executable, str(script), "--rundir", str(rundir)],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=180)


def report_codes(rundir, level):
    """The codes ARE the distinct V-codes a run reported at one severity level."""
    report = json.loads((rundir / "validation.json").read_text(encoding="utf-8"))
    return sorted({entry["code"] for entry in report[level]})


def check(name, operations, want_exit, want_codes, root, want_warnings=None):
    """A fixture check IS its validate exit code and reported codes matching the table.

    An exit-2 row is a LOAD failure, so it has no codes to compare: it asserts
    instead that the run produced no report and no merged log at all.
    """
    rundir = materialized(name, operations, root)
    got = script_run(VALIDATE, rundir)
    detail = ascii_safe(got.stderr.strip()[:300])
    if want_exit == 2:
        assert got.returncode == 2, "%s: exit %d, want 2 (stderr %s)" % (name, got.returncode, detail)
        for artifact in ("validation.json", "log.md"):
            assert not (rundir / artifact).exists(), \
                "%s: a load failure must not write %s" % (name, artifact)
        return rundir
    assert (rundir / "validation.json").exists(), \
        "%s: no validation.json (stderr: %s)" % (name, detail)
    codes = report_codes(rundir, "errors")
    assert got.returncode == want_exit, \
        "%s: exit %d, want %d (codes %s, stderr %s)" % (
            name, got.returncode, want_exit, codes, ascii_safe(got.stderr.strip()[:300]))
    assert codes == sorted(want_codes), "%s: error codes %s, want %s" % (name, codes, sorted(want_codes))
    if want_warnings is not None:
        warnings = report_codes(rundir, "warnings")
        assert warnings == sorted(want_warnings), \
            "%s: warning codes %s, want %s" % (name, warnings, sorted(want_warnings))
    if name in RENDERED:
        assert (rundir / "log.md").exists(), "%s: no log.md" % name
        check_render(name, rundir)
    return rundir


def check_render(name, rundir):
    """A render check IS one page per rundir whose ts links match the log line count."""
    rendered = script_run(RENDER, rundir)
    assert rendered.returncode == 0, "%s: render exit %d (stderr %s)" % (
        name, rendered.returncode, ascii_safe(rendered.stderr.strip()[:300]))
    pages = list(rundir.glob("*.html"))
    assert len(pages) == 1, "%s: %d html files, want exactly 1" % (name, len(pages))
    page = pages[0].read_text(encoding="utf-8")
    assert 'class="ts"' in page, '%s: rendered page has no class="ts"' % name
    want = json.loads((rundir / "validation.json").read_text(encoding="utf-8"))["n_log_lines"]
    got = page.count('class="ts"')
    assert got == want, "%s: %d ts links, want %d non-blank log lines" % (name, got, want)
    if name == "F4_silence_marked":
        assert 'class="silence"' in page, '%s: rendered page has no class="silence"' % name


def sole_page(rundir):
    """The page IS the single rendered html of a run directory."""
    pages = list(rundir.glob("*.html"))
    assert len(pages) == 1, "%d html files in %s, want exactly 1" % (len(pages), rundir.name)
    return pages[0].read_text(encoding="utf-8")


def fresh(name, root):
    """A fresh fixture IS one materialized alone, so repeat checks cannot collide."""
    operations = {f[0]: f[1] for f in FIXTURES}[name]
    return materialized(name, operations, tempfile.mkdtemp(dir=root))


def check_part_line(root):
    """A finding IS locatable in its own part file, not only in the merged log."""
    rundir = fresh("F2_missing_ts", root)
    script_run(VALIDATE, rundir)
    entry = json.loads((rundir / "validation.json").read_text(encoding="utf-8"))["errors"][0]
    assert entry["line"] == 3, "merged line %s, want 3" % entry.get("line")
    assert entry["part_line"] == 3, "part_line %s, want 3" % entry.get("part_line")
    print("part_line PASS (F2's error carries both merged line 3 and part line 3)")


def check_banner(root):
    """A failed validation IS visible on the page it produced.

    The bare string `hyl-degraded` is in the template's CSS on every page, so the
    banner is detected by its element, not by that substring.
    """
    failing = fresh("F3_gap_content", root)
    script_run(VALIDATE, failing)
    rendered = script_run(RENDER, failing)
    assert rendered.returncode == 0, "render refused a failing log: %s" % ascii_safe(
        rendered.stderr.strip()[:200])
    page = sole_page(failing)
    assert '<div class="hyl-degraded"' in page, "no degraded banner on a failing log"
    assert "VALIDATION FAILED - 1 error(s)" in page, "banner omits its error count"

    passing = fresh("F1_clean", root)
    script_run(VALIDATE, passing)
    script_run(RENDER, passing)
    assert '<div class="hyl-degraded"' not in sole_page(passing), \
        "a clean log carries a degraded banner"
    print("banner PASS (failing page banners with its count, clean page does not)")


def check_language_injection(root):
    """A hostile meta.language IS neutralised, never interpolated into the page."""
    rundir = fresh("F1_clean", root)
    meta = json.loads((rundir / "meta.json").read_text(encoding="utf-8"))
    meta["language"] = XSS_LANGUAGE
    with open(rundir / "meta.json", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(meta, ensure_ascii=False))
    script_run(VALIDATE, rundir)
    rendered = script_run(RENDER, rundir)
    assert rendered.returncode == 0, "render failed on a hostile language: %s" % ascii_safe(
        rendered.stderr.strip()[:200])
    page = sole_page(rundir)
    assert "<script>alert(1)</script>" not in page, "the injected script reached the page"
    assert 'alert(1)' not in page, "the injected payload reached the page in some form"
    assert '<html lang="ko">' in page, "the lang attribute is not sane"
    print("injection PASS (hostile meta.language falls back to ko, payload absent)")


def check_cross_fragment(root):
    """A quote IS allowed to span adjacent caption fragments, as real speech does."""
    rundir = fresh("F1_clean", root)
    with open(rundir / "parts" / "part_01.md", "a", encoding="utf-8", newline="\n") as fh:
        fh.write(CROSS_ADDED)
    got = script_run(VALIDATE, rundir)
    codes = report_codes(rundir, "errors")
    assert got.returncode == 0 and codes == [], \
        "a quote spanning two caption lines was rejected: %s" % codes
    print("cross-fragment PASS (a quote joining two transcript lines validates clean)")


def rendered_page(rundir, verify=None):
    """A rendered page IS one fixture validated, optionally given a verdict, and rendered."""
    if verify is not None:
        with open(rundir / "verify.json", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(verify if isinstance(verify, str) else json.dumps(verify))
    script_run(VALIDATE, rundir)
    rendered = script_run(RENDER, rundir)
    assert rendered.returncode == 0, "render exit %d: %s" % (
        rendered.returncode, ascii_safe(rendered.stderr.strip()[:200]))
    return sole_page(rundir)


def check_verify_status(root):
    """A page IS explicit about whether anyone checked it for fabrication."""
    verified = rendered_page(fresh("F1_clean", root), CLEAN_VERIFY)
    assert '<div class="hyl-unverified"' not in verified, "a verified log still shows amber"
    assert "verified targeted, 3 spans, clean" in verified, "the footer omits the verdict"
    assert '<div class="hyl-degraded"' not in verified, "a clean log shows the red banner"

    bare = rendered_page(fresh("F1_clean", root))
    assert '<div class="hyl-unverified"' in bare, "an unchecked log carries no amber banner"
    assert "UNVERIFIED - semantic fidelity" in bare, "the amber banner lost its wording"
    assert '<div class="hyl-degraded"' not in bare, "an unverified but valid log shows red"

    broken = rendered_page(fresh("F1_clean", root), "{not json")
    assert '<div class="hyl-unverified"' in broken, "malformed verify.json must read as unverified"

    open_findings = rendered_page(fresh("F1_clean", root),
                                  {"status": "findings_open", "findings": 2})
    assert "VERIFICATION FOUND UNRESOLVED ISSUES (2)" in open_findings, \
        "an open-findings verdict is not surfaced"
    print("verify-status PASS (clean footers; absent, malformed and open-findings all banner)")


def main():
    root = tempfile.mkdtemp(prefix="hyl_fixtures_")
    try:
        for name, operations, want_exit, want_codes, want_warnings in FIXTURES:
            check(name, operations, want_exit, want_codes, root, want_warnings)
            print("%s PASS" % name)
        check_part_line(root)
        check_banner(root)
        check_language_injection(root)
        check_cross_fragment(root)
        check_verify_status(root)
        print("FIXTURES OK")
    finally:
        shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
