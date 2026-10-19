# Runtime mapping: Claude Code and Codex

Read the section for the current host before dispatch. Fill every slot in the
shared logger or verifier prompt before sending it. Skill resource paths are
relative to the directory containing the loaded SKILL.md; worker input/output
paths are absolute paths in the shared filesystem.

## Claude Code

- Invoke as `/hyl <YouTube URL>` or through a matching natural-language request.
- LOGGER: Agent tool, `subagent_type: "hyl-logger"`, unnamed, no `model` override.
  The existing `~/.claude/agents/hyl-logger.md` pins `model: sonnet`,
  `effort: xhigh`, `tools: [Read, Write]`.
- VERIFIER: Agent tool, `subagent_type: "hyl-verifier"`, unnamed, no `model`
  override. The existing `~/.claude/agents/hyl-verifier.md` pins `model: opus`,
  `effort: xhigh`, `tools: [Read]`.
- Only if dispatch reports an unknown agent type, use `general-purpose` with
  `model: "sonnet"` for a logger or `model: "opus"` for a verifier, and the same
  shared prompt. Tell the user the custom effort and tool restrictions are
  inactive for that fallback; restart Claude Code after installing the agent
  definitions to restore them. Prompt restrictions still apply.
- Dispatch independent workers in parallel up to the available capacity.

## Codex

- Invoke as `$hyl <YouTube URL>` or through a matching natural-language request.
  Codex needs no Claude installation or files under `~/.claude/agents/`.
- Use native subagent tools exposed by the session, such as
  `collaboration.spawn_agent` or `spawn_agent`. Inspect their schema: namespaces
  and accepted fields vary by client. Do not pass Claude's `subagent_type`,
  `sonnet`, or `opus` fields to Codex tools.
- Use a fresh context for each window logger and each verifier. With
  `collaboration.spawn_agent`, set `fork_turns: "none"`, a unique `task_name`
  such as `hyl_v1_logger_01`, and `message` to the filled shared prompt. For a
  tool with a boolean context-fork setting, leave history copying disabled.
  Do not send the main conversation or this SKILL.md to workers.
- Pin the model by role, including retries and repairs:
  - LOGGER: `model: "gpt-6.1-sol"` (GPT-6.1 Sol).
  - VERIFIER: `model: "gpt-6-astra"` (GPT-6 Astra).
  With `collaboration.spawn_agent`, pass that model alongside
  `fork_turns: "none"`; do not inherit the orchestrator's model. A later explicit
  user choice takes precedence. If the host cannot select or run the requested
  model, report the unavailable role/model and stop; never silently substitute.
- Leave reasoning effort at the runtime defaults unless the user supplies an
  override. Do not assume that omitting effort pins a particular value or cost.
  Record requested model/effort separately from effective settings when the host
  exposes them; label unavailable effective metadata as unverified.
- Logger instructions permit reading its window (and its previous part on
  repair) and writing its assigned part only. Verifier instructions permit
  reading its named inputs and returning a verdict only. Codex workers may
  still have shell/write tools: these are behavioral restrictions, not a claim
  that a prompt removes capabilities. Use host tool restrictions when exposed,
  without changing global configuration.
- Dispatch up to the free worker slots and queue remaining windows/verifiers.
  A one-slot host can run separate workers sequentially. Collect results with
  the native wait/result tools. Retain the agent-to-window mapping and close
  finished workers when the host requires it to release slots. Reuse a logger
  only for repairs of its own window; verification remains independent.
- Do not start nested `codex exec` or invoke Claude to emulate missing native
  tools. If independent subagents are unavailable or disabled, report the
  prerequisite and stop before fetching. Do not load transcripts into the
  orchestrator as a silent fallback.

## Files, shells, and permissions

- `Read` and `Write` in the prompts describe operations, not mandatory tool
  names. Use the host's available file or shell tools. A logger must read its
  complete window, in chunks if tool output limits require it. Never send the
  transcript back to the orchestrator.
- Use one Python interpreter for preflight, installation, and scripts. Examples
  use `python -X utf8`; substitute an available Python 3 launcher or virtual
  environment consistently. `-X utf8` avoids Windows locale corruption of Korean
  text. Read/write UTF-8 artifacts; Windows PowerShell needs explicit UTF-8
  encoding rather than its default redirection.
- `/` in example paths denotes a directory separator. Join paths for the host
  OS and quote each path/URL as one shell argument. Use native shell syntax:
  PowerShell `$env:HYL_OUTPUT_ROOT`, Bash `printenv HYL_OUTPUT_ROOT`.
- Workers share files. Only the orchestrator runs risk generation, validation,
  rendering, and verdict persistence. Serialize risk.json updates within each
  run; do not rewrite a part while its verifier is reading it. After repairs,
  refresh risk data and verification for the current part.
- The skill grants no additional filesystem, network, installation, or approval
  permissions. Use existing authorization and the host's normal permission
  mechanism; report policy or transport failures as runtime failures, not log
  defects. Do not fabricate a successful check.

Codex reference: [Subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).
The session's actual tool schema determines the exact dispatch call.
