# BaseScout 🔎

**An AI DeFi research analyst for the Base network.**

![BaseScout Demo Screenshot](https://raw.githubusercontent.com/shriyashsoni/BaseScout/main/static/demo.png)

Point it at any token — a ticker, a name, or a `0x` contract address — and BaseScout
investigates it live: pulling real market data and on-chain facts, running a
deterministic risk engine, and writing an honest, plain-English research brief.

Built for the **Orion Builder Hackathon**.

> ⚠️ Not financial advice. BaseScout produces heuristic research to help you DYOR — it does not tell you what to buy.

---

## What it does

Given a token, BaseScout autonomously:

1. **Resolves** a name/ticker to a Base contract address (DexScreener search).
2. **Fetches live market data** — price, liquidity, 24h volume, FDV, pair age, across every Base pair.
3. **Reads on-chain facts** — contract bytecode, ERC-20 decimals, total supply — straight from a Base RPC node (no third-party indexer).
4. **Scores risk** deterministically — liquidity depth, volume/liquidity churn (wash-trading tell), liquidity-vs-FDV (rug surface), pair age, venue concentration.
5. **Writes a research brief** with Claude — a TL;DR verdict, the risk band, the numbers that matter, and what to watch.

The AI is the *analyst*; the numbers are *ground truth*. The model reasons over
real tool results — it never invents data.

## Why it's different

- **Real work, verifiable.** Every claim traces back to a live tool call, shown in the UI's agent trace.
- **Keyless core.** The market + on-chain + risk engine needs **zero API keys** — it runs against public DexScreener and Base RPC endpoints. Only the AI write-up needs a Claude key.
- **Base-native.** Purpose-built for Base pairs and Base RPC, not a generic multi-chain wrapper.
- **Honest by design.** The risk engine is rule-based and reproducible, so the agent can't hand-wave away red flags.

---

## Architecture

```
                 ┌─────────────────────────────┐
   user query →  │  agent.py  (Claude Opus 4.8) │  manual tool-use loop
                 │  adaptive thinking + tools   │
                 └───────────────┬─────────────┘
                                 │ calls tools
        ┌────────────────────────┼───────────────────────────┐
        ▼                        ▼                            ▼
 search_tokens          compute_risk_signals         get_onchain_token_info
 (DexScreener)           (risk.py — rules)             (Base JSON-RPC)
        │                        │                            │
        └──────── data_sources.py: DexScreener + Base RPC ────┘
                     (free, keyless public endpoints)
```

| File | Role |
|---|---|
| `basescout/data_sources.py` | Keyless data: DexScreener market data + Base RPC on-chain reads (raw `eth_call`, no web3 dependency). |
| `basescout/risk.py` | Deterministic rule-based risk scoring. |
| `basescout/agent.py` | Claude tool-use loop (`claude-opus-4-8`, adaptive thinking). |
| `cli.py` | Command-line interface. |
| `app.py` | FastAPI backend with SSE streaming of the agent trace. |
| `static/index.html` | Single-page demo UI. |

---

## 🚀 Deployment (Render)

BaseScout is ready to be deployed on Render for free:
1. Connect your GitHub repository to [Render](https://render.com/).
2. Create a new **Web Service**.
3. It will automatically detect the `render.yaml` Blueprint or the `Procfile`.
4. Go to the service **Environment** settings and add your `ANTHROPIC_API_KEY`.
5. Deploy!

---

## Quick start

```bash
# 1. Install
pip install -r requirements.txt

# 2. Configure (only needed for the AI write-up)
cp .env.example .env
#   then paste your key from https://console.anthropic.com/  into ANTHROPIC_API_KEY

# 3a. Run the web app  →  http://127.0.0.1:8000
uvicorn app:app --reload

# 3b. …or the CLI
python cli.py "AERO"
python cli.py 0x940181a94A35A4569E4529A3CDfB74e38FD98631

# 3c. …or the keyless risk engine (no API key required)
python cli.py --signals 0x940181a94A35A4569E4529A3CDfB74e38FD98631
```

### Example (keyless, live data)

```
$ python cli.py --signals 0x940181a94A35A4569E4529A3CDfB74e38FD98631

MODERATE RISK  (score 14/100)
Token: AERO — Aerodrome

Signals:
  🟢 Adequate liquidity: $39,042,482 pooled across 30 pair(s).
  🟡 Low liquidity-to-FDV: Liquidity is 4.8% of FDV.
  🟢 Established pair: Oldest pair is ~1070 days old.
```

---

## Configuration

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | for AI reports | — | Claude API key. |
| `BASESCOUT_MODEL` | no | `claude-opus-4-8` | Claude model. |
| `BASE_RPC_URL` | no | `https://mainnet.base.org` | Base mainnet RPC (swap in Alchemy/Infura if rate-limited). |

---

## Data sources

- **DexScreener** (`api.dexscreener.com`) — market data, keyless.
- **Base mainnet RPC** (`mainnet.base.org`) — on-chain reads via `eth_call` / `eth_getCode`, keyless.
- **Anthropic Claude** — the reasoning/write-up layer.

## Roadmap ideas

- Top-holder concentration & LP-lock checks (via a Base indexer).
- Honeypot / sell-tax simulation.
- Wallet portfolio analysis and multi-token watchlists.
- Telegram/Discord bot front-end.

## License

MIT — see [LICENSE](LICENSE).
