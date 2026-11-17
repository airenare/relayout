"""Decide whether a finished word was typed in the wrong layout.

Each interpretation of the keystrokes (one per layout in the pair) gets a
log-probability from a language model that interpolates a word-frequency
list with a letter-trigram model, so unknown words, names and typos still
get a sensible score. The word flips when the other layout beats the current
one by more than a threshold.

The scoring approach (frequency list + letter trigrams, flip on a
log-probability lead) follows kladaFOX/layoutless, reimplemented here.
"""
from __future__ import annotations

import gzip
import math
import os
import re
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

# Layout code -> language of its word list. Anything else falls back to the
# layout code itself (so a `de.txt.gz` list works for `de`).
LANG_OF_LAYOUT = {"us": "en", "gb": "en", "ru": "ru"}

# One-letter words. A single letter flips when it is a word in the other
# layout and not in the current one ("d" -> "в", but "a" stays).
SINGLE_LETTER_WORDS = {
    "en": {"a", "i"},
    "ru": {"а", "в", "и", "к", "о", "с", "у", "я"},
}

BEGIN, END = "^", "$"
SMOOTHING_K = 0.01
# Characters that mean "this is not prose" (URLs, emails, paths, flags,
# math, passwords...). A chunk containing any of them, or a digit, in either
# rendering is never auto-corrected.
NON_PROSE = set("-=_@#%^&*+~|<>{}\\")


def _blocked_by_symbols(cur: str, other: str) -> bool:
    """Symbols that make this not prose: URLs, emails, flags, passwords...

    ``cur`` and ``other`` are the same keystrokes in each layout, so they line
    up character by character. A symbol is fine when its key is a letter in
    the other layout (a Russian capital `Б` is `<` on us), when it trails the
    word (`привет?` is `ghbdtn&`), or when a hyphen sits between two letters.
    """
    letter = [a.isalpha() or b.isalpha() for a, b in zip(cur, other)]
    end = max((i + 1 for i, v in enumerate(letter) if v), default=0)
    for i in range(end):
        a, b = cur[i], other[i]
        for sym, twin in ((a, b), (b, a)):
            if sym not in NON_PROSE or twin.isalpha():
                continue
            interior_hyphen = (
                sym == "-" and 0 < i < end - 1 and letter[i - 1] and letter[i + 1]
            )
            if not interior_hyphen:
                return True
    return False


def deliberate_case(shifted: list[bool], cur_text: str, other_text: str) -> bool:
    """Capitals beyond the first letter mean it was typed on purpose.

    ``iPhone``, ``camelCase`` and ALL CAPS (``USA``, ``ФРГ``) are left alone;
    a capital that starts a hyphenated part (``Санкт-Георген``) is a name.
    ``shifted[i]`` says whether key i was typed with Shift. Only keys that are
    letters in both layouts count (Shift on `;` is `:`).
    """
    parts: list[list[bool]] = [[]]
    for flag, a, b in zip(shifted, cur_text, other_text):
        if a == "-":
            parts.append([])
        elif a.isalpha() and b.isalpha():
            parts[-1].append(flag)
    for part in parts:
        n = sum(part)
        if n != 0 and not (n == 1 and part[0]):
            return True
    return False


def language_for(layout: str) -> str:
    return LANG_OF_LAYOUT.get(layout, layout)


@dataclass(frozen=True)
class Params:
    #: Minimum log-probability lead (nats) of the other layout to flip.
    threshold: float = 4.0
    #: Weight of the word list vs the letter model.
    lam: float = 0.9


