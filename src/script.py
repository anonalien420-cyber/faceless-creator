"""Write ORIGINAL scripts: Shorts (30-60s) and long-form (8-12 min).

Originality rule (also in README.md): scripts are generated from an
original angle — hook, beats/sections, call to action — using only the
candidate's topic as a prompt. Never copy a source video's title, script,
or wording, never reuse copyrighted characters or music, and never
present a paraphrase of someone else's script as your own work.
If a candidate has no usable topic, it is skipped, not copied.

Shorts target: 120-180 words (roughly 45-60 seconds spoken).
Long-form target: 1200-1800 words (roughly 8-12 minutes spoken), with
chapters/sections. The long script's sections become YouTube chapters
in the upload description (timestamps computed from narration length
in run.py — chapters are section titles, not copied content).

Hook styles (review.py can set review_preferred_hook_style in
config.yaml to the style winning videos share; script.py honours it
unless --hook-style is passed explicitly):
- statement: "Stop scrolling. If X has been stressing you out..."
- question:  "What if X is simpler than everyone says?"
- shock:     "Most people get X completely backwards."
- story:     "I used to get X wrong every single week."

History-mystery style (--style history_mystery, auto-detected when the
locked/first niche in config.yaml mentions history + mystery):
every script presents EVIDENCE first, then COMPETING THEORIES (each
labelled as a theory, never as proven fact), then WHAT IS STILL
UNEXPLAINED. It never presents a theory as proven fact, and it never
invents historical "facts": dates, names, and findings in the template
are structural ("researchers found...", "one theory says..."), and the
script's `notes` field carries the rule that every concrete claim
must be checked against a real source before publishing, with sources
cited in `sources`. The generator itself cites no invented source.

Shock, honestly (see README "Shock, honestly"): a history video
opens with a verified SHOCK HOOK — a genuinely surprising but TRUE
fact (scale, contrast, or twist) supplied with its source, labelled
KNOWN, and carried in the script's `shock_hook` field. The generator
cannot invent a shock fact: supply one per video via the candidate's
`shock_fact` + `shock_source` fields (or fill `shock_hook` in the
script JSON by hand). A shock claim without a source is DROPPED by
drop_unverified, and the QA gate then blocks the video — there is no
shocking claim without a source, ever. Curiosity loops close every
section with an open question the next section answers, and every
video ends with a cliffhanger / next-episode tease in addition to
the open viewer question. Shock comes from real scale, contrast,
and twists in verified facts — never from exaggeration, invented
numbers, or misleading framing.
"""

import argparse
import json
import os
import re

try:
    from src.config import load_config
except ImportError:
    from config import load_config

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "for", "in", "on", "how",
    "why", "what", "best", "top", "you", "your", "with", "that", "this",
}

EXTRA_SENTENCES = [
    "That is it. Small, repeatable, and honest beats big, dramatic, and abandoned.",
    "Start tonight, while it is still fresh, and let the streak do the talking.",
    "If it feels boring, that is usually a sign it is working.",
    "One good week beats one perfect day, every time.",
]


def topic_from_candidate(candidate):
    topic = (candidate.get("topic") or "").strip()
    if topic:
        return topic
    title = candidate.get("title", "")
    words = [w for w in re.findall(r"[a-zA-Z']+", title.lower()) if w not in STOPWORDS]
    return " ".join(words[:4]) or "this topic"


def hook_for(style, topic):
    styles = {
        "statement": (
            f"Stop scrolling. If {topic} has been stressing you out, "
            "this is the one habit that actually changes it."),
        "question": (
            f"What if {topic} is simpler than everyone makes it sound? "
            "Here is the version that actually works in real life."),
        "shock": (
            f"Most people get {topic} completely backwards, and that one "
            "mistake is why they keep starting over."),
        "story": (
            f"I used to get {topic} wrong every single week, until I stopped "
            "trying to fix everything at once."),
    }
    return styles.get(style, styles["statement"])


def _sentences(text):
    return re.split(r"(?<=[.!?])\s+", text.strip())


def _trim_to_words(text, target):
    """Trim whole sentences to near target words (never mid-sentence)."""
    words = text.split()
    if len(words) <= target + 20:
        return text
    kept, count = [], 0
    for sentence in _sentences(text):
        if count + len(sentence.split()) > target and kept:
            break
        kept.append(sentence)
        count += len(sentence.split())
    return " ".join(kept)


