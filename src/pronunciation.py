"""Pronunciation dictionary for Deep Scan narration (Kokoro TTS).

The dictionary maps written forms to the text Kokoro should actually be
fed (``kokoro_text``) so historical names and technical terms come out
sounding right. It is applied ONLY at narration-generation time, in
memory: the ledger, the script text, scripts.json, and the subtitles
always keep the correct written forms.

Rules (mirroring the Pokemon pronunciation system):
- NEVER invent a pronunciation. An entry is ``verified`` only when a
  reliable source (dictionary, encyclopedia, official guide, or the
  regular reading of a cited original-language spelling) supports it.
  Anything else is ``unknown — flag for review`` with null IPA /
  respelling / kokoro_text, and is NEVER fed to TTS as a respelling.
- Only ``verified`` entries with a non-null ``kokoro_text`` are applied.
  ``kokoro_text`` is a phonetic respelling in mixed case (so Kokoro
  does not shout it), chosen empirically: the respelling is only
  accepted after a Kokoro render of it is transcribed back and heard
  as the target pronunciation.
- Matching is longest-form-first and word-boundary aware, so a
  multi-word entry (e.g. "Taposiris Magna") wins over its parts, and
  a possessive such as "Stais's" still matches "Stais".
"""

import json
import os
import re

DEFAULT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "pronunciation_dictionary.json")


def load_dictionary(path=None):
    """Load the pronunciation dictionary JSON. Raises FileNotFoundError
    if the file does not exist (callers should warn and continue
    without respelling rather than fail the render)."""
    path = path or DEFAULT_PATH
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _forms(entry):
    """Written forms for an entry: canonical name first, then aliases."""
    return [entry["name"]] + list(entry.get("aliases") or [])


def verified_entries(dictionary):
    """Entries that may be applied to TTS input: verified AND with a
    non-null kokoro_text. A verified entry with kokoro_text null means
    "pronunciation known, current Kokoro rendering already correct —
    no respelling needed"."""
    return [entry for entry in dictionary.get("entries", [])
            if entry.get("status") == "verified"
            and entry.get("kokoro_text")]


def apply_pronunciation(text, dictionary=None):
    """Return (spoken_text, applied_names): the text with verified
    respellings substituted, and the canonical names that were applied.
    Unknown entries are never applied. The input text is not modified
    in place and the written forms in scripts/ledger/subtitles are
    untouched — this only transforms the in-memory TTS input."""
    dictionary = dictionary if dictionary is not None else load_dictionary()
    subs = []
    for entry in verified_entries(dictionary):
        for form in _forms(entry):
            subs.append((form, entry["kokoro_text"], entry["name"]))
    # Longest written form first: multi-word entries beat their parts.
    subs.sort(key=lambda item: len(item[0]), reverse=True)
    result = text
    applied = []
    for written, spoken, canonical in subs:
        pattern = re.compile(r"\b" + re.escape(written) + r"\b",
                             re.IGNORECASE)
        if pattern.search(result):
            result = pattern.sub(spoken, result)
            applied.append(canonical)
    return result, sorted(set(applied))


def flag_unknown(text, dictionary=None):
    """Return the sorted canonical names of unknown-status entries
    found in the text. These are spoken as written (no respelling
    applied) and flagged so a human can verify them before a future
    script relies on them."""
    dictionary = dictionary if dictionary is not None else load_dictionary()
    flagged = []
    for entry in dictionary.get("entries", []):
        if entry.get("status") == "verified":
            continue
        for form in _forms(entry):
            if re.search(r"\b" + re.escape(form) + r"\b", text,
                         re.IGNORECASE):
                flagged.append(entry["name"])
                break
    return sorted(set(flagged))
