#!/usr/bin/env python3
# script_version: 1.0.1
# Purpose: Public Brain runtime bootstrap; plan by default, explicit installation and verification.
# Usage: python3 bootstrap.py --config /absolute/profile.json [--operation plan|preflight|install|verify] [--execute --yes] [--json|--pretty]
# Output: JSON with common framework metadata; progress/errors never corrupt stdout.
# Prerequisites: Python3.11+, Git and a reviewed source checkout; no private integration repository.
from brain_bridge.__main__ import main
import sys
if __name__=='__main__':
    arguments=sys.argv[1:]
    raise SystemExit(main(arguments if arguments in (['--version'],['--license']) else ['bootstrap',*arguments]))
