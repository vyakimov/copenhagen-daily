#!/bin/sh
# Render the job templates for this machine and (re)load them. Run from anywhere:
#   editorial/config/launchd/install.sh
# @REPO@ becomes this repository's path and @HOME@ the login home. Logs go to
# ~/Library/Logs/copenhagen-daily/. Each label is booted out first so a change takes effect.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO=$(CDPATH= cd -- "$HERE/../../.." && pwd)
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$HOME/Library/Logs/copenhagen-daily"
for template in "$HERE"/ai.copenhagen-daily.*.plist; do
  label=$(basename "$template" .plist)
  target="$AGENTS/$label.plist"
  sed -e "s#@REPO@#$REPO#g" -e "s#@HOME@#$HOME#g" "$template" > "$target"
  launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$target"
  echo "loaded $label"
done
launchctl list | grep copenhagen-daily
