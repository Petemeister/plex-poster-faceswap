# plex-poster-faceswap

Put **your own face** on the posters in your Plex library.

It goes through your films and/or TV shows, finds the most prominent face on each poster, swaps in your face,
sharpens it, and gives Plex the new poster (locked, so Plex keeps it). Every original is backed up first and one
command puts them all back.

- Films, TV shows (show and season posters), or both
- Replace the most prominent face, or only male or only female faces
- Built from 2–3 photos of you, averaged for a steadier likeness
- Big close-ups are handled carefully: the poster is scaled so the face can be rebuilt with full detail, and
  only the face itself is touched
- Keeps checking for newly added films and shows
- `redo` a single title after picking a different poster in Plex; `restore` to undo everything
- Runs on a normal PC or a Raspberry Pi 5, CPU only (no graphics card needed)

> **Personal, non-commercial use only.** The face-swap and face-detection models this uses are licensed for
> non-commercial use (see [Licences](#licences)). And please only use photos of yourself, or of people who are
> happy to be on your posters.

## What you need

- A Plex Media Server you can reach over the network
- Your Plex token ([how to find it](#finding-your-plex-token))
- 2–3 clear, front-facing photos of the face to swap in: good light, no sunglasses, face filling a good part of the
  frame, one person per photo
- Docker (easiest), or Python 3.11 with pip
- About 2.5 GB of free RAM while it runs, and ~1.2 GB of disk for the models

## Quick start (Docker)

```bash
git clone https://github.com/Petemeister/plex-poster-faceswap.git
cd plex-poster-faceswap
cp docker-compose.example.yml docker-compose.yml   # then edit the settings in it
mkdir faces && cp ~/Pictures/me-*.jpg faces/        # your 2-3 photos
docker compose build

# try it on 10 random posters first - this doesn't change anything in Plex
docker compose run --rm faceswap preview
#   ...look at the results in ./data/preview

# happy? do the whole library, then keep checking for new items every hour
docker compose up -d
docker compose logs -f
```

The first run downloads the models (about 1.2 GB) into `./data/models`.

## Settings

All settings are environment variables (in `docker-compose.yml`, or a `.env` file when running without Docker).

| Setting | Default | What it does |
|---|---|---|
| `PLEX_URL` | *required* | e.g. `http://192.168.1.10:32400` |
| `PLEX_TOKEN` | *required* | your Plex token |
| `LIBRARIES` | `movies` | `movies`, `tv` or `both` |
| `LIBRARY_NAMES` | all | only these Plex libraries, comma-separated (e.g. `Films,Kids TV`) |
| `FACE_TARGET` | `any` | `any` = most prominent face; `male` / `female` = most prominent face of that gender |
| `PATH_MAP` | none | how Plex's media paths map to paths on this machine (see below) |
| `SAVE_LOCAL_POSTER` | `true` | also save the new poster as `poster.jpg` / `season01.jpg` in the media folder |
| `SCHEDULE_MINUTES` | `0` | `0` = run once and stop; `60` = keep checking for new items every hour |
| `MIN_AGE_MINUTES` | `30` | leave brand-new items alone for a while, so Plex has fetched their real poster |
| `THREADS` | `2` | CPU threads for the models |
| `FACES_DIR` | `/faces` | folder with your photos |
| `DATA_DIR` | `/data` | models, original posters, progress |

### Path mapping

Saving `poster.jpg` into your media folders needs to know where Plex's folders are on the machine running this.
If Plex runs in Docker it sees paths like `/movies/Alien (1979)`, while the same folder might be
`/mnt/media/movies/Alien (1979)` on the host. Map each Plex path prefix to the local one:

```
PATH_MAP=/movies=/media/movies,/tv=/media/tv
```

(In the example compose file, `/media/movies` and `/media/tv` are where your folders are mounted into the
container.) If you set `SAVE_LOCAL_POSTER=false`, no mapping or media mounts are needed: posters only go to Plex.

## Commands

```bash
docker compose run --rm faceswap preview --count 10   # try on random posters, nothing changes
docker compose run --rm faceswap run                  # do everything not done yet
docker compose run --rm faceswap run --limit 20       # ...or just the next 20
docker compose run --rm faceswap redo "The Martian"   # swap again (see below)
docker compose run --rm faceswap restore              # put every original poster back
docker compose run --rm faceswap restore --title "Alien"
docker compose run --rm faceswap status
```

**Didn't like a swap?** Pick the original poster in Plex (Edit → Poster). Nothing will swap it again.

**Want a different poster swapped?** Pick it in Plex, then run `redo "<title>"`. It notices you chose a new poster
and swaps that one. An exact title match wins over partial matches, so `redo "Wanted"` won't also hit
*Madagascar 3: Europe's Most Wanted*.

## Without Docker

```bash
python3.11 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env    # fill it in; use real paths for FACES_DIR and DATA_DIR
venv/bin/python -m plex_poster_faceswap preview
```

## Speed

CPU only: roughly 15–30 seconds per poster depending on the machine and the `cpus` limit, so a library of 1,500
films takes most of a night on a Raspberry Pi 5. It can be stopped and restarted at any time and carries on where
it left off. The `cpus`/`cpu_shares` limits in the example compose file keep Plex responsive meanwhile.

## Finding your Plex token

In Plex Web, open any film → **⋯ → Get Info → View XML**. The address of the page that opens ends in
`X-Plex-Token=...`; that value is your token. Keep it private: it gives full access to your server.

## Licences

- **This code:** MIT (see `LICENSE`).
- **Models** (downloaded at first run, not included here, each checked against a known SHA-256):
  - InsightFace `buffalo_l` (face detection and recognition) and `inswapper_128` (face swap):
    non-commercial research use only ([InsightFace](https://github.com/deepinsight/insightface)).
  - GFPGAN v1.4 (face restoration), from [TencentARC/GFPGAN](https://github.com/TencentARC/GFPGAN).
  - The ONNX versions of `inswapper_128` and GFPGAN are downloaded from the
    [FaceFusion assets](https://github.com/facefusion/facefusion-assets) releases.

Plex is a trademark of Plex, Inc. This project isn't affiliated with or endorsed by Plex.