def build_script(topic, hook_style="statement", target_words=None):
    """Short script: hook + 3 beats + CTA, 120-180 words by default."""
    hook = hook_for(hook_style, topic)
    beat1 = (
        "First, most people try to fix everything at once. That fails because "
        "willpower runs out fast. Pick one small win you can repeat every single "
        "day, and protect it like an appointment."
    )
    beat2 = (
        "Second, make it automatic. Put the decision on your calendar, set a "
        "reminder, and remove one friction point tonight. When the easy choice "
        "is also the right choice, you stop relying on motivation."
    )
    beat3 = (
        "Third, track it for seven days, not seven months. A short streak you "
        "can see beats a perfect plan you never start. If you miss a day, "
        "restart the next morning without the guilt spiral."
    )
    cta = (
        "Try it today, save this video so you can find it again, and tell me "
        "in the comments which small win you are picking first."
    )
    text = " ".join([hook, beat1, beat2, beat3, cta])
    target = target_words or 150
    i = 0
    while len(text.split()) < target and i < len(EXTRA_SENTENCES):
        text = f"{text} {EXTRA_SENTENCES[i]}"
        i += 1
    if len(text.split()) > target + 30:
        text = _trim_to_words(text, target)
    return {
        "hook": hook,
        "beats": [beat1, beat2, beat3],
        "cta": cta,
        "text": text,
        "word_count": len(text.split()),
        "format": "short",
    }


CLAIM_TIERS = {
    # KNOWN: verified, sourced fact — must have a real source in `sources`.
    # DEBATED: genuine disagreement; both sides must be named, neither
    #   presented as settled. UNKNOWN: genuinely unexplained — stated
    #   plainly, never filled in with a guess.
    "KNOWN": "Verified, sourced fact.",
    "DEBATED": "Genuine disagreement; both sides named, neither settled.",
    "UNKNOWN": "Genuinely unexplained; stated plainly, never guessed at.",
}

HISTORY_NOTES = (
    "History-mystery rules for this script — CONTENT PRINCIPLE: "
    "everything must be historically accurate and only what is known "
    "to be true. Be interesting and well informed, and leave the "
    "mystery open so viewers can bring their own thoughts and "
    "speculations. Every section carries a claim tier: KNOWN (verified, "
    "sourced fact), DEBATED (genuine disagreement, both sides named), "
    "or UNKNOWN (genuinely unexplained, never filled in with a guess). "
    "No invented dates, names, quotes, artifacts, or findings: any "
    "concrete claim without a real source is DROPPED from the script, "
    "not softened into a guess, and listed in `dropped_unverified`. "
    "Tone: dramatic delivery (hook, pacing, visuals) is welcome, but "
    "never by exaggerating a fact — if a fact is uncertain, say so on "
    "screen and in narration. Viewer speculation is engagement, never "
    "evidence: a commenter's theory must never be presented in a later "
    "video as fact. Evidence first, competing theories labelled as "
    "theories, and a clear what-is-still-unexplained section. The "
    "template itself contains no concrete historical claims — every "
    "concrete date, name, or finding must be checked against a real "
    "source before publishing, and the sources used must be cited in "
    "the video description / notes. SHOCK, HONESTLY: open with a "
    "verified shock hook (a genuinely surprising but TRUE fact, "
    "labelled KNOWN, with its source in `shock_hook`); shock comes "
    "from real scale, contrast, or a twist in verified facts, never "
    "from exaggeration, invented numbers, or misleading framing. A "
    "shock claim without a source is dropped and blocks upload. Keep "
    "curiosity loops running — each section ends with an open question "
    "the next section answers — and end with a next-episode tease as "
    "well as the open viewer question, so viewers leave wanting the "
    "next investigation, not a made-up answer to this one."
)

# Section title -> claim tier for history-mystery long scripts.
HISTORY_SECTION_TIERS = {
    "The mystery": "UNKNOWN",
    "What the evidence actually shows": "KNOWN",
    "Theory one": "DEBATED",
    "Theory two": "DEBATED",
    "What modern tech reveals": "KNOWN",
    "What is still unexplained": "UNKNOWN",
}

OPEN_VIEWER_QUESTION = "What do you think happened?"


