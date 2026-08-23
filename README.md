# hyl

Turn a YouTube video into a **verified, deep-linked, timestamped log** — one
self-contained HTML page where every `[hh:mm:ss]` opens the video at that
second.

hyl is a [Claude Code](https://claude.com/claude-code) skill. It is **not a
summarizer**: it writes a *log* — a strict-chronology outline on a 30-second
time grid, in the audio's own language, with built-in fabrication defenses and
an adversarial verification pass. Nothing is compressed away; order is time,
never topic.

## What you get

- **High-resolution log** — no gap larger than 30 seconds wherever the
  transcript has content; 3-level outline; Korean video → fully Korean log,
  English video → English log.
- **Deep links** — every timestamp is a link into the video at that second.
- **Keyboard UI** — vim-style: `j`/`k`, `gg`/`G`, `{`/`}` between sections,
  folding with `a o c r m R M` (vim's `z`-spellings work too), `/` search
  (IME-safe), `Enter` opens the video at the cursor line, `?` for the key map.
  Light/dark theme, print-friendly, zero external resources.
- **Fabrication defense, four gates**
  1. *Generation protocol* — polarity, attribution and number words must trace
     to explicit transcript tokens; claim-type lines must end with a verbatim
     `「anchor quote」`; unresolvable ASR garble is surfaced as
     `(불명확: …)`, never silently resolved; truncated sentences are never
     completed.
  2. *Mechanical validation (V1–V11)* — line grammar, monotonic time, window
     bounds, 30-s grid coverage, hierarchy, language ratio, duration, and a
     string check of **every anchor quote against the full transcript**.
  3. *Deterministic risk scoring + adversarial verifier* — boundary zones,
     the logger's own uncertainty labels, transcript-quality signals and
     compression outliers are scored into risk spans; a separate
     verifier agent (Opus) re-reads those spans and every self-labeled line
     for entailment.
  4. *A page that testifies about itself* — amber `UNVERIFIED` banner when
     semantic verification is missing or unresolved, red `VALIDATION FAILED`
     banner when mechanical checks failed, and a `verified …` footer only when
     the run is clean.

## Install

Copy two directories into your Claude Code home:

```
skills/hyl/            →  ~/.claude/skills/hyl/
agents/hyl-logger.md   →  ~/.claude/agents/hyl-logger.md
agents/hyl-verifier.md →  ~/.claude/agents/hyl-verifier.md
```

Then restart Claude Code (agent definitions load at session start).

**Requirements**: Claude Code, Python 3.10+ (scripts are stdlib-only), and
[yt-dlp](https://github.com/yt-dlp/yt-dlp) — if it is missing, the skill
announces and installs it itself (`pip install -U yt-dlp`) on first run.

## Use

```
/hyl https://www.youtube.com/watch?v=...
```

or just paste a YouTube URL and ask for a timestamped log. The first run asks
where to keep outputs and offers to persist that choice as `HYL_OUTPUT_ROOT`.

Works on any video with a caption track (manual or auto-generated). Multiple
URLs in one request are pipelined per video.

## How it works

```
fetch (yt-dlp → normalized transcript, 30-min windows with 60-s context margins)
  → N parallel logger agents (Sonnet), one per window
  → per-window: deterministic risk scoring → adversarial verifier agent (Opus)
  → mechanical validation V1–V11 (merges parts into log.md)
  → targeted repairs (window-scoped, at most one round per gate)
  → render (self-checking; banners/footer read the verification verdicts)
```

Verification is pipelined behind the loggers, so it adds little wall-clock.
Measured: a 2 h 18 m video went URL → finished HTML in about 17 minutes.

**Cost note**: one run dispatches N logger agents (Sonnet) and N verifier
agents (Opus) for N ≈ duration/30 min — a 2-hour video is ~5+5 agent calls on
your Claude plan.

## Limits

- **Caption-bound.** No caption track → no log (Whisper is out of scope), and
  log quality is bounded by caption quality; visibly garbage auto-captions are
  reported as such.
- Verification is *targeted* (risk spans + coverage samples per window), not
  an exhaustive line-by-line audit.
- Language checks are tuned for Korean and English transcripts; other
  languages run but with weaker automatic language-drift detection.

## Tests

Offline smoke suite (no network, no LLM):

```
cd skills/hyl/scripts
python tests/test_windows_of.py && python tests/test_caption_parsers.py && \
python tests/run_fixture_tests.py && python tests/test_grammar_sync.py && \
python tests/test_risk_spans.py && python tests/check_stdlib_only.py
```

## 한국어 소개

hyl은 유튜브 영상을 **검증된 타임스탬프 딥링크 로그**(단일 HTML)로 바꾸는
Claude Code 스킬입니다. 요약이 아니라 **로그**입니다 — 30초 그리드, 3단계
계층, 자막 언어 그대로, 시간순 엄수. 모든 `[hh:mm:ss]`가 영상의 해당 순간으로
연결됩니다.

핵심은 조작(fabrication) 방어입니다: 극성·귀속·숫자는 자막 토큰 추적 필수,
주장형 라인은 「원문 앵커 인용」 필수(기계적 문자열 대조), 불명확한 자막은
`(불명확: …)`으로 표면화, 그리고 별도의 적대적 검증 에이전트가 위험 구간을
재정독합니다. 검증되지 않은 페이지는 스스로 UNVERIFIED 배너를 답니다.

**설치**: 위 Install 절의 두 디렉토리를 `~/.claude/` 아래로 복사하고 Claude
Code를 재시작하세요. **사용**: `/hyl <유튜브 URL>` 또는 URL을 붙여넣고
타임스탬프 로그를 요청하면 됩니다. yt-dlp가 없으면 첫 실행 때 스킬이 직접
설치합니다.

## License

Personal Use License — personal, noncommercial use and modification are
allowed; redistribution or commercial use requires prior written permission.
See [LICENSE](LICENSE).
