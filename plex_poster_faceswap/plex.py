"""The small slice of the Plex API this tool needs."""
import os
from dataclasses import dataclass
from pathlib import Path

import requests

TYPE_IDS = {"movie": 1, "show": 2, "season": 3}


@dataclass
class Item:
    key: str              # Plex ratingKey
    kind: str             # movie | show | season
    title: str            # for logs, e.g. "Alien (1979)" or "Severance - Season 2"
    match: str            # what --redo/--only match against: the film or show title
    thumb: str | None     # Plex URL of the currently selected poster
    added: int
    section: str
    folder: Path | None   # media folder on this machine (None if it can't be resolved)
    filename: str         # local poster file name Plex recognises (poster.jpg, season01.jpg, ...)


class Plex:
    def __init__(self, url, token):
        self.url, self.s = url, requests.Session()
        self.s.headers.update({"X-Plex-Token": token, "Accept": "application/json"})

    def _get(self, path, **params):
        r = self.s.get(f"{self.url}{path}", params=params, timeout=120)
        r.raise_for_status()
        return r.json()["MediaContainer"]

    def sections(self, kind):
        return [d for d in self._get("/library/sections").get("Directory", []) if d["type"] == kind]

    def items(self, libraries, to_local, names=None):
        out = []
        wanted = {"movies": ["movie"], "tv": ["show"], "both": ["movie", "show"]}[libraries]
        for kind in wanted:
            for sec in self.sections(kind):
                if names and sec["title"].lower() not in names:
                    continue
                out += self._movies(sec, to_local) if kind == "movie" else self._shows(sec, to_local)
        return out

    def _movies(self, sec, to_local):
        res = []
        for m in self._get(f"/library/sections/{sec['key']}/all").get("Metadata", []):
            try:
                folder = to_local(os.path.dirname(m["Media"][0]["Part"][0]["file"]))
            except (KeyError, IndexError):
                folder = None
            res.append(Item(m["ratingKey"], "movie", f"{m['title']} ({m.get('year', '')})", m["title"], m.get("thumb"),
                            m.get("addedAt", 0), sec["key"], folder, "poster.jpg"))
        return res

    def _shows(self, sec, to_local):
        res, folders = [], {}
        for sh in self._get(f"/library/sections/{sec['key']}/all").get("Metadata", []):
            meta = self._get(f"/library/metadata/{sh['ratingKey']}").get("Metadata", [{}])[0]
            loc = (meta.get("Location") or [{}])[0].get("path")
            folders[sh["ratingKey"]] = to_local(loc) if loc else None
            res.append(Item(sh["ratingKey"], "show", f"{sh['title']} (show)", sh["title"], sh.get("thumb"),
                            sh.get("addedAt", 0), sec["key"], folders[sh["ratingKey"]], "poster.jpg"))
        for se in self._get(f"/library/sections/{sec['key']}/all", type=3).get("Metadata", []):
            n = se.get("index", 0)
            name = "season-specials-poster.jpg" if n == 0 else f"season{n:02d}.jpg"  # Plex local-asset names
            res.append(Item(se["ratingKey"], "season", f"{se.get('parentTitle', '')} - {se['title']}",
                            se.get("parentTitle", ""), se.get("thumb"), se.get("addedAt", 0), sec["key"],
                            folders.get(se.get("parentRatingKey")), name))
        return res

    def download(self, path):
        r = self.s.get(f"{self.url}{path}", timeout=60, headers={"Accept": "*/*"})
        r.raise_for_status()
        return r.content

    def current_poster(self, key):
        meta = self._get(f"/library/metadata/{key}").get("Metadata", [{}])[0]
        return self.download(meta["thumb"]) if meta.get("thumb") else None

    def upload_poster(self, item: Item, data: bytes, lock=True):
        r = self.s.post(f"{self.url}/library/metadata/{item.key}/posters", data=data, timeout=60)
        r.raise_for_status()
        self.s.put(f"{self.url}/library/sections/{item.section}/all", timeout=60,
                   params={"type": TYPE_IDS[item.kind], "id": item.key,
                           "thumb.locked": 1 if lock else 0}).raise_for_status()
