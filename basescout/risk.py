"""Deterministic risk signals for a Base token.

This is intentionally *rule-based*, not AI. It gives the agent (and the UI) a
set of hard, reproducible signals to reason about, so the final assessment is
grounded in numbers rather than vibes. The LLM layer interprets these; it does
not invent them.

Not financial advice — these are heuristics, not guarantees.
"""

from __future__ import annotations

import time

from . import data_sources


def compute_risk_signals(token_address: str) -> dict:
    """Combine market + on-chain data into scored risk flags.

    Returns a dict with a 0-100 risk score (higher = riskier), a coarse band,
    and a list of individual signals each tagged low/medium/high.
    """
    market = data_sources.get_token_market_data(token_address)
    onchain = data_sources.get_onchain_token_info(token_address)

    signals: list[dict] = []

    def flag(level: str, title: str, detail: str) -> None:
        signals.append({"level": level, "title": title, "detail": detail})

    # ── contract existence ──
    if not onchain.get("is_contract"):
        flag("high", "No contract bytecode", "Address has no deployed code on Base — likely an EOA or wrong address.")

    # ── market presence ──
    if not market.get("found"):
        flag("high", "No liquidity pools found", "Token has no tradeable Base pairs on DexScreener.")
        return _finalize(token_address, market, onchain, signals)

    liq = market.get("total_liquidity_usd") or 0
    vol = market.get("total_volume_24h_usd") or 0
    fdv = market.get("fdv_usd") or 0
    pairs = market.get("pairs") or []

    # ── liquidity depth ──
    if liq < 5_000:
        flag("high", "Very low liquidity", f"Only ${liq:,.0f} pooled — trades will slip hard and exit may be impossible.")
    elif liq < 50_000:
        flag("medium", "Thin liquidity", f"${liq:,.0f} pooled — meaningful slippage on larger trades.")
    else:
        flag("low", "Adequate liquidity", f"${liq:,.0f} pooled across {len(pairs)} pair(s).")

    # ── volume / liquidity ratio (churn) ──
    if liq > 0:
        ratio = vol / liq
        if ratio > 20:
            flag("high", "Extreme volume vs liquidity", f"24h volume is {ratio:.0f}x liquidity — possible wash trading or a pump.")
        elif ratio > 5:
            flag("medium", "High turnover", f"24h volume is {ratio:.1f}x liquidity — unusually active.")

    # ── liquidity vs FDV (rug surface) ──
    if fdv > 0 and liq > 0:
        liq_ratio = liq / fdv
        if liq_ratio < 0.01:
            flag("high", "Liquidity tiny vs valuation", f"Pooled liquidity is {liq_ratio*100:.2f}% of FDV (${fdv:,.0f}) — large paper cap, little real backing.")
        elif liq_ratio < 0.05:
            flag("medium", "Low liquidity-to-FDV", f"Liquidity is {liq_ratio*100:.1f}% of FDV.")

    # ── age ──
    created = market.get("pairs", [{}])[0].get("pair_created_at")
    if created:
        age_days = (time.time() * 1000 - created) / 86_400_000
        if age_days < 2:
            flag("high", "Brand-new pair", f"Oldest pair is ~{age_days:.1f} day(s) old — no track record.")
        elif age_days < 14:
            flag("medium", "Young pair", f"Oldest pair is ~{age_days:.0f} days old.")
        else:
            flag("low", "Established pair", f"Oldest pair is ~{age_days:.0f} days old.")

    # ── single-pair concentration ──
    if len(pairs) == 1:
        flag("medium", "Single trading venue", "Only one pair exists — no market redundancy if it's pulled.")

    return _finalize(token_address, market, onchain, signals)


def _finalize(token_address, market, onchain, signals) -> dict:
    weights = {"high": 34, "medium": 14, "low": 0}
    score = min(100, sum(weights[s["level"]] for s in signals))
    if score >= 67:
        band = "HIGH RISK"
    elif score >= 34:
        band = "ELEVATED RISK"
    elif score >= 14:
        band = "MODERATE RISK"
    else:
        band = "LOWER RISK"

    return {
        "token_address": token_address,
        "risk_score": score,
        "risk_band": band,
        "signals": signals,
        "market_snapshot": {
            "symbol": market.get("symbol"),
            "name": market.get("name"),
            "price_usd": market.get("price_usd"),
            "total_liquidity_usd": market.get("total_liquidity_usd"),
            "total_volume_24h_usd": market.get("total_volume_24h_usd"),
            "fdv_usd": market.get("fdv_usd"),
            "pair_count": market.get("pair_count"),
        },
        "onchain_snapshot": {
            "is_contract": onchain.get("is_contract"),
            "decimals": onchain.get("decimals"),
            "total_supply": onchain.get("total_supply"),
        },
        "disclaimer": "Heuristic signals only. Not financial advice. Always DYOR.",
    }
