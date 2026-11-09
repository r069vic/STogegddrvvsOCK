#!/usr/bin/env bash
# On-demand quote lookup via GitHub Actions.
# Usage: scripts/q.sh SOXX,2330,^VIX
# Needs: gh CLI with access to this repo (REST only). Takes ~30-90s.
set -euo pipefail

R="${QUOTES_REPO:-r069vic/STogegddrvvsOCK}"
SYMS="${1:?usage: q.sh SYMBOL[,SYMBOL...]}"
START=$(date -u -d '-30 seconds' +%Y-%m-%dT%H:%M:%SZ)

gh api -X POST "repos/$R/actions/workflows/quotes.yml/dispatches" \
  -f ref=main -f "inputs[symbols]=$SYMS" >/dev/null
echo "dispatched: $SYMS" >&2
sleep 6

RUN=""
for _ in $(seq 1 60); do
  row=$(gh api "repos/$R/actions/runs?event=workflow_dispatch&per_page=10" \
    -q "[.workflow_runs[]|select(.created_at>=\"$START\")]|sort_by(.created_at)|last|\"\(.id) \(.status) \(.conclusion)\"" 2>/dev/null || true)
  RUN=${row%% *}
  case "$row" in
    *"completed success"*) break ;;
    *"completed "*) echo "run $RUN failed: $row" >&2; exit 1 ;;
  esac
  sleep 5
done
[ -n "$RUN" ] || { echo "run not found" >&2; exit 1; }

gh api "repos/$R/contents/quotes.json?ref=adhoc" -q .content | base64 -d | python3 -I -c '
import json, sys
d = json.load(sys.stdin)
print("generated", d["generated_at_taipei"], "| errors:", d["errors"])
for k, v in d["quotes"].items():
    t = v.get("time") or v.get("stooq_datetime")
    row = [k, v["price"], "chg", v.get("change_pct"), v["source"], v.get("session"), t]
    print(*row, sep="  ")
'
