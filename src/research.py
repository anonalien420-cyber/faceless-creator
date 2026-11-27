"""Free, key-less research: Wikipedia REST + Wikidata -> verified facts
and real {title, url} sources that feed the KNOWN tier and the shock
hook. No API key, no paid service, $0 by default.

What this does (and does NOT do):
- Pulls the Wikipedia summary extract and a few structured Wikidata
  claims for a topic. Every fact carries the real page it came from as
  its source. Nothing is invented: facts are verbatim sentences from
  the extract or literal Wikidata values, each with a URL.
- Surfaces a `shock_candidate`: a surprising-but-TRUE sentence taken
  verbatim from the extract (one containing a number, date, or
  superlative), with its Wikipedia source. It is a CANDIDATE — the
  creator still verifies it in the review queue before publishing, and
  the QA accuracy gate still requires a filled source.
- Optional LLM draft tier (template -> local -> api). The default
  `template` tier composes the verified facts into prose with no
  network call. The `api` tier (OpenAI-compatible) is opt-in via an env
  key and NEVER bypasses drop_unverified / the QA gate.

Network failures are non-fatal: research_topic returns an empty result
(provider="none") and the pipeline falls back to its template scripts.
Research is opt-in (config research_enabled, default false) so the
$0/offline default behaviour is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request

UA = {"User-Agent": "faceless-creator/1.0 (research; +https://github.com/anonalien420-cyber/faceless-creator)"}

# Wikidata properties worth surfacing as plain facts (label, property id).
WD_PROPS = [
    ("inception", "P571"),
    ("country", "P17"),
    ("location", "P276"),
    ("instance of", "P31"),
    ("discoverer", "P61"),
    ("date of discovery", "P575"),
]

SUPERLATIVES = re.compile(
    r"\b(oldest|largest|smallest|first|only|never|longest|deepest|"
    r"tallest|most|least|ancient|earliest|latest|rare|unexplained|"
    r"mysterious|unknown|lost|hidden)\b", re.IGNORECASE)
NUMBER = re.compile(r"\b\d[\d,\.]*\b|\b\d+(?:st|nd|rd|th)\b")


def _get_json(url, headers=None, timeout=20):
    """Fetch + parse JSON. Patched in tests; raises on network failure."""
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s.strip()]


def search_wikipedia(topic, lang="en"):
    """Best-matching Wikipedia page title for a topic (or '')."""
    url = (f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search"
           f"&srsearch={urllib.parse.quote(topic)}&srlimit=1&format=json")
    try:
        data = _get_json(url)
        hits = data.get("query", {}).get("search", [])
        return hits[0]["title"] if hits else ""
    except Exception as exc:
        print(f"WARNING: Wikipedia search failed ({exc}).", file=sys.stderr)
        return ""


def fetch_summary(title, lang="en"):
    url = (f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/"
           f"{urllib.parse.quote(title.replace(' ', '_'))}")
    try:
        return _get_json(url)
    except Exception as exc:
        print(f"WARNING: Wikipedia summary failed ({exc}).", file=sys.stderr)
        return {}


def parse_summary(summary):
    """Turn a REST summary into facts + a shock candidate, each sourced.

    Pure function (no network) so it is unit-testable. Facts are the
    extract's sentences verbatim; the source is the real desktop page
    URL. The shock candidate is the first sentence that looks genuinely
    surprising (a number/date or a superlative) — still verbatim, still
    sourced, never paraphrased into a bigger claim.
    """
    if not summary or summary.get("type") == "disambiguation":
        return {"title": "", "extract": "", "url": "", "facts": [], "shock_candidate": None}
    title = summary.get("title", "")
    extract = summary.get("extract", "") or ""
    url = (summary.get("content_urls", {}).get("desktop", {}).get("page", "")
           or f"https://en.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}")
    source = {"title": f"Wikipedia: {title}", "url": url, "no_public_url": False}
    sentences = _sentences(extract)
    facts = [{"text": s, "source": dict(source), "tier": "KNOWN"} for s in sentences]
    shock = None
    for s in sentences:
        if NUMBER.search(s) or SUPERLATIVES.search(s):
            shock = {"text": s, "tier": "KNOWN", "source": dict(source)}
            break
    return {"title": title, "extract": extract, "url": url,
            "facts": facts, "shock_candidate": shock}


def search_wikidata(topic, lang="en"):
    url = (f"https://www.wikidata.org/w/api.php?action=wbsearchentities"
           f"&search={urllib.parse.quote(topic)}&language={lang}&limit=1&format=json")
    try:
        data = _get_json(url)
        hits = data.get("search", [])
        return hits[0]["id"] if hits else ""
    except Exception as exc:
        print(f"WARNING: Wikidata search failed ({exc}).", file=sys.stderr)
        return ""


def _wd_value(claim, entity_data):
    """Render a Wikidata claim's main value as plain text (best effort)."""
    try:
        snak = claim["mainsnak"]["datavalue"]
    except (KeyError, TypeError):
        return ""
    vtype = snak.get("type")
    value = snak.get("value")
    if vtype == "time":
        # +1850-00-00T00:00:00Z -> 1850
        m = re.match(r"[+-]?(\d+)", str(value.get("time", "")))
        return m.group(1) if m else ""
    if vtype == "wikibase-entityid":
        qid = value.get("id", "")
        label = (entity_data.get("entities", {}).get(qid, {})
                 .get("labels", {}).get("en", {}).get("value", ""))
        return label or qid
    if vtype == "string":
        return str(value)
    if vtype == "quantity":
        return str(value.get("amount", "")).lstrip("+")
    return ""


