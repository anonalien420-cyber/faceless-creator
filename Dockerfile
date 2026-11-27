# Reproducible render environment: ffmpeg + ffprobe + DejaVu fonts + deps.
# Build:  docker build -t faceless-creator .
# Run:    docker run --rm -v "$PWD/data:/app/data" faceless-creator run --niche "history mysteries"
#
# The image ships everything the pipeline needs so renders are identical
# across machines (font metrics, ffmpeg filters, libass). API keys are
# passed as env vars at run time, never baked into the image.
FROM python:3.11-slim

# ffmpeg (renders + probes), fonts-dejavu (caption/card/thumbnail font),
# and libsndfile1 (optional local Kokoro voice tier).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg \
        fonts-dejavu-core \
        libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install dependencies first (layer caching).
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Project source + default config.
COPY pyproject.toml README.md ./
COPY src ./src
COPY scripts ./scripts
COPY config.yaml ./
RUN pip install --no-cache-dir --no-deps .

# Data dir is a volume so outputs/cache/history persist across runs.
RUN mkdir -p /app/data
VOLUME ["/app/data"]

# Non-root for safety.
RUN useradd --create-home creator && chown -R creator /app
USER creator

ENTRYPOINT ["faceless"]
CMD ["--help"]
