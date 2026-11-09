"""Exercise the real FFmpeg filter-graph renderer without network or API keys."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Running a file inside scripts/ puts that folder, not the repository root,
# at sys.path[0]. Add the project root so the production module is importable.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.video import build_video


def run(command):
    subprocess.run(command, check=True, capture_output=True, text=True)


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height", "-of", "json", path],
        check=True, capture_output=True, text=True,
    )
    import json
    return json.loads(result.stdout)["streams"]


def main():
    with tempfile.TemporaryDirectory(prefix="deep-scan-ffmpeg-") as work:
        image = os.path.join(work, "test-frame.png")
        audio = os.path.join(work, "test-audio.wav")
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             "color=c=0x24324a:s=640x640:d=1", "-frames:v", "1", image])
        run(["ffmpeg", "-y", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=27", "-c:a", "pcm_s16le", audio])

        cases = [
            # Portrait crosses the 10-second pattern-interrupt boundary.
            ("short", 320, 568, 12),
            # Landscape crosses the 25-second long-form boundary.
            ("long", 568, 320, 26),
        ]
        for name, width, height, duration in cases:
            output = os.path.join(work, f"{name}.mp4")
            build_video(
                {"topic": "Render smoke test", "hook": "A verified test hook.",
                 "text": "This is a synthetic render test, not a historical claim."},
                audio, output,
                visuals=[{"file": image, "type": "image"}],
                duration=duration, bitrate="500k", min_resolution=100,
                width=width, height=height,
                end_card_text="Smoke test complete",
            )
            streams = probe(output)
            video_stream = next(s for s in streams if s["codec_type"] == "video")
            audio_stream = next(s for s in streams if s["codec_type"] == "audio")
            assert (video_stream["width"], video_stream["height"]) == (width, height)
            assert audio_stream["codec_type"] == "audio"
            assert os.path.getsize(output) > 10_000
            assert os.path.exists(output + ".ass")
            print(f"PASS {name}: {width}x{height}, {duration}s, video+audio, captions")

    print("Both FFmpeg render smoke tests passed.")


if __name__ == "__main__":
    main()