def drop_unverified(script, unverified_claims):
    """Drop concrete claims that have no real source.

    `unverified_claims` is a list of claim strings a human (or a source
    check) could not verify. Each is removed from the script text, its
    section text, and its beats where it appears, and recorded in
    `dropped_unverified` — it is NEVER softened into a guess or kept
    with hedging language. Returns the updated script dict.
    """
    dropped = list(script.get("dropped_unverified", []))
    for claim in unverified_claims or []:
        if not claim or claim in dropped:
            continue
        script["text"] = script["text"].replace(claim, "").strip()
        for section in script.get("sections", []):
            section["text"] = section["text"].replace(claim, "").strip()
        script["beats"] = [b.replace(claim, "").strip()
                           for b in script.get("beats", [])]
        # A dropped shock claim takes the shock hook with it: no
        # shocking claim without a source, in any field.
        hook = script.get("shock_hook") or {}
        if hook.get("text") and hook["text"] in claim:
            script["shock_hook"] = None
            if script.get("hook") == hook["text"]:
                script["hook"] = ""
        dropped.append(claim)
    script["dropped_unverified"] = dropped
    script["word_count"] = len(script["text"].split())
    return script

HISTORY_SOURCES_PLACEHOLDER = [
    "Sources to cite before publishing (do NOT publish with this placeholder): "
    "attach the real primary sources, museum/academic records, and reputable "
    "reporting you verified for this topic. No source was invented by this generator.",
]

# Curiosity loops: each section ends with an open question that the
# NEXT section answers. Generic structural questions only — they claim
# no fact, so they need no source. The last section instead ends with
# the viewer question + next-episode tease.
# Short loops are kept to a few words: the full loop sentences
# would push a Short past its 30-60s (120-180 word) target.
SHORT_CURIOSITY_LOOPS = {
    "What the evidence actually shows":
        " Why do experts disagree?",
    "Competing theories":
        " So what is still missing?",
}
LONG_CURIOSITY_LOOPS = {
    "The mystery":
        " So what do we actually know for certain? That is where the "
        "evidence comes in.",
    "What the evidence actually shows":
        " If the evidence is this solid, why do experts still disagree? "
        "The theories are next.",
    "Theory one":
        " That explains part of it — but what about the evidence it "
        "cannot explain? The second theory takes that on.",
    "Theory two":
        " Two theories, both incomplete. What do modern tools add? "
        "That is next.",
    "What modern tech reveals":
        " Even with new tools, something is still missing. What is it? "
        "The final section names it.",
}


def normalize_shock_source(source):
    """Normalize a shock source to {title, url, no_public_url} or None.

    Accepts a dict ({title, url} or {title, no_public_url: true}) or a
    plain string (treated as a title with no public URL — the URL is
    NEVER invented). Returns None for empty/placeholder sources.
    """
    if not source:
        return None
    if isinstance(source, dict):
        title = (source.get("title") or "").strip()
        url = (source.get("url") or "").strip() or None
        if not title and not url:
            return None
        return {"title": title or url or "Untitled source",
                "url": url,
                "no_public_url": bool(source.get("no_public_url")) or url is None}
    text = str(source).strip()
    if not text or any(m.lower() in text.lower()
                       for m in ("do NOT publish", "placeholder")):
        return None
    if text.startswith("http"):
        return {"title": text, "url": text, "no_public_url": False}
    return {"title": text, "url": None, "no_public_url": True}


def make_shock_hook(shock_fact, shock_source):
    """Build the verified shock hook, or return None.

    Returns (hook_dict, dropped_entry): hook_dict is
    {text, tier: "KNOWN", source} when BOTH a fact and a real source
    are supplied; otherwise None plus a dropped_unverified entry
    explaining why (an unsourced shock claim is dropped, never kept).
    """
    fact = (shock_fact or "").strip()
    if not fact:
        return None, None
    source = normalize_shock_source(shock_source)
    if source is None:
        return None, f"SHOCK HOOK (dropped, no source): {fact}"
    return {"text": fact, "tier": "KNOWN", "source": source}, None


def next_episode_tease(next_topic, short=False):
    """Cliffhanger tease for the next video. Generic unless a real
    next topic is supplied — a next topic is never invented. The
    short form is one sentence, so a Short stays in its 30-60s
    (120-180 word) target."""
    if short:
        return (f"Next time: {next_topic}."
                if next_topic else "Next time, a new mystery.")
    if next_topic:
        return (f"Next time, we investigate {next_topic} — and the "
                "evidence there is even stranger. Subscribe so you do "
                "not miss it.")
    return ("Next time, we open a new mystery from somewhere else in "
            "the world — one the textbooks barely mention. Subscribe "
            "so you do not miss it.")