def parse_wikidata(entity_data, entity_id):
    """Extract a few labelled facts from Wikidata EntityData JSON.

    Pure function. Each fact is '<label>: <value>' with the Wikidata
    entity URL as its source. Only literal values present in the data
    are surfaced — nothing is inferred or invented.
    """
    entity = (entity_data or {}).get("entities", {}).get(entity_id, {})
    if not entity:
        return []
    label = entity.get("labels", {}).get("en", {}).get("value", entity_id)
    claims = entity.get("claims", {})
    url = f"https://www.wikidata.org/wiki/{entity_id}"
    source = {"title": f"Wikidata: {label}", "url": url, "no_public_url": False}
    facts = []
    for prop_label, pid in WD_PROPS:
        for claim in claims.get(pid, [])[:1]:
            value = _wd_value(claim, entity_data)
            if value:
                facts.append({"text": f"{label} — {prop_label}: {value}.",
                              "source": dict(source), "tier": "KNOWN"})
    return facts


def fetch_wikidata(entity_id):
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{entity_id}.json"
    try:
        return _get_json(url)
    except Exception as exc:
        print(f"WARNING: Wikidata entity fetch failed ({exc}).", file=sys.stderr)
        return {}


def research_topic(topic, config=None, lang="en"):
    """Aggregate Wikipedia + Wikidata research for a topic.

    Returns {topic, provider, facts, sources, shock_candidate}. On any
    failure returns provider="none" with empty lists so callers fall
    back to template scripts. Never raises on network errors.
    """
    config = config or {}
    lang = config.get("research_language", lang) or lang
    result = {"topic": topic, "provider": "none", "facts": [],
              "sources": [], "shock_candidate": None}
    title = search_wikipedia(topic, lang)
    summary = parse_summary(fetch_summary(title, lang)) if title else parse_summary({})
    facts = list(summary["facts"])
    sources = []
    if summary["url"]:
        sources.append({"title": summary["facts"][0]["source"]["title"] if summary["facts"]
                        else f"Wikipedia: {summary['title']}",
                        "url": summary["url"], "no_public_url": False})
    eid = search_wikidata(topic, lang)
    if eid:
        wd_facts = parse_wikidata(fetch_wikidata(eid), eid)
        facts.extend(wd_facts)
        if wd_facts:
            sources.append(wd_facts[0]["source"])
    if facts:
        result.update(provider="wikipedia+wikidata", facts=facts,
                      sources=sources, shock_candidate=summary["shock_candidate"])
    return result


# ------------------------------------------------------------- LLM draft tier
def llm_draft(topic, facts, tier="template"):
    """Compose a draft paragraph from VERIFIED facts.

    tier:
      - template (default, $0, offline): joins the sourced facts into
        prose. No network, no invention.
      - local: placeholder for a local model; falls back to template
        when no local backend is configured (never fails the run).
      - api: OpenAI-compatible chat completion, opt-in via LLM_API_KEY
        (or OPENAI_API_KEY) + LLM_API_BASE. The draft is STILL passed
        through drop_unverified + the QA gate by the caller; this
        function only produces text, it never publishes.

    Returns {text, tier, sources}. Sources are the facts' real sources.
    """
    sources = [f["source"] for f in facts if f.get("source")]
    if tier == "api":
        key = os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY") or ""
        base = os.environ.get("LLM_API_BASE", "https://api.openai.com/v1")
        model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        if key:
            try:
                body = json.dumps({
                    "model": model,
                    "messages": [
                        {"role": "system", "content":
                         "Write a short, accurate narration paragraph using ONLY "
                         "the provided verified facts. Do not invent dates, names, "
                         "or findings. If a fact is uncertain, say so."},
                        {"role": "user", "content":
                         f"Topic: {topic}\nVerified facts:\n" +
                         "\n".join(f"- {f['text']}" for f in facts)},
                    ],
                    "temperature": 0.4,
                }).encode("utf-8")
                req = urllib.request.Request(
                    f"{base}/chat/completions", data=body, method="POST",
                    headers={"Authorization": f"Bearer {key}",
                             "Content-Type": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.load(resp)
                text = data["choices"][0]["message"]["content"].strip()
                return {"text": text, "tier": "api", "sources": sources}
            except Exception as exc:
                print(f"WARNING: LLM api draft failed ({exc}); using template.",
                      file=sys.stderr)
        else:
            print("WARNING: LLM api tier requested but no LLM_API_KEY; "
                  "using template tier.", file=sys.stderr)
    # template / local fallback: join verified facts, no invention.
    text = " ".join(f["text"] for f in facts) or (
        f"Here is what the verified record shows about {topic}.")
    return {"text": text, "tier": "template", "sources": sources}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Free Wikipedia/Wikidata research.")
    parser.add_argument("--topic", required=True)
    parser.add_argument("--output", default="")
    parser.add_argument("--lang", default="en")
    parser.add_argument("--llm-tier", default="template",
                        choices=["template", "local", "api"])
    args = parser.parse_args(argv)
    result = research_topic(args.topic, lang=args.lang)
    if args.llm_tier != "template" and result["facts"]:
        result["draft"] = llm_draft(args.topic, result["facts"], tier=args.llm_tier)
    text = json.dumps(result, indent=2)
    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Research -> {args.output} ({len(result['facts'])} facts, "
              f"provider {result['provider']})")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
