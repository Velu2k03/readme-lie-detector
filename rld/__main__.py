import argparse
import sys

from . import check as chk
from . import llm


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="rld")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="verify README claims against a running app")
    c.add_argument("--url", required=True)
    c.add_argument("--readme", required=True)
    c.add_argument("--out", default="report/")
    c.add_argument("--lock", default="claims.lock.json")
    c.add_argument("--confirm", action="store_true", help="re-run a red claim once before calling it false")
    a = ap.parse_args(argv)
    try:
        return chk.check(a.url, a.readme, a.out, a.lock, a.confirm)
    except llm.LLMLimit as e:
        print(f"Claude usage limit: {e}", file=sys.stderr)
        return 4
    except llm.LLMError as e:
        print(f"LLM error: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
