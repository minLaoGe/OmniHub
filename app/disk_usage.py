"""Cached, bounded background scans of application installation directories."""
import os
import queue
import threading
import time
from pathlib import Path


def measure_directory(path, timeout=30):
    total = 0
    partial = False
    stack = [path]
    deadline = time.monotonic() + timeout
    while stack:
        if time.monotonic() > deadline:
            partial = True
            break
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    if time.monotonic() > deadline:
                        partial = True
                        stack.clear()
                        break
                    try:
                        st = entry.stat(follow_symlinks=False)
                        if entry.is_symlink() or getattr(st, "st_file_attributes", 0) & 1024:
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += st.st_size
                    except OSError:
                        partial = True
        except OSError:
            partial = True
    return {"disk_bytes": total, "disk_status": "partial" if partial else "ready", "disk_scanned_at": time.time()}


class DiskUsageCache:
    def __init__(self):
        self.cache = {}
        self.pending = set()
        self.lock = threading.Lock()
        self.jobs = queue.Queue()
        threading.Thread(target=self._worker, daemon=True, name="app-disk-scan").start()

    def _worker(self):
        while True:
            key = self.jobs.get()
            try:
                result = measure_directory(key)
            except Exception:
                result = {"disk_bytes": None, "disk_status": "unavailable", "disk_scanned_at": time.time()}
            with self.lock:
                self.cache[key] = result
                self.pending.discard(key)
            self.jobs.task_done()

    def describe(self, app):
        raw = app.get("install_location")
        if not raw and app.get("launch_path"):
            raw = str(Path(app["launch_path"]).parent)
        unknown = {"disk_bytes": None, "disk_status": "unavailable", "disk_path": ""}
        if not raw:
            return unknown
        path = Path(os.path.expandvars(str(raw).strip().strip('"'))).expanduser()
        if not path.is_absolute() or not path.exists():
            return unknown
        if path.is_file():
            path = path.parent
        path = path.resolve()
        # A shared system/container directory is not an application's size.
        excluded = [os.environ.get(k) for k in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "APPDATA", "LOCALAPPDATA", "USERPROFILE", "ProgramData")]
        if path == Path(path.anchor) or any(v and os.path.normcase(str(path)) == os.path.normcase(v) for v in excluded):
            return unknown
        windir = os.environ.get("WINDIR")
        if windir and (path == Path(windir) or Path(windir) in path.parents):
            return unknown
        if any(part.lower() == "start menu" for part in path.parts):
            return unknown
        key = os.path.normcase(str(path))
        with self.lock:
            result = self.cache.get(key)
            if (not result or time.time() - result["disk_scanned_at"] > 900) and key not in self.pending:
                self.pending.add(key)
                self.jobs.put(key)
            result = dict(result) if result else {"disk_bytes": None, "disk_status": "scanning"}
        return {**result, "disk_path": str(path)}


disk_usage_cache = DiskUsageCache()
