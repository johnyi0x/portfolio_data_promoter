# bagrank promoter

Python process that posts Hyperliquid crowd-hold snapshots from the same Neon tables as [bagrank.xyz](https://bagrank.xyz). Separate GitHub repo, separate Railway service. It does not write to the collectors or the website.

## What a post is supposed to do

The image has to stand on its own after X compresses it. The caption has to make a trader want the live board, not look like a bot dumping a metric.

**Image**

- Title names the coin (`$SUI hold share`)
- Legend with color swatches and end values (`$SUI 6.0%` / `$NEAR 17.5%`)
- Max 3 series, focus coin drawn thickest
- Axis ticks, hour labels, and `bagrank.xyz` in ~24–34px type so they survive the feed

**Caption (2–4 lines)**

1. Hook — sentence case, `$TICKER`, what changed
2. Meaning — share of top-N wallets, one vote each, not a whale tracker (once, not every time)
3. Last line `bagrank.xyz` (or `/?ranker=roi` / `both`) — never `source:`

Bad: `$sui hold 2.0% → 6.0% in 18 hours.` / `the 7d pnl crowd been adding.` / `source: bagrank.xyz`

Better:

```
$SUI just tripled on the board — 2.0% → 6.0% in 18 hours.

That's the share of Hyperliquid's top 200 (7d PnL) sitting in it. One wallet, one vote.

bagrank.xyz
```

Templates own the numbers. Claude (Haiku) only rearranges words on ~40% of board posts, and is dropped if it changes a figure or sounds like a bot.

## Cadence

About every **2–3 hours**, jittered, never on `:00`. Cap **8 posts / UTC day**. Pattern:

1. Board post (chart from Neon)
2. Board post
3. Quote a real trending post about a high bagrank pair (filtered)
4. Repeat

~8% of slots are left empty on purpose. After a quote, the next wait is a bit longer.

## Cost (estimate, Sep 2026)

Board post (typical):

| Piece | What happens | $ |
|---|---|---|
| Neon | 2 SELECTs on PnL (4 if ROI/combined), then disconnect | ~$0.00001 |
| PNG | Pillow on the box | $0 |
| Claude Haiku 4.5 | ~40% of punchy posts, ~500 in / 120 out tokens at $1 / $5 per MTok | **~$0.001 when used**, ~$0.0003 averaged across board posts |
| X | 1 media upload + 1 create tweet | $0 extra under plan quota |

Quote post:

| Piece | What happens | $ |
|---|---|---|
| Neon | none if last board is cached in `bagrank_promoter_state` | $0 |
| X search | 1 recent-search, `max_results=10` | $0 extra under plan quota |
| X quote | 1 create tweet, no image | $0 extra |
| Claude | never | $0 |

At 8 posts/day × ~5.3 board + ~2.7 quote: **about $0.002–0.005/day in Claude**, Neon in the noise, X = your existing plan. Monthly Claude ≈ **$0.06–0.15**.

The X plan is the real cost: quote-reposts need **read + recent search**. If search is 403, quotes pause 24h and the account stays on board posts only.

## X Keys & Tokens (ignore most of that page)

The Keys & Tokens tab has **three** groups. This process uses **OAuth 1.0a user context** only (`tweepy.OAuth1UserHandler`). Bearer and OAuth 2.0 cannot post media as your account here.

### Put these four in env — the **OAuth 1.0 Keys** block

| What you click | Two values you get | Env |
|---|---|---|
| Consumer Key → **Regenerate** | **Consumer Key** and **Consumer Secret** | `X_API_KEY` / `X_API_SECRET` |
| Access Token under **OAuth 1.0 Keys** → **Regenerate** | **Access Token** and **Access Token Secret** | `X_ACCESS_TOKEN` / `X_ACCESS_TOKEN_SECRET` |

That OAuth 1.0 Access Token row should say **For @yourhandle** and **Read and write**. After you switch accounts, regenerate **that** token so it is issued for the new handle.

Consumer Key is the same thing as “API Key”. Consumer Secret is the same thing as “API Secret”. You only see the secrets at regenerate time — copy both immediately.

### Do not put these in env

| On the page | Why |
|---|---|
| Bearer Token (App-Only Authentication) | App-only. Cannot tweet as you. |
| OAuth 2.0 Client ID | Different auth system. |
| OAuth 2.0 Client Secret | Different auth system. |
| OAuth 2.0 Access Token (scopes like `tweet.write`, “Refresh token active”) | User token for OAuth 2. Regenerating it does nothing for this bot. |

Two “Access Token / Regenerate” buttons is the trap: the **upper** one (under OAuth 1.0 Keys, next to Consumer Key) is what we use. The **lower** one (under OAuth 2.0 Keys, with the scope chips) is not.

## Railway

Root of this folder. Start: `python -m promoter`

```
python -m promoter --once --dry-run
```

## Env

- `NEON_PNL` — PnL Neon (required)
- `NEON_BAGRANK` — ROI Neon (optional, for ROI / PnL+ROI)
- `X_API_KEY` `X_API_SECRET` `X_ACCESS_TOKEN` `X_ACCESS_TOKEN_SECRET` — OAuth 1.0a only
- `ANTHROPIC_API_KEY` — optional
- `X_USER` — default `johnyi0x` (never quote yourself)
