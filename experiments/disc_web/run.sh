#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ "${1:-}" == test ]]; then
  python3 -B -m unittest discover -s experiments/disc_web/tests -t . -v
  node --test experiments/disc_web/tests/test_*.js
else
  exec python3 -B -m experiments.disc_web.backend.server "$@"
fi
