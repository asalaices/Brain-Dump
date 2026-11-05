# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Creative Software Development
"""Pre-index validation must be atomic across the complete JSON batch."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from brain_bridge.store import rebuild, is_fresh
from brain_bridge.contract import ContractError

FIXTURE = Path(__file__).resolve().parents[1] / "schemas" / "record.v3.synthetic.json"
ROOTNAME = "2026-11-02-12-00-00-11111111-1111-4111-8111-111111111111.json"

class BatchValidationTests(unittest.TestCase):
    def test_invalid_second_record_preserves_all_existing_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "records"
            folder = root / "2026" / "11"
            folder.mkdir(parents=True)
            db = Path(tmp) / "index.sqlite"
            doc = json.loads(FIXTURE.read_text())
            (folder / ROOTNAME).write_text(json.dumps(doc))
            self.assertEqual(rebuild(root, db, contract="v3"), 1)
            con = sqlite3.connect(db)
            before = (con.execute("SELECT file,sha256 FROM files ORDER BY file").fetchall(),
                      con.execute("SELECT COUNT(*) FROM nodes").fetchone())
            con.close()

            second = copy.deepcopy(doc)
            second["entry"]["id"] = "22222222-2222-4222-8222-222222222222"
            second["entry"]["context"].pop("coverage_since")
            (folder / ROOTNAME.replace("11111111-1111-4111-8111-111111111111",
                                       "22222222-2222-4222-8222-222222222222")).write_text(json.dumps(second))
            with self.assertRaises(ContractError):
                rebuild(root, db, contract="v3")
            con = sqlite3.connect(db)
            after = (con.execute("SELECT file,sha256 FROM files ORDER BY file").fetchall(),
                     con.execute("SELECT COUNT(*) FROM nodes").fetchone())
            con.close()
            self.assertEqual(before, after)
            self.assertFalse(is_fresh(root, db))

if __name__ == "__main__":
    unittest.main()
