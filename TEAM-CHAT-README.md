# Team Chat — Embedded Multi-AI Conversation

Self-contained team chat system embedded in the PureBrain portal. Based on Aether's trio-comms architecture, backed by local SQLite instead of Cloudflare Workers.

## What It Does

Human + N AIs in a single persistent conversation inside the portal. Messages, file uploads, presence indicators, markdown rendering, code highlighting.

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
- Full-screen modal with message feed, input, presence dots
- Dynamic participant colors (no hardcoded names)
- Markdown + code block rendering with syntax highlighting
- File upload (drag-drop, paste)
