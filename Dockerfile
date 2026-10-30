FROM python:3.11-slim-bookworm AS build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.11-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*
COPY --from=build /wheels /wheels
# insightface depends on the desktop OpenCV build, which needs X11/GL libraries; swap it for the headless one
RUN pip install --no-cache-dir /wheels/* \
 && pip uninstall -y opencv-python \
 && pip install --no-cache-dir --no-deps --force-reinstall /wheels/opencv_python_headless-* \
 && rm -rf /wheels
WORKDIR /app
COPY plex_poster_faceswap ./plex_poster_faceswap
# all models are downloaded into /data/models on first run, so they survive image updates
ENV PYTHONUNBUFFERED=1 PYTHONWARNINGS=ignore \
    DATA_DIR=/data FACES_DIR=/faces
ENTRYPOINT ["python", "-m", "plex_poster_faceswap"]
CMD ["run"]
