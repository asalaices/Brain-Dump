import tempfile,json,unittest
from pathlib import Path
from brain_bridge.store import json_search,rebuild,sqlite_search,is_fresh,search
class StorageTests(unittest.TestCase):
    def test_nested_and_reindex(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t)/"records";r.mkdir()
            (r/"a.json").write_text(json.dumps({"a/b":{"x~y":["no","NeEdLe",{"needle_key":"yes"}]}}))
            expected=json_search(r,"needle")
            self.assertEqual(2,len(expected))
            self.assertTrue(any(x["pointer"]=="/a~1b/x~0y/1" for x in expected))
            db=Path(t)/"cache.sqlite"
            self.assertEqual(1,rebuild(r,db))
            self.assertEqual(expected,sqlite_search(db,"needle"))
            self.assertTrue(is_fresh(r,db))
            self.assertEqual(expected,search(r,"needle","auto",db))
            self.assertEqual(expected,search(r,"needle","sqlite",db))
            (r/"a.json").unlink()
            self.assertFalse(is_fresh(r,db))
            self.assertEqual([],search(r,"needle","auto",db))
            with self.assertRaises(RuntimeError): search(r,"needle","sqlite",db)
            rebuild(r,db)
            self.assertEqual([],sqlite_search(db,"needle"))
    def test_missing_index_does_not_create_db(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t)/"records";r.mkdir()
            (r/"a.json").write_text('{"value":"hello"}')
            db=Path(t)/"missing.sqlite"
            self.assertEqual(1,len(search(r,"hello","auto",db)))
            self.assertFalse(db.exists())
            with self.assertRaises(RuntimeError): search(r,"hello","sqlite",db)

    def test_changed_records_and_corrupt_index(self):
        with tempfile.TemporaryDirectory() as t:
            r=Path(t)/"records";r.mkdir()
            f=r/"a.json";f.write_text('{"value":"first"}')
            db=Path(t)/"cache.sqlite"
            rebuild(r,db)
            f.write_text('{"value":"second"}')
            self.assertFalse(is_fresh(r,db))
            self.assertEqual(1,len(search(r,"second","auto",db)))
            db.write_bytes(b"not a database")
            self.assertFalse(is_fresh(r,db))
            self.assertEqual(1,len(search(r,"second","auto",db)))

if __name__=="__main__":unittest.main()
