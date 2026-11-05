"""Compatibility reads never upgrade or rewrite historical records."""
import copy,json,unittest
from pathlib import Path
from brain_bridge.contract import validate_record,validate_history,record_entries,ContractError

class HistoryTests(unittest.TestCase):
    def setUp(self):self.doc=json.loads((Path(__file__).resolve().parents[1]/'schemas/record.v3.synthetic.json').read_text())
    def test_v2_without_provenance_is_readable_but_not_publishable(self):
        self.doc['schema_version']=2;self.doc['entry'].pop('provenance');before=copy.deepcopy(self.doc)
        validate_history(self.doc,'Brain-Bridge/2026/11/2026-11-02-legacy.json')
        self.assertEqual(self.doc,before)
        with self.assertRaises(ContractError):validate_record(self.doc)
    def test_v1_multiple_entries_preserve_legacy_ids(self):
        entry=self.doc.pop('entry');self.doc['schema_version']=1
        entry.pop('provenance');entry['analysis']='Historical prose remains unchanged';entry['id']='legacy-agent-turn-1';other=copy.deepcopy(entry);other['id']='legacy-agent-turn-2'
        self.doc['entries']=[entry,other];validate_history(self.doc,'Brain-Bridge/2026/11/2026-11-02.json')
        self.assertEqual(len(record_entries(self.doc)),2)
    def test_duplicate_legacy_ids_and_traversal_rejected(self):
        entry=self.doc.pop('entry');self.doc.update(schema_version=1,entries=[entry,copy.deepcopy(entry)])
        with self.assertRaises(ContractError):validate_history(self.doc)
        with self.assertRaises(ContractError):validate_history(self.doc,'Brain-Bridge/2026/11/../private.json')
    def test_future_schemas_do_not_fall_back(self):
        self.doc['schema_version']=4
        with self.assertRaises(ContractError):validate_history(self.doc)

if __name__=='__main__':unittest.main()