def build_history_short_script(topic, hook_style="question", target_words=150,
                               shock_fact=None, shock_source=None,
                               next_topic=None):
    """Short history-mystery script: shock hook + evidence + theories +
    unexplained + CTA, with curiosity loops and a next-episode tease.

    Every claim is hedged on purpose: theories are theories, evidence is
    described as evidence, and the ending names what is still unknown.
    If shock_fact + shock_source are supplied, the shock hook IS the
    opening line (KNOWN, sourced). If a shock fact arrives without a
    source, it is dropped into `dropped_unverified` and the opening
    falls back to a generic curiosity line that claims nothing — and
    the QA gate will block the video until a verified shock hook is
    supplied, because a history video must open with a sourced shock
    fact, not a placeholder.
    """
    shock_hook, dropped = make_shock_hook(shock_fact, shock_source)
    hook = (
        shock_hook["text"] if shock_hook else
        f"Something about {topic} still does not add up — and modern tools "
        "are finally putting it to the test."
    )
    evidence = (
        "Here is what the evidence actually shows, as far as researchers can "
        "verify it. There are records, physical traces, and findings studied "
        "for years — and they agree on some points while leaving others wide open."
    )
    theories = (
        "Researchers disagree on what it means. One theory says the explanation "
        "is more ordinary than it looks. Another says something rarer is going "
        "on. Neither theory is proven — treating either one as settled fact "
        "would be misleading, so we will not do that here."
    )
    unexplained = (
        "What is still unexplained is the part that keeps researchers coming "
        "back: the pieces that do not fit either theory cleanly. Modern tools "
        "— scans, forensic analysis, satellite imagery, reconstruction — are "
        "narrowing the gap, but they have not closed it yet."
    )
    # Curiosity loops: each section ends with the question the next
    # section answers (generic questions, no factual claims).
    evidence = evidence + SHORT_CURIOSITY_LOOPS["What the evidence actually shows"]
    theories = theories + SHORT_CURIOSITY_LOOPS["Competing theories"]
    tease = next_episode_tease(next_topic, short=True)
    cta = (
        f"{OPEN_VIEWER_QUESTION} Which theory do you find most convincing, "
        "and why? Tell me in the comments — your speculation is welcome, "
        "and it stays speculation until evidence proves otherwise. "
        f"{tease}"
    )
    text = " ".join([hook, evidence, theories, unexplained, cta])
    sections = [
        {"title": "What the evidence actually shows", "tier": "KNOWN",
         "text": evidence},
        {"title": "Competing theories", "tier": "DEBATED", "text": theories},
        {"title": "What is still unexplained", "tier": "UNKNOWN",
         "text": unexplained},
    ]
    return {
        "hook": hook,
        "shock_hook": shock_hook,
        "next_episode_tease": tease,
        "beats": [evidence, theories, unexplained],
        "sections": sections,
        "claim_tiers": CLAIM_TIERS,
        "cta": cta,
        "text": text,
        "word_count": len(text.split()),
        "format": "short",
        "style": "history_mystery",
        "notes": HISTORY_NOTES,
        "sources": HISTORY_SOURCES_PLACEHOLDER,
        "dropped_unverified": [dropped] if dropped else [],
    }


