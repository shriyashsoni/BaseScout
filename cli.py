"""BaseScout command-line interface.

Usage:
    python cli.py "AERO"
    python cli.py 0x940181a94A35A4569E4529A3CDfB74e38FD98631
    python cli.py "is this token safe? 0x..."

    # Skip the AI layer and just print the raw rule-based risk signals:
    python cli.py --signals 0x940181a94A35A4569E4529A3CDfB74e38FD98631
"""

from __future__ import annotations

import argparse
import json
import sys

# Windows consoles default to cp1252, which chokes on emoji / em-dashes.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass

from basescout import agent, risk


def _print_event(event: dict) -> None:
    etype = event.get("type")
    if etype == "tool_call":
        print(f"  ↳ calling {event['name']}({json.dumps(event['input'])})", file=sys.stderr)
    elif etype == "tool_result":
        res = event["result"]
        note = res.get("risk_band") if isinstance(res, dict) else None
        print(f"    ✓ {event['name']} returned" + (f" [{note}]" if note else ""), file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="BaseScout — AI DeFi research analyst for Base.")
    parser.add_argument("query", help="Token name, ticker, contract address, or a question.")
    parser.add_argument("--signals", action="store_true",
                        help="Print raw rule-based risk signals only (no AI, no API key needed). "
                             "Requires a contract address.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args()

    if args.signals:
        result = risk.compute_risk_signals(args.query)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _print_signals(result)
        return 0

    try:
        print("BaseScout is researching…\n", file=sys.stderr)
        result = agent.analyze(args.query, on_event=_print_event)
    except RuntimeError as exc:  # missing API key
        print(f"\nError: {exc}", file=sys.stderr)
        print("Tip: run with --signals <address> to use the keyless risk engine.", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print("\n" + result["report"])
    return 0


def _print_signals(result: dict) -> None:
    print(f"\n{result['risk_band']}  (score {result['risk_score']}/100)")
    snap = result["market_snapshot"]
    if snap.get("symbol"):
        print(f"Token: {snap.get('symbol')} — {snap.get('name')}")
    print("\nSignals:")
    for s in result["signals"]:
        marker = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(s["level"], "•")
        print(f"  {marker} {s['title']}: {s['detail']}")
    print(f"\n{result['disclaimer']}")


if __name__ == "__main__":
    raise SystemExit(main())
