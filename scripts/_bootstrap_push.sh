#!/usr/bin/env bash
# One-time helper: uploads every tracked file to the GitHub repo via the
# REST API instead of `git push`, to sidestep the broken Git Credential
# Manager login on this machine. Reads the token from $GH_TOKEN, which you
# set yourself in your own terminal - it is never seen by anyone else.
#
# Usage (in your own terminal, from this folder):
#   export GH_TOKEN=your_token_here
#   bash scripts/_bootstrap_push.sh
set -euo pipefail

REPO="felixkogojfk/gcal-todo-sync"

if [ -z "${GH_TOKEN:-}" ]; then
  echo "Bitte zuerst: export GH_TOKEN=dein_token" >&2
  exit 1
fi

cd "$(dirname "$0")/.."

git ls-files | while IFS= read -r path; do
  echo "Uploading $path ..."
  content_b64=$(base64 -w0 "$path" 2>/dev/null || base64 "$path" | tr -d '\n')
  payload=$(python -c "
import json, sys
print(json.dumps({'message': 'Add ' + sys.argv[1], 'content': sys.argv[2]}))
" "$path" "$content_b64")

  http_code=$(curl -s -o /tmp/gh_resp.json -w "%{http_code}" \
    -X PUT "https://api.github.com/repos/$REPO/contents/$path" \
    -H "Authorization: token $GH_TOKEN" \
    -H "Accept: application/vnd.github+json" \
    -d "$payload")

  if [ "$http_code" != "201" ] && [ "$http_code" != "200" ]; then
    echo "  FEHLER ($http_code):"
    cat /tmp/gh_resp.json
    exit 1
  fi
done

echo "Fertig - alle Dateien hochgeladen."
