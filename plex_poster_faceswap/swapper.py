"""Find the most prominent face on a poster, swap in the source face, and sharpen it with GFPGAN."""
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from insightface.app import FaceAnalysis
from insightface.app.common import Face
from insightface.model_zoo import get_model

MIN_FACE = 48          # px; smaller faces can't be swapped meaningfully
MAX_FACE = 560         # px; bigger faces get the poster scaled down first, as GFPGAN rebuilds faces at 512px
RESTORE_BLEND = 0.8    # how much of GFPGAN's output to use on normal-sized faces (1.0 on big ones)
# where GFPGAN expects the eyes, nose and mouth corners in its 512x512 input (FFHQ alignment)
FFHQ_512 = np.array([[192.98, 239.95], [318.90, 240.19], [256.63, 314.02], [201.26, 371.41], [313.09, 371.15]],
                    dtype=np.float32)
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


def area(f):
    x1, y1, x2, y2 = f.bbox
    return (x2 - x1) * (y2 - y1)


class Swapper:
    def __init__(self, models, faces_dir: Path, face_target="any", threads=2, log=print):
        """models: paths from models.ensure(); the face detector (buffalo_l) is downloaded next to them."""
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        providers = ["CPUExecutionProvider"]
        self.face_target = face_target
        self.app = FaceAnalysis(name="buffalo_l", root=str(Path(models["inswapper_128.onnx"]).parent / "insightface"),
                                providers=providers)
        self.app.prepare(ctx_id=-1, det_size=(640, 640))
        self.swapper = get_model(str(models["inswapper_128.onnx"]), providers=providers)
        self.gfpgan = ort.InferenceSession(str(models["gfpgan_1.4.onnx"]), opts, providers=providers)
        self.source = self._source_face(faces_dir, log)

    def _source_face(self, faces_dir, log):
        """Average the identity over all photos in faces_dir for a steadier likeness."""
        embs = []
        photos = sorted(p for p in faces_dir.glob("*") if p.suffix.lower() in IMAGE_TYPES)
        for p in photos:
            img = cv2.imread(str(p))
            faces = self.app.get(img) if img is not None else []
            if not faces:
                log(f"warning: no face found in {p.name}, ignoring it")
                continue
            if len(faces) > 1:
                log(f"warning: {p.name} has {len(faces)} faces, using the largest")
            embs.append(max(faces, key=area).normed_embedding)
        if not embs:
            raise SystemExit(f"no usable face photos in {faces_dir} (add 2-3 clear, front-facing photos)")
        log(f"source face built from {len(embs)} photo(s)")
        e = np.mean(embs, axis=0)
        return Face(embedding=e / np.linalg.norm(e))

    def _pick(self, faces, w):
        if self.face_target != "any":
            want = "M" if self.face_target == "male" else "F"
            faces = [f for f in faces if getattr(f, "sex", None) == want]
        if not faces:
            return None

        def prominence(f):  # biggest face wins, with a small bonus for being near the horizontal centre
            cx = (f.bbox[0] + f.bbox[2]) / 2
            return area(f) * (1.15 - 0.3 * abs(cx - w / 2) / (w / 2)) * f.det_score
        return max(faces, key=prominence)

    def _restore(self, img, base, kps, blend):
        """GFPGAN-sharpen the swapped face in img and paste only the face area onto base (the original)."""
        m, _ = cv2.estimateAffinePartial2D(kps.astype(np.float32), FFHQ_512, method=cv2.LMEDS)
        crop = cv2.warpAffine(img, m, (512, 512), borderMode=cv2.BORDER_REFLECT)
        x = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB).astype(np.float32) / 127.5 - 1
        out = self.gfpgan.run(None, {self.gfpgan.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0]
        out = cv2.cvtColor(((out.transpose(1, 2, 0).clip(-1, 1) + 1) * 127.5).astype(np.uint8), cv2.COLOR_RGB2BGR)
        out = cv2.addWeighted(out, blend, crop, 1 - blend, 0)
        # face-shaped mask: outside it the poster stays untouched (the swap model works at 128px, so its own
        # paste-back leaves blocky edges in hair, helmets and reflections on big faces)
        mask = np.zeros((512, 512), np.float32)
        cv2.ellipse(mask, (256, 290), (168, 210), 0, 0, 360, 1, -1)
        mask = cv2.GaussianBlur(mask, (0, 0), 18)
        inv = cv2.invertAffineTransform(m)
        h, w = img.shape[:2]
        back = cv2.warpAffine(out, inv, (w, h))
        mback = cv2.warpAffine(mask, inv, (w, h))[..., None]
        return (back * mback + base * (1 - mback)).astype(np.uint8)

    def swap(self, src: Path, dst: Path):
        """Returns (True, description) after writing dst, or (False, reason) if there's no suitable face."""
        img = cv2.imread(str(src))
        if img is None:
            return False, "unreadable image"
        h, w = img.shape[:2]
        faces = [f for f in self.app.get(img) if min(f.bbox[2] - f.bbox[0], f.bbox[3] - f.bbox[1]) >= MIN_FACE]
        target = self._pick(faces, w)
        if target is None:
            return False, "no usable face" if not faces else f"no {self.face_target} face"
        fw = target.bbox[2] - target.bbox[0]
        big = fw > MAX_FACE
        if big:  # scale the poster so the face is ~MAX_FACE wide, and detect again at that size
            img = cv2.resize(img, None, fx=MAX_FACE / fw, fy=MAX_FACE / fw, interpolation=cv2.INTER_AREA)
            h, w = img.shape[:2]
            target = self._pick(self.app.get(img), w) or target
        out = self.swapper.get(img, target, self.source, paste_back=True)
        out = self._restore(out, img, target.kps, 1.0 if big else RESTORE_BLEND)
        if big:  # restored faces are noise-free; a touch of grain makes them match the poster
            grain = np.random.default_rng(0).normal(0, 3.5, out.shape).astype(np.float32)
            out = np.clip(out.astype(np.float32) + grain, 0, 255).astype(np.uint8)
        cv2.imwrite(str(dst), out, [cv2.IMWRITE_JPEG_QUALITY, 92])
        sex = {"M": "male", "F": "female"}.get(getattr(target, "sex", None), "?")
        note = f", poster scaled to {w}x{h}" if big else ""
        return True, f"{len(faces)} face(s), swapped a {sex} face {int(fw)}px wide{note}"
