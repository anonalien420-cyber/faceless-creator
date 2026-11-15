"""Regression test for the xfade-overlap duration bug (found 2026-11-15
on the first REAL Antikythera Short run through the branch pipeline).

build_video joins one filtered stream per pattern-interrupt chunk with
0.5s xfades. Joining n segments of `chunk` seconds with (n-1) fades
produces n*chunk - (n-1)*FADE seconds of video, not n*chunk — so with
chunk = duration / chunk_count a 63.03s narration rendered as a 60.03s
video and `-shortest` silently cut the last ~3s of narration (the CTA)
off. The fix lengthens each segment to
(duration + (n-1)*FADE) / n so the joined video is exactly `duration`.

The test inspects the ffmpeg filtergraph (no real render): for a 30s
Short (3 chunks of 10.33s, 0.5s fades) the trims must be 10.33s long
and the xfade offsets 9.83s and 19.67s — the buggy values were 10.00s
trims with 9.50s / 19.00s offsets (29.00s of video for 30s of audio).
"""
import os
import re
import tempfile
import unittest
from unittest.mock import patch

from src.video import build_video

FAKE_VISUALS = [
    {"path": "/tmp/fake_a.mp4", "type": "video",
     "width": 1920, "height": 1080, "duration": 12.0},
    {"path": "/tmp/fake_b.mp4", "type": "video",
     "width": 1920, "height": 1080, "duration": 12.0},
    {"path": "/tmp/fake_c.mp4", "type": "video",
     "width": 1920, "height": 1080, "duration": 12.0},
]


def _filter_complex(script=None):
    script = script or {"topic": "Synthetic Pipeline Test",
                        "text": "SYNTHETIC TEST CLAIM: one sentence."}
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "out.mp4")
        with patch("src.video.resolve_visuals",
                   return_value=(FAKE_VISUALS, [])), \
                patch("src.video._run_ffmpeg") as mocked:
            build_video(script, os.path.join(tmp, "narr.mp3"), out,
                        visuals=["/tmp/fake_a.mp4"], duration=30.0)
        cmd = mocked.call_args.args[0]
        return cmd[cmd.index("-filter_complex") + 1]


class XfadeDurationTests(unittest.TestCase):
    def test_segments_lengthened_for_xfade_overlap(self):
        fc = _filter_complex()
        # Each video segment is trimmed to (30 + 2*0.5) / 3 = 10.33s.
        trims = re.findall(r"trim=([\d.]+):([\d.]+)", fc)
        self.assertEqual(len(trims), 3, "expected 3 trimmed segments, got: " + fc[:400])
        for start, end in trims:
            self.assertAlmostEqual(float(end) - float(start), 10.33, places=2,
                                   msg=f"segment trim {start}:{end} is not 10.33s")

    def test_xfade_offsets_match_lengthened_segments(self):
        fc = _filter_complex()
        offsets = re.findall(r"xfade=transition=fade:duration=0\.5:offset=([\d.]+)", fc)
        self.assertEqual([round(float(o), 2) for o in offsets], [9.83, 19.67],
                         "xfade offsets must be chunk-FADE apart on 10.33s "
                         "segments (buggy build used 9.50/19.00): " + fc[:400])

    def test_joined_video_equals_narration_duration(self):
        # n*chunk - (n-1)*FADE must equal the requested duration exactly,
        # so -shortest cannot cut the narration tail.
        chunk = (30.0 + 2 * 0.5) / 3
        self.assertAlmostEqual(3 * chunk - 2 * 0.5, 30.0, places=6)


if __name__ == "__main__":
    unittest.main()
