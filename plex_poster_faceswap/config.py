"""Settings, all from environment variables (or a .env file next to where you run it)."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv(path=Path(".env")):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = re.sub(r"\s+#.*$", "", line).strip()   # drop trailing " # comments"
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


@dataclass
class Config:
    plex_url: str
    plex_token: str
    libraries: str = "movies"                 # movies | tv | both
    face_target: str = "any"                  # any | male | female
    path_map: list = field(default_factory=list)   # [(path as Plex sees it, path on this machine), ...]
    faces_dir: Path = Path("/faces")
    data_dir: Path = Path("/data")
    save_local: bool = True                   # also write poster.jpg into the media folder
    min_age_minutes: int = 30                 # skip items Plex added more recently than this
    schedule_minutes: int = 0                 # >0: keep running and check for new items this often
    threads: int = 2

    @property
    def models_dir(self):
        return self.data_dir / "models"

    @property
    def originals_dir(self):
        return self.data_dir / "originals"

    @property
    def state_file(self):
        return self.data_dir / "state.json"

    def to_local(self, plex_path):
        """Translate a path as Plex reports it into a path on this machine, using PATH_MAP."""
        for plex_prefix, local_prefix in sorted(self.path_map, key=lambda m: -len(m[0])):
            if plex_path == plex_prefix or plex_path.startswith(plex_prefix.rstrip("/") + "/"):
                return Path(local_prefix.rstrip("/") + plex_path[len(plex_prefix.rstrip("/")):])
        return Path(plex_path)


def parse_path_map(text):
    """'/movies=/mnt/media/movies, /tv=/mnt/media/tv' -> [('/movies', '/mnt/media/movies'), ('/tv', '/mnt/media/tv')]"""
    pairs = []
    for part in filter(None, (p.strip() for p in (text or "").split(","))):
        if "=" not in part:
            raise SystemExit(f"PATH_MAP entry {part!r} must look like /plex/path=/local/path")
        a, b = part.split("=", 1)
        pairs.append((a.strip(), b.strip()))
    return pairs


def load():
    _load_dotenv()
    env = os.environ.get
    missing = [k for k in ("PLEX_URL", "PLEX_TOKEN") if not env(k)]
    if missing:
        raise SystemExit(f"missing settings: {', '.join(missing)} (see README)")
    cfg = Config(
        plex_url=env("PLEX_URL").rstrip("/"),
        plex_token=env("PLEX_TOKEN"),
        libraries=env("LIBRARIES", "movies").lower(),
        face_target=env("FACE_TARGET", "any").lower(),
        path_map=parse_path_map(env("PATH_MAP", "")),
        faces_dir=Path(env("FACES_DIR", "/faces")),
        data_dir=Path(env("DATA_DIR", "/data")),
        save_local=env("SAVE_LOCAL_POSTER", "true").lower() in ("1", "true", "yes"),
        min_age_minutes=int(env("MIN_AGE_MINUTES", "30")),
        schedule_minutes=int(env("SCHEDULE_MINUTES", "0")),
        threads=int(env("THREADS", "2")),
    )
    if cfg.libraries not in ("movies", "tv", "both"):
        raise SystemExit("LIBRARIES must be movies, tv or both")
    if cfg.face_target not in ("any", "male", "female"):
        raise SystemExit("FACE_TARGET must be any, male or female")
    return cfg
