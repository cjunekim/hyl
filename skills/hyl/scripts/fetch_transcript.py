"""A YouTube URL IS a windowed, normalized transcript run directory.

Usage: python fetch_transcript.py <URL> --outdir <DIR> [--window-min 30]

Outputs under --outdir: meta.json, transcript.txt, windows/window_NN.txt,
windows/index.json. Exit 0 ok, 2 yt-dlp-or-parse failure, 3 no captions,
4 bad args. Stdlib only; stdout is ASCII; every artifact is UTF-8.
"""
import argparse
import datetime
import html
import json
import pathlib
import re
import shutil
import subprocess
import sys

MARGIN_S = 60
TAIL_MIN_S = 600
WINDOW_S = 1800
TIMEOUT_S = 180

HEADER = "### WINDOW {k}/{n} -- LOG RANGE [{start} - {end})"
MARGIN_BEFORE = "### CONTEXT MARGIN (before) -- context only, do NOT log"
CONTENT = "### WINDOW CONTENT -- log ALL of this"
MARGIN_AFTER = "### CONTEXT MARGIN (after) -- context only, do NOT log"

TAGS = re.compile(r"<[^>]*>")
SRV3_CUE = re.compile(r"<p\b([^>]*)>(.*?)</p>", re.S)
SRV3_START = re.compile(r'\bt="(\d+)"')
VTT_CUE = re.compile(r"(?:(\d{1,3}):)?(\d{2}):(\d{2})[.,](\d{3})\s*-->")
LANG_RE = re.compile(r"[a-z]{2,3}")
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{11}")
MANIFEST = ".hyl_outputs"


class Failure(Exception):
    """A Failure IS an abort carrying its ASCII message and process exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = ascii_safe(message)


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


def primary(tag):
    """The primary tag IS the lowercased first subtag of a language tag."""
    return str(tag).split("-")[0].lower() if tag else ""


def brief(stream, n=400):
    """The brief form IS the tail of a stream as one ASCII line."""
    return ascii_safe(" ".join((stream or "").split())[-n:])


def windows_of(duration_s, window_s=WINDOW_S, tail_min_s=TAIL_MIN_S):
    """The windows ARE the content bounds of each log window.

    Full windows tile the duration; a remainder shorter than tail_min_s extends
    the last window (or forms the only one when there is no full window), and a
    remainder at least tail_min_s long becomes a window of its own. The caller
    scales tail_min_s to the window size.
    """
    n_full = duration_s // window_s
    remainder = duration_s - n_full * window_s
    full = [(k * window_s, (k + 1) * window_s) for k in range(n_full)]
    if remainder >= tail_min_s:
        return full + [(n_full * window_s, duration_s)]
    if not full:
        return [(0, duration_s)]
    return full[:-1] + [(full[-1][0], duration_s)]


def ytdlp_command():
    """The yt-dlp command IS the binary when it is on PATH, else this interpreter's module.

    shutil.which applies PATHEXT case-insensitively, so it resolves `yt-dlp.EXE`
    where a POSIX-style `which` does not; the module form covers machines whose
    PATH omits pip's Scripts directory.
    """
    exe = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    return [exe] if exe else [sys.executable, "-m", "yt_dlp"]


def ytdlp(argv):
    """The yt-dlp result IS the CompletedProcess of the resolved command run with argv."""
    try:
        return subprocess.run(ytdlp_command() + list(argv), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=TIMEOUT_S)
    except subprocess.TimeoutExpired:
        raise Failure(2, "YTDLP_TIMEOUT after %ds" % TIMEOUT_S)


def info_of(url):
    """The info dict IS yt-dlp's -J metadata for the url."""
    probe = ytdlp(["-J", "--skip-download", "--no-playlist", url])
    if probe.returncode != 0:
        raise Failure(2, "YTDLP_PROBE_FAILED rc=%d %s" % (probe.returncode, brief(probe.stderr)))
    try:
        return json.loads(probe.stdout)
    except ValueError as exc:
        raise Failure(2, "YTDLP_PROBE_UNPARSEABLE %s" % exc)


def lang_match(tag, language):
    """A tag MATCHES a language when it is that language or one of its subtags.

    The `-` boundary is what keeps `kok` (Konkani) from matching `ko`.
    """
    return tag == language or bool(language) and tag.startswith(language + "-")


def chosen_track(language, subs, autos):
    """The chosen track IS (lang_tag, kind) under the skill's priority order, or None.

    Order: (a) a manual track in the video's language; (b) the auto original
    `<language>-orig`; (c) the auto track `<language>`; (d) any manual track, a
    wrong-language last resort; (e) with no declared language, the first auto
    original. An audio-language ORIGINAL is more faithful than a foreign manual
    track, so (b) and (c) outrank (d).
    """
    matching = [t for t in subs if lang_match(t, language)]
    originals = [t for t in autos if t.endswith("-orig")]
    if matching:
        return (matching[0], "manual")
    if language and "%s-orig" % language in autos:
        return ("%s-orig" % language, "auto")
    if language and language in autos:
        return (language, "auto")
    if subs:
        return (list(subs)[0], "manual")
    if not language and originals:
        return (originals[0], "auto")
    return None


