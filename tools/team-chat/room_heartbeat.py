#!/usr/bin/env python3
"""room_heartbeat.py — AI container heartbeat daemon, OS-separate from room_poller.

Thread B Phase 1, Day 8 (2026-05-13). Per CTO Decision 5e:

    "Heartbeat MUST be an OS-separate process from the message poller,
     or the indicator is lying. If the poller crashes silently and the
     heartbeat keeps firing from inside the same process, presence shows
     online while no messages flow. Two processes = two health signals."

Posts POST /rooms/{room_id}/heartbeat every 60s using the same ai_token from
~/duo/room-config.json. On 401 it re-reads config (handles rotation), then
exponential-backs-off identically to room_poller.

Config: same file as room_poller (~/duo/room-config.json). Read-only here —
heartbeat NEVER mutates last_seq_seen (that's the poller's job).

Run: python3 tools/room_heartbeat.py
Systemd: aether-room-heartbeat@{ai_id}.service (one per AI per container)
Logs: ~/duo/logs/room_heartbeat_{ai_id}.log
"""
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HOME = Path(os.environ.get("HOME", "/home/aether"))
DUO_DIR = Path(os.environ.get("DUO_DIR", str(HOME / "duo")))
CONFIG_FILE = Path(os.environ.get("ROOM_CONFIG", str(DUO_DIR / "room-config.json")))
LOG_DIR = DUO_DIR / "logs"

HEARTBEAT_INTERVAL_SEC = int(os.environ.get("ROOM_HEARTBEAT_INTERVAL", "60"))
BACKOFF_SCHEDULE = [1, 2, 4, 8, 16, 30]
USER_AGENT = "room-heartbeat/1.0"

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(LOG_DIR / "room_heartbeat.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("room_heartbeat")


def load_config():
    if not CONFIG_FILE.exists():
        log.error("config not found: %s", CONFIG_FILE)
        sys.exit(2)
    try:
        cfg = json.loads(CONFIG_FILE.read_text())
    except Exception as e:
        log.error("config parse error: %s", e)
        sys.exit(2)
    for k in ("room_id", "ai_id", "ai_token", "trio_comms_url"):
        if not cfg.get(k):
            log.error("config missing key: %s", k)
            sys.exit(2)
    return cfg


def post_heartbeat(cfg, last_seq_seen=None):
    base = cfg["trio_comms_url"].rstrip("/")
    url = f"{base}/rooms/{urllib.parse.quote(cfg['room_id'], safe='')}/heartbeat"
    body = {}
    # Read poller's last_seq_seen from config (best-effort) — provides better presence info
    if last_seq_seen is None:
        body_seq = int(cfg.get("last_seq_seen") or 0)
        if body_seq > 0:
            body["last_seq_seen"] = body_seq
    elif last_seq_seen >= 0:
        body["last_seq_seen"] = int(last_seq_seen)

    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {cfg['ai_token']}",
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""


def main():
    cfg = load_config()
    log.info(
        "room_heartbeat starting: room=%s ai_id=%s interval=%ds",
        cfg["room_id"], cfg["ai_id"], HEARTBEAT_INTERVAL_SEC,
    )
    backoff_idx = 0
    auth_failed_once = False

    while True:
        # Always re-read config at the top of each cycle — poller updates
        # last_seq_seen; we want to report freshest seq in heartbeat.
        try:
            cfg_fresh = json.loads(CONFIG_FILE.read_text())
            cfg.update(cfg_fresh)
        except Exception:
            pass

        try:
            status, _body = post_heartbeat(cfg)
        except Exception as e:
            wait = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
            log.warning("network error: %s — backoff %ds", e, wait)
            backoff_idx += 1
            time.sleep(wait)
            continue

        if status == 401:
            if not auth_failed_once:
                log.warning("401 on heartbeat — re-reading config")
                cfg = load_config()
                auth_failed_once = True
                continue
            wait = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
            log.error("401 persists — backoff %ds", wait)
            backoff_idx += 1
            time.sleep(wait)
            continue

        if status >= 500 or status in (408, 429):
            wait = BACKOFF_SCHEDULE[min(backoff_idx, len(BACKOFF_SCHEDULE) - 1)]
            log.warning("HTTP %s — backoff %ds", status, wait)
            backoff_idx += 1
            time.sleep(wait)
            continue

        if status != 200:
            log.error("unexpected HTTP %s", status)
            time.sleep(HEARTBEAT_INTERVAL_SEC)
            continue

        backoff_idx = 0
        auth_failed_once = False
        log.debug("heartbeat ok")
        time.sleep(HEARTBEAT_INTERVAL_SEC)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("interrupted — exiting clean")
        sys.exit(0)