class LangModel:
    def __init__(self, lang: str, lines):
        self.lang = lang
        self.words: dict[str, float] = {}
        self.total = 0.0
        trigrams: dict[str, float] = {}
        contexts: dict[str, float] = {}
        alphabet: set[str] = set()
        for line in lines:
            word, _, count_s = line.partition(" ")
            if not count_s:
                continue
            count = float(count_s)
            self.total += count
            self.words[word] = count
            # Weight the letter model by log frequency: it scores rare and
            # unknown words, so it should learn word shapes, not just the
            # handful of most frequent words.
            weight = math.log1p(count)
            padded = BEGIN * 2 + word + END
            alphabet.update(word)
            for i in range(len(padded) - 2):
                tri = padded[i : i + 3]
                trigrams[tri] = trigrams.get(tri, 0.0) + weight
                ctx = tri[:2]
                contexts[ctx] = contexts.get(ctx, 0.0) + weight
        self.trigrams = trigrams
        self.contexts = contexts
        self.alphabet = len(alphabet) + 1.0  # + END
        self.unseen_penalty = math.log(self.alphabet)
        self.letters = alphabet

    @classmethod
    def load(cls, lang: str, data_dir: Path | None = None) -> "LangModel":
        if data_dir is not None:
            path = data_dir / f"{lang}.txt.gz"
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return cls(lang, f)
        res = resources.files("relayout") / "data" / f"{lang}.txt.gz"
        with res.open("rb") as raw, gzip.open(raw, "rt", encoding="utf-8") as f:
            return cls(lang, f)

    def letters_logp(self, word: str) -> float:
        padded = BEGIN * 2 + word + END
        total = 0.0
        for i in range(len(padded) - 2):
            tri = padded[i : i + 3]
            num = self.trigrams.get(tri, 0.0) + SMOOTHING_K
            den = self.contexts.get(tri[:2], 0.0) + SMOOTHING_K * self.alphabet
            total += math.log(num / den)
        return total

    def core(self, text: str) -> str:
        """The word without surrounding punctuation."""
        start, end = 0, len(text)
        while start < end and text[start] not in self.letters:
            start += 1
        while end > start and text[end - 1] not in self.letters:
            end -= 1
        return text[start:end]

    def _word_logp(self, word: str, params: Params) -> float:
        p_word = self.words.get(word, 0.0) / self.total
        p_letters = math.exp(self.letters_logp(word))
        mixed = params.lam * p_word + (1.0 - params.lam) * p_letters
        return math.log(mixed) if mixed > 0.0 else -math.inf

    def score(self, text: str, params: Params) -> float:
        core = self.core(text)
        if not core:
            return -math.inf
        # Hyphenated words are scored part by part ("санкт-георген").
        parts = [p for p in core.split("-") if p]
        if not parts:
            return -math.inf
        total = sum(self._word_logp(p, params) for p in parts)
        # Punctuation around a word ("hello.") is fine, but less likely
        # than a clean word: charge one unseen letter per stripped char.
        stripped = len(text) - len(core)
        return total - stripped * self.unseen_penalty


def path_commands() -> frozenset[str]:
    """Executables in $PATH (lowercase letters only, 2+ chars)."""
    names: set[str] = set()
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        try:
            for entry in os.listdir(directory or "."):
                if len(entry) >= 2 and re.fullmatch(r"[a-z]+", entry):
                    names.add(entry)
        except OSError:
            continue
    return frozenset(names)


def normalize(text: str, lang: str) -> str:
    text = text.lower()
    return text.replace("ё", "е") if lang == "ru" else text


class Detector:
    """Flip/keep verdicts for a word typed in one layout of a pair."""

    def __init__(
        self,
        models: dict[str, LangModel],
        params: Params | None = None,
        commands: frozenset[str] = frozenset(),
    ):
        self.models = models  # lang -> model
        self.params = params or Params()
        self.commands = commands

    @classmethod
    def for_layouts(
        cls,
        layout_a: str,
        layout_b: str,
        params: Params | None = None,
        data_dir: Path | None = None,
        commands: frozenset[str] | None = None,
    ) -> "Detector | None":
        """Build a detector, or None when a layout has no word list."""
        models: dict[str, LangModel] = {}
        for layout in (layout_a, layout_b):
            lang = language_for(layout)
            if lang in models:
                continue
            try:
                models[lang] = LangModel.load(lang, data_dir)
            except (FileNotFoundError, OSError):
                return None
        return cls(models, params, path_commands() if commands is None else commands)

    def supports(self, layout: str) -> bool:
        return language_for(layout) in self.models

    def score(self, layout: str, text: str) -> float:
        lang = language_for(layout)
        return self.models[lang].score(normalize(text, lang), self.params)

    def decide(
        self,
        cur_layout: str,
        cur_text: str,
        other_layout: str,
        other_text: str,
        deliberate_case: bool = False,
        extra_margin: float = 0.0,
    ) -> bool:
        """True if the keystrokes read better in the other layout.

        ``cur_text``/``other_text`` are the same keystrokes rendered in each
        layout (case preserved).
        """
        if not cur_text or deliberate_case:
            return False
        if not (self.supports(cur_layout) and self.supports(other_layout)):
            return False
        if any(c.isdigit() for c in cur_text + other_text):
            return False
        if _blocked_by_symbols(cur_text, other_text):
            return False

        cur_lang, other_lang = language_for(cur_layout), language_for(other_layout)
        cur_norm = normalize(cur_text, cur_lang)
        other_norm = normalize(other_text, other_lang)
        if cur_lang == "en" and self.models["en"].core(cur_norm) in self.commands:
            return False

        cur_core = self.models[cur_lang].core(cur_norm)
        other_core = self.models[other_lang].core(other_norm)
        if len(cur_core) == 1 or len(other_core) == 1:
            # A single letter: flip only when it is a word in the other layout
            # and not in this one ("d" -> "в", but "a" stays). An initial
            # ("R.", "E.") is a capital letter plus a period: never flipped.
            if len(cur_text) > 1 and cur_text[0].isupper() and cur_text.endswith("."):
                return False
            if len(cur_core) != 1 or len(other_core) != 1:
                return False

            def is_word(lang: str, t: str) -> bool:
                return t in SINGLE_LETTER_WORDS.get(lang, ())

            return is_word(other_lang, other_core) and not is_word(cur_lang, cur_core)

        lead = self.score(other_layout, other_text) - self.score(cur_layout, cur_text)
        return lead > self.params.threshold + extra_margin
