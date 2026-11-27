"""Typed data models for the pipeline (stdlib dataclasses, no deps).

The pipeline historically passed loose dicts between stages. These
dataclasses give the new code a typed, validated shape while staying
100% backward compatible: every model round-trips to/from the plain
dicts the existing JSON files and module APIs already use, so nothing
that reads `script["text"]` or `report["overall"]` breaks.

Use them where convenient (research, caching, manifests, scene B-roll);
the dict-based APIs keep working unchanged.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from typing import Any


def content_hash(text: str) -> str:
    """Stable short hash of script/audio content for cache keys."""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


@dataclass
class Source:
    title: str = ""
    url: str | None = None
    no_public_url: bool = False

    @classmethod
    def from_dict(cls, data: Any) -> Source:
        if isinstance(data, str):
            return cls(title=data, url=None, no_public_url=True)
        data = data or {}
        url = (data.get("url") or "").strip() or None
        return cls(title=(data.get("title") or "").strip(),
                   url=url,
                   no_public_url=bool(data.get("no_public_url")) or url is None)

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url,
                "no_public_url": self.no_public_url}


@dataclass
class Scene:
    """One script section mapped to its B-roll keywords + chosen visual."""
    title: str = ""
    text: str = ""
    tier: str = "UNKNOWN"
    keywords: list = field(default_factory=list)
    visual: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> Scene:
        return cls(title=data.get("title", ""), text=data.get("text", ""),
                   tier=data.get("tier", "UNKNOWN"),
                   keywords=list(data.get("keywords") or []),
                   visual=data.get("visual"))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Script:
    rank: int = 0
    topic: str = ""
    text: str = ""
    hook: str = ""
    fmt: str = "short"
    style: str = "general"
    sections: list = field(default_factory=list)
    chapters: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    shock_hook: dict | None = None
    cta: str = ""
    word_count: int = 0
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> Script:
        known = {"rank", "topic", "text", "hook", "style", "sections",
                 "chapters", "sources", "shock_hook", "cta", "word_count"}
        extra = {k: v for k, v in data.items() if k not in known and k != "format"}
        return cls(rank=data.get("rank", 0), topic=data.get("topic", ""),
                   text=data.get("text", ""), hook=data.get("hook", ""),
                   fmt=data.get("format", "short"), style=data.get("style", "general"),
                   sections=list(data.get("sections") or []),
                   chapters=list(data.get("chapters") or []),
                   sources=list(data.get("sources") or []),
                   shock_hook=data.get("shock_hook"), cta=data.get("cta", ""),
                   word_count=data.get("word_count", len(data.get("text", "").split())),
                   extra=extra)

    def to_dict(self) -> dict:
        out = {"rank": self.rank, "topic": self.topic, "text": self.text,
               "hook": self.hook, "format": self.fmt, "style": self.style,
               "sections": self.sections, "chapters": self.chapters,
               "sources": self.sources, "shock_hook": self.shock_hook,
               "cta": self.cta, "word_count": self.word_count}
        out.update(self.extra)
        return out

    def cache_key(self) -> str:
        return content_hash(self.text)

    def scenes(self) -> list:
        return [Scene.from_dict(s) for s in self.sections]


@dataclass
class VideoReport:
    video: str = ""
    overall: str = "fail"
    checks: list = field(default_factory=list)
    fixes_applied: list = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> VideoReport:
        return cls(video=data.get("video", ""), overall=data.get("overall", "fail"),
                   checks=list(data.get("checks") or []),
                   fixes_applied=list(data.get("fixes_applied") or []))

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def passed(self) -> bool:
        return self.overall == "pass"

    @property
    def pass_rate(self) -> float:
        if not self.checks:
            return 0.0
        ok = sum(1 for c in self.checks if c.get("status") == "pass")
        return ok / len(self.checks)


@dataclass
class Brand:
    """Channel brand kit driving cards, captions, watermark, thumbnails."""
    accent: str = "#FFCB05"
    accent_alt: str = "#E3350D"
    font: str = "DejaVu Sans"
    text_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    logo: str = ""
    watermark: str = ""

    @classmethod
    def from_config(cls, config: dict) -> Brand:
        data = config.get("brand") or {}
        if not isinstance(data, dict):
            data = {}
        defaults = cls()
        return cls(**{k: data.get(k, getattr(defaults, k)) for k in
                      ("accent", "accent_alt", "font", "text_color",
                       "outline_color", "logo", "watermark")})

    def to_dict(self) -> dict:
        return asdict(self)


def dump_json(path: str, obj: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, indent=2)
