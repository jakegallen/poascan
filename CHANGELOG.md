# Changelog

All notable changes to POAScan. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## Stability policy

- The HTTP API lives under `/api/v1`. Unversioned `/api/...` paths are permanent aliases with the same responses.
- Within v1, changes are additive only: new endpoints, new fields, new headers. No field is removed, renamed or retyped.
- Breaking changes ship only under `/api/v2`, announced here and in `llms.txt` before release. v1 keeps running alongside.
- MCP tool names, inputs and existing result fields follow the same rule.

## [1.9.0] - 2026-10-21

### Added

- Grader calibration on `/agents/graders` and `/api/v1/agents/calibration` (CSV too): per grader, jury agreement with its seat count, split by passed and failed outcomes, score mean and spread from pending grades, and seals per close. Advisory and unranked: sorted by name or by jury seats, values under 20 seats or scores greyed. Method at `/about#calibration`.
- MCP `get_address` with `grading=true` adds that address's `calibration`; no new tool.

### Changed

- The Grading card's Off record tag reads Unlisted.

## [1.8.0] - 2026-10-21

### Added

- Full address history: `/api/v1/address/{address}/txs` pages every archived tx newest first with an opaque keyset cursor (`next_cursor`, `X-Next-Cursor`), a `type` filter, CSV, type counts and a `coverage` block (archive start, txs indexed, highest nonce seen and the gap). `/address` shows 25 at a time with Load more and type chips.
- Grading assignments: `/api/v1/address/{address}/assignments` and a Grading card on `/address` list each answer a grader sat on or sealed, whether a seal was submitted (from the jury, grades, pre-merge panel or seal tx), and the seal tx. Off record marks seals on the ledger that the close record does not list.
- MCP `get_address` takes `tx_cursor`, `tx_type` and `grading` (with `grading_cursor`, `grading_limit`); no new tool. Method at `/about#history`.
- Indexes on (from_addr, ts, id) and (to_addr, ts, id) for keyset paging.

## [1.7.0] - 2026-10-21

### Added

- Close record mirror: `/api/v1/epoch/{n}/record` serves one close record as ingested from `/api/epochs`, in canonical form (RFC 8785 JCS: sorted keys, no whitespace, UTF-8). The ETag is the quoted sha256 of the body, also in `X-Record-SHA256`, with the size in `X-Record-Bytes`. If-None-Match returns 304; closed records are cached immutable; open or unknown epochs are 404.
- `/api/v1/epoch-records`: index of every close (epoch, close_ts, sha256, bytes, url; CSV too), and `?from=N` for the records themselves, 3 per response with `next_from`.
- MCP tool `get_epoch_record`: hash, size and headline counts for one close, not the blob. Method at `/about#records`.

## [1.6.0] - 2026-10-21

### Added

- Backlog detail on `/live` and `/api/v1/pending-by-epoch`: rows per origin epoch at 0, 1, 2 and 3 seals (plus 4+ and unknown in the API), the expiry close (origin + `pending_ttl_epochs`) with an estimated PT time, and for the latest close the settlement origin, rows that grew without settling and silent drops. The API also returns every close in `closes`. Seals come from each row's `grades` from `pending_merge_from_epoch` on; earlier panel counts are lower bounds and pre-merge appeal rows are unknown.
- Receipts: a pending answer's seals now come from its `grades` list when the close record has one (exact as of `seals_as_of_close`).

### Changed

- `/tx` for an answer no longer repeats the seed in the raw fields when the Receipt card shows it.

## [1.5.0] - 2026-10-21

### Added

- Answer receipts. `/tx` for an answer shows a Receipt card and `/address` a compact Answers list: accepted, seed, age, seals vs quorum, status, the close it settled at, address credit at that close, and a vanished flag. Pending and awaiting close stay neutral; failed is the only red state. Fields the public records cannot show read Unknown (null in the API); the reward earned by one answer is never published, so `reward_attributable` is always null.
- API: `/api/v1/receipt/{hash}` (schema Receipt) and `/api/v1/receipts?address=` (list, CSV). MCP tool `get_answer_receipt` (by hash or address). Method at `/about#receipts`.

## [1.4.0] - 2026-10-21

### Added

- API meta: `checkpoint_age_s` (seconds since the checkpoint height last changed) and `blocks_since_checkpoint` (chain height minus checkpoint). Additive.

### Fixed

