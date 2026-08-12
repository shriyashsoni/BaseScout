"""The BaseScout agent: a Claude-driven DeFi research analyst for Base.

Runs a manual tool-use loop so we get full control over the trace (useful for
the UI and for showing judges the agent's real work). The model decides which
tools to call; our code executes them against live Base data and feeds results
back until the model produces a final report.
"""

from __future__ import annotations

import json
from typing import Any, Callable

import anthropic

from . import config, data_sources, risk

SYSTEM_PROMPT = """\
You are BaseScout, a sharp, sceptical DeFi research analyst specialising in the \
Base network (Coinbase's Ethereum L2).

Your job: given a token, a contract address, or a research question, investigate \
using the provided tools and produce a clear, honest research brief for a retail \
crypto user who is NOT an expert.

How you work:
- Always ground claims in tool data. If you didn't fetch it, don't assert it.
- Prefer calling `compute_risk_signals` for any specific token — it bundles \
market + on-chain data and returns hard, reproducible risk flags. Call the \
narrower tools only when you need extra detail.
- If the user gives a name/ticker rather than an address, use `search_tokens` \
first to resolve it, then confirm which token you analysed (symbol + address).
- Be concrete about numbers (liquidity, volume, FDV, age) and what they imply.
- Call out risks plainly. Low liquidity, brand-new pairs, wash-trading patterns, \
and huge FDV vs tiny liquidity are red flags. Say so.

Output format (Markdown):
1. **TL;DR** — 2-3 sentence verdict, and the token you analysed (symbol + short address).
2. **Risk assessment** — the risk band + score, and the top signals in plain English.
3. **Market & on-chain snapshot** — key numbers as a short bullet list.
4. **What to watch** — 2-4 concrete things a user should check or monitor.

End every report with: *"Not financial advice — always do your own research."*

Be direct and readable. No hype, no filler. If data is missing or the token \
looks like a scam, say that clearly."""


# ── Tool schemas exposed to the model ────────────────────────────────────

TOOLS: list[dict] = [
    {
        "name": "search_tokens",
        "description": "Search Base-network tokens/pairs by name, ticker, or partial address. Returns candidate tokens with symbol, address, price and liquidity. Use to resolve a name to a contract address.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search, e.g. 'AERO' or 'aerodrome'."}
            },
            "required": ["query"],
        },
    },
    {
        "name": "compute_risk_signals",
        "description": "Primary tool. For a specific token contract address on Base, returns a bundled risk report: 0-100 risk score, risk band, individual flags, plus a market and on-chain snapshot. Prefer this for any token analysis.",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string", "description": "The token's Base contract address (0x...)."}
            },
            "required": ["token_address"],
        },
    },
    {
        "name": "get_token_market_data",
        "description": "Detailed DexScreener market data for a token address on Base: every pair, price, liquidity, 24h volume, FDV, price changes. Use for deeper market detail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string", "description": "The token's Base contract address (0x...)."}
            },
            "required": ["token_address"],
        },
    },
    {
        "name": "get_onchain_token_info",
        "description": "Raw on-chain facts for a token address on Base: whether it's a contract, bytecode size, ERC-20 decimals, and total supply. Use to confirm a contract is real.",
        "input_schema": {
            "type": "object",
            "properties": {
                "token_address": {"type": "string", "description": "The token's Base contract address (0x...)."}
            },
            "required": ["token_address"],
        },
    },
]

# Map tool names to the Python callables that execute them.
_TOOL_IMPLS: dict[str, Callable[..., Any]] = {
    "search_tokens": lambda query: data_sources.search_tokens(query),
    "compute_risk_signals": lambda token_address: risk.compute_risk_signals(token_address),
    "get_token_market_data": lambda token_address: data_sources.get_token_market_data(token_address),
    "get_onchain_token_info": lambda token_address: data_sources.get_onchain_token_info(token_address),
}


def _run_tool(name: str, tool_input: dict) -> Any:
    impl = _TOOL_IMPLS.get(name)
    if impl is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return impl(**tool_input)
    except data_sources.DataError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - surface any failure to the model
        return {"error": f"{type(exc).__name__}: {exc}"}


def analyze(query: str, max_turns: int = 8, on_event: Callable[[dict], None] | None = None) -> dict:
    """Run the agent on a user query.

    Args:
        query: token name/ticker/address or a research question.
        max_turns: safety cap on the agentic loop.
        on_event: optional callback for streaming progress events
                  ({"type": "tool_call"|"tool_result"|"final", ...}).

    Returns a dict with the final ``report`` (Markdown) and the ``trace``.
    """
    client = anthropic.Anthropic(api_key=config.require_api_key())

    messages: list[dict] = [{"role": "user", "content": query}]
    trace: list[dict] = []

    def emit(event: dict) -> None:
        if on_event:
            on_event(event)

    for _turn in range(max_turns):
        response = client.messages.create(
            model=config.MODEL,
            max_tokens=4096,
            thinking={"type": "adaptive"},
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                emit({"type": "tool_call", "name": block.name, "input": block.input})
                result = _run_tool(block.name, dict(block.input))
                trace.append({"tool": block.name, "input": dict(block.input), "result": result})
                emit({"type": "tool_result", "name": block.name, "result": result})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, default=str),
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        # No more tool calls — extract the final text.
        report = "".join(b.text for b in response.content if b.type == "text").strip()
        emit({"type": "final", "report": report})
        return {"report": report, "trace": trace, "stop_reason": response.stop_reason}

    fallback = "Analysis stopped: reached the maximum number of research steps without a final answer."
    emit({"type": "final", "report": fallback})
    return {"report": fallback, "trace": trace, "stop_reason": "max_turns"}
