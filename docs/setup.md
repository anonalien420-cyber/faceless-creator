# Setup

## Requirements
- Python 3.11+
- `ffmpeg` and `ffprobe` on PATH (renders + probes). The pipeline fails
  loudly if either is missing.
- DejaVu fonts (`fonts-dejavu-core`) for captions, cards, and thumbnails.

## Install (local)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # or: pip install -r requirements.lock
pip install -e .                       # provides the `faceless` CLI
```
PyYAML is recommended (full YAML config). Without it, a stdlib fallback
parser still handles `config.yaml`, including the `brand:` block.

## Install (Docker — reproducible renders)
```bash
docker build -t faceless-creator .
docker run --rm -v "$PWD/data:/app/data" faceless-creator run --niche "history mysteries"
```
The image ships ffmpeg + DejaVu + deps so font metrics and filters are
identical across machines. Pass API keys as env vars at run time.

## Quick start (no keys, $0)
```bash
faceless trends --manual-only --input data/trends_input.example.json --output data/top5.json
faceless script --input data/top5.json --format short --count 2 --style history_mystery
faceless run --niche "history mysteries investigated with modern tech"   # dry-run upload
```
`faceless run` orchestrates trends → scripts → narrate → music → video →
QA → upload. Uploads are **dry-run by default**; nothing is posted unless
you pass `--upload` AND set `UPLOAD_ENABLED=true`.

## Optional API keys (env vars, never in config.yaml)
| Key | Enables | Default without it |
| --- | --- | --- |
| `YT_API_KEY` | YouTube trend search | manual trend input |
| `PEXELS_API_KEY` / `PIXABAY_API_KEY` | HD stock video/images | gradient fallback |
| `ELEVENLABS_API_KEY` | paid narrator tier | free Edge TTS |
| `LLM_API_KEY` / `OPENAI_API_KEY` | research LLM api tier | template tier |
| `YT_CLIENT_SECRETS` / `YT_TOKEN` | actual upload + stats read | dry-run |

## Voice tiers
- `free` (default): Edge TTS neural voices + rate/punctuation pacing.
- `local`: Kokoro open-weight if installed (`pip install -e .[local]`),
  else Edge TTS fallback.
- `paid`: ElevenLabs (`pip install -e .[paid]`); fails loudly if the key
  is missing rather than silently downgrading.

## Dev tooling
```bash
pip install -e .[dev]
pre-commit install
ruff check src scripts        # lint gate
python -m unittest discover -s tests
```
