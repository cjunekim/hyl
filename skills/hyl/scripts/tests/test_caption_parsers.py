"""The caption-parser suite IS offline coverage for the branches a live fetch may miss.

YouTube commonly serves json3 auto-captions, leaving the manual-track rules and
the srv3/vtt parsers (including rolling-caption dedup) unexercised by the live
gates. These cases are synthetic and need no network. Run:
    python test_caption_parsers.py
"""
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import fetch_transcript
import render_html
from fetch_transcript import (chosen_track, collapsed, json3_events, srv3_events,
                              unrolled, vtt_events)

SRV3 = """<?xml version="1.0" encoding="utf-8"?>
<timedtext format="3"><body>
<p t="0" d="2000"><s>안녕</s><s> 하세요</s></p>
<p t="2000" d="2000">두 번째 줄</p>
<p t="4000" d="2000"></p>
<p t="6000" d="2000">두 번째 줄</p>
<p t="8000" d="2000">&amp;co &lt;tag&gt;</p>
</body></timedtext>
"""
SRV3_WANT = [(0, "안녕 하세요"), (2, "두 번째 줄"), (8, "&co <tag>")]

VTT = """WEBVTT

00:00:01.000 --> 00:00:03.000 align:start position:0%
hello

00:00:03.000 --> 00:00:05.000
hello<00:00:03.500><c> world</c>

00:00:05.000 --> 00:00:07.000
hello world again

00:00:09.000 --> 00:00:11.000
hello world again
"""
VTT_WANT = [(1, "hello"), (3, "world"), (5, "again")]

JSON3 = """{"events": [
 {"tStartMs": 0, "segs": [{"utf8": "첫 줄"}]},
 {"tStartMs": 1500, "aAppend": 1, "segs": [{"utf8": "APPENDED"}]},
 {"tStartMs": 2000, "segs": [{"utf8": ""}]},
 {"tStartMs": 3000, "segs": [{"utf8": "둘째"}, {"utf8": " 줄"}]},
 {"tStartMs": 4000},
 {"tStartMs": 5000, "segs": [{"utf8": "둘째 줄"}]}
]}"""
JSON3_WANT = [(0, "첫 줄"), (3, "둘째 줄")]

TRACKS = [
    ("manual exact match", "ko", {"ko": [], "en": []}, {"ko-orig": []}, ("ko", "manual")),
    ("manual prefix match", "ko", {"ko-KR": []}, {"ko-orig": []}, ("ko-KR", "manual")),
    # An audio-language original outranks a foreign manual sub: the old order fed
    # loggers English while meta.language still claimed Korean.
    ("original outranks foreign manual", "ko", {"en": []}, {"ko-orig": []}, ("ko-orig", "auto")),
    # A former livestream carries a live_chat pseudo-track; it must never win.
    ("live_chat loses to the original", "ko", {"live_chat": []}, {"ko-orig": []},
     ("ko-orig", "auto")),
    # ...but with no auto track at all it WOULD be the last-resort manual, which is
    # exactly why run() filters live_chat out before calling chosen_track.
    ("live_chat is why the call site filters", "ko", {"live_chat": []}, {},
     ("live_chat", "manual")),
    # Subtag boundary: kok (Konkani) is not a Korean track.
    ("kok does not match ko", "ko", {"kok": []}, {}, ("kok", "manual")),
    ("auto <lang>-orig", "ko", {}, {"ko": [], "ko-orig": []}, ("ko-orig", "auto")),
    ("auto exact", "ko", {}, {"ko": [], "en": []}, ("ko", "auto")),
    ("wrong-language manual last resort", "ko", {"ja": []}, {"en": []}, ("ja", "manual")),
    ("no language, first -orig", "", {}, {"en": [], "ja-orig": []}, ("ja-orig", "auto")),
    ("none available (exit 3)", "ko", {}, {"en": []}, None),
]

PRIORITY_MARKERS = [("(a)", "manual"), ("(b)", "-orig"), ("(c)", "auto track"),
                    ("(d)", "manual"), ("(e)", "original")]


def ascii_safe(s):
    """The ascii-safe form IS the string with every non-ASCII character escaped."""
    return str(s).encode("ascii", "backslashreplace").decode("ascii")


def check_srv3():
    """srv3 parsing IS tag stripping, entity unescaping, and empty-cue dropping."""
    got = collapsed(unrolled(srv3_events(SRV3)))
    assert got == SRV3_WANT, "srv3: got %s, want %s" % (ascii_safe(got), ascii_safe(SRV3_WANT))
    return "srv3: tags stripped, entities unescaped, empty and repeated cues dropped"