HISTORY_LONG_SECTIONS = [
    ("The mystery", [
        "Let us start with the mystery itself, and with what makes {topic} "
        "worth investigating rather than just repeating. Something happened, "
        "or something was found, that does not fit neatly into the story we "
        "usually tell about that time and place. That misfit is the whole "
        "reason researchers keep returning to it. It is not that there is no "
        "evidence — there is, and some of it is strong — it is that the "
        "evidence does not yet point to one settled answer, and honest "
        "researchers say so instead of pretending otherwise.",
    ]),
    ("What the evidence actually shows", [
        "Before theories, the evidence. What can actually be verified matters "
        "more than what sounds exciting. Records, physical traces, and "
        "findings that have been examined and re-examined form the floor of "
        "this story: the parts that different researchers, even ones who "
        "disagree, tend to accept. Where the record is thin, we will say so. "
        "A gap in the evidence is not a licence to fill it with a guess and "
        "call the guess a discovery. Keeping the verified parts and the "
        "missing parts separate is what separates an investigation from a story.",
    ]),
    ("Theory one", [
        "The first theory worth taking seriously says the explanation is more "
        "ordinary than the mystery suggests. Its supporters point to the "
        "evidence that fits their reading, and they argue that the strange "
        "parts have explanations we already understand, once the context is "
        "right. This theory is a theory, not a verdict: it explains some of "
        "the evidence well and other parts less well, and its supporters "
        "disagree among themselves about the details. That is normal for a "
        "live question, and it is not a weakness to admit it.",
    ]),
    ("Theory two", [
        "The second theory says something rarer is going on. Its supporters "
        "point to the evidence the first theory struggles with, and they argue "
        "that the ordinary explanation leaves too much unexplained. This "
        "theory is also a theory, not a verdict. It is worth hearing out "
        "because it takes the awkward evidence seriously, and it is worth "
        "holding to a high standard for exactly the same reason. An exciting "
        "theory still needs evidence, and excitement is not evidence.",
    ]),
    ("What modern tech reveals", [
        "This is where modern tools change the investigation. Satellite "
        "imagery can reveal patterns invisible from the ground. Forensic "
        "analysis can test materials and traces in ways earlier researchers "
        "could not. AI reconstruction can model what a site, an object, or an "
        "event might have looked like, given the evidence we have. Each tool "
        "narrows the range of possible answers — and each tool has limits, "
        "because a reconstruction is only as good as the evidence fed into "
        "it. Modern tech tests theories; it does not bless them.",
    ]),
    ("What is still unexplained", [
        "So what is still unexplained about {topic}? The pieces that do not "
        "fit either theory cleanly, the questions new tools have raised "
        "faster than they have answered, and the evidence nobody has found "
        "yet — or that may no longer exist. That is the honest ending, and "
        "it is also the interesting one: a mystery that is still open is an "
        "invitation to keep looking, not a permission to stop and declare an "
        "answer. If new evidence appears, this story should be updated, and "
        "any earlier video on it should be corrected, not quietly left standing.",
    ]),
]


def build_history_long_script(topic, hook_style="question", target_words=1500,
                              shock_fact=None, shock_source=None,
                              next_topic=None):
    """Long history-mystery script: shock hook + mystery + evidence +
    2 theories + modern tech + unexplained, 1200-1800 words, with
    chapters, curiosity loops, and a next-episode tease. Shock-hook
    rules are the same as the short builder: sourced fact or nothing —
    an unsourced shock claim is dropped and the QA gate blocks upload
    until a verified shock hook is supplied."""
    shock_hook, dropped = make_shock_hook(shock_fact, shock_source)
    hook = (
        shock_hook["text"] if shock_hook else
        f"Something about {topic} still does not add up — and in this video, "
        "we are investigating it properly: evidence first, theories labelled "
        "as theories, and an honest account of what is still unexplained."
    )
    intro = (
        f"We will cover the mystery itself, what the evidence actually shows, "
        "two competing theories and what each one explains — and fails to "
        "explain — what modern tools like satellite imagery, forensic "
        "analysis, and AI reconstruction reveal, and what remains unexplained. "
        "Nothing here is presented as proven unless the evidence proves it."
    )
    sections = []
    for title, paragraphs in HISTORY_LONG_SECTIONS:
        body = " ".join(p.format(topic=topic) for p in paragraphs)
        # Curiosity loop: the question the NEXT section answers.
        body = body + LONG_CURIOSITY_LOOPS.get(title, "")
        sections.append({"title": title, "text": body,
                         "tier": HISTORY_SECTION_TIERS.get(title, "UNKNOWN")})
    tease = next_episode_tease(next_topic)
    cta = (
        f"If this investigation helped, subscribe for the next one. "
        f"{OPEN_VIEWER_QUESTION} Tell me in the comments which theory you "
        "find most convincing — and what evidence would change your mind. "
        "Your theories are welcome here, and they stay theories until "
        "evidence proves otherwise. The summary: the evidence is real, "
        "the theories disagree, and the mystery is still open. "
        f"{tease}"
    )
    parts = [hook, intro] + [s["text"] for s in sections] + [cta]
    text = " ".join(parts)
    while len(text.split()) < target_words:
        text = (f"{text} One point worth repeating: a theory is not a fact "
                "until the evidence proves it, and an open question is not a "
                "failure — it is the reason to keep investigating.")
        if len(text.split()) >= target_words:
            break
    if len(text.split()) > target_words + 100:
        text = _trim_to_words(text, target_words)
    chapters = ["Intro"] + [s["title"] for s in sections] + ["Summary"]
    return {
        "hook": hook,
        "shock_hook": shock_hook,
        "next_episode_tease": tease,
        "sections": sections,
        "chapters": chapters,
        "claim_tiers": CLAIM_TIERS,
        "cta": cta,
        "text": text,
        "word_count": len(text.split()),
        "format": "long",
        "style": "history_mystery",
        "notes": HISTORY_NOTES,
        "sources": HISTORY_SOURCES_PLACEHOLDER,
        "dropped_unverified": [dropped] if dropped else [],
    }