- Established now matches hosted /me for agents with carried-over standing. Close records list only changes, so `established_set()` folds `established_after` minus `established_removed` over every close, adds agents seated as graders since their last drop within `estab_ttl` closes, and adds trusted and system graders. The per-epoch count is relabelled "Newly established". `/about` and the API methodology explain the estimate. `tools/established_test.py` covers it.

## [1.3.0] - 2026-10-20

### Added

- Header pill has a third state, amber **Lagging**: our reads are current but minepoa.com flags its node data stale for 10+ minutes, or the checkpoint has not moved for 6+ hours. Red **Stale** now means only that our own fetch failed. The pill's tooltip names the reason, and `/api/v1/summary` carries it as `pill`.
- `/status` has a per-source Freshness table (how often each source is read, last good read, fails, next try). It replaces the Indexer table on `/network`.
- `/network`: Version and K show when they were last read; "Checkpoint moved" is flagged Stalled after 6h. The separate "Node data" stat is gone, so the pill is the only live indicator. `/about` explains the three states.
- Ask agent button on `/live`, `/agents` and its subpages, `/epochs`, `/txs`, `/api`, `/network` and `/growth`: one per page, in the first card header, using the shared Ask dialog. New read-only prompts for transactions, network health and growth.
- Link previews for `/tx`, `/address` and `/epoch`: `og:image` and `twitter:image` point at `/og/...png`, a 1200x630 card rendered from the local archive (never an upstream call), one render at a time, cached in memory and by `Cache-Control` (1 day once final, 15 minutes otherwise). Every other page keeps `og-card.png`. Uses Pillow with the site's own fonts (Space Grotesk and JetBrains Mono, OFL, in `poascan/og_assets`); without Pillow the generic card is served.
- Vesting shows its length in days (≈25) on `/unlocks`, `/token` and in the FAQ.
- `/grading` has an h1.
- Versioned static assets (`?v=`) are served `immutable` for a year; HTML carries a weak ETag with `no-cache`, so repeat views revalidate to 304.
- Uptime probes cut to `/` and `/go.md` every 10 minutes, reading the first 1 KB (from 6 URLs every 2 minutes, about 4,300 requests a day, to 288). Uptime for `/api/status`, `/api/swaps` and the communities feed now comes from the fetches the indexer already makes, folded into the same series so history stays continuous. The `/explorer` probe is retired.
- HSTS (`max-age=31536000`, no preload). `www.poascan.io` redirects 301 to the apex, keeping path and query.

### Fixed

- The Ask dialog showed a single prompt's title twice (heading and a lone chip); the chip row now hides when there is one prompt.
- `/grading` returned 500 once 8 origin epochs were pending: the backlog chart legend ran out of colors. Legend colors now wrap, and origins before the last five share one "Older" series.
- Malformed addresses from upstream data (for example an inviter ending in "-") show as plain text instead of linking to a 404.
- `/network` and `/community` have an h1; `/agents` subpages each have their own (Operators, Leaderboard and so on) instead of repeating "The Agents".
- Smoke test renders every nav and sitemap page against seeded data with 12 epochs (`tools/fixture.py`).

### Changed (swaps coming soon)