def caption_path(url, tag, kind, outdir):
    """The caption path IS the subtitle file yt-dlp writes for the chosen track."""
    for stale in outdir.glob("captions.*"):
        stale.unlink()
    flag = "--write-subs" if kind == "manual" else "--write-auto-subs"
    got = ytdlp([flag, "--sub-langs", tag, "--sub-format", "json3/srv3/vtt",
                 "--skip-download", "--no-playlist", "-o",
                 str(outdir / "captions.%(ext)s"), url])
    written = [p for p in outdir.glob("captions.*") if p.suffix != ".part"]
    if not written:
        raise Failure(2, "CAPTION_DOWNLOAD_EMPTY rc=%d %s" % (got.returncode, brief(got.stderr)))
    if got.returncode != 0:
        raise Failure(2, "CAPTION_DOWNLOAD_PARTIAL rc=%d %s" % (got.returncode, brief(got.stderr)))
    for suffix in (".json3", ".srv3", ".vtt"):
        preferred = [p for p in written if p.suffix == suffix]
        if preferred:
            return preferred[0]
    return sorted(written)[0]


def json3_events(text):
    """The json3 events ARE (second, text) pairs of the non-append caption events."""
    events = json.loads(text).get("events", [])
    spoken = [(int(ev.get("tStartMs", 0)) // 1000,
               " ".join("".join(seg.get("utf8", "") for seg in ev.get("segs") or []).split()))
              for ev in events if ev.get("segs") and not ev.get("aAppend")]
    return [(t, s) for t, s in spoken if s]


def srv3_events(text):
    """The srv3 events ARE (second, text) pairs read from timed <p> cues."""
    cues = [(SRV3_START.search(attrs), body) for attrs, body in SRV3_CUE.findall(text)]
    spoken = [(int(start.group(1)) // 1000,
               " ".join(html.unescape(TAGS.sub("", body)).split()))
              for start, body in cues if start]
    return [(t, s) for t, s in spoken if s]


