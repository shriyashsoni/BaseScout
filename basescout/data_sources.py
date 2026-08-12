"""Data sources for BaseScout.

Everything here uses **free, keyless** public endpoints:

* DexScreener  — market data (price, liquidity, volume, FDV) for Base pairs.
* Base mainnet JSON-RPC — on-chain facts (contract bytecode, ERC-20 decimals,
  total supply) fetched with plain `eth_call`, no web3 dependency.

These functions return plain dicts/lists so they can be handed straight back to
the model as tool results, or rendered in a UI.
"""

from __future__ import annotations

import requests

from . import config

_DEX_BASE = "https://api.dexscreener.com/latest/dex"

# ERC-20 function selectors (first 4 bytes of keccak256 of the signature).
_SEL_DECIMALS = "0x313ce567"      # decimals()
_SEL_TOTAL_SUPPLY = "0x18160ddd"  # totalSupply()


class DataError(Exception):
    """Raised when an upstream data source fails or returns garbage."""


def _headers() -> dict[str, str]:
    return {"User-Agent": config.USER_AGENT, "Accept": "application/json"}


# ────────────────────────────── DexScreener ──────────────────────────────

def _summarize_pair(pair: dict) -> dict:
    """Reduce a raw DexScreener pair to the fields we care about."""
    liq = pair.get("liquidity") or {}
    vol = pair.get("volume") or {}
    change = pair.get("priceChange") or {}
    txns = pair.get("txns") or {}
    base = pair.get("baseToken") or {}
    quote = pair.get("quoteToken") or {}
    return {
        "dex": pair.get("dexId"),
        "pair_address": pair.get("pairAddress"),
        "url": pair.get("url"),
        "base_token": {"address": base.get("address"), "symbol": base.get("symbol"), "name": base.get("name")},
        "quote_token": {"address": quote.get("address"), "symbol": quote.get("symbol")},
        "price_usd": _to_float(pair.get("priceUsd")),
        "liquidity_usd": _to_float(liq.get("usd")),
        "volume_24h_usd": _to_float(vol.get("h24")),
        "volume_6h_usd": _to_float(vol.get("h6")),
        "price_change_24h_pct": _to_float(change.get("h24")),
        "price_change_1h_pct": _to_float(change.get("h1")),
        "txns_24h": _sum_txns(txns.get("h24")),
        "fdv_usd": _to_float(pair.get("fdv")),
        "market_cap_usd": _to_float(pair.get("marketCap")),
        "pair_created_at": pair.get("pairCreatedAt"),
    }


def _base_pairs(pairs: list[dict] | None) -> list[dict]:
    """Keep only Base-network pairs, best liquidity first."""
    pairs = pairs or []
    base_only = [p for p in pairs if p.get("chainId") == config.BASE_CHAIN_ID]
    summarized = [_summarize_pair(p) for p in base_only]
    summarized.sort(key=lambda p: p.get("liquidity_usd") or 0, reverse=True)
    return summarized


def search_tokens(query: str, limit: int = 8) -> list[dict]:
    """Search DexScreener for tokens/pairs on Base matching a free-text query."""
    try:
        resp = requests.get(
            f"{_DEX_BASE}/search",
            params={"q": query},
            headers=_headers(),
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise DataError(f"DexScreener search failed: {exc}") from exc

    results = _base_pairs(data.get("pairs"))
    return results[:limit]


def get_token_market_data(token_address: str) -> dict:
    """Fetch all Base market pairs for a specific token address."""
    addr = token_address.strip()
    try:
        resp = requests.get(
            f"{_DEX_BASE}/tokens/{addr}",
            headers=_headers(),
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise DataError(f"DexScreener token lookup failed: {exc}") from exc

    pairs = _base_pairs(data.get("pairs"))
    if not pairs:
        return {"token_address": addr, "found": False, "pairs": []}

    total_liq = sum(p.get("liquidity_usd") or 0 for p in pairs)
    total_vol = sum(p.get("volume_24h_usd") or 0 for p in pairs)
    top = pairs[0]
    return {
        "token_address": addr,
        "found": True,
        "symbol": top["base_token"].get("symbol"),
        "name": top["base_token"].get("name"),
        "price_usd": top.get("price_usd"),
        "fdv_usd": top.get("fdv_usd"),
        "market_cap_usd": top.get("market_cap_usd"),
        "total_liquidity_usd": total_liq,
        "total_volume_24h_usd": total_vol,
        "pair_count": len(pairs),
        "pairs": pairs,
    }


# ────────────────────────────── Base RPC ──────────────────────────────

def _rpc_call(method: str, params: list) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        resp = requests.post(
            config.BASE_RPC_URL,
            json=payload,
            headers={**_headers(), "Content-Type": "application/json"},
            timeout=config.REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        body = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise DataError(f"Base RPC call failed ({method}): {exc}") from exc

    if "error" in body:
        raise DataError(f"Base RPC error ({method}): {body['error']}")
    return body


def _eth_call(to: str, data: str) -> str:
    body = _rpc_call("eth_call", [{"to": to, "data": data}, "latest"])
    return body.get("result", "0x")


def get_onchain_token_info(token_address: str) -> dict:
    """Read on-chain facts for a token: is-contract, decimals, total supply.

    Uses raw eth_call so there's no ABI/web3 dependency. Fields that can't be
    read (e.g. a non-standard token) come back as null rather than erroring.
    """
    addr = token_address.strip()

    # 1) Is there deployed bytecode at this address?
    code = _rpc_call("eth_getCode", [addr, "latest"]).get("result", "0x")
    is_contract = bool(code and code not in ("0x", "0x0"))

    info: dict = {
        "token_address": addr,
        "is_contract": is_contract,
        "bytecode_size_bytes": max(0, (len(code) - 2) // 2) if code else 0,
        "decimals": None,
        "total_supply_raw": None,
        "total_supply": None,
    }
    if not is_contract:
        return info

    # 2) decimals()
    try:
        dec_hex = _eth_call(addr, _SEL_DECIMALS)
        if dec_hex and dec_hex != "0x":
            info["decimals"] = int(dec_hex, 16)
    except DataError:
        pass

    # 3) totalSupply()
    try:
        ts_hex = _eth_call(addr, _SEL_TOTAL_SUPPLY)
        if ts_hex and ts_hex != "0x":
            raw = int(ts_hex, 16)
            info["total_supply_raw"] = raw
            if info["decimals"] is not None:
                info["total_supply"] = raw / (10 ** info["decimals"])
    except DataError:
        pass

    return info


# ────────────────────────────── helpers ──────────────────────────────

def _to_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sum_txns(bucket) -> int | None:
    if not isinstance(bucket, dict):
        return None
    buys = bucket.get("buys") or 0
    sells = bucket.get("sells") or 0
    try:
        return int(buys) + int(sells)
    except (TypeError, ValueError):
        return None