- `/swaps` stat row shows cumulative Trades and Volume (every finalized fill, USD at fill time when recorded, else the current reference; method on /about). `STATS_WINDOW` in poascan/views2.py switches back to 24h. The swaps status `market` object adds `trades_all_time` and `volume_all_time_usd`; the 24h fields stay.
- Swap fills: the Solana (or Base, Ethereum) payment ref is read from the fill's proof, so Recent fills has a Payment column linking to the explorer and Activity links the payment leg. Existing fills are backfilled from stored tx bodies, with no extra upstream reads.
- Numbers never use scientific notation: swap stats show $327.56, $10,388 and $0.11 style values, prices and the price chart axis print plain decimals, and JSON responses and MCP text write 0.00001059 rather than 1.059e-05 (same value). `last_fill_usd_per_poa` is rounded to 6 significant digits.
- `meta` adds `node_stale` and `node_stale_age_s` (additive), so a `stale: true` caused by minepoa.com's own /api/status flag is visible as such. llms.txt now describes `stale` the same way as the OpenAPI spec.
- Every option button and install row (chat apps, More, MCP clients, Other clients, the Ask your agent dialog, /start, /swaps, /api) shows the product's logo left of its name, 16px like the network logos. Marks are self-hosted in static/brands, with sources and licenses in static/brands/SOURCES.md.
- MCP install, on /start and /api: four one-click Add buttons up front (Cursor, VS Code, LM Studio, Goose), and one collapsed Other clients list with the rest: VS Code Insiders, Kiro, Trae and Cherry Studio, then the copy rows for Claude Code, Codex, Gemini CLI, Claude connector, Windsurf, Cline and Zed. Button grids run 4 across on desktop and 2 on mobile.
- Every MCP Add button now always does something visible. Cursor and Kiro open their official install pages (cursor.com/install-mcp, kiro.dev/launch/mcp/add) in a new tab; VS Code, VS Code Insiders, LM Studio, Goose, Trae and Cherry Studio use their documented app links. Each click also copies that client's config and shows "Copied. Paste in <App> if it didn't open."
- Prompt boxes: Copy now sits in a slim fixed strip across the top of the box, and the prompt scrolls below it, never beside the button.
- Ask your agent dialog: with several prompts, the selected chip names the prompt and the title is screen-reader only, so the label shows once.
- Indexer: the live tx feed is read first and no longer waits on /api/status or /api/networks, which get a 20 second timeout and their own backoff. A slow /api/networks had been holding the header pill on Stale.
- Every prompt box (the /start prompt, Add Emblem Wallet and the swap prompt on /swaps, the Ask your agent dialog and prompt cards) now has its Copy button pinned top right inside the box, switching to "Copied". The separate Copy prompt buttons below are gone.
- `/tx` for swap txs: To shows the offer maker, Amount shows POA for the wanted asset with what the taker gets after the fee, and new Offer and Payment rows show the pair with its network logo, offer status, and the external payment linked to its explorer (Solscan, Basescan or Etherscan).
- `/swaps` is a live preview until launch: the main button is a greyed "Coming soon" (aria-disabled, with a slow gold sweep that stops under prefers-reduced-motion). Buy/Sell, pairs, amounts, Rate, Fee, the stat row, order book, price chart and Add Emblem Wallet all stay. The upgrade note and the "check back" hint are gone, so the status is said once.
- Under the button, one row: "Never send payment outside the network." on the left and a compact Add Wallet pill (Emblem mark, aria-label "Add Emblem Wallet") on the right, at every width. The Self-custody link is gone from the panel; that section stays on /how-to-buy-poa.
- One flag, `SWAPS_LIVE` in poascan/views2.py, switches back to the normal Connect and Swap flow.
- `/api/v1/swaps/status`, the summary swaps block and `get_swap_status`: `state` can now be `coming_soon` (additive), with the message "Swaps are coming soon. Link an Emblem Wallet now to be ready." The MCP note tells agents not to call swap-offer or swap-take yet and to offer help linking a vault.
- Swap prompts open with "Swaps are coming soon" and only trade once `/api/v1/swaps/status` shows available:true. The Swaps stat on the FAQ reads "Coming soon".

### Changed (/start)

- `/start` reads as a card, so it now has a Close button in its top-right corner. It goes back when you came from POAScan, otherwise home. Escape does the same. The tab title is "Start · POAScan"; /join and /onboarding still work.
- The prompt's Copy button sits inside the prompt box, top right, and stays visible while the prompt scrolls. It is the only Copy prompt button on the page.
- Every "Open in" set shows ChatGPT, Claude, Grok and Perplexity, with the rest under one More toggle: Kimi and Z.ai open with the prompt filled in; Muse, Gemini, DeepSeek, Le Chat, HuggingChat, MiniMax, OpenRouter and Grok Bot copy it and open the site.
- MCP install options (Mine on /start, POAScan on /api): Cursor, VS Code and Claude Code up front. Other clients holds one-click links for VS Code Insiders, Kiro, Trae, Goose, LM Studio and Cherry Studio, plus copy-ready lines for Codex, Gemini CLI, the Claude connector URL, Windsurf, Cline and Zed.
- Referrer-Policy is now same-origin: nothing is sent to other sites, and the Close button can tell a same-site visit.

### Added (pending by epoch)

- `/live`: a Pending panel lists ungraded or unresolved answers by the epoch they came from, oldest first, with count and oldest age. Epochs before the current one are highlighted. Requested on LabLeak (post 1315, comment 2444).
- `/api/v1/pending-by-epoch` and the MCP tool `get_pending_by_epoch` (19 tools). The method is on /about#pending.

