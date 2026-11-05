# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Ensure invalid v3 records cannot replace an existing SQLite index."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brain_bridge.store import rebuild, is_fresh
from brain_bridge.contract import ContractError

FIXTURE = Path(__file__).resolve().parents[1] / "schemas" / "record.v3.synthetic.json"
NAME = "2026-11-02-12-00-00-11111111-1111-4111-8111-111111111111.json"

class PreIndexContractTests(unittest.TestCase):
    def test_validation_blocks_index_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "records"
            path = root / "2026" / "11" / NAME
            path.parent.mkdir(parents=True)
            db = Path(tmp) / "cache.sqlite"
            doc = json.loads(FIXTURE.read_text())
            path.write_text(json.dumps(doc))
            self.assertEqual(rebuild(root, db, contract="v3"), 1)
            self.assertTrue(is_fresh(root, db))
            con=sqlite3.connect(db)
            original=con.execute("SELECT COUNT(*) FROM nodes").fetchone()
            con.close()
            broken = copy.deepcopy(doc)
            broken["entry"]["context"].pop("coverage_since")
            path.write_text(json.dumps(broken))
            with self.assertRaises(ContractError):
                rebuild(root, db, contract="v3")
            con=sqlite3.connect(db)
            after=con.execute("SELECT COUNT(*) FROM nodes").fetchone()
            con.close()
            self.assertEqual(original, after)

    def test_version_rejected_before_database_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "records"
            path = root / "2026" / "11" / NAME
            path.parent.mkdir(parents=True)
            doc = json.loads(FIXTURE.read_text())
            doc["schema_version"] = 4
            path.write_text(json.dumps(doc))
            db = Path(tmp) / "cache.sqlite"
            with self.assertRaises(ContractError):
                rebuild(root, db, contract="v3")
            self.assertFalse(db.exists())

if __name__ == "__main__":
    unittest.main()
