#!/bin/bash
# Run with project venv Python (never system Homebrew Python)
cd "$(dirname "$0")"
exec ./venv/bin/python keychain.py "$@"
