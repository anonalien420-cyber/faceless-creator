"""Beep scan for the Deep Scan Antikythera Short (2026-11-15).

Background: the in-house mellow bed contains an exposed pure 440 Hz
note (bed 3.0-3.8s) that reads as a beep when it rings out alone after
speech ends. A "suspect" is a sustained pure tone: in a 0.25s window
(hop 0.125s), one FFT bin in 300-3000 Hz holds >60% of the band energy
while the window is louder than -50 dBFS, sustained for >= 3 windows
(>= 0.375s). Also reports the loudest 440 Hz +/- 5 Hz energy per
window for the record. Decodes with ffmpeg to 24 kHz mono PCM first;
no seeking (mp3 -ss seeks are unreliable on these files).
"""
import json
import subprocess
import sys

import numpy as np

AUDIO = sys.argv[1] if len(sys.argv) > 1 else (
    "productions/antikythera-short-2026-11-15/final-audio.mp3")
OUT = sys.argv[2] if len(sys.argv) > 2 else (
    "productions/antikythera-short-2026-11-15/beep_scan.json")
SR = 24000
WIN = int(0.25 * SR)
HOP = int(0.125 * SR)

raw = subprocess.run(
    ["ffmpeg", "-v", "error", "-i", AUDIO, "-ac", "1", "-ar", str(SR),
     "-f", "f32le", "-"], capture_output=True, check=True).stdout
x = np.frombuffer(raw, dtype=np.float32)
freqs = np.fft.rfftfreq(WIN, 1 / SR)
band = (freqs >= 300) & (freqs <= 3000)
a440 = (freqs >= 435) & (freqs <= 445)
window = np.hanning(WIN)
suspects = []
peak_440_db = -120.0
for start in range(0, max(1, len(x) - WIN), HOP):
    seg = x[start:start + WIN] * window
    rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
    db = 20 * np.log10(rms + 1e-12)
    spec = np.abs(np.fft.rfft(seg)) ** 2
    band_e = float(spec[band].sum())
    peak_e = float(spec[band].max()) if band_e > 0 else 0.0
    share = peak_e / band_e if band_e > 0 else 0.0
    peak_f = float(freqs[band][int(np.argmax(spec[band]))]) if band_e > 0 else 0.0
    e440 = float(spec[a440].max()) if spec[a440].size else 0.0
    peak_440_db = max(peak_440_db, 10 * np.log10(e440 + 1e-12))
    if db > -50 and share > 0.60:
        suspects.append({"t": round(start / SR, 3), "db": round(db, 1),
                         "peak_freq_hz": round(peak_f, 1),
                         "peak_share": round(share, 3)})
# Merge consecutive suspect windows into sustained events (>= 3 windows).
events = []
for s in suspects:
    if events and s["t"] - events[-1]["end_t"] <= 0.126:
        events[-1]["end_t"] = s["t"]
        events[-1]["windows"] += 1
        events[-1]["peak_freq_hz"] = s["peak_freq_hz"]
    else:
        events.append({"start_t": s["t"], "end_t": s["t"], "windows": 1,
                       "peak_freq_hz": s["peak_freq_hz"], "db": s["db"]})
sustained = [e for e in events if e["windows"] >= 3]
report = {"audio": AUDIO, "duration_s": round(len(x) / SR, 3),
          "method": "0.25s Hann windows, hop 0.125s; suspect = one bin "
                    ">60% of 300-3000 Hz band energy at >-50 dBFS, "
                    "sustained >=3 windows",
          "suspect_windows": len(suspects),
          "sustained_events": sustained,
          "peak_440hz_bin_db": round(peak_440_db, 1),
          "result": "PASS (0 suspects)" if not sustained
                    else f"FAIL ({len(sustained)} sustained pure-tone event(s))"}
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(report, fh, indent=2)
print(json.dumps(report, indent=2))
