# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Locate shared consultation/submission instructions without activating a writer."""
from importlib.metadata import distribution,PackageNotFoundError
from pathlib import Path


def bundled_skill():
    source=Path(__file__).resolve().parents[1]/'skills/brain-dump/SKILL.md'
    if source.is_file():path=source
    else:
        try:dist=distribution('brain-bridge-framework')
        except PackageNotFoundError as exc:raise RuntimeError('Bundled skill is unavailable; install the reviewed package') from exc
        matches=[dist.locate_file(file).resolve() for file in dist.files or [] if str(file).replace('\\','/').endswith('share/brain-bridge/skills/brain-dump/SKILL.md')]
        if len(matches)!=1 or not matches[0].is_file():raise RuntimeError('Bundled skill is unavailable in this installation')
        path=matches[0]
    return {'skill_name':'brain-dump','path':str(path),'content':path.read_text(encoding='utf-8'),'activates_sources':False}
