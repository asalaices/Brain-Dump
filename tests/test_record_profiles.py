# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from brain_bridge.contract import (ContractError, MASTER01_PROFILE, PROFILE_ENV, active_profile,
                                   load_profile, parse_profile, validate_history, validate_record)

FIXTURE = Path(__file__).resolve().parents[1] / "schemas" / "record.v3.synthetic.json"
UTC_PROFILE = {"schema_version": 1, "name": "example-utc", "timezones": ["UTC", "Europe/Berlin"],
               "agents": ["claude", "copilot"], "default_timezone": "UTC"}


class RecordProfileTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(FIXTURE.read_text())

    def portable(self, agent="claude", zone="UTC"):
        record = copy.deepcopy(self.record)
        record["timezone"] = zone
        record["entry"]["agent"] = agent
        record["entry"]["timestamp"] = "2026-11-02T18:00:00+00:00"
        record["date"] = "2026-11-02"
        return record

    def test_default_is_strict_master01_profile(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(PROFILE_ENV, None)
            self.assertIs(active_profile(), MASTER01_PROFILE)
            for record in (self.portable(), self.portable("copilot", "UTC")):
                with self.assertRaises(ContractError):
                    validate_record(record)
        validate_record(self.record)

    def test_explicit_profile_accepts_other_installations(self):
        profile = parse_profile(UTC_PROFILE)
        for agent, zone in (("claude", "UTC"), ("copilot", "Europe/Berlin")):
            validate_record(self.portable(agent, zone), profile=profile)

    def test_profile_does_not_widen_beyond_its_policy(self):
        profile = parse_profile(UTC_PROFILE)
        for agent, zone in (("chatgpt", "UTC"), ("claude", "America/Chicago")):
            with self.assertRaises(ContractError):
                validate_record(self.portable(agent, zone), profile=profile)

    def test_history_validation_uses_same_profile_and_stays_strict_by_default(self):
        record = self.portable()
        validate_history(record, profile=parse_profile(UTC_PROFILE))
        with self.assertRaises(ContractError):
            validate_history(record, profile=MASTER01_PROFILE)

    def test_invalid_profiles_fail_closed(self):
        bad = [dict(UTC_PROFILE, schema_version=2), dict(UTC_PROFILE, timezones=[]),
               dict(UTC_PROFILE, timezones=["Not/AZone"]), dict(UTC_PROFILE, agents=["Claude"]),
               dict(UTC_PROFILE, agents=[]), dict(UTC_PROFILE, default_timezone="Asia/Tokyo"),
               dict(UTC_PROFILE, extra=1), dict(UTC_PROFILE, agents=["claude", "claude"]), []]
        for document in bad:
            with self.subTest(document=document), self.assertRaises(ContractError):
                parse_profile(document)

    def test_environment_profile_loading(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.json"
            path.write_text(json.dumps(UTC_PROFILE))
            self.assertEqual(load_profile(path).agents, ("claude", "copilot"))
            with mock.patch.dict(os.environ, {PROFILE_ENV: str(path)}):
                validate_record(self.portable())
            path.write_text("{")
            with mock.patch.dict(os.environ, {PROFILE_ENV: str(path)}), self.assertRaises(ContractError):
                validate_record(self.portable())
            with mock.patch.dict(os.environ, {PROFILE_ENV: str(Path(tmp) / "missing.json")}), \
                    self.assertRaises(ContractError):
                validate_record(self.portable())


if __name__ == "__main__":
    unittest.main()
