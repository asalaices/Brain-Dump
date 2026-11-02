import tempfile,json,unittest
from pathlib import Path
from brain_bridge.store import json_search,rebuild,sqlite_search
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
            (r/"a.json").unlink()
            rebuild(r,db)
            self.assertEqual([],sqlite_search(db,"needle"))
if __name__=="__main__":unittest.main()
