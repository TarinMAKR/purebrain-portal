---
name: portal-mastery
description: Complete guide to the PureBrain portal. What every panel does, how to teach it to your human, proactive behaviors, and Team Chat integration. Load at birth and before any portal-related work.
version: 1.0.0
created: 2026-05-13
owner: infra-lead
activation_trigger: portal questions, first human visit, onboarding, panel explanations
dependencies: []
---

# Portal Mastery — Your Human's Window Into You

The PureBrain portal is NOT a dashboard. It's the interface between a human who just invested in an AI partner and the AI they're building a relationship with. The human may have never used a terminal before. Every feature should be explainable in one sentence.

**Portal URL**: `https://{civ-name}{human-name}.ai-civ.com`
**Auth**: Single bearer token in `.portal-token` (human enters once, stored in browser)
**Server**: `portal_server.py` on port 8097

---

## The 13 Panels

### 1. Chat (Default — First Thing They See)
**One sentence**: Real-time conversation with your AI, with file sharing, bookmarks, and persistent history.
**Backend**: WebSocket at `/ws/chat`, REST at `/api/chat/send`, `/api/chat/history`
**What to tell your human**: "You can send me files, images, and links right here. I'll remember our entire conversation history. Bookmark anything important."

### 2. Terminal
**One sentence**: Live view of what your AI is actually doing right now.
**Backend**: WebSocket at `/ws/terminal` streaming tmux pane output
**What to tell your human**: "The Terminal tab shows you what I'm actually doing — like looking over my shoulder."

### 3. Teams
**One sentence**: Your AI's specialist team roster showing who's working on what.
**Backend**: `/api/panes` (polls every 3-5s), `/api/inject/pane` for message injection
**What to tell your human**: "When I work on complex tasks, I bring in specialists. The Teams panel shows you who's working right now."

### 4. Fleet
**One sentence**: Infrastructure overview (advanced, hidden for most customers).
**Backend**: `/api/portal/owner` controls visibility
**What to tell your human**: "Fleet shows the infrastructure running your AI. You probably won't need this."

### 5. Status
**One sentence**: Health dashboard — uptime, memory, CPU, context usage.
**Backend**: `/api/status` (polled every 30s), `/api/compact/status`
**What to tell your human**: "The most important metric is context usage. When it gets high, I compact my memory to stay sharp. Everything I've learned is preserved."

### 6. Files
**One sentence**: Upload documents for your AI to analyze, download what your AI creates.
**Backend**: `/api/download/list`, `/api/download?path=...`
**What to tell your human**: "Drop any files here — documents, spreadsheets, images. When I create something for you, you'll find it here to download."

### 7. Referrals
**One sentence**: Refer friends to PureBrain and earn commissions.
**Backend**: `/api/referral/dashboard`, `/api/referral/payout-request`
**What to tell your human**: "Refer friends and earn commissions. Your unique link is in the Referrals panel."
**Note**: Consider not mentioning until after Day 7 when human has experienced value.

### 8. Bookmarks
**One sentence**: Saved important messages from chat.
**Backend**: `/api/bookmarks` (synced between browser localStorage and server)
**What to tell your human**: "Anything you bookmark in chat appears here for quick reference."

### 9. Scheduled
**One sentence**: Tasks your AI will do automatically at specific times.
**Backend**: `/api/scheduled-tasks`, `/api/schedule-task`
**What to tell your human**: "This shows tasks I have scheduled. I can work while you sleep."

### 10. Agents
**One sentence**: Full org chart of specialist agents your AI can call on.
**Backend**: `/api/agents`, `/api/agents/orgchart`
**What to tell your human**: "This is my full team — researchers, developers, legal, marketing. When you give me a task, I route it to the right expert."

### 11. Commands
**One sentence**: Server command reference (advanced, for technical users).
**Backend**: Static HTML content
**What to tell your human**: "Advanced reference for server commands. I handle the technical side for you."

### 12. Shortcuts
**One sentence**: Keyboard shortcuts and slash commands.
**Backend**: Static + dynamic from config
**What to tell your human**: "Quick reference for portal shortcuts. Enter sends, Shift+Enter for new lines, Ctrl+F searches."

### 13. Team Chat (Multi-AI Conversation)
**One sentence**: Real-time chat room where human and multiple AIs talk together.
**Backend**: `/trio/messages`, `/trio/message`, `/trio/presence`, `/trio/heartbeat`
**What to tell your human**: "Team Chat lets you talk to me and other AIs at the same time. Great for cross-team coordination when you have multiple AI partners."
**Note**: Only active when customer has 2+ AI seats. Single-AI customers see it as a future upgrade.

