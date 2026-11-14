#!/usr/bin/env python3
"""Scrub a Kane NDJSON run so it is safe to commit: home paths, share-link tokens.

usage: scrub_fixture.py <in.ndjson> <out.ndjson>
"""
import json
import re
import sys

HOME = re.compile(r"/home/[A-Za-z0-9_.-]+")
SHARE = re.compile(r"/dashboard/share/[A-Za-z0-9_]+")
KEYLIKE = re.compile(r"\b(LT_[A-Z_]+|LTAK[A-Za-z0-9]{10,}|sk-[A-Za-z0-9]{16,})\b")


def scrub(text: str) -> str:
    text = HOME.sub("/home/user", text)
    text = SHARE.sub("/dashboard/share/SCRUBBED", text)
    return text


def main(src: str, dst: str) -> None:
    out = []
    for line in open(src, encoding="utf-8"):
        line = line.rstrip("\n")
        if not line.strip():
            continue
        line = scrub(line)
        if KEYLIKE.search(line):
            raise SystemExit("credential-like string found; refusing to write")
        json.loads(line)  # still valid JSON
        out.append(line)
    with open(dst, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
