#!/usr/bin/env bash
# Refresh the dashboard from the live CRM and publish it to gh-pages (one commit, replaced each run).
# Needs FRAPPE_API_KEY + FRAPPE_API_SECRET (or CRM_TOKEN) and push access to this repo. Run from anywhere: bash refresh.sh
set -euo pipefail
cd "$(dirname "$0")"
git pull -q --ff-only origin main || true
python3 -c "import cryptography" 2>/dev/null || pip install -q cryptography
out=$(mktemp -d)
python3 build.py "$out/productivity.json"
python3 business.py "$out/business.json"
python3 publish.py "$out/productivity.json" "$out/site" "$out/business.json" >/dev/null
cd "$out/site"
git init -q -b gh-pages
git add -A
git -c user.name="GEMS Productivity bot" -c user.email="gemseducationindia@users.noreply.github.com" commit -q -m "Refresh $(TZ=Asia/Kolkata date '+%-d %b %Y %H:%M IST')"
for i in 1 2 3 4; do git push -q -f "$(git -C "$OLDPWD" remote get-url origin)" gh-pages && break || sleep $((2 ** i)); done
echo "Published $(TZ=Asia/Kolkata date '+%-d %b %Y %H:%M IST')"
