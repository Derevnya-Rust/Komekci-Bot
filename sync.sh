#!/usr/bin/env bash
set -e
git add -A
git commit -m "sync: $(date -Is)" || true
git pull --rebase origin main
git push origin main
