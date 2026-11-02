"""Guarded, explicitly invoked Git-to-SQLite synchronization."""
import subprocess
from pathlib import Path
from .store import rebuild, is_fresh

class SyncError(RuntimeError):
    pass

def _git(repo, *args):
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], check=True,
                           capture_output=True, text=True, timeout=90)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise SyncError("Git operation failed: " + " ".join(args)) from exc
    return p.stdout.strip()

def sync(repo, expected_remote, branch, records_dir, database, contract=None):
    """Sync an existing clean checkout; never clone, reset, or force-pull."""
    repo = Path(repo).expanduser().resolve(strict=True)
    if not repo.is_dir() or not (repo / ".git").exists():
        raise SyncError("Only an existing standalone Git checkout is supported")
    if not expected_remote or not branch or branch.startswith("-") or "/" in branch:
        raise SyncError("Explicit remote identity and simple branch name required")
    if _git(repo, "rev-parse", "--show-toplevel") != str(repo):
        raise SyncError("Repository path must be the checkout root")
    if _git(repo, "remote", "get-url", "origin") != expected_remote:
        raise SyncError("Remote identity mismatch")
    if _git(repo, "symbolic-ref", "--quiet", "--short", "HEAD") != branch:
        raise SyncError("Checked-out branch mismatch")
    if _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise SyncError("Checkout is dirty; refusing to pull")
    record_root = (repo / records_dir).resolve(strict=True)
    if not record_root.is_dir() or not record_root.is_relative_to(repo):
        raise SyncError("Records directory must be inside the checkout")
    db = Path(database).expanduser().absolute()
    if db.is_relative_to(repo):
        raise SyncError("SQLite index must be outside the Git checkout")
    _git(repo, "fetch", "--no-tags", "origin", branch)
    _git(repo, "merge", "--ff-only", "FETCH_HEAD")
    head = _git(repo, "rev-parse", "HEAD")
    count = rebuild(record_root, db, contract=contract)
    if not is_fresh(record_root, db):
        raise SyncError("SQLite index verification failed")
    return {"commit": head, "indexed": count, "fresh": True}
