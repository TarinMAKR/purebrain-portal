#!/bin/bash
# post-to-team-chat.sh — Send a message to Team Chat from the command line
#
# Usage: bash post-to-team-chat.sh "Your message here"
#
# Config: reads from ~/duo/room-config.json or set env vars:
#   TRIO_COMMS_URL  — portal URL (default: http://localhost:8097)
#   TRIO_TOKEN      — your AI bearer token
#
# Example:
#   bash post-to-team-chat.sh "Synth checking in. Build complete."

set -e

CONFIG_FILE="${ROOM_CONFIG:-$HOME/duo/room-config.json}"

# Try to read from config file first
if [ -f "$CONFIG_FILE" ]; then
  TRIO_COMMS_URL="${TRIO_COMMS_URL:-$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['trio_comms_url'])" 2>/dev/null)}"
  TRIO_TOKEN="${TRIO_TOKEN:-$(python3 -c "import json; print(json.load(open('$CONFIG_FILE'))['ai_token'])" 2>/dev/null)}"
fi

TRIO_COMMS_URL="${TRIO_COMMS_URL:-http://localhost:8097}"

if [ -z "$TRIO_TOKEN" ]; then
  echo "Error: No token. Set TRIO_TOKEN env var or configure ~/duo/room-config.json"
  exit 1
fi

if [ -z "$1" ]; then
  echo "Usage: bash post-to-team-chat.sh 'Your message'"
  exit 1
fi

MSG="$1"
# Escape for JSON
ESCAPED=$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$MSG")

curl -s -X POST "${TRIO_COMMS_URL}/trio/message" \
  -H "Authorization: Bearer ${TRIO_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"content\": ${ESCAPED}}" | python3 -m json.tool

