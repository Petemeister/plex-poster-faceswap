"""plex-poster-faceswap: put your face on your Plex posters.

  run       swap every poster not done yet (with SCHEDULE_MINUTES set, keeps checking for new items)
  redo T    swap the poster(s) for title T again, using whichever poster is currently selected in Plex
  restore   put the original posters back (all, or --title T)
  status    show what has been done
  preview   swap a few random posters into DATA_DIR/preview without touching Plex or your media folders
"""
import argparse
import fcntl
import hashlib
import json
import os
import random
import time
from contextlib import contextmanager
from pathlib import Path

from . import config, models
from .plex import Plex


def log(msg):
    print(time.strftime("%F %T"), msg, flush=True)


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text()) if path.exists() else {}

    def get(self, key):
        return self.data.get(key, {})

    def set(self, key, **entry):
        self.data[key] = entry
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1, ensure_ascii=False))
        os.replace(tmp, self.path)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def process(item, cfg, plex, swapper, state, redo=False):
    """Back up the original once, swap it, upload and lock the result, optionally save it in the media folder."""
    orig = cfg.originals_dir / f"{item.key}.jpg"
    prev = state.get(item.key)
    if redo and orig.exists():
        cur = plex.current_poster(item.key)
        if cur and sha(cur) != prev.get("uploaded"):
            # a different poster was picked in Plex: keep the old original, use the new pick
            os.replace(orig, orig.with_name(f"{item.key}-{time.strftime('%Y%m%d-%H%M%S')}.jpg"))
            orig.write_bytes(cur)
            log(f"{item.title}: using the poster currently selected in Plex")
    if not orig.exists():
        if not item.thumb:
            raise RuntimeError("Plex has no poster for this item")
        orig.parent.mkdir(parents=True, exist_ok=True)
        orig.write_bytes(plex.download(item.thumb))
    out = cfg.data_dir / "work.jpg"
    ok, msg = swapper.swap(orig, out)
    if not ok:
        state.set(item.key, title=item.title, status="no_face")
        return f"left as is ({msg})"
    data = out.read_bytes()
    entry = {"title": item.title, "status": "swapped", "uploaded": sha(data)}
    if cfg.save_local and item.folder and item.folder.is_dir():
        local = item.folder / item.filename
        if local.exists() and sha(local.read_bytes()) != prev.get("uploaded"):
            # never lose a poster file the user had: keep it for `restore`
            keep = cfg.originals_dir / f"{item.key}-local-{item.filename}"
            if not keep.exists():
                keep.write_bytes(local.read_bytes())
            entry["local_backup"] = keep.name
        elif prev.get("local_backup"):
            entry["local_backup"] = prev["local_backup"]
        tmp = local.with_name(f".{local.name}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, local)
        entry["local"] = str(local)
    plex.upload_poster(item, data)
    state.set(item.key, **entry)
    return f"swapped - {msg}"


@contextmanager
def run_lock(cfg, wait):
    """Only one pass at a time. Yields False if another is running and wait is False."""
    with open(cfg.data_dir / ".lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if not wait:
                yield False
                return
            log("another run is in progress; waiting for it to finish...")
            fcntl.flock(f, fcntl.LOCK_EX)
        yield True


def select(items, title):
    exact = [i for i in items if i.match.lower() == title.lower()]
    return exact or [i for i in items if title.lower() in i.match.lower()]


def cmd_run(cfg, plex, a, redo_title=None):
    from .swapper import Swapper
    swapper = None
    while True:
        # a scheduled pass skips if a redo/restore is running; one-off commands wait for it
        with run_lock(cfg, wait=bool(redo_title) or not cfg.schedule_minutes) as got:
            if got:
                state = State(cfg.state_file)  # re-read: a redo may have changed it since the last pass
                items = plex.items(cfg.libraries, cfg.to_local, a.library_names)
                if redo_title:
                    todo = select(items, redo_title)
                    if not todo:
                        raise SystemExit(f"nothing in {cfg.libraries} matches {redo_title!r}")
                else:
                    todo = [i for i in items if state.get(i.key).get("status") not in ("swapped", "no_face", "restored")
                            and time.time() - i.added >= cfg.min_age_minutes * 60]
                    if a.only:
                        todo = [i for i in todo if a.only.lower() in i.match.lower()]
                    todo = todo[:a.limit] if a.limit else todo
                if todo:
                    log(f"{len(items)} posters in {cfg.libraries}, {len(todo)} to do")
                    swapper = swapper or Swapper(models.ensure(cfg.models_dir, log), cfg.faces_dir, cfg.face_target,
                                                 cfg.threads, log)
                    for n, item in enumerate(todo, 1):
                        t = time.time()
                        try:
                            msg = process(item, cfg, plex, swapper, state, redo=bool(redo_title))
                        except Exception as e:  # keep going; it is retried next run
                            state.set(item.key, title=item.title, status="error", error=str(e)[:300])
                            msg = f"ERROR {e}"
                        log(f"[{n}/{len(todo)}] {item.title}: {msg} ({time.time() - t:.0f}s)")
        if redo_title or not cfg.schedule_minutes:
            return
        time.sleep(cfg.schedule_minutes * 60)


def cmd_restore(cfg, plex, a):
    state = State(cfg.state_file)
    items = {i.key: i for i in plex.items(cfg.libraries, cfg.to_local, a.library_names)}
    keys = [i.key for i in select(list(items.values()), a.title)] if a.title else list(items)
    done = 0
    for key in keys:
        st, item = state.get(key), items[key]
        orig = cfg.originals_dir / f"{key}.jpg"
        if st.get("status") != "swapped" or not orig.exists():
            continue
        plex.upload_poster(item, orig.read_bytes(), lock=False)
        local = Path(st["local"]) if st.get("local") else None
        if local and local.exists() and sha(local.read_bytes()) == st.get("uploaded"):
            if st.get("local_backup"):
                local.write_bytes((cfg.originals_dir / st["local_backup"]).read_bytes())
            else:
                local.unlink()
        state.set(key, title=st["title"], status="restored")
        done += 1
        log(f"restored {st['title']}")
    log(f"{done} poster(s) restored")


def cmd_status(cfg):
    state = State(cfg.state_file)
    counts = {}
    for v in state.data.values():
        counts[v["status"]] = counts.get(v["status"], 0) + 1
    print(json.dumps(counts or {"nothing done yet": 0}, indent=1))
    for v in state.data.values():
        if v["status"] == "error":
            print(f"  error: {v['title']}: {v.get('error')}")


def cmd_preview(cfg, plex, a):
    from .swapper import Swapper
    items = [i for i in plex.items(cfg.libraries, cfg.to_local, a.library_names) if i.thumb]
    out = cfg.data_dir / "preview"
    out.mkdir(parents=True, exist_ok=True)
    swapper = Swapper(models.ensure(cfg.models_dir, log), cfg.faces_dir, cfg.face_target, cfg.threads, log)
    for item in random.sample(items, min(a.count, len(items))):
        name = "".join(c if c.isalnum() or c in " ()-" else "_" for c in item.title)
        src = out / f"{name} - original.jpg"
        src.write_bytes(plex.download(item.thumb))
        ok, msg = swapper.swap(src, out / f"{name} - swapped.jpg")
        log(f"{item.title}: {msg}")
    log(f"preview images in {out}")


def main():
    ap = argparse.ArgumentParser(prog="plex-poster-faceswap", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--limit", type=int, help="stop after N posters")
    p_run.add_argument("--only", help="only titles containing this text")
    p_redo = sub.add_parser("redo")
    p_redo.add_argument("title")
    p_res = sub.add_parser("restore")
    p_res.add_argument("--title", help="only this title (default: everything)")
    sub.add_parser("status")
    p_pre = sub.add_parser("preview")
    p_pre.add_argument("--count", type=int, default=10)
    a = ap.parse_args()
    cfg = config.load()
    a.library_names = {n.strip().lower() for n in os.environ.get("LIBRARY_NAMES", "").split(",") if n.strip()}
    a.only = getattr(a, "only", None)
    a.limit = getattr(a, "limit", None)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    if a.cmd == "status":
        return cmd_status(cfg)
    plex = Plex(cfg.plex_url, cfg.plex_token)
    if a.cmd == "run":
        cmd_run(cfg, plex, a)
    elif a.cmd == "redo":
        cmd_run(cfg, plex, a, redo_title=a.title)
    elif a.cmd == "restore":
        with run_lock(cfg, wait=True):
            cmd_restore(cfg, plex, a)
    elif a.cmd == "preview":
        cmd_preview(cfg, plex, a)  # writes only to DATA_DIR/preview, so it needs no lock
