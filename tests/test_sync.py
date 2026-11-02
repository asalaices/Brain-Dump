import subprocess
import tempfile
import unittest
from pathlib import Path
from brain_bridge.sync import sync, SyncError
from brain_bridge.store import search

def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout.strip()

class SyncTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name)
        self.remote = p / "remote.git"; self.writer = p / "writer"; self.reader = p / "reader"
        git("init", "--bare", str(self.remote))
        git("clone", str(self.remote), str(self.writer))
        git("checkout", "-b", "main", cwd=self.writer)
        git("config", "user.name", "Test", cwd=self.writer)
        git("config", "user.email", "test@example.com", cwd=self.writer)
        (self.writer / "records").mkdir()
        (self.writer / "records" / "one.json").write_text('{"note":"first"}')
        git("add", ".", cwd=self.writer); git("commit", "-m", "seed", cwd=self.writer)
        git("push", "-u", "origin", "main", cwd=self.writer)
        git("clone", "-b", "main", str(self.remote), str(self.reader))
        self.db = p / "state" / "index.sqlite"

    def tearDown(self): self.tmp.cleanup()

    def run_sync(self, **kw):
        return sync(self.reader, kw.get("remote", str(self.remote)),
                    kw.get("branch", "main"), "records", self.db)

    def test_initial_sync_and_update(self):
        self.assertEqual(1, self.run_sync()["indexed"])
        self.assertEqual(1, len(search(self.reader / "records", "first", "sqlite", self.db)))
        (self.writer / "records" / "two.json").write_text('{"note":"second"}')
        git("add", ".", cwd=self.writer); git("commit", "-m", "add", cwd=self.writer)
        git("push", cwd=self.writer)
        self.assertEqual(2, self.run_sync()["indexed"])
        self.assertEqual(1, len(search(self.reader / "records", "second", "sqlite", self.db)))

    def test_dirty_checkout_rejected(self):
        self.run_sync()
        (self.reader / "records" / "one.json").write_text('{"note":"locally edited"}')
        with self.assertRaisesRegex(SyncError, "dirty"): self.run_sync()
        self.assertEqual(1, len(search(self.reader / "records", "locally edited", "auto", self.db)))

    def test_wrong_identity_or_branch_rejected(self):
        with self.assertRaisesRegex(SyncError, "identity"): self.run_sync(remote="https://wrong.invalid/repo")
        with self.assertRaisesRegex(SyncError, "branch"): self.run_sync(branch="else")
        self.assertFalse(self.db.exists())

    def test_db_inside_checkout_rejected(self):
        with self.assertRaisesRegex(SyncError, "outside"):
            sync(self.reader, str(self.remote), "main", "records", self.reader / "bad.sqlite")

if __name__ == "__main__": unittest.main()
