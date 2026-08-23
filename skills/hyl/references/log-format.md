# The HYL log contract

The log IS the video's content as a high-resolution chronological stream — a
**log, not a summary**: nothing is compressed away, and order is time, never
topic. Distilled from the original `multipage_hyl` chat prompt (§1, §2, §4); that
prompt's pagination protocol and anti-falloff directives (§3, §6, §7) are retired,
replaced by windowed parallel dispatch plus `scripts/validate.py` invariants.

## Language protocol
The log is written in the EXACT language of the audio/transcript. Never
translate. Korean audio → entirely Korean log (headers, bullets, everything);
English audio → English log.

## Time grid
- Strict chronological order.
- No gap larger than **30 seconds** between consecutive log timestamps wherever
  the transcript has content. A 3-minute story = 6–7+ bullets tracking its
  progression; banter and "boring" stretches are logged too
  (`[00:15:30] Host jokes about the weather`).
- Where the transcript itself is silent for >30 s, one marker line:
  `* [hh:mm:ss] <Silence / Musical Interlude>` (level 1, not bold). The marker
  text stays this exact English token in every language; its timestamp is the
  last transcript line before the silence. A silence spanning a window boundary
  is marked by the earlier window's logger.
- Every timestamp is copied from a transcript line at or immediately before the
  content it describes — never invented, never interpolated.

## Format
Three levels, two spaces of indent per level, every line timestamped:

```
* [hh:mm:ss] **Section Header**
  * [hh:mm:ss] Main point (in the native language)
    * [hh:mm:ss] Specific detail, quote, or transitional phrase
    * [hh:mm:ss] Another detail
  * [hh:mm:ss] Main point B (new thought)
* [hh:mm:ss] **Next Section Header**
```

- Level-1 lines are **bold section headers** (exception: the silence marker); a
  header is wholly one `**...**` pair, and its timestamp is its section's first
  transcript line.
- Claim-type lines (procedural outcomes, votes/objections, role/party
  attributions, dosages, statistics, directions) end with a verbatim anchor quote
  `「…」` (≤ ~8 words, copied exactly from the transcript, may span adjacent
  caption fragments) — the validator string-checks every quote against the
  transcript (`V11_QUOTE_NOT_IN_TRANSCRIPT`). Unresolvable ASR garble at a
  decision point is surfaced as `(불명확: <verbatim garble>)`, never silently
  resolved.
- Bullet text carries no markdown styling — plain text after the timestamp.
- Blank lines are permitted and ignored by tooling; every non-blank line starts
  with `* [hh:mm:ss] ` after its indent.
- No URLs anywhere in the log — deep links are added at render time.
- Part files contain pure log lines: no preamble, no code fences, no commentary.
