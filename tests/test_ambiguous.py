"""Words that are real in both layouts (`of` / `ща`) follow the sentence."""
import json

import pytest

from relayout.buffer import TypedTextBuffer
from relayout.detect import Detector
from relayout.keymap import LayoutPair

from .test_autocorrect import make, type_text, word_and_space  # noqa: F401
from .test_autocorrect import detector, pair  # noqa: F401  (fixtures)


def flips(d, buf, pair, layout, sentence):
    """Type `sentence` on `layout` and return whether its last word flips."""
    chunk, spaces = word_and_space(buf, pair, layout, sentence)
    return d.should_flip(chunk, layout, *pair.render(chunk, layout))


# --- what counts as "real in both layouts" ----------------------------

def test_ambiguity_comes_from_the_word_lists(detector):
    assert detector.ambiguous("us", "of", "ru", "ща")
    assert detector.ambiguous("ru", "ща", "us", "of")
    # not words in the other layout: never ambiguous, so they keep flipping
    assert not detector.ambiguous("ru", "щл", "us", "ok")
    assert not detector.ambiguous("us", "ghbdtn", "ru", "привет")
    assert not detector.ambiguous("us", "hello", "ru", "руддщ")


# --- the sentence decides ----------------------------------------------

def test_russian_sentence_keeps_ща_even_with_a_rule_towards_of(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.store.words["of"] = "us"                    # a rule tipped towards "of"
    assert not flips(d, buf, pair, "ru", "Окей, ща")


def test_english_sentence_keeps_of_even_with_a_rule_towards_ща(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.store.words["ща"] = "ru"                    # a rule tipped towards "ща"
    assert not flips(d, buf, pair, "us", "House of")


def test_context_survives_an_auto_correction(pair, detector, tmp_path):
    """`Jrtq` is fixed to `Окей`; the next word is still in a Russian sentence."""
    d, buf, fx = make(pair, detector, tmp_path)
    chunk, spaces = word_and_space(buf, pair, "us", "Jrtq")
    assert d.auto_correct(chunk, spaces)
    assert buf.context_layout == "ru"
    d.store.words["of"] = "us"
    assert not flips(d, buf, pair, "ru", "ща")


def test_context_is_forgotten_with_the_line(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    type_text(buf, pair, "ru", "Окей, ")
    buf.clear()                                   # Enter, click, idle...
    d.store.words["of"] = "us"
    assert flips(d, buf, pair, "ru", "ща")        # no context: the rule decides


def test_ambiguous_word_at_line_start_uses_rules_and_detector(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.store.words["ща"] = "ru"
    assert not flips(d, buf, pair, "ru", "ща")    # learned: stays Russian
    buf.clear()
    d.store.words.clear()
    assert flips(d, buf, pair, "ru", "ща")        # no context, no rule: frequency wins


def test_typing_in_a_new_layout_is_not_overridden(pair, detector, tmp_path):
    """Russian sentence, then you switch to English on purpose for `of`."""
    d, buf, fx = make(pair, detector, tmp_path)
    type_text(buf, pair, "ru", "Окей, ")
    assert not flips(d, buf, pair, "us", "of")    # `of` is far likelier than `ща`


# --- non-words keep flipping, in any context ----------------------------

@pytest.mark.parametrize("layout,typed", [
    ("ru", "щл"),       # "ok" typed on the Russian layout
    ("us", "ghbdtn"),
    ("ru", "руддщ"),
])
def test_non_words_still_flip_after_context(pair, detector, tmp_path, layout, typed):
    d, buf, fx = make(pair, detector, tmp_path)
    assert flips(d, buf, pair, layout, typed)
    buf.clear()
    type_text(buf, pair, layout, "привет " if layout == "ru" else "hello ")
    assert flips(d, buf, pair, layout, typed)


def test_ds_flips_on_its_own_and_in_a_russian_sentence(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    assert flips(d, buf, pair, "us", "ds")            # вы
    buf.clear()
    type_text(buf, pair, "ru", "Привет, ")
    assert flips(d, buf, pair, "us", "ds")            # typed in en inside a ru sentence


# --- learning a neutral rule ---------------------------------------------

def test_contradicting_rules_become_a_keep_rule(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.store.words["ща"] = "ru"                    # "ща" stays Russian
    for _ in range(2):                            # you flip "ща" -> "of" by hand twice
        buf.clear()
        d.last = None
        type_text(buf, pair, "ru", "ща")
        d.correct()
    assert d.store.is_kept("of") and d.store.is_kept("ща")
    assert "ща" not in d.store.words and "of" not in d.store.words
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["keep"] == ["of", "ща"]
    # and neither is ever auto-flipped again, in either layout
    buf.clear()
    assert not flips(d, buf, pair, "ru", "ща")
    buf.clear()
    assert not flips(d, buf, pair, "us", "of")


def test_a_single_direction_stays_a_normal_rule(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    for _ in range(2):
        buf.clear()
        d.last = None
        type_text(buf, pair, "ru", "ща")
        d.correct()
    assert d.store.words == {"of": "us"} and d.store.keep == []


def test_non_words_never_become_keep_rules(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    d.store.words["щл"] = "ru"
    for _ in range(2):
        buf.clear()
        d.last = None
        type_text(buf, pair, "ru", "щл")
        d.correct()
    assert d.store.keep == [] and d.store.words.get("ok") == "us"


def test_keep_and_rm_commands(pair, detector, tmp_path):
    d, buf, fx = make(pair, detector, tmp_path)
    assert d.handle_command("rules keep of") == "ok"
    assert sorted(d.store.keep) == ["of", "ща"]
    assert sorted(json.loads(d.handle_command("status"))["keep"]) == ["of", "ща"]
    assert d.handle_command("rules rm of") == "ok"
    assert d.store.keep == []


def test_known_trade_off_ds_in_an_english_sentence_is_kept(pair, detector, tmp_path):
    """`ds` is in the English list, so inside an English sentence it is a word.

    Pinned on purpose: on its own or after a Russian word it flips (see above).
    """
    d, buf, fx = make(pair, detector, tmp_path)
    type_text(buf, pair, "us", "hello ")
    assert not flips(d, buf, pair, "us", "ds")
