# bagrank promoter

Python process that posts Hyperliquid crowd-hold snapshots from the same Neon tables as [bagrank.xyz](https://bagrank.xyz). Separate GitHub repo, separate Railway service. It does not write to the collectors or the website.

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
| Claude Haiku 4.5 | ~25% of punchy posts, ~400 in / 80 out tokens at $1 / $5 per MTok | **$0.0008 when used**, ~$0.00015 averaged across board posts |
| X | 1 media upload + 1 create tweet | $0 extra under plan quota |

Quote post:

| Piece | What happens | $ |
|---|---|---|
| Neon | none if last board is cached in `bagrank_promoter_state` | $0 |
| X search | 1 recent-search, `max_results=10` | $0 extra under plan quota |
| X quote | 1 create tweet, no image | $0 extra |
| Claude | never | $0 |

At 8 posts/day × ~5.3 board + ~2.7 quote: **about $0.001–0.003/day in Claude**, Neon in the noise, X = your existing plan. Monthly Claude ≈ **$0.03–0.10**.

The X plan is the real cost: quote-reposts need **read + recent search**. If search is 403, quotes pause 24h and the account stays on board posts only.

## Bot vs person

- Intervals are triangular + extra jitter, not a 2h timer
- Source line is omitted ~30% of board posts and ~65% of quotes
- Claude only rewrites words and is rejected if it changes a number
- Rank lists stay templates (more useful, $0)
- Quote filter drops airdrops, CAs, t.me, follow-me, new/tiny accounts, signal-group names, shill hashtag dumps, and authors already quoted in 3 days
- State lives in Neon (`bagrank_promoter_state` on the PnL DB) so a Railway restart does not double-post

## Railway

Root of this folder. Start: `python -m promoter`

```
python -m promoter --once --dry-run
```

## Env

- `NEON_PNL` — PnL Neon (required)
- `NEON_BAGRANK` — ROI Neon (optional, for ROI / PnL+ROI)
- `X_API_KEY` `X_API_SECRET` `X_ACCESS_TOKEN` `X_ACCESS_TOKEN_SECRET`
- `ANTHROPIC_API_KEY` — optional
- `X_USER` — default `johnyi0x` (never quote yourself)