LONG_SECTIONS = [
    ("The problem, honestly", [
        "Let us start with why this feels hard, because the usual advice skips that part. "
        "Most people do not fail at {topic} because they are lazy. They fail because the "
        "starting point they were given is wrong: it asks for a perfect week, a perfect "
        "routine, and a perfect mindset, all at once. Nobody lives like that. Real weeks "
        "have late nights, bad weather, busy days, and days when motivation simply does "
        "not show up. A plan that only works on a perfect day is not a plan, it is a wish. "
        "So the first thing to fix is not your effort, it is the expectation. If you have "
        "tried before and stopped, that is data, not a character flaw. It tells you the "
        "old approach asked too much, too fast, with too little room for a normal life.",
    ]),
    ("The mistake most people make", [
        "The most common mistake with {topic} is trying to change five things on Monday "
        "morning. By Wednesday, three of them are gone, and by Friday the whole thing "
        "feels like proof that you cannot do it. That cycle is expensive, because every "
        "restart costs confidence. The fix is almost boring: change one thing, and let "
        "it survive a bad week before you add anything else. One thing that survives is "
        "worth more than five things that collapse. If you catch yourself adding a second "
        "habit before the first one is automatic, that is the mistake happening in real "
        "time. Pause, protect the first win, and let the second one wait its turn.",
    ]),
    ("The simple system", [
        "Here is the system, in full. Pick one small action that takes under ten minutes "
        "and ties directly to {topic}. Attach it to something you already do every day, "
        "like making coffee or getting home from work, so you do not need a reminder to "
        "remember it. Write it on your calendar for the same time daily, and set one alarm "
        "for the first week only. Then track it with a single mark per day, on paper or "
        "in your phone, for seven days. That is the whole system. No app subscription, "
        "no complicated spreadsheet, no new personality required. Simple survives; "
        "complicated gets abandoned the first time life gets busy, and life always gets busy.",
    ]),
    ("What it looks like in practice", [
        "In practice, a good week of {topic} does not look impressive from the outside. "
        "It looks like seven small marks in a row, a couple of days where you did the "
        "minimum and moved on, and one day where you almost skipped and did it anyway. "
        "That almost-skipped day is the most important one, because it is where the habit "
        "stops depending on mood. Do not chase a perfect streak; chase a fast restart. "
        "Missing a day is normal. Missing two days in a row is where the slide starts, "
        "so the rule is simple: never miss twice. If you miss once, the next morning is "
        "a restart, not a failure, and you do not owe anyone an explanation for it.",
    ]),
    ("Common traps", [
        "Watch for three traps. The first is the gear trap: buying tools, courses, or "
        "equipment for {topic} before you have done the basic version for two weeks. "
        "Gear feels like progress, but it is usually procrastination with a receipt. "
        "The second is the comparison trap: measuring your week one against someone "
        "else's year ten. You only see their highlight reel, never their first month. "
        "The third is the all-or-nothing trap: one missed day becomes a reason to quit "
        "for a month. All three traps have the same cure, which is to return to the one "
        "small action, today, without drama and without a big announcement about it.",
    ]),
    ("Your 7-day plan", [
        "Here is your plan for the next seven days. Day one, pick the one small action "
        "and do it once, however imperfectly. Day two, attach it to your daily anchor and "
        "set the alarm. Days three and four, just collect the marks; do not improve the "
        "system yet. Day five, remove one friction point that slowed you down. Day six, "
        "notice what almost made you skip, and fix that one thing. Day seven, look at "
        "the row of marks and decide: keep this exact version for another week, or make "
        "one small upgrade. Then start again. That is how {topic} stops being a project "
        "you restart and becomes something you simply do, quietly, every day.",
    ]),
]


