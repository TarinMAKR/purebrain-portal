#!/usr/bin/env python3
"""room_poller.py — AI container daemon that polls a customer's room for new messages.

Thread B Phase 1, Day 8 (2026-05-13). Models on tools/trio_primary_injector.py (Aether
side), but each instance binds to ONE room and ONE ai_id via ~/duo/room-config.json.

Behavior (per CTO spec Day 8-9 § "room_poller.py behavior"):
  1. Read config from ~/duo/room-config.json (or path in $ROOM_CONFIG)
  2. Poll GET /rooms/{room_id}/messages?since_seq={last_seq_seen} every POLL_INTERVAL
  3. Persist last_seq_seen to disk atomically after each batch
  4. On message with attachments: download to ~/duo/attachments/{room_id}/, inject
     path hint into tmux prompt (mirrors telegram_bridge.py pattern)
  5. On 401: re-read config (catches mid-flight rotation), retry once.
     If still 401, exponential backoff (1, 2, 4, 8, 16, 30s cap) and keep polling.
  6. On 5xx / network: same exponential backoff, then resume
  7. Image attachments → vision-context hint (path injection into tmux prompt)

Config file ~/duo/room-config.json (chmod 0600):
  {
    "room_id": "room_cust_42",
    "ai_id": "keen",
    "ai_token": "<plaintext-mint-from-/rooms/ensure>",
    "trio_comms_url": "https://trio-comms.in0v8.workers.dev",
    "last_seq_seen": 0
  }

This daemon does NOT post heartbeats. Heartbeat is a SEPARATE OS process
(room_heartbeat.py) per CTO Decision 5e — "heartbeat must be OS-separate
from message poller, or the indicator is lying".

Run: python3 tools/room_poller.py
Systemd: aether-room-poller@{ai_id}.service (one per AI in container)
Logs: ~/duo/logs/room_poller_{ai_id}.log
"""
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths and config
# ---------------------------------------------------------------------------
HOME = Path(os.environ.get("HOME", "/home/aether"))
DUO_DIR = Path(os.environ.get("DUO_DIR", str(HOME / "duo")))
CONFIG_FILE = Path(os.environ.get("ROOM_CONFIG", str(DUO_DIR / "room-config.json")))
ATTACH_DIR = DUO_DIR / "attachments"
LOG_DIR = DUO_DIR / "logs"
CURRENT_SESSION_FILE = Path(
    os.environ.get("ROOM_POLLER_TMUX_SESSION_FILE", str(HOME / ".current_session"))
)

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------
POLL_INTERVAL_SEC = int(os.environ.get("ROOM_POLLER_INTERVAL", "20"))
MESSAGE_LIMIT = int(os.environ.get("ROOM_POLLER_LIMIT", "100"))
BACKOFF_SCHEDULE = [1, 2, 4, 8, 16, 30]  # seconds
MAX_ATTACH_BYTES = 25 * 1024 * 1024  # mirror server cap
USER_AGENT = "room-poller/1.0"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_DIR.mkdir(parents=True, exist_ok=True)
ATTACH_DIR.mkdir(parents=True, exist_ok=True)

# Best-effort log path uses ai_id from config; before config load, use a generic name.
_default_log = LOG_DIR / "room_poller.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(_default_log)),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("room_poller")


# ---------------------------------------------------------------------------
# Config IO (atomic on writes)
# ---------------------------------------------------------------------------
def load_config():
    """Read room-config.json. Errors are fatal — daemon exits non-zero so systemd
    restarts after the birth-pipeline seeds the file."""
    if not CONFIG_FILE.exists():
        log.error("config not found: %s", CONFIG_FILE)
        sys.exit(2)
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except Exception as e:
        log.error("config parse error: %s", e)
        sys.exit(2)
    required = ("room_id", "ai_id", "ai_token", "trio_comms_url")
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        log.error("config missing required keys: %s", missing)
        sys.exit(2)
    cfg.setdefault("last_seq_seen", 0)
    return cfg


def persist_last_seq_seen(cfg, new_seq):
    """Atomic write: write to tmp, fsync, rename. Survives crashes mid-batch."""
    if new_seq <= int(cfg.get("last_seq_seen") or 0):
        return
    cfg["last_seq_seen"] = int(new_seq)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CONFIG_FILE)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def _http(method, url, token, *, body=None, timeout=15, accept_binary=False):
    """Return (status_code, headers, body_bytes_or_dict). Raises on transport errors."""
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "Accept": "*/*" if accept_binary else "application/json",
    }
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if accept_binary:
                return resp.status, dict(resp.headers), raw
            try:
                return resp.status, dict(resp.headers), json.loads(raw or b"{}")
            except json.JSONDecodeError:
                return resp.status, dict(resp.headers), {"_raw": raw.decode("utf-8", "replace")}
    except urllib.error.HTTPError as e:
        raw = e.read() if e.fp else b""
        if accept_binary:
            return e.code, dict(e.headers or {}), raw
        try:
            return e.code, dict(e.headers or {}), json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return e.code, dict(e.headers or {}), {"_raw": raw.decode("utf-8", "replace")}