def check_vtt():
    """vtt parsing IS rolling captions reduced to the text each cue newly adds."""
    got = collapsed(unrolled(vtt_events(VTT)))
    assert got == VTT_WANT, "vtt: got %s, want %s" % (ascii_safe(got), ascii_safe(VTT_WANT))
    return "vtt: prefix-overlap cue keeps only its suffix, exact repeat dropped"


def check_json3():
    """json3 parsing IS spoken events only: append and segment-less events are skipped."""
    got = collapsed(json3_events(JSON3))
    assert got == JSON3_WANT, "json3: got %s, want %s" % (ascii_safe(got), ascii_safe(JSON3_WANT))
    return "json3: aAppend, empty-segs and segs-less events skipped, duplicate collapsed"


def check_tracks():
    """Track selection IS the skill's priority order, ending in the no-track case."""
    for label, language, subs, autos, want in TRACKS:
        got = chosen_track(language, subs, autos)
        assert got == want, "track rule %r: got %r, want %r" % (label, got, want)
    return "track choice: %d cases including the no-track case that drives exit 3" % len(TRACKS)


def check_priority_doc():
    """The docstring IS in step with the code: five branches, labelled, in order."""
    doc = " ".join(chosen_track.__doc__.split())
    positions = [doc.find(marker) for marker, _ in PRIORITY_MARKERS]
    missing = [marker for (marker, _), at in zip(PRIORITY_MARKERS, positions) if at < 0]
    assert not missing, "priority markers absent from the docstring: %s" % missing
    assert positions == sorted(positions), "priority markers out of order: %s" % positions
    edges = positions + [len(doc)]
    for i, (marker, keyword) in enumerate(PRIORITY_MARKERS):
        segment = doc[edges[i]:edges[i + 1]]
        assert keyword in segment, "branch %s no longer mentions %r: %r" % (marker, keyword, segment)
    return "priority docstring: %d branches documented in code order" % len(PRIORITY_MARKERS)


CONTAINMENT = [
    ("windows traversal", "", "..\\outside", "outside"),
    ("posix traversal", "", "../../etc/passwd", "etcpasswd"),
    ("reserved device", "", "CON", "hyl"),
    ("nothing at all", "", "", "hyl"),
]
BAD_IDS = ("..\\x", "../x", "short", "waytoolongforanid", "abc def1234", "")


def check_containment():
    """A slug IS a plain contained filename stem, whatever hostile input builds it."""
    for label, title, vid, want in CONTAINMENT:
        got = render_html.slug_of(title, vid)
        assert got == want, "%s: slug_of(%r, %r) = %r, want %r" % (label, title, vid, got, want)
        assert "/" not in got and "\\" not in got and got.strip(".") == got, \
            "%s: slug escapes its directory: %r" % (label, got)
    for bad in BAD_IDS:
        assert not fetch_transcript.VIDEO_ID_RE.fullmatch(bad), "id gate accepted %r" % (bad,)
    assert fetch_transcript.VIDEO_ID_RE.fullmatch("6ZRXNJhyhy0"), "id gate rejected a real id"
    return "A7: slugs stay contained filenames; the id gate rejects traversal and wrong lengths"


def check_command():
    """The yt-dlp command IS the resolved binary, or this interpreter's module form."""
    fallback = [sys.executable, "-m", "yt_dlp"]
    fake = "C:\\fake\\Scripts\\yt-dlp.EXE"
    original = shutil.which
    try:
        shutil.which = lambda _name: fake
        found = fetch_transcript.ytdlp_command()
        assert found == [fake], "a PATH hit must be used verbatim: %s" % ascii_safe(found)
        shutil.which = lambda _name: None
        forced = fetch_transcript.ytdlp_command()
        assert forced == fallback, "fallback: got %s, want %s" % (ascii_safe(forced),
                                                                  ascii_safe(fallback))
    finally:
        shutil.which = original
    live = fetch_transcript.ytdlp_command()
    assert live == fallback or (len(live) == 1 and live[0]), \
        "unexpected live command %s" % ascii_safe(live)
    return "yt-dlp command: PATH hit used verbatim, absent binary falls back to the module"


def main():
    for check in (check_srv3, check_vtt, check_json3, check_tracks,
                  check_priority_doc, check_containment, check_command):
        print("  %s" % check())
    print("CAPTION PARSERS OK")


if __name__ == "__main__":
    main()
