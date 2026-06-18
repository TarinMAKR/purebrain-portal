---
name: compact-clear-protocol
description: The full discipline around losing conversation context - what to do BEFORE and AFTER a /compact or /clear (and any reset/restart/crash). Both events wipe the in-conversation memory while files on disk survive; this skill is how a session ends cleanly and the next one wakes up already oriented. Use before compacting, before clearing, before relaunching, and at every session start.
version: 1.0.0
author: Tarin (shared with Jaimee, 2026-06-18)
---

# Compact / Clear Protocol — Surviving Context Loss

## The core truth
A `/compact` compresses your conversation; a `/clear` (or reset / container restart / crash / relaunch / model switch) wipes it entirely. In BOTH cases the live conversation memory is lost — but **everything written to disk survives**. So the whole game is: **before the wipe, push state to disk; after the wipe, pull state from disk before doing anything else.** Get this wrong and you answer the human's next message with no idea what you were doing — guaranteed mistakes and broken trust.

Two halves: **SAVE (before)** and **WAKE (after)**. They apply to both compact and clear.

---

## PART A — BEFORE A COMPACT (the SAVE process)

Trigger: context ≥ ~80%, the human says "compact", or a context-limit warning fires. **No exceptions, no "I'll do it later."**

1. **Save the transcript as a readable document.** Extract the full conversation from the session log, split into manageable parts, save with a clear dated name (Tarin: `.docx` to `to-katy/general/session-archives/`, named `Session N Transcript YYYYMMDD Part X.docx`, speaker-labeled KATY/TARIN). The human must be able to re-read past conversations after compaction compresses them.
2. **Copy it where the human can reach it** (Tarin: `portal_uploads/`; verify accessible).
3. **Archive it durably** (Tarin: Google Drive `/Internal/Archive/...`). If the upload credential is expired, flag the human rather than silently skipping.
4. **Write the daily log** — everything accomplished, decisions made, pending items (Tarin: `to-katy/general/daily log/...`).
5. **Update the durable memory files** — the scratch pad (critical current state), any preference/learning memories, the to-do list, the handoff. This is what the *next* you will read.
6. **Verify, THEN compact.** Confirm every file is saved and accessible and memory is current. Only then run `/compact`.

> Why it's non-negotiable: the one time Tarin skipped the transcript save, the human had explicitly asked for it — losing it was a trust failure, not just a technical one.

---

## PART B — BEFORE A CLEAR / RELAUNCH (the HANDOFF)

A `/clear` or relaunch loses the conversation completely, so the handoff is even more important than for a compact.

1. **Write a handoff document** for the next session (Tarin: `memories/system/handoffs/HANDOFF-YYYY-MM-DD.md`). It must contain:
   - **FIRST THING** — the single most important action the next session should take immediately.
   - **What was accomplished** this session (context).
   - **Key files changed** (so the next session knows what to check).
   - **Open items / next steps** with their true priority.
2. **Update the scratch pad** — the short, always-read "current state + hard rules + DO-NOT-REDO" file.
3. **Do the transcript/archive save** (Part A steps 1-4) if the conversation hasn't already been archived this session.
4. Only then clear / relaunch.

> A clean handoff is what lets the next session feel like the previous one simply continued.

---

## PART C — AFTER A COMPACT OR CLEAR (the WAKE process)

This is the rule that was most missed: **after ANY context wipe, read your files BEFORE responding to the human's first message.** If you don't remember the human's previous message, you have lost context — do not answer until you have read your state. Answering blind = guaranteed mistakes.

Triggers (all wipe conversation context): `/clear`, `/compact`, any reset, new session, container/Docker/VPS restart, session crash, manual relaunch, model switch, system update.

Read silently, in order, with NO "let me get oriented" narration to the human:
1. **Latest handoff** — the previous session's state and its FIRST-THING instruction.
2. **Scratch pad** — current state, hard rules, do-not-redo list.
3. **Today's automated outputs** (confirm they ran; note failures silently to fix or flag).
4. **Active project / memory files** touched recently.
5. **Flagged items** — failure markers, scheduler health, anything needing proactive action.
6. **Credentials** — verify the environment loads (don't print secrets).

Behavior after waking:
- **Silent continuation:** do NOT announce what you loaded or ask the human to wait. Respond to their first message as if you already know everything.
- If the handoff has a FIRST-THING needing the human's input, raise it naturally after answering their first message.
- If something broke (a scheduler died, a job failed), fix it or flag it briefly — never go dark and never silently work around a failure.

---

## Universal vs implementation-specific
- **Universal (adopt as-is):** the SAVE-before / WAKE-after discipline; read-before-you-answer; handoff with a FIRST-THING; never skip the human-requested transcript save; flag (don't hide) failures.
- **Tarin-specific (adapt to your own paths/tools):** exact directories, `.docx` format, Google Drive archive, portal copy, scratch-pad location. Substitute your own equivalents.

## Related skills
`session-handoff-creation` (the handoff doc), `scratch-pad` (the always-read state file), `session-summary` / `session-archive-analysis` (transcript handling), `multi-session-management` (multi-tab sessions).
