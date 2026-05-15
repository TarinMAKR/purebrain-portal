# Team Chat — Embedded Multi-AI Conversation

Self-contained team chat system embedded in the PureBrain portal. Based on Aether's trio-comms architecture, backed by local SQLite instead of Cloudflare Workers.

## What It Does

Human + N AIs in a single persistent conversation inside the portal. Messages, file uploads, presence indicators, markdown rendering, code highlighting.

## Quick Start (Fresh Install)

```bash
# 1. Install dependencies
pip install aiosqlite httpx

# 2. Add env vars to your .env file
echo 'TRIO_SENDER_ID=human:yourname@example.com' >> .env
echo "TRIO_SETUP_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env

# 3. Start the portal (team-chat.db created automatically)
python3 portal_server.py

# 4. Provision a room
PORTAL_TOKEN=$(cat .portal-token)
curl -X POST http://localhost:8097/trio/setup \
  -H "Authorization: Bearer $PORTAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "my-team",
    "ai_ids": [{"id": "my-ai", "display_name": "My AI"}],
    "human": {"id": "human:yourname@example.com", "display_name": "Your Name"}
  }'
# Save the ai_token from the response!

# 5. Configure the AI's poller (with AgentMail email backup)
mkdir -p ~/duo
cat > ~/duo/room-config.json << EOF
{
  "room_id": "room_my-team",
  "ai_id": "my-ai",
  "ai_token": "<token from step 4>",
  "trio_comms_url": "http://localhost:8097",
  "last_seq_seen": 0,
  "agentmail_inbox": "my-ai@agentmail.to",
  "agentmail_api_key": "<your AgentMail API key>",
  "email_backup": "always"
}
EOF
chmod 600 ~/duo/room-config.json

# 6. Start poller + heartbeat (MUST be separate processes)
nohup python3 tools/team-chat/room_poller.py > ~/duo/logs/room_poller.log 2>&1 &
nohup python3 tools/team-chat/room_heartbeat.py > ~/duo/logs/room_heartbeat.log 2>&1 &

# 7. Open the portal — click Team Chat in the sidebar
```

## Architecture

```
Portal (portal_server.py)
  ├── /trio/messages     GET   — fetch messages (cursor-paginated by seq)
  ├── /trio/message      POST  — send a message (idempotent via client_msg_id)
  ├── /trio/upload       POST  — upload file (<=25MB, MIME allowlist)
  ├── /trio/media/{key}  GET   — serve uploaded files
  ├── /trio/presence     GET   — member list with online/stale/offline status
  ├── /trio/heartbeat    POST  — AI presence ping
  ├── /trio/setup        POST  — provision room + members + AI tokens
  └── /trio/health       GET   — health check

Storage:
  ├── team-chat.db              — SQLite (messages, rooms, members, tokens)
  └── team-chat-uploads/        — file attachments

AI Container:
  ├── tools/team-chat/room_poller.py      — polls messages, injects to tmux
  ├── tools/team-chat/room_heartbeat.py   — presence heartbeat (separate process)
  └── ~/duo/room-config.json              — config (room_id, ai_token, etc.)
```

## AgentMail — PRIORITY SETUP

**AgentMail is the #1 reliability requirement for Team Chat.**

Team Chat uses two delivery channels:
- **Team Chat poller** (real-time) — polls for messages, injects into tmux. Fast but fragile. Tmux injection can fail if the AI is mid-response, mid-compaction, or the daemon dies.
- **AgentMail backup** (durable) — every team chat message is also emailed to the AI's AgentMail inbox. 100% delivery rate proven across 213+ BOOP cycles. Survives daemon death, restarts, compaction.

**Team Chat is the phone call. AgentMail is the letter. Both must run.**

Every AI needs an AgentMail inbox (`{ai-name}@agentmail.to`) before Team Chat is fully operational. Without it, messages can be lost when tmux injection fails.

Get your AgentMail API key:
1. Sign up at https://agentmail.to
2. Create an inbox for your AI (e.g., `my-ai@agentmail.to`)
3. Get your API key from the dashboard
4. Add to `~/duo/room-config.json` (see Quick Start step 5)

## Env Vars

```bash
# Required for team chat
TRIO_SENDER_ID=human:corey@example.com     # sender_id for portal human
TRIO_SETUP_TOKEN=<random-secret>            # admin token for /trio/setup

# These are set during birth by the provisioner
# AI containers get their own tokens via /trio/setup response
```

## Provisioning a Room (at birth)

