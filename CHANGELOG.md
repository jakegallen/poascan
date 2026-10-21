# Changelog

All notable changes to POAScan. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## Stability policy

- The HTTP API lives under `/api/v1`. Unversioned `/api/...` paths are permanent aliases with the same responses.
- Within v1, changes are additive only: new endpoints, new fields, new headers. No field is removed, renamed or retyped.
- Breaking changes ship only under `/api/v2`, announced here and in `llms.txt` before release. v1 keeps running alongside.
- MCP tool names, inputs and existing result fields follow the same rule.

## [1.3.0] - 2026-10-20

### Changed (swaps coming soon)

- `/tx` for swap txs: To shows the offer maker, Amount shows POA for the wanted asset with what the taker gets after the fee, and new Offer and Payment rows show the pair with its network logo, offer status, and the external payment linked to its explorer (Solscan, Basescan or Etherscan).
- `/swaps` is a live preview until launch: the main button is a greyed "Coming soon" (aria-disabled, with a slow gold sweep that stops under prefers-reduced-motion). Buy/Sell, pairs, amounts, Rate, Fee, the stat row, order book, price chart and Add Emblem Wallet all stay. The upgrade note and the "check back" hint are gone, so the status is said once.
- The safety line under the button now reads "Never send payment outside the network." on one line, and Self-custody sits on the same row as Add Emblem Wallet.
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

[1.3.0]: https://github.com/jakegallen/poascan/compare/v1.2.0...v1.3.0
[1.2.0]: https://github.com/jakegallen/poascan/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/jakegallen/poascan/releases/tag/v1.1.0
[1.0.0]: https://github.com/jakegallen/poascan/commit/3e706fb
