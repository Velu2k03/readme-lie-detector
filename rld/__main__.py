import argparse
import sys

from . import check as chk
from . import gate as gt
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
    g = sub.add_parser("gate", help="cheap check loop for the Stop hook (exit 0/1/3/4)")
    g.add_argument("--url", required=True)
    g.add_argument("--readme", required=True)
    g.add_argument("--out", default="report/")
    g.add_argument("--lock", default="claims.lock.json")
    g.add_argument("--app-dir", default="demo-app/", help="where the app code lives (used in the fix hint)")
    g.add_argument("--failed-first", action="store_true", help="run claims that were red last time first")
    g.add_argument("--stop-on-red", action="store_true", help="stop at the first red claim")
    g.add_argument("--confirm", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "gate":
            return gt.gate(a.url, a.readme, a.out, a.lock, a.app_dir, a.failed_first, a.stop_on_red, a.confirm)
        return chk.check(a.url, a.readme, a.out, a.lock, a.confirm)
    except llm.LLMLimit as e:
        print(f"Claude usage limit: {e}", file=sys.stderr)
        return 4
    except llm.LLMError as e:
        print(f"LLM error: {e}", file=sys.stderr)
        return 4
    except Exception as e:  # a crash is infra (exit 4), never a red claim (exit 1)
        print(f"rld crashed: {type(e).__name__}: {e}", file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
