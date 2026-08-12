"""Runtime configuration for BaseScout.

Loads settings from environment variables (optionally via a local `.env`).
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Anthropic
ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY") or None
MODEL: str = os.getenv("BASESCOUT_MODEL", "claude-opus-4-8")

# Base network
BASE_RPC_URL: str = os.getenv("BASE_RPC_URL", "https://mainnet.base.org")
BASE_CHAIN_ID: str = "base"  # DexScreener chain identifier

# HTTP
REQUEST_TIMEOUT: int = 20  # seconds
USER_AGENT: str = "BaseScout/0.1 (+https://github.com/)"


def require_api_key() -> str:
    """Return the Anthropic API key or raise a friendly error."""
    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and add your key "
            "(get one at https://console.anthropic.com/)."
        )
    return ANTHROPIC_API_KEY