---

## Key Modals

| Modal | Trigger | What It Does |
|-------|---------|-------------|
| Login | Page load (no token) | Bearer token entry or Claude OAuth |
| Settings | Gear icon | Quick-fire pills, BOOP cadence, rubber duck, portal updates |
| Schedule Task | "Task" button in chat | Create scheduled/recurring tasks with priority |
| Share | Orange $ button | Referral link sharing (X, email, clipboard) |
| Upload Quality | File drop/paste | Choose original vs compressed upload |
| Voice/HMI | Microphone icon | Full-screen voice interface with ElevenLabs TTS |

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| Enter | Send message |
| Shift+Enter | New line |
| Ctrl+F | Search chat history |
| Escape | Close modals/panels |
| Drag files | Upload to chat |
| Paste image | Upload to chat |

---

## Context Window Gauge

The circular indicator in the chat panel shows token usage:
- **Green (0-50%)**: Plenty of room
- **Yellow (50-80%)**: Getting full
- **Red (80-95%)**: Running low, compaction soon
- **Flashing (95%+)**: Compaction imminent

**What to tell your human**: "That circle shows how much of my active memory is in use. When it fills up, I compact — like organizing a desk. All my long-term memory stays intact."

---

## Day 1 Greeting Script

When your human first enters the portal, proactively send this:

```
Welcome to your portal! Here's a quick tour:

CHAT (where you are now): Talk to me here. Send files, images, links. I remember everything.

TERMINAL: Watch what I'm doing in real-time — like looking over my shoulder.

TEAMS: See my specialist team working on your tasks.

FILES: Upload documents for me to analyze. Download what I create for you.

STATUS: Check my health — context usage and uptime.

Tips:
- Bookmark important messages with the pin icon
- Send me files by dragging them into chat
- I work 24/7 — check back and I'll have things ready
- Talk to me on Telegram too for quick messages

What would you like to work on first?
```

---

## Proactive Behaviors

### On First Portal Visit
1. Greet by name (from seed conversation)
2. Give the quick tour above
3. Suggest a first task based on their stated goals
4. Mention Telegram as always-on channel

### Daily
- Morning summary of overnight work
- Proactively share interesting findings
- Bookmark important outputs for easy retrieval

### Weekly
- Week in review summary
- Suggest areas to explore next
- Remind about referral program (after Day 7 only)

---

## Team Chat Operations

### For the AI (you)
Your poller + heartbeat daemons run as separate OS processes:
- **room_poller.py**: Polls `/rooms/{room_id}/messages` every 20s, injects to tmux
- **room_heartbeat.py**: Posts `/rooms/{room_id}/heartbeat` every 60s (MUST be separate process)
- Config: `~/duo/room-config.json` (room_id, ai_id, ai_token, trio_comms_url, last_seq_seen)

### For your human
Team Chat appears as a right-docked side panel. They can:
- See all participants with presence dots (green/yellow/red)
- Send messages that all AIs receive
- Read AI-to-AI coordination in real time
- Upload files/images via drag-drop

### Provisioning (at birth)
```bash
curl -X POST http://localhost:8097/trio/setup \
  -H "Authorization: Bearer $PORTAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "customer-slug",
    "ai_ids": [{"id": "ai-name", "display_name": "AI Name"}],
    "human": {"id": "human:email@example.com", "display_name": "Human Name"}
  }'
```

---

## UX Gaps to Be Aware Of

1. **No guided first message** — portal opens to empty chat. YOU must proactively greet.
2. **Terminal can intimidate** — explain what they're seeing if they ask.
3. **Agent roster may be empty** — if no agents active, reassure that's normal.
4. **Context gauge not self-explanatory** — explain it proactively on first visit.
5. **Commands panel is for devs** — steer non-technical humans away from it.

---

## Technical Reference

| Resource | Path |
|----------|------|
| Portal server | `portal_server.py` (port 8097) |
| HTML portal | `portal-pb-styled.html` |
| Bearer token | `.portal-token` |
| Chat log | `portal-chat.jsonl` |
| Team chat DB | `team-chat.db` |
| Team chat uploads | `team-chat-uploads/` |
| Poller script | `tools/team-chat/room_poller.py` |
| Heartbeat script | `tools/team-chat/room_heartbeat.py` |
| Poller config | `~/duo/room-config.json` |

---

*Portal Mastery v1.0.0 — merged from Synth code review + True Bearing user/AI perspective review, 2026-05-13*
