"""Multi-language reach: narrator voice selection + localized metadata.

History is global; YouTube supports multi-language audio tracks and
localized titles/descriptions. This module provides the $0 building
blocks:

- voice_for_language(): maps a language code to a natural edge-tts neural
  voice (free). The narrator uses it when config `language` is not English
  and no explicit voice was chosen.
- translate_metadata(): optional title/description translation for the
  upload's `localizations` field. The default `template` tier does NOT
  translate (it returns None — never fake a translation). The `api` tier
  uses an OpenAI-compatible endpoint when LLM_API_KEY/OPENAI_API_KEY is
  set; failures fall back to None. Human review still applies.

Upload sets snippet.defaultAudioLanguage / defaultLanguage and any
localizations, so a video narrated in Spanish is discoverable in Spanish.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request

# Free edge-tts neural voices per language (representative defaults).
VOICE_MAP = {
    "en": "en-US-ChristopherNeural",
    "es": "es-MX-JorgeNeural",
    "fr": "fr-FR-HenriNeural",
    "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural",
    "it": "it-IT-DiegoNeural",
    "hi": "hi-IN-MadhurNeural",
    "ja": "ja-JP-KeitaNeural",
    "ko": "ko-KR-InJoonNeural",
    "ar": "ar-SA-HamedNeural",
    "id": "id-ID-ArdiNeural",
    "tr": "tr-TR-AhmetNeural",
}


def voice_for_language(language, current_voice="", default_voice="en-US-ChristopherNeural"):
    """Pick the narrator voice for a language.

    An explicitly configured voice that already matches the language is
    kept; otherwise the language's default neural voice is used. Unknown
    languages keep the configured/default voice (never fail a run over a
    locale)."""
    lang = (language or "en").split("-")[0].lower()
    if current_voice and current_voice.lower().startswith(lang + "-"):
        return current_voice
    return VOICE_MAP.get(lang, current_voice or default_voice)


def translate_metadata(title, description, language, tier="template"):
    """Return {title, description} localized for `language`, or None.

    template tier: None (no machine translation without an explicit opt-in
    — a wrong translation is worse than none). api tier: OpenAI-compatible
    chat completion; any failure returns None. The result feeds YouTube
    `localizations`, which is additive (the original metadata stays)."""
    lang = (language or "").split("-")[0].lower()
    if not lang or lang == "en" or tier != "api":
        return None
    key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
    if not key:
        print("WARNING: localization api tier requested but no LLM_API_KEY; "
              "skipping translation.", file=sys.stderr)
        return None
    base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
    model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    try:
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content":
                 "Translate the YouTube title and description into the target "
                 "language (ISO code given). Keep facts identical; do not add "
                 "claims. Reply as JSON: {\"title\": ..., \"description\": ...}."},
                {"role": "user", "content": json.dumps(
                    {"language": lang, "title": title, "description": description})},
            ],
            "temperature": 0.2,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{base}/chat/completions", data=body, method="POST",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.load(resp)
        parsed = json.loads(data["choices"][0]["message"]["content"])
        if parsed.get("title") and parsed.get("description"):
            return {"title": parsed["title"], "description": parsed["description"]}
    except Exception as exc:
        print(f"WARNING: metadata translation failed ({exc}); "
              "uploading without localizations.", file=sys.stderr)
    return None