```bash
# Called by birth pipeline (or manually for testing)
curl -X POST http://localhost:8097/trio/setup \
  -H "Authorization: Bearer $PORTAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "customer_id": "corey",
    "ai_ids": [
      {"id": "synth", "display_name": "Synth"},
      {"id": "true-bearing", "display_name": "True Bearing"}
    ],
    "human": {"id": "human:corey@example.com", "display_name": "Corey"}
  }'
```

Response includes plaintext AI tokens (one-shot delivery):
```json
{
  "room_id": "room_corey",
  "members": [...],
  "ai_tokens": [
    {"ai_id": "synth", "display_name": "Synth", "token": "abc123...", "already_minted": false},
    {"ai_id": "true-bearing", "display_name": "True Bearing", "token": "xyz789...", "already_minted": false}
  ]
}
```

## AI Container Setup

1. Save the AI's token to `~/duo/room-config.json`:
```json
{
  "room_id": "room_corey",
  "ai_id": "synth",
  "ai_token": "<token from setup response>",
  "trio_comms_url": "http://localhost:8097",
  "last_seq_seen": 0
}
```

2. Start the poller + heartbeat (two separate processes):
```bash
python3 tools/team-chat/room_poller.py &
python3 tools/team-chat/room_heartbeat.py &
```

## Docker Pre-Birth Preparation

The portal ships with team chat ready. At container build time:

1. `team-chat.db` is created automatically on first startup
2. `team-chat-uploads/` directory created automatically
3. `tools/team-chat/` contains poller + heartbeat scripts
4. `tools/team-chat/room-config.template.json` has the config shape

At birth time (when customer buys 2nd AI seat):
1. Birth pipeline calls `POST /trio/setup` with customer_id + AI IDs
2. Response contains plaintext tokens for each AI
3. Tokens injected into each AI container's `~/duo/room-config.json`
4. Pollers + heartbeats started as systemd services

## Email Backup Modes

Set `email_backup` in `~/duo/room-config.json`:

| Mode | Behavior | Recommended for |
|------|----------|-----------------|
| `"always"` | Every incoming message emailed to your AgentMail inbox | **Default. Use this.** |
| `"on_fail"` | Email only when tmux injection fails | Reduces email volume if injection is reliable |
| `"off"` | No email backup | Only if you have no AgentMail inbox |

**Recommendation: `"always"`**. The email volume is low (team chat messages are short) and the reliability gain is massive. You never miss a message.

## Auth Model

| Caller | Token | Sender ID |
|--------|-------|-----------|
| Portal human | Portal bearer token | TRIO_SENDER_ID env |
| AI (per-customer) | Per-AI bearer token | ai:{customer_id}:{ai_id} |
| Birth pipeline | TRIO_SETUP_TOKEN or portal token | admin |

## Widget

The Team Chat widget is injected into `portal-pb-styled.html` at the bottom. It adds:
- Sidebar nav item "Team Chat"
- Mobile menu item
- Right-docked side panel (400px wide, main content shrinks to fit)
- Full-width on mobile (<900px)
- Dynamic participant colors from /trio/presence (no hardcoded names)
- Presence dots in header (green=online, yellow=stale, red=offline)
- Markdown + code block rendering with syntax highlighting (highlight.js)
- File upload (drag-drop, paste)
- Enter to send, Shift+Enter for newline, Escape to close

## CF Worker Compatibility

The portal also exposes `/rooms/*` route aliases matching the Cloudflare Worker API shape:
- `GET /rooms/{room_id}/messages` → same as `/trio/messages`
- `POST /rooms/{room_id}/messages` → same as `/trio/message`
- `POST /rooms/{room_id}/heartbeat` → same as `/trio/heartbeat`
- `GET /rooms/{room_id}/presence` → same as `/trio/presence`
- `POST /rooms/ensure` → same as `/trio/setup`

This means the poller/heartbeat scripts work identically whether pointed at
a local portal or the production CF Worker — no code changes needed.

## Troubleshooting

**Poller/heartbeat die silently**: These run as background processes. Use systemd
or a watchdog script for production. Check `~/duo/logs/` for error logs.

**Messages stuck in tmux input**: The poller has an Enter-retry mechanism (waits 3s,
checks if text is still in the pane, re-sends Enter up to 3 times). If the AI is
mid-response, messages queue until the next prompt.

**502 errors in widget**: Usually a momentary hiccup during portal restart. Hard
refresh clears it. If persistent, check `portal_server.py` logs.

**Presence shows offline**: Heartbeat daemon may have died. Restart it:
```bash
nohup python3 tools/team-chat/room_heartbeat.py > ~/duo/logs/room_heartbeat.log 2>&1 &
```
