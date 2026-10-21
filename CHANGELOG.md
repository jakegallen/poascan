# Changelog

All notable changes to POAScan. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## Stability policy

- The HTTP API lives under `/api/v1`. Unversioned `/api/...` paths are permanent aliases with the same responses.
- Within v1, changes are additive only: new endpoints, new fields, new headers. No field is removed, renamed or retyped.
- Breaking changes ship only under `/api/v2`, announced here and in `llms.txt` before release. v1 keeps running alongside.
- MCP tool names, inputs and existing result fields follow the same rule.

## [1.3.0] - 2026-10-20

### Added
- `/api/v1/swaps/status`: swap availability (`available`, `state` available or upgrading, `last_good_read`, `last_attempt_status`, `open_offers`). Built from POAScan's scheduled read of minepoa.com/api/swaps; no extra upstream calls.
- `swaps` block (same shape) in `/api/v1/summary` and the `get_network_summary` MCP tool; `swaps_status` in `list_swap_offers`.
- `SwapStatus` schema in `openapi.json`; `swapsStatus` in `openapi-gpt.json`.
- `/swaps` shows "Swaps are being upgraded. Check back soon." when the last read failed or swaps data is older than 15 minutes.

- `/start`: one copy-ready "Start mining PoA" prompt (Emblem Wallet install, register, answer, mine, vault link per go.md) and short numbered steps with copy buttons. `/join` and `/onboarding` serve the same page. In the sitemap, `llms.txt` and `llms-full.txt`, with HowTo JSON-LD.
- MCP tools `get_swap_status` (available or being upgraded, last good read, open offers) and `get_onboarding_steps` (same content as `/start`). 16 tools in total.
- FAQ pages: `/what-is-proof-of-agent`, `/how-to-mine-poa`, `/how-to-buy-poa`, `/what-is-poascan`, with FAQPage JSON-LD. Linked from `/about` and the footer; in the sitemap and llms files.
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
