#!/usr/bin/env python3
"""Build relayout/data/<lang>.txt.gz from hermitdave/FrequencyWords.

    scripts/build-wordlists.py en ru           # downloads, filters, writes
    scripts/build-wordlists.py --src DIR en    # use DIR/<lang>_50k.txt

Output format: one "word count" per line, lowercase, letters of the
language's alphabet only, `ё` folded into `е` for Russian. Source data is
OpenSubtitles 2018 via FrequencyWords, CC BY-SA 4.0 (see relayout/data/README.md).
"""
import argparse
import gzip
import re
import urllib.request
from collections import Counter
from pathlib import Path

URL = "https://raw.githubusercontent.com/hermitdave/FrequencyWords/master/content/2018/{l}/{l}_50k.txt"
ALPHABETS = {
    "en": re.compile(r"^[a-z]{2,}$"),
    "ru": re.compile(r"^[а-я]{2,}$"),
}
OUT = Path(__file__).resolve().parent.parent / "relayout" / "data"


def build(lang: str, src: Path | None) -> int:
    if src:
        text = (src / f"{lang}_50k.txt").read_text(encoding="utf-8")
    else:
        text = urllib.request.urlopen(URL.format(l=lang)).read().decode("utf-8")
    pattern = ALPHABETS[lang]
    counts: Counter[str] = Counter()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[1].isdigit():
            continue
        word = parts[0].lower()
        if lang == "ru":
            word = word.replace("ё", "е")
        if pattern.match(word):
            counts[word] += int(parts[1])
    OUT.mkdir(parents=True, exist_ok=True)
    with gzip.open(OUT / f"{lang}.txt.gz", "wt", encoding="utf-8", compresslevel=9) as f:
        for word, count in counts.most_common():
            f.write(f"{word} {count}\n")
    return len(counts)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("langs", nargs="+", choices=sorted(ALPHABETS))
    ap.add_argument("--src", type=Path)
    args = ap.parse_args()
    for lang in args.langs:
        print(lang, build(lang, args.src), "words")