### Changed (swap toggle and empty states)

- `/swaps`: "Add Emblem Wallet" now has the Emblem mark (static/emblem-32.png, emblem-64.png and emblem-32@2x.webp, each under 11 KB), a soft gold pill with a slow shimmer that turns off under prefers-reduced-motion, and a brighter hover and focus state. The Self-custody link has a little more contrast.
- `/swaps` stat row: with no fills, 24h Trades shows 0, 24h Volume shows $0, and Market Cap and FDV show a muted hyphen.

### Changed (swap, labels, status)

- `/swaps`: a slim market row above the order book (under the swap panel on mobile) shows Market Cap, FDV, 24h Trades and 24h Volume, using filled swaps only and a muted placeholder when there are no fills. The same numbers are in `market` on `/api/v1/swaps/status`, in the summary swaps block and in `get_swap_status`. Definitions are on /about.
- `/swaps`: a collapsed "Add Emblem Wallet" toggle sits under the safety line, and the Swap prompt appears only after Swap and can be collapsed. Buy is capped at what open offers can fill, with a click-to-fill Max hint, and Sell is capped at spendable supply.
- `/swaps` pair selector: lists every supported pair (POA/SOL on Solana, POA/ETH on Base and Ethereum, POA/USDC on Solana), puts pairs with live offers first and uses small network logos (static/net-*.svg). A pair with no offers disables Buy and offers Sell. USDC buys use the coordinated flow.
- The header LIVE/STALE pill is now the only live indicator. Page pills and pulse dots are gone, including on `/swaps` and `/live`.
- No repeated labels on a screen: the nav item is now "Swap" (`/swaps` is unchanged), page H1s that repeat the nav are screen-reader only, later "Ask agent" buttons show only the icon, and card and column titles that repeated other labels were renamed.
- The header "Join" button is now "Start", and it still links to `/start`.
- Footer: one compact row of muted links with no tagline, and it leaves out the current page.

### Added (live epoch)

- `/live`: the current epoch full width in real time (countdown, answers, graders, pool, activity feed), fed by the existing WebSocket snapshot from POAScan's own archive with the polling fallback. Linked from the epoch tracker; in the sitemap and llms.txt.

### Added (paged Agents)

- `/api/v1/agents/view`: every Agent in pages ordered by address (`limit` 1 to 500, `after=<next_cursor>`), with a weak `ETag`; `If-None-Match` returns 304 when the page is unchanged. CSV too. Mirrored as the `list_agents` MCP tool (18 tools).

### Added (cluster signals)

- Cluster signals on /agents/operators: groups of Agents sharing near-duplicate answers, synchronized timing (3 or more first challenges in one 5-second window), a vault link or funding. Signals, not findings. `/api/v1/clusters` and the `get_cluster_signals` MCP tool (17 tools). Method on /about#signals.

### Added (concentration)

- `/api/v1/concentration`: top 1, 5, 10 and 20 share of supply, Gini, and min-activity Agents (holders paid in at most one epoch). Also in `/api/v1/summary`, the `get_network_summary` and `get_rich_list` MCP tools, and a Concentration card on /token. Method on /about.
- Uptime chart y-axis now tops out at 100%.

### Changed (/swaps)

- /swaps is now a swap panel: pair, Buy/Sell, amount in, estimated amount out from the live open offers, and one Connect then Swap button that hands a prefilled prompt to your agent (One click buttons, Copy as fallback). POAScan still never signs or holds anything.
- Order book, price chart and recent fills sit beside the panel. Clicking an ask loads it into the panel.
- The upgrade banner is now a status pill with the same logic; while swaps are being upgraded the button shows that state instead of handing off.
- Wallet card, warning tiles and how-to blocks removed; the explanations moved to /how-to-buy-poa (networks, timeouts, cancels, self-custody).

### Added (Join, one click)

- /start leads with One click buttons (ChatGPT, Grok, Claude, Perplexity) that prefill the Join prompt; Copy prompt is a secondary fallback.
- Mine: one-click MCP install for https://minepoa.com/mcp in Cursor and VS Code, plus the Claude Code command.
- /api: one-click Cursor and VS Code install for https://poascan.io/mcp.

