import copy
import json
import unittest
from pathlib import Path
from brain_bridge.contract import validate_record, ContractError

FIXTURE = Path(__file__).resolve().parents[1] / "schemas" / "record.v3.synthetic.json"
PATH = "Brain-Bridge/2026/11/2026-11-02-12-00-00-11111111-1111-4111-8111-111111111111.json"

class ContractTests(unittest.TestCase):
    def setUp(self):
        self.record = json.loads(FIXTURE.read_text())

    def test_valid_v3_and_unchanged(self):
        before = copy.deepcopy(self.record)
        self.assertIs(validate_record(self.record, PATH), self.record)
        self.assertEqual(before, self.record)

    def test_evidence_objects_accept_master01_shapes(self):
        self.record["entry"]["validation"] = {"full_offline": {"passed": 148}}
        self.record["entry"]["repository_state"] = {"repo": "example/repo", "implementation_merged": True}
        self.assertIs(validate_record(self.record, PATH), self.record)

    def test_filename_uses_record_timezone_not_timestamp_offset(self):
        self.record["entry"]["timestamp"] = "2026-11-02T18:00:00+00:00"
        validate_record(self.record, PATH)

    def test_provenance_collections_and_coverage_are_typed(self):
        self.record["entry"]["provenance"]["users"] = {}
        with self.assertRaises(ContractError): validate_record(self.record)

    def test_reject_wrong_version(self):
        self.record["schema_version"] = 4
        with self.assertRaises(ContractError): validate_record(self.record)

    def test_reject_missing_status(self):
        del self.record["entry"]["context"]["coverage_since"]
        with self.assertRaises(ContractError): validate_record(self.record)

    def test_reject_mismatched_layout(self):
        with self.assertRaises(ContractError):
            validate_record(self.record, PATH.replace("/11/", "/10/"))

    def test_reject_naive_timestamp(self):
        self.record["entry"]["timestamp"] = "2026-11-02T12:00:00"
        with self.assertRaises(ContractError): validate_record(self.record)

if __name__ == "__main__":
    unittest.main()
