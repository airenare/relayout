#!/usr/bin/env python3
"""Measure the detector on real text.

    scripts/eval.py en wiki-en.txt            # English text, typed on `us`
    scripts/eval.py ru wiki-ru.txt [--threshold 4]

Every word (surrounding punctuation stripped, digits skipped) is tested twice:
typed on its own layout it must be kept, typed on the other layout it must
flip. Prints false flips and misses with the most frequent offenders.
Any plain-text file works; random Wikipedia intros are a good, independent
corpus (the word lists come from film subtitles). Keys are mapped through the
real XKB layouts, exactly as the daemon sees them.
"""
import argparse
import collections
from pathlib import Path

from relayout.detect import Detector, Params, deliberate_case
from relayout.keymap import LayoutPair

LAYOUT_OF = {"en": "us", "ru": "ru"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("lang", choices=sorted(LAYOUT_OF))
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--threshold", type=float, default=Params().threshold)
    ap.add_argument("--show", type=int, default=10)
    args = ap.parse_args()

    pair = LayoutPair("us", "ru")
    layout = LAYOUT_OF[args.lang]
    other = pair.other(layout)
    detector = Detector.for_layouts(
        "us", "ru", Params(threshold=args.threshold), commands=frozenset()
    )

    index = {}
    for kc in sorted(pair.table_for(layout)):
        for lv, ch in enumerate(pair.table_for(layout)[kc]):
            if ch:
                index.setdefault(ch, (kc, lv))

    def on_other_layout(token: str) -> str | None:
        out = []
        for ch in token:
            key = index.get(ch)
            chars = pair.table_for(other).get(key[0]) if key else None
            if not chars or key[1] >= len(chars) or not chars[key[1]]:
                return None
            out.append(chars[key[1]])
        return "".join(out)

    n = false_flips = misses = 0
    ff, ms = collections.Counter(), collections.Counter()
    strip = ".,;:!?()«»\"'[]—–"
    for path in args.files:
        for raw in path.read_text(encoding="utf-8").split():
            token = raw.strip(strip)
            if not token or any(c.isdigit() for c in token):
                continue
            wrong = on_other_layout(token)
            if wrong is None or wrong == token:
                continue
            deliberate = deliberate_case([c.isupper() for c in token], token, wrong)
            n += 1
            if detector.decide(layout, token, other, wrong, deliberate):
                false_flips += 1
                ff[token] += 1
            if not detector.decide(other, wrong, layout, token, deliberate):
                misses += 1
                ms[token] += 1
    print(f"{args.lang}: {n} words, threshold {args.threshold}")
    print(f"  false flips (typed right, flipped): {false_flips} ({false_flips / n:.2%})")
    print(f"  misses (typed wrong, kept):         {misses} ({misses / n:.2%})")
    print("  false flips:", ff.most_common(args.show))
    print("  misses:", ms.most_common(args.show))


if __name__ == "__main__":
    main()
