"""Persistent user state: learned words, app exclusions, auto on/off.

Plain JSON at ~/.local/share/relayout/state.json. Learned words are only
words the user explicitly flipped/undid, never a log of typing.
"""
from __future__ import annotations

import json
import os
import string
import tempfile
from pathlib import Path

_STRIP = string.punctuation + "«»„“”—–…"


def rule_key(text: str) -> str:
    """Normal form of a word for rule lookup: lowercase, edge punctuation off."""
    return text.lower().replace("ё", "е").strip(_STRIP)


def default_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "relayout" / "state.json"


class Store:
    def __init__(self, path: Path | None = None, default_excluded=(), default_auto=True):
        self.path = path or default_path()
        self.words: dict[str, str] = {}
        # Words (both renderings) that are real in both layouts and must never
        # be auto-flipped in either direction.
        self.keep: list[str] = []
        self.excluded: list[str] = list(default_excluded)
        self.auto: bool = default_auto
        self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return
        words = data.get("words")
        if isinstance(words, dict):
            self.words = {str(k): str(v) for k, v in words.items()}
        keep = data.get("keep")
        if isinstance(keep, list):
            self.keep = [str(x) for x in keep]
        excluded = data.get("excluded")
        if isinstance(excluded, list):
            self.excluded = [str(x) for x in excluded]
        if isinstance(data.get("auto"), bool):
            self.auto = data["auto"]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"auto": self.auto, "excluded": self.excluded, "words": self.words}
        if self.keep:
            payload["keep"] = sorted(set(self.keep))
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".state-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def is_excluded(self, app: str) -> bool:
        app = app.lower()
        return bool(app) and any(app == x.lower() for x in self.excluded)

    def add_word(self, word: str, layout: str) -> None:
        key = rule_key(word)
        if key:
            self.words[key] = layout
            self.save()

    def remove_word(self, word: str) -> bool:
        key = rule_key(word)
        removed = self.words.pop(key, None) is not None
        if key in self.keep:
            self.keep.remove(key)
            removed = True
        if removed:
            self.save()
        return removed

    def is_kept(self, word: str) -> bool:
        return rule_key(word) in self.keep

    def add_keep(self, *words: str) -> None:
        """Never auto-flip these words; replaces any directional rule for them."""
        for word in words:
            key = rule_key(word)
            if key:
                self.words.pop(key, None)
                if key not in self.keep:
                    self.keep.append(key)
        self.save()