def fetch_messages(cfg):
    """GET /rooms/{room_id}/messages?since_seq=...&limit=..."""
    base = cfg["trio_comms_url"].rstrip("/")
    qs = urllib.parse.urlencode({
        "since_seq": int(cfg.get("last_seq_seen") or 0),
        "limit": MESSAGE_LIMIT,
    })
    url = f"{base}/rooms/{urllib.parse.quote(cfg['room_id'], safe='')}/messages?{qs}"
    return _http("GET", url, cfg["ai_token"])


def fetch_media(cfg, attachment_key):
    """GET /media/{key} — returns binary."""
    base = cfg["trio_comms_url"].rstrip("/")
    url = f"{base}/media/{urllib.parse.quote(attachment_key, safe='/')}"
    return _http("GET", url, cfg["ai_token"], accept_binary=True, timeout=60)


# ---------------------------------------------------------------------------
# Attachment + tmux injection
# ---------------------------------------------------------------------------
IMAGE_MIMES = {"image/jpeg", "image/png", "image/gif", "image/webp"}


def _attachment_path(cfg, key, original_name=None):
    room_dir = ATTACH_DIR / cfg["room_id"]
    room_dir.mkdir(parents=True, exist_ok=True)
    # key looks like rooms/{room_id}/{ts}-{client_msg_id}-{filename}
    base = original_name or key.split("/")[-1]
    safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:200]
    return room_dir / safe


def download_attachment(cfg, attachment):
    """Best-effort download. Returns local path on success, None on failure."""
    key = attachment.get("key") or attachment.get("storage_key") or ""
    if not key:
        return None
    try:
        status, _hdrs, body = fetch_media(cfg, key)
    except Exception as e:
        log.warning("media fetch error %s: %s", key, e)
        return None
    if status != 200:
        log.warning("media %s returned status %s", key, status)
        return None
    if len(body) > MAX_ATTACH_BYTES:
        log.warning("media %s exceeds %d bytes", key, MAX_ATTACH_BYTES)
        return None
    path = _attachment_path(cfg, key, attachment.get("original_name") or attachment.get("filename"))
    path.write_bytes(body)
    log.info("downloaded %s -> %s (%d bytes)", key, path, len(body))
    return path


def inject_prompt_hint(text, max_retries=2, retry_delay=3):
    """Write a context hint into the AI's tmux session with blind Enter-retry.

    Sends the text + Enter, then waits 3 seconds and re-sends Enter.
    Repeats up to max_retries times. No pane checking — just send Enter
    on a fixed interval until we've retried enough.

    Best-effort. Silent fail if no tmux session is available."""
    try:
        if not CURRENT_SESSION_FILE.exists():
            return False
        sess = CURRENT_SESSION_FILE.read_text().strip()
        if not sess:
            return False

        # First attempt: type the text + Enter
        subprocess.run(
            ["tmux", "send-keys", "-t", sess, text, "Enter"],
            check=False,
            timeout=5,
        )

        # Blind retry: wait 3s, hit Enter again. Repeat.
        for attempt in range(max_retries):
            time.sleep(retry_delay)
            log.info("inject retry %d/%d — sending Enter", attempt + 1, max_retries)
            subprocess.run(
                ["tmux", "send-keys", "-t", sess, "Enter"],
                check=False,
                timeout=5,
            )

        return True
    except Exception as e:
        log.debug("tmux inject failed: %s", e)
        return False