def build_long_script(topic, hook_style="statement", target_words=1500):
    """Long-form script: hook + intro + 6 sections + CTA, 1200-1800 words."""
    hook = hook_for(hook_style, topic)
    intro = (
        f"In this video, we are going deep on {topic}: not the quick tips version, "
        "but the version that holds up when life gets busy. We will cover the real "
        "problem, the mistake most people make, a simple system you can actually keep, "
        "what it looks like in practice, the traps to avoid, and a seven-day plan you "
        "can start tonight. If you want the short version, the summary is at the end, "
        "but the middle is where the useful part lives, so stay with it."
    )
    sections = []
    for title, paragraphs in LONG_SECTIONS:
        body = " ".join(p.format(topic=topic) for p in paragraphs)
        sections.append({"title": title, "text": body})
    cta = (
        "If this helped, subscribe for the next deep dive, and tell me in the comments "
        "which part you are starting with first. The summary: pick one small action, "
        "attach it to something you already do, track it for seven days, and never miss "
        "twice. Start tonight, and let the streak do the talking."
    )
    parts = [hook, intro] + [s["text"] for s in sections] + [cta]
    text = " ".join(parts)
    while len(text.split()) < target_words:
        text = (f"{text} One more thing worth repeating: simple survives, "
                "complicated gets abandoned, so keep the system small until it is automatic.")
        if len(text.split()) >= target_words:
            break
    if len(text.split()) > target_words + 100:
        text = _trim_to_words(text, target_words)
    chapters = ["Intro"] + [s["title"] for s in sections] + ["Summary"]
    return {
        "hook": hook,
        "sections": sections,
        "chapters": chapters,
        "cta": cta,
        "text": text,
        "word_count": len(text.split()),
        "format": "long",
    }


def load_candidates(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, list):
        return data
    return data.get("candidates", data.get("videos", []))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/top5.json")
    parser.add_argument("--output", default="data/scripts.json")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--format", default="short", choices=["short", "long"])
    parser.add_argument("--hook-style", default="")
    parser.add_argument("--target-words", type=int, default=0)
    parser.add_argument("--style", default="",
                        help="Script style: general (default) or history_mystery. "
                             "Empty = auto-detect from config's first niche "
                             "(history + mystery -> history_mystery).")
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args(argv)

    config = {}
    try:
        config = load_config(args.config)
    except Exception:
        pass
    hook_style = args.hook_style or config.get("review_preferred_hook_style", "") or "statement"
    # Style: explicit --style wins; otherwise auto-detect from the locked
    # / first niche (history + mystery in its name -> history_mystery).
    style = args.style
    if not style:
        first_niche = ((config.get("niches") or [config.get("niche", "")])[0]
                       if (config.get("niches") or config.get("niche")) else "")
        lowered = (first_niche or "").lower()
        style = "history_mystery" if ("history" in lowered and "myster" in lowered) else "general"
    if style == "history_mystery":
        hook_style = args.hook_style or "question"
    if args.format == "long":
        target = args.target_words or 1500
        builder = build_history_long_script if style == "history_mystery" else build_long_script
    else:
        # Review length preference (seconds) -> words at ~150 wpm.
        length = config.get("review_preferred_length_seconds")
        target = args.target_words or (int(length) * 150 // 60 if length else 150)
        builder = build_history_short_script if style == "history_mystery" else build_script
    candidates = load_candidates(args.input)
    scripts = []
    for rank, cand in enumerate(candidates[: args.count], start=1):
        topic = topic_from_candidate(cand)
        # History shock hook + next-episode tease come from the
        # candidate (verified by a human before the run) — the
        # generator never invents either one.
        extra = {}
        if style == "history_mystery":
            extra = {"shock_fact": cand.get("shock_fact"),
                     "shock_source": cand.get("shock_source"),
                     "next_topic": cand.get("next_topic")}
        if args.format == "long":
            script = builder(topic, hook_style=hook_style, target_words=target, **extra)
        else:
            script = builder(topic, hook_style=hook_style, target_words=target, **extra)
        script.setdefault("dropped_unverified", [])
        scripts.append({
            "rank": rank,
            "topic": topic,
            "source_url": cand.get("url", ""),
            "source_channel": cand.get("channel", ""),
            "original_script": True,
            "hook_style": hook_style,
            "style": script.get("style", style),
            **script,
        })
    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        json.dump(scripts, fh, indent=2)
    for item in scripts:
        print(f"#{item['rank']} [{item['format']}] {item['topic']} — {item['word_count']} words")
    print(f"Wrote {len(scripts)} {args.format} scripts to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