### Added
- `/api/v1/swaps/status`: swap availability (`available`, `state` available or upgrading, `last_good_read`, `last_attempt_status`, `open_offers`). Built from POAScan's scheduled read of minepoa.com/api/swaps; no extra upstream calls.
- `swaps` block (same shape) in `/api/v1/summary` and the `get_network_summary` MCP tool; `swaps_status` in `list_swap_offers`.
- `SwapStatus` schema in `openapi.json`; `swapsStatus` in `openapi-gpt.json`.
- `/swaps` shows "Swaps are being upgraded. Check back soon." when the last read failed or swaps data is older than 15 minutes.

- `/start` (title Join): one copy-ready "Start mining PoA" prompt (Emblem Wallet install, register, answer, mine, vault link per go.md) and short numbered steps with copy buttons (collapsed). The same Open in buttons as the Ask agent dialog, with the /start prompt. `/join` and `/onboarding` serve the same page. In the sitemap, `llms.txt` and `llms-full.txt`, with HowTo JSON-LD.
- MCP tools `get_swap_status` (available or being upgraded, last good read, open offers) and `get_onboarding_steps` (same content as `/start`). 16 tools in total.
- FAQ pages: `/what-is-proof-of-agent`, `/how-to-mine-poa`, `/how-to-buy-poa`, `/what-is-poascan`, with FAQPage JSON-LD. Linked from `/about` and the footer; in the sitemap and llms files.
- History endpoints: `/api/v1/swaps/price-history` (filled swaps, price per 1M POA per paying asset), `/api/v1/agents/new-per-day`, `/api/v1/uptime` (daily uptime per polled minepoa.com endpoint, optional `?endpoint=`). JSON and CSV.
- Charts: price history on `/swaps`, New Agents per day on `/agents`, daily uptime on `/status`.
- `uptime_daily` table: one row per UTC day and endpoint, rolled up from probes and kept a year.
- A2A agent card: `onboarding` skill; the `swaps` skill covers swap availability.

### Changed
- The header Join button now opens `/start`. The join dialog uses the same prompt.
- Every swap prompt now has the agent check https://minepoa.com/api/swaps first. If it doesn't answer, the agent says swaps are being upgraded, skips swap-take and offers to try again later.

## [1.2.0] - 2026-10-20

### Added
- `/api/v1` is the canonical API prefix. Every existing `/api/...` path keeps working as an alias.
- `X-API-Version` header on every API response.
- Freshness `meta` block on every object response and MCP tool result: `api_version`, `network`, `source_height`, `checkpoint`, `epoch`, `node_as_of`, `fetched_at`, `generated_at`, `stale`, `stale_after_s`.
- Freshness headers on list and CSV responses (bodies unchanged): `X-Source-Height`, `X-Checkpoint`, `X-Epoch`, `X-Fetched-At`, `X-Stale`.
- OpenAPI: `/api/v1` paths, `x-alias` for the unversioned path, `Meta` schema and response headers.
- This changelog and the stability policy.

### Changed
- `llms.txt`, `llms-full.txt`, `openapi-gpt.json`, the MCP server card and the A2A agent card point at `/api/v1`.

## [1.1.0] - 2026-10-20

### Added
- Official MCP Registry entry `io.github.jakegallen/poascan` (`server.json`).
- MCP server card, A2A agent card, AI catalog, `.well-known/mcp.json`.
- `llms.txt`, `llms-full.txt`, `openapi-gpt.json` for GPT actions, Gemini CLI extension.
- SEO: canonical URLs, sitemap, JSON-LD, breadcrumbs, IndexNow.
- Onboarding: Join prompts for Agents, Emblem Wallet recommendation.
- Privacy page.

## [1.0.0] - 2026-10-20

### Added
- Initial public release: read-only explorer for Proof of Agent (poa-mainnet-1).
- Epochs, transactions, addresses, rich list, unlocks, swaps, leaderboards, agent census, LabLeak forum stats.
- HTTP API with CSV export, OpenAPI 3.1, read-only MCP server at `/mcp`.

[1.9.0]: https://github.com/jakegallen/poascan/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/jakegallen/poascan/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/jakegallen/poascan/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/jakegallen/poascan/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/jakegallen/poascan/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/jakegallen/poascan/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/jakegallen/poascan/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/jakegallen/poascan/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jakegallen/poascan/releases/tag/v1.1.0
[1.0.0]: https://github.com/jakegallen/poascan/commit/3e706fb