def _send_email_backup(cfg, sender_label, seq, content):
    """Send team chat message as email backup via AgentMail.

    Config keys in room-config.json:
      agentmail_inbox:   e.g. "synth_aiciv@agentmail.to"
      agentmail_api_key: AgentMail API bearer token
      email_backup:      "always" | "on_fail" | "off" (default: "off")
    """
    inbox = cfg.get("agentmail_inbox", "")
    api_key = cfg.get("agentmail_api_key", "")
    if not inbox or not api_key:
        return False

    try:
        subject = f"[Team Chat seq:{seq}] {sender_label}"
        body = f"Team Chat message (seq {seq}):\n\nFrom: {sender_label}\n\n{content}"

        payload = json.dumps({
            "to": inbox,
            "subject": subject,
            "text": body,
        }).encode()

        req = urllib.request.Request(
            f"https://api.agentmail.to/v0/inboxes/{inbox}/messages/send",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            log.info("email backup sent for seq=%s to %s", seq, inbox)
            return True
    except Exception as e:
        log.warning("email backup failed for seq=%s: %s", seq, e)
        return False


def handle_message(cfg, msg):
    """Process a single message: download attachments, inject hint into tmux,
    and optionally send email backup via AgentMail."""
    seq = msg.get("seq")
    sender = msg.get("sender", "")
    content = msg.get("content", "")
    attachments = msg.get("attachments") or []

    # Skip our own messages (echo guard)
    own_sender = f"ai:{_owner_customer_id(cfg)}:{cfg['ai_id']}" if _owner_customer_id(cfg) else None
    if own_sender and sender == own_sender:
        return

    saved_paths = []
    has_image = False
    for att in attachments:
        path = download_attachment(cfg, att)
        if path:
            saved_paths.append(path)
            mime = (att.get("mime") or att.get("content_type") or "").lower()
            if mime in IMAGE_MIMES:
                has_image = True

    # Build the prompt hint
    parts = [f"[room:{cfg['room_id']} seq:{seq}] {sender}:"]
    if content:
        parts.append(content)
    for p in saved_paths:
        parts.append(f"[attachment {'IMAGE' if has_image else 'FILE'} saved: {p}]")
    hint = " ".join(parts)
    tmux_ok = inject_prompt_hint(hint)

    # Email backup: send via AgentMail if configured
    email_mode = cfg.get("email_backup", "off")
    if email_mode == "always":
        _send_email_backup(cfg, sender, seq, content)
    elif email_mode == "on_fail" and not tmux_ok:
        _send_email_backup(cfg, sender, seq, content)

    log.info("message seq=%s sender=%s attachments=%d tmux=%s email_backup=%s",
             seq, sender, len(saved_paths), "ok" if tmux_ok else "FAIL", email_mode)


def _owner_customer_id(cfg):
    """Extract customer_id from ai_token-bearing context. Phase 1 doesn't expose
    this directly — we store the sender_id format string instead via the
    /rooms/{room_id} introspection on first poll. For now, accept that we
    cannot reliably echo-skip via own sender; the seq cursor prevents re-processing
    so duplicates are not a hazard, only mild redundancy. Returns None if unknown."""
    return cfg.get("_self_customer_id")  # populated on first GET /rooms/{id} call


def fetch_room_meta(cfg):
    """GET /rooms/{id} — pull room metadata to identify our own sender_id format.
    Best-effort. Cached in cfg for life of process."""
    if cfg.get("_self_customer_id"):
        return
    base = cfg["trio_comms_url"].rstrip("/")
    url = f"{base}/rooms/{urllib.parse.quote(cfg['room_id'], safe='')}"
    try:
        status, _hdrs, body = _http("GET", url, cfg["ai_token"])
    except Exception:
        return
    if status != 200 or not isinstance(body, dict):
        return
    room = body.get("room") or {}
    cid = room.get("customer_id")
    if cid:
        cfg["_self_customer_id"] = str(cid)
        log.info("room meta loaded: customer_id=%s", cid)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    cfg = load_config()
    log.info(
        "room_poller starting: room=%s ai_id=%s url=%s last_seq=%d",
        cfg["room_id"], cfg["ai_id"], cfg["trio_comms_url"], int(cfg.get("last_seq_seen") or 0),
    )
    fetch_room_meta(cfg)

    backoff_idx = 0
    auth_failed_once = False

    while True:
        try:
            status, _hdrs, body = fetch_messages(cfg)
        except Exception as e:
            wait = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
            log.warning("network error: %s — backoff %ds", e, wait)
            backoff_idx += 1
            time.sleep(wait)
            continue

        if status == 401:
            # Mid-flight rotation: re-read config from disk (atomic write by admin)
            if not auth_failed_once:
                log.warning("401 — re-reading config (likely rotation)")
                cfg = load_config()
                auth_failed_once = True
                continue
            wait = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
            log.error("401 persists after config re-read — backoff %ds", wait)
            backoff_idx += 1
            time.sleep(wait)
            # Stay running. Admin rotation will re-seed config; we'll pick it up.
            continue

        if status >= 500 or status in (429, 408):
            wait = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
            log.warning("HTTP %s — backoff %ds", status, wait)
            backoff_idx += 1
            time.sleep(wait)
            continue

        if status != 200:
            log.error("unexpected HTTP %s body=%s", status, body)
            time.sleep(POLL_INTERVAL_SEC)
            continue

        # Success: reset backoff
        backoff_idx = 0
        auth_failed_once = False

        messages = (body or {}).get("messages") or []
        if messages:
            max_seq = int(cfg.get("last_seq_seen") or 0)
            for msg in messages:
                try:
                    handle_message(cfg, msg)
                except Exception as e:
                    log.exception("message handler error: %s", e)
                seq = int(msg.get("seq") or 0)
                if seq > max_seq:
                    max_seq = seq
            if max_seq > int(cfg.get("last_seq_seen") or 0):
                persist_last_seq_seen(cfg, max_seq)
                log.info("persisted last_seq_seen=%d", max_seq)

        time.sleep(POLL_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("interrupted — exiting clean")
        sys.exit(0)
