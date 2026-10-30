"""Download the face models on first use and check them against known SHA-256 hashes.

The models are not part of this repository: their licences only allow non-commercial use (see README).
InsightFace's face detector (buffalo_l) is fetched by the insightface package itself.
"""
import hashlib
from pathlib import Path

import requests

BASE = "https://github.com/facefusion/facefusion-assets/releases/download/models-3.0.0"
MODELS = {
    "inswapper_128.onnx": "a290273ed497312095dac48cdef20feec9d5208298223dd01288ab202b54bea7",
    "gfpgan_1.4.onnx": "accc4757b26bdb89b32b4d3500d4f79c9dff97c1dd7c7104bf9dcb95e3311385",
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ensure(models_dir: Path, log=print):
    models_dir.mkdir(parents=True, exist_ok=True)
    for name, digest in MODELS.items():
        path = models_dir / name
        if path.exists() and sha256(path) == digest:
            continue
        log(f"downloading {name} (one-off, several hundred MB)...")
        tmp = path.with_suffix(".part")
        with requests.get(f"{BASE}/{name}", stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        if sha256(tmp) != digest:
            tmp.unlink()
            raise SystemExit(f"{name}: checksum mismatch, refusing to use it")
        tmp.replace(path)
    return {name: models_dir / name for name in MODELS}