def vtt_events(text):
    """The vtt events ARE (second, text) pairs read from cue blocks."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    starts = [(i, VTT_CUE.match(line.strip())) for i, line in enumerate(lines)]
    spoken = []
    for i, cue in [(i, c) for i, c in starts if c]:
        body = []
        for following in lines[i + 1:]:
            if not following.strip() or VTT_CUE.match(following.strip()):
                break
            body.append(following)
        flat = " ".join(html.unescape(TAGS.sub("", " ".join(body))).split())
        h, m, s, _ms = cue.groups()
        if flat:
            spoken.append((int(h or 0) * 3600 + int(m) * 60 + int(s), flat))
    return spoken


def unrolled(events):
    """The unrolled events ARE rolling-caption cues reduced to their new suffix."""
    kept, prev = [], ""
    for t, s in events:
        fresh = s[len(prev):].strip() if prev and s.startswith(prev) else s
        prev = s
        if fresh:
            kept.append((t, fresh))
    return kept


def collapsed(events):
    """The collapsed events ARE the events with consecutive duplicate texts dropped."""
    kept = []
    for t, s in events:
        if not kept or kept[-1][1] != s:
            kept.append((t, s))
    return kept


def transcript_of(path):
    """The transcript IS the normalized (second, text) events of a caption file."""
    text = path.read_text(encoding="utf-8", errors="replace")
    parsers = {".json3": json3_events, ".srv3": srv3_events, ".vtt": vtt_events}
    parse = parsers.get(path.suffix, vtt_events)
    try:
        events = parse(text)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise Failure(2, "CAPTION_PARSE_FAILED %s %s" % (path.suffix, exc))
    events = [(t, s) for t, s in events if t >= 0]
    normalized = collapsed(events if path.suffix == ".json3" else unrolled(events))
    if not normalized:
        raise Failure(2, "CAPTION_PARSE_EMPTY %s" % path.suffix)
    if any(nxt[0] < cur[0] for cur, nxt in zip(normalized, normalized[1:])):
        raise Failure(2, "TRANSCRIPT_NOT_MONOTONIC %s" % path.suffix)
    return normalized


def lines_in(events, lo, hi):
    """The lines IS the `[hh:mm:ss] text` rendering of events within [lo, hi)."""
    return ["[%s] %s" % (hms(t), s) for t, s in events if lo <= t < hi]


def window_text(k, n, start, end, events, duration):
    """A window file IS its header plus the optional context margins around its content."""
    head = [HEADER.format(k=k, n=n, start=hms(start), end=hms(end))]
    before = ([MARGIN_BEFORE] + lines_in(events, max(0, start - MARGIN_S), start)) if k > 1 else []
    content = [CONTENT] + lines_in(events, start, end if k < n else end + 1)
    after = ([MARGIN_AFTER] + lines_in(events, end, min(end + MARGIN_S, duration))) if k < n else []
    return "\n".join(head + before + content + after) + "\n"


def clear_stale(outdir):
    """The cleared run dir IS the previous run's pipeline-owned artifacts, removed.

    Called only once the probe, download and parse have all succeeded, so a transient
    network failure can never dismantle a good previous run. HTML is deleted only when
    `.hyl_outputs` names it, which leaves a reader's own copies of the page alone.
    The semantic verdict goes with them: a new transcript invalidates it, and a stale
    verify.json would otherwise let the next render call an unverified page verified.
    """
    manifest = outdir / MANIFEST
    named = manifest.read_text(encoding="utf-8").splitlines() if manifest.exists() else []
    pages = [outdir / name.strip() for name in named if name.strip()]
    owned = (list(outdir.glob("parts/*.md")) + list(outdir.glob("windows/window_*.txt"))
             + [outdir / name for name in ("log.md", "validation.json",
                                           "verify.md", "verify.json", "risk.json")])
    for stale in owned + [page for page in pages if page.parent == outdir]:
        if stale.exists():
            stale.unlink()


def write_text(path, text):
    """A written artifact IS UTF-8 text with LF line endings."""
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def chapters_of(info):
    """The chapters ARE (floored start second, title) records, empty when absent."""
    return [{"start_s": int(ch.get("start_time") or 0),
             "start_hms": hms(int(ch.get("start_time") or 0)),
             "title": ch.get("title") or ""}
            for ch in (info.get("chapters") or [])]


def run(args):
    """The run IS the fetch: probe, choose a track, download, parse, and write."""
    if args.window_min <= 0:
        raise Failure(4, "BAD_ARGS --window-min must be positive")
    outdir = pathlib.Path(args.outdir)
    (outdir / "windows").mkdir(parents=True, exist_ok=True)
    (outdir / "parts").mkdir(parents=True, exist_ok=True)

    info = info_of(args.url)
    vid = info.get("id") or ""
    if not VIDEO_ID_RE.fullmatch(vid):
        raise Failure(2, "BAD_VIDEO_ID %s" % ascii_safe(vid))
    duration = int(info.get("duration") or 0)
    if duration <= 0:
        raise Failure(2, "NO_DURATION id=%s" % ascii_safe(vid))
    language = primary(info.get("language"))
    subs = {t: v for t, v in (info.get("subtitles") or {}).items() if t != "live_chat"}
    track = chosen_track(language, subs, info.get("automatic_captions") or {})
    if track is None:
        raise Failure(3, "NO_SUBTITLES id=%s" % ascii_safe(vid))
    tag, kind = track
    chosen_primary = primary(tag)
    meta_language = (chosen_primary if kind == "manual" and chosen_primary != language
                     else (language or chosen_primary))
    meta_language = meta_language if LANG_RE.fullmatch(meta_language) else ""
    events = transcript_of(caption_path(args.url, tag, kind, outdir))

    clear_stale(outdir)

    window_s = args.window_min * 60
    bounds = windows_of(duration, window_s, min(TAIL_MIN_S, window_s // 2))
    n = len(bounds)
    index = [{"k": k, "file": "windows/window_%02d.txt" % k,
              "start_s": start, "end_s": end,
              "start_hms": hms(start), "end_hms": hms(end),
              "transcript_lines": len(lines_in(events, start, end if k < n else end + 1))}
             for k, (start, end) in enumerate(bounds, 1)]
    meta = {"id": vid, "url": "https://www.youtube.com/watch?v=%s" % vid,
            "title": info.get("title") or vid,
            "duration_s": duration, "language": meta_language,
            "track": {"lang": tag, "kind": kind}, "chapters": chapters_of(info),
            "n_windows": n, "window_min": args.window_min,
            "fetched_at": datetime.datetime.now().replace(microsecond=0).isoformat()}

    write_text(outdir / "transcript.txt",
               "\n".join("[%s] %s" % (hms(t), s) for t, s in events) + "\n")
    write_text(outdir / "meta.json", json.dumps(meta, ensure_ascii=False, indent=1) + "\n")
    write_text(outdir / "windows" / "index.json",
               json.dumps({"windows": index}, ensure_ascii=False, indent=1) + "\n")
    for k, (start, end) in enumerate(bounds, 1):
        write_text(outdir / "windows" / ("window_%02d.txt" % k),
                   window_text(k, n, start, end, events, duration))

    return "OK id=%s duration=%d lang=%s track=%s/%s lines=%d windows=%d" % (
        ascii_safe(vid), duration, ascii_safe(meta["language"]), ascii_safe(tag), kind,
        len(events), n)


def parser():
    """The parser IS the CLI contract; usage errors exit 4."""
    cli = ArgParser(description="Fetch and window a YouTube transcript.")
    cli.add_argument("url")
    cli.add_argument("--outdir", required=True)
    cli.add_argument("--window-min", type=int, default=30)
    return cli


def main():
    args = parser().parse_args()
    try:
        print(run(args))
    except Failure as exc:
        sys.stderr.write(exc.message + "\n")
        raise SystemExit(exc.code)
    except Exception as exc:
        sys.stderr.write("UNEXPECTED_ERROR %s\n" % ascii_safe(repr(exc)))
        raise SystemExit(2)


if __name__ == "__main__":
    main()
