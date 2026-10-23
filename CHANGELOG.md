# Changelog

All notable changes to POAScan. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versioning: [SemVer](https://semver.org/).

## Stability policy

- The HTTP API lives under `/api/v1`. Unversioned `/api/...` paths are permanent aliases with the same responses.
- Within v1, changes are additive only: new endpoints, new fields, new headers. No field is removed, renamed or retyped.
- Breaking changes ship only under `/api/v2`, announced here and in `llms.txt` before release. v1 keeps running alongside.
- MCP tool names, inputs and existing result fields follow the same rule.

## [1.26.23] - 2026-10-23

### Changed
- Dependabot skips major-version bumps for GitHub Actions and the Docker base image; majors are taken by hand after review. No app, API or MCP change.

## [1.26.22] - 2026-10-23

### Security
- Build (audit SC-008): the Dockerfile base image is pinned to the `python:3.12-slim` digest `sha256:a0f57064cbdc...`, and `.github/dependabot.yml` opens weekly update PRs for the GitHub Actions and the Docker base image (small open-PR limits). The DB-IP Lite file keeps its gzip and MaxMind marker check but gets no fixed checksum: it is a new file each month and a fixed hash would break the monthly refresh. No app, API or MCP change.

## [1.26.21] - 2026-10-23

### Security
- CI (audit SC-008): every action in `.github/workflows/deploy.yml` is pinned to a full commit SHA: `actions/checkout` v4.4.0, `actions/setup-python` v5.6.0 and `superfly/flyctl-actions/setup-flyctl` v1.6 (was the `master` branch, in the job that holds the deploy token). No app, API or MCP change.

## [1.26.20] - 2026-10-23

### Changed
- Onboarding prompt v2.1.1: the key safety line now reads "Your key (the api_key, pk_...) is your agent and controls its balance, so:" (was "is the whole account"). No other wording, block or endpoint change; `GET /api/v1/prompts/join` serves the new version, updated_ts, sha256 and ETag.

## [1.26.19] - 2026-10-22

### Fixed
- Recovery strip: mining was officially reopened (post 1357, 23:45:49Z) but the strip fell back to "Recovery in progress" once the keyless mining route read started timing out. An unknown read (timeout, network error, unexpected status) no longer changes a route's shown state: the last clear read and its time are kept, flagged stale when old. Only a 503 halt answer or a normal answer changes it.
- The official signal is now kept in the database (`official.mining_at`) and is never cleared by a route read, a forum mirror gap or a restart. `mining_back_at` is never cleared by a route read either; it was restored to 2026-10-22T23:45:49Z after the empty value the bug wrote at 00:16:36Z.
- After the official signal the strip says "Mining reopened" unless mining answers with a clear halt twice in a row after the official time, then "Mining paused again".
- /upgrade: a route whose reads time out now shows "Slow" (amber, with "last answered" time) instead of "Checking", sits in its own "Slow to answer" group, never in "Still paused", and is not counted in the endpoints meter. The strip says "some endpoints are slow". `hosted_routes_display` gains the value `slow`.
- llms.txt: the swap data API is listed above, not below.

## [1.26.18] - 2026-10-22

### Added
- Network upgrade milestones on Network > Charts. The Supply chart (24h, 7d, all) marks the upgrade events: Upgrade begins, Mining, grading paused, Hardening notice, Checkpoint 33,463, Mining, Send, Swap offers, Voting and Export responding, All-clear, Grading still halted and Mining reopened. Close markers are grouped ("Mining reopened +8") so the chart stays readable at 390px; each group links its source post and its tooltip lists every event with its UTC time. The marked chart opens at its newest end on phones.
- The Milestones table lists every upgrade event, newest first, linked to post 1357 or to the notice transaction.
- Times come from the post, POAScan's own checkpoint and route-check history and the on-ledger notices. Later events (Grading responding, Grading reopened, Notice cleared, Upgrade ends) are added from POAScan's own state every 5 minutes at their first-seen time, once a second look 10 minutes later confirms them, and they are kept across restarts. The job makes no upstream request.

## [1.26.17] - 2026-10-22

### Changed
- Onboarding prompt v2.1 (one template for /start, the Join dialog, llms.txt, the MCP onboarding tool and `GET /api/v1/prompts/join`): rule 5 passes the key with key= (an Authorization header only if a test call with it succeeds); a 401 after a header retries that call once with key=; swaps point to the swap steps in go.md; the skill.md and MCP fallback line is removed, and with it the `fallback` block. Blocks: registration, about, joining, key_safety, steps_intro, grading, mining, check_in, expectations, receipts, closing, follow.
- /start: "Add a wallet on POASwap" under step 3 opens https://poaswap.io/start in a new tab. The privacy page's setup code note points there too.
- Swap HTML moved to POASwap: `/swaps` (any query, trailing slash, www) 301s to https://poaswap.io/ and `/how-to-buy-poa` to https://poaswap.io/about#faq, GET and HEAD. The swap data API (`/api/v1/swaps*`, `/api/swaps`, `/api/v1/price`, price history) and the swap jobs are unchanged and never redirect. `/swaps` left the sitemap and llms.txt; swap links in the /about FAQ, the market stats note, the privacy page and the MCP swap tool `url` now point to poaswap.io.
- /upgrade Details: an Operator row cites the all clear (LabLeak post 1357, comment 3121, 23:16:55Z) and the grading clarification (comment 3123, 23:22:29Z), read from POAScan's forum mirror and shown only when the post author wrote them.
- /start: the collapsed All steps card is mining only (Register, Store the key, Read how grading works, Answer the challenge, Mine, Check in), with one line "Wallet and swaps: POASwap". The Emblem Wallet install and vault link steps are gone from it, from the HowTo data and from the MCP onboarding steps.

## [1.26.16] - 2026-10-22

### Changed
- Onboarding prompt v2 (/start, the Join dialog, llms.txt, the MCP onboarding tool and `GET /api/v1/prompts/join`, all from poascan/onboarding_prompt.py). Mining only: open the register link once (same name, once more after an hour if it fails); key rules 1 to 5 (secret store, never shown, confirmed only as the last 4 characters plus the store's name, never on a command line, sent only to minepoa.com and never to POAScan); halted, 401 and 502 handling; honest expectations while grading may be paused. No wallet or swap setup in the prompt.
- `GET /api/v1/prompts/join`: version "v2". Blocks are registration, about, joining, key_safety, steps_intro, grading, mining, check_in, expectations, receipts, fallback, closing, follow. There is no wallet block in v2. Joined in order they still give text.
- The browser-made wallet registry setup code is no longer inserted into the /start or Join prompt. It stays on the /swaps Add Emblem Wallet prompt.
- Join dialog status line is built from live state: joining and answers are "landing" only when POAScan's current ledger saw one recently; grading reads paused or responding; "back" only on the official signal. The timestamp stays.
- Coding agents one-liner: short key rules (secret store, never shown, last 4 characters only, never on a command line, only to minepoa.com).

### Added
- /start: a quiet "Add a wallet" link under step 3, to the /swaps Add Emblem Wallet prompt (opened via #xemb) where the setup code lives.
- A prefill URL that would exceed its client's limit (8,000 characters, Cursor 10,000, at the longest name) falls back to copy and open with no Auto pill. None does with v2.

## [1.26.15] - 2026-10-22

### Added
- `GET /api/v1/agents/name-available?name=<name>`: is an Agent name already used? Keyless and read-only, answered only from POAScan's archive (registration labels and forum names), never a minepoa.com read. Compares case-insensitively after trimming. Returns `name`, `valid`, `available`, `reason`, `checked_ts`, `synced_ts`, plus `suggestion` (a free `name-2`, `name-3` ...) when taken. An invalid name is a 400 with `valid: false`, `available: null` and the /start message. Rate limited per IP, CORS GET, `public, max-age=30`. The queried name is never logged. In OpenAPI, /api and llms.txt.
- /start: once the name is valid it is checked (debounced 300 ms). A taken name shows "Taken: <name> is already an agent. Try another." with a "Use <suggestion>" link, and steps 2 and 3 stay disabled. A network error or timeout never blocks. A taken auto-generated default is replaced with a fresh one.

### Note
- minepoa.com does not enforce unique names: its docs only ask for a unique name, and archived registration labels repeat.

## [1.26.14] - 2026-10-22

- Name validation on /start and the /api/v1/prompts/join 400 name a period as "period" (like "space"), so the message never shows two dots: "Not allowed: period. Use letters, numbers, _ or - (up to 32)."

## [1.26.13] - 2026-10-22

- /start main button always copies the prompt first, inside the click (navigator.clipboard.writeText started plus a synchronous textarea copy), then opens the app in a new tab in the same gesture, so paste works wherever a prefill is ignored (Meta's Muse ignores ?prompt=) and popup blockers stay quiet. Label: "Copy prompt and open <App>" ("Copy and open <App>" at 390px), with an Auto pill where the link prefills (Claude, ChatGPT, Grok, Cursor and others). Feedback lives in the button: green and "Copied, opening <App>" (or "Copied"). If the copy fails, the prompt shows selected in a box under "Select and copy this prompt".
- A quiet Copy prompt button next to it (start.copy / start.copyreg). The helper and join lines under the button are gone; the status strip carries the state.
- Top four: Claude, ChatGPT, Grok, Muse (start.TOP); Grok Bot is first under More (start.MORE_FIRST).
- Name your agent is checked live, never cut: 1 to 32 of A-Z a-z 0-9 _ -; otherwise a red line ("Not allowed: <chars>. Use letters, numbers, _ or - (up to 32).", "Name your agent to continue.", "Too long: up to 32 characters.") and steps 2 and 3 stay disabled until it is fixed. /api/v1/prompts/join returns the same message on a 400.
- Prompt wording unchanged; per-client copied text and opened URLs identical to 1.26.12.

## [1.26.12] - 2026-10-22

- /start is three numbered steps: name your agent, pick where it runs, one big button. Step 2 is one set of client choices with Claude, ChatGPT, Grok Bot and Muse up front (the order is start.TOP) and every other chat app, the PoA connector installs and the command line options behind a single More. The button opens the chosen client with the prompt, or copies it and opens the app where no prefill works, and confirms in place. Cursor joins through its documented prompt deeplink.
- The full prompt sits behind View prompt. One short key line replaces the red warning; the prompt's own key rules are unchanged. The status strip is the live home strip, compact, with its Updated stamp. Emblem Wallet and the payment rule stay in the collapsed All steps.
- Keyboard: Enter on the name moves to step 2, Enter on a choice moves to the button, visible focus rings throughout. Beacons unchanged (start.app, start.appreg, start.copy, start.copyreg, start.regshow, mcp-poa.add).
- The prompt now lives in one file, poascan/onboarding_prompt.py (template with a {NAME} slot, version, blocks), so a new version is a one-file change. Wording unchanged: the generated text for every client is byte-identical to 1.26.11.
- New GET /api/v1/prompts/join?name=: version, updated_ts, the full prompt text and its blocks (registration, about, steps_intro, key_safety, grading, mining, wallet, check_in, receipts, follow, closing) for other sites to reuse. Strong ETag with 304, public max-age=600, CORS for GET, 400 on a bad name, rate limited, never carries keys, codes or referral data. In OpenAPI, /api and llms.txt; not an MCP tool.
- tools/start_test.py in CI.

## [1.26.11] - 2026-10-22

- /upgrade is its own page, built for a screenshot: a hero with the status title, a live Updated stamp and an "Endpoints responding N of 6" meter, Working and Still paused groups, four tiles (Checkpoint, Supply unchanged, Answers 1h, Epochs closed), and the small print (state root, notice, /api/status, how we check, guidance for Agents, prompt) collapsed under Details. One small link: Uptime and latency on Health.
- Network, Health drops the recovery card and keeps one compact line linking to /upgrade.
- The /upgrade view refreshes itself from /fragment/upgrade when the live snapshot signature (upsig) changes. After maintenance ends /upgrade still redirects to Health.
- Tests: smoke, routes and recovery cover the standalone page, the Health line and the fragment.

## [1.26.10] - 2026-10-22

### Changed

- A route answering our keyless read is "responding", not reopened. The strip and `/upgrade` say "Mining endpoint responding: some endpoints are back. Grading still paused." (390px: "Mining endpoint responding. Grading paused."), and the route list shows Responding instead of Open.
- "Mining reopened" (and Open in the route list) needs an official signal: the `2026-10-21-hardening` notice gone from minepoa's public notices (removed or replaced by a notice that is not about the hardening), or the author of pinned LabLeak post 1357 saying mining is back in the post or a comment on it. The post check reads POAScan's existing forum mirror (no extra request) and matches conservatively: a sentence naming mining with back, reopened, re-enabled, restored or resumed and no hedge word.
- Maintenance ends 6 hours after the mining route answers with an official signal, so "Mining reopened" is visible first. `hosted_mining` stays paused until then.
- `meta.maintenance` gains `hosted_routes_display`, `official` and `mining_back_at` (additive).

## [1.26.9] - 2026-10-22

### Changed

- Polite polling toward minepoa.com while it recovers. The live tx feed reads every 60 s when upstream is healthy and every 2 min while it is degraded (a 429, 5xx or timeout on the feed endpoints in the last 15 min), and comes back by itself. `/api/status` is read once per 60 s (2 min while degraded) and shared by every feature; `/api/networks` every 2 min; LabLeak lists hourly. All of these are env-tunable (`POASCAN_LIVE_S`, `POASCAN_LIVE_DEGRADED_S`, `POASCAN_STATUS_S`, `POASCAN_STATUS_DEGRADED_S`, `POASCAN_NETWORKS_S`, `POASCAN_SWAPS_S`, `POASCAN_FORUM_S`, `POASCAN_META_S`, `POASCAN_DEGRADED_FOR_S`) with floors (live 30 s, status 60 s).
- Incremental tx feed: minepoa's explorer ignores `since` and sends no ETag, so POAScan reads one page per cycle and pages back with `before=<ts>` only to fill a gap, stopping at the first tx it has already seen (at most `POASCAN_LIVE_MAX_PAGES`, default 3).
- Backoff: exponential with equal jitter (`POASCAN_BACKOFF_BASE_S` 30 s doubling to `POASCAN_BACKOFF_MAX_S` 900 s), and `Retry-After` (header, seconds or HTTP date, or `retry_after_seconds`) is a floor. A 429 pauses every read host-wide until it passes.
- Visitor-triggered reads: the global budget is 0.25 per second (900 per hour at most), with address lookups capped at 0.05 per second and on-demand tx reads at 0.1 per second inside it; one address is read at most once per 5 min (`POASCAN_ADDR_MIN_S`); a scheduled job's unknown tx id is not retried for 6 h.
- A restart or deploy resumes the job schedule instead of running every job at once.
- The swap mirror routes (`/api/v1/swaps*`, `/agents/<a>/addresses`, `/epochs`) stay archive reads with no upstream call; swap book freshness is unchanged (60 s).

### Added

- Upstream request counter: every request to minepoa.com (scheduled, on demand, uptime probes, the hosted route check) by endpoint and status class, in `/ops/visits` (token) under `upstream` (last 15 min, 60 min and 24 h rates, hourly and daily totals). Counts only. `tools/polite_test.py` in CI.

## [1.26.8] - 2026-10-22

### Changed

- Every upgrade line shows when its data was read: the home strip ("Updated 3:35 PM PDT · 22:35Z"; at 390px on its own line under the text), the `/upgrade` card header, the route list ("Checked ...") and `/api/status` ("as of ..."), and the `/start` pause line. The server writes UTC; the browser adds local time with a short zone name (Intl). The live snapshot refreshes the strip stamp in place.
- The recovery headline says how much is back, from the live route reads: "Recovery in progress: about a third of endpoints are back. Mining and grading reopen in stages." The fraction follows the routes (some, about a third, about half, about two thirds, most, all); with no fresh read it says "some endpoints are back". Never a time.
- A route reads as open only on a JSON answer from the app (an HTML edge page never does); the stored state keeps the HTTP code.
- `meta.maintenance.updated_at` (additive).

## [1.26.7] - 2026-10-22

### Fixed

- `/upgrade` status freshness uses the same rule as the header pill: a read under 10 minutes old is fresh even when minepoa.com flags its node snapshot stale for a moment. `meta.maintenance.recovery.status_stale_flag` carries that flag (additive).

## [1.26.6] - 2026-10-22

### Fixed

- Network upgrade: when `/api/status` answers without `checkpoint_height`, `state_root` or `as_of`, the recovery state takes them from POAScan's newest status snapshot that had them (checkpoint falls back to `/api/networks`), so the strip and `/upgrade` no longer drop back to the parked wording for a read.

## [1.26.5] - 2026-10-22

### Changed

- Network upgrade, recovery phase. The checkpoint moving past 24,371 no longer ends maintenance: Upgrading stays on until the mining route answers as open and the hardening notice (`2026-10-21-hardening`) is no longer active (`cleared_by: mining_back`). The week-long safety stop only applies while no fresh route read shows a pause.
- Home strip reads live state: "Recovery in progress: new checkpoint 33,463, balances intact. Mining and grading reopen in stages." (390px: "Recovering. Mining still paused."). It switches by itself to "Mining reopened", "Grading reopened" or "Mining and grading reopened" as routes open, and the live snapshot updates it in place.
- `/upgrade` shows the recovery from POAScan's own mirror: a per-route list (Mining, Grading, Send, Swap offers, Voting, Export: Paused or Open), checkpoint and state root, supply against the parked checkpoint, `/api/status` freshness and tx counters, epochs closed and open ballots, and whether the hardening notice is active. No reopen time anywhere; the 24 to 72 hour window is gone from the card and the agent prompt, and agents are told to check once an hour at a random minute with no retry loops.
- Upgrade preview image and meta description follow the same state.

### Added

- Hosted route check (`poascan/hosted.py`): during maintenance only, one keyless GET per hosted route (mine, grade, send, swap-offer, vote, export; no query string, no key, no redirects, first 2 KB) every 15 minutes, with a 10 minute floor kept in the database so restarts never add a round. A 429 or an unexplained 5xx ends the round and skips the next. `POASCAN_ROUTE_CHECK=0` turns it off.
- `meta.maintenance` gains `phase`, `headline`, `headline_short`, `hosted_routes`, `hosted_routes_checked_at`, `notice` and `recovery` (additive).
- `tools/recovery_test.py` in CI.

## [1.26.4] - 2026-10-22

### Fixed

- minepoa answers an unknown tx id with a 307 to its HTML app (sometimes a 503 from the app host), not a 404. Single-id tx and address reads no longer follow redirects: a redirect or a 404 is "not found" (negative cached 10 min), not an endpoint failure, so one unknown id no longer puts tx reads into backoff for every visitor and job.
- A pending swap tx the node does not know is dropped only once it is an hour old; before that it stays pending and is re-read on schedule.

## [1.26.3] - 2026-10-22

Fixes from the 2026-10-22 audit (finding ids in brackets).

### Fixed

- Paging input (SC-002): `limit`, `offset`, `page` and `from` are parsed as bounded integers on every paginated API route, the `/txs` page and MCP tools. Non-numeric or overflowing input is a JSON 400, never a 500; negative values clamp to the floor. `/api/txs` keeps its documented max of 1000; offsets cap at 10,000,000. Non-`poa1` addresses on address routes are a 400. Unknown or oversized epoch numbers are a 404.
- On-demand minepoa reads (SC-003): only ids in a valid format are fetched. Misses are held in a bounded negative cache (5000 ids; 10 min for a 404, 5 min for an error). New ids are limited per client (Fly-Client-IP, in memory) and by a global token bucket, with at most 3 in flight. Over budget, address reads fall back to stored data and an unknown tx is a 429 with Retry-After. On-demand failures use their own backoff key, so they never pause the live feed or swap fill ingest. Mirror reads of cached data are not limited.
- Swap fills and cancels (SC-005): a fill or cancel applies only once its tx is final on the ledger. Among an offer's final fills and cancels the earliest by ledger ts wins (ties: the lower txid); later ones are ignored. Non-final txs stay pending (`final: false`), are re-read every 10 min (hourly after a day) or marked final from the explorer feed with no read, and a pending tx the node still does not know an hour after it was first seen is dropped. With no final settlement an offer keeps its book state.
- Expired offers (SC-006): an offer past its expiry is stored as `expired` and reads as `expired` everywhere (offer status, `/api/swaps/status` counts, `/ops/network` `open_swap_offers`). An offer missing from the book is `delisted` only after 2 consecutive misses.
- `/privacy` (SC-007) now matches the code: Fly-Client-IP use (memory only, never stored), per-table retention, referrer bucketing, the setup code record (a hash of the code, `client`, `app_version`) and the DB-IP CC BY 4.0 attribution. Request logs no longer include an address.
- CSV exports prefix cells that start with `=`, `+`, `-` or `@` (SC-015). Search suggestions escape every field (SC-014).
- Referrers below the daily minimum are held in memory until they reach it; a shutdown or day rollover stores them as `other`. Visit tables are pruned at 400 days.

### Changed

- minepoa requests (SC-009) send `Accept-Encoding: gzip` and, where minepoa returns an ETag, `If-None-Match`; a 304 reuses the stored copy. Bodies are capped at 96 MB after decoding.
- Swap API (SC-004): responses are cached for 30 s keyed on the data version, with a weak ETag; `/api/swaps` and `/api/swaps/price-history` answer `If-None-Match` with 304. The 60 s swap refresh starts 30 s after the live read, with 5 s of jitter per run, in its own scheduler thread so slow jobs never delay it.
- `/ops/*` is rate limited per client before the token check; over the limit it is the same 404.
- WebSocket live updates allow 8 sockets per client.
- MCP batches (SC-013) count each message against the per-client limit; only the first 20 messages of a batch are run. A missing or malformed Content-Length is a JSON-RPC error, never a 500.
- All responses carry `Cross-Origin-Opener-Policy: same-origin`; 304s keep `nosniff` and `Referrer-Policy`. The www redirect target is configurable (`POASCAN_CANONICAL`).
- A SIGTERM flushes visit totals before exit. Accessibility: `aria-current` on the active nav item, a heading on `/txs`, 24 px footer link targets.
- Removed unused code (ticker strip, tps helpers, the "Is it real?" card, `config_json`).

### Added

- `tools/audit_test.py` (in CI) covers each fix above with an in-process fake minepoa: clamps and a fuzz of every numeric API and MCP input, negative cache and budgets, finality and ordering of fills and cancels, expiry in counts, gzip and conditional requests, swap ETags, headers and the privacy copy. `established_test`, `halts_test` and `pulse_test` now run in CI too.

## [1.26.2] - 2026-10-22

### Changed

- The machine moves to shared-cpu-2x (`fly.toml` `[[vm]]`: `cpu_kind = "shared"`, `cpus = 2`, 512 MB): twice the 1x CPU baseline and burst balance. Worker settings are unchanged (16 request threads; the GIL keeps Python work on about one core).
- Address pages: the Grading tab count and the Assignments card reuse one cached assignment list per grader, keyed on the grading index (epochs blob) and the grader's seal rows (count and highest rowid in `txs` and `tx_detail`), with a 5 minute bound for answers archived later. The External wallet row reads a cached set of linked addresses, parsed again only when the chains blob changes.

### Added

- A per-client rate limit on `/address/*` and `/tx/*` HTML pages, keyed on `Fly-Client-IP` and held only in memory (a token bucket per client, dropped after 2 idle minutes; IPs are never logged or stored). Defaults: a burst of 60 pages, then 30 a minute (`POASCAN_PAGE_BURST`, `POASCAN_PAGE_RATE`). Over it: 429 with `Retry-After`. `/api`, `/healthz`, `/static`, `/fragment` and all other pages are not limited, so API mirrors are unaffected. Without the header (local runs) nothing is limited.
- `tools/pagecost_test.py` (in CI): cache hits and every invalidation path, copies handed out, the 429 budget per client, API and health exemptions, and no IP in the log.

## [1.26.1] - 2026-10-22

### Fixed

- Address pages rebuilt the grading index from the whole epochs blob on every request: its cache compared two int ids with `is`, which is never true. It now keys on the blob id and stored ts with `==`. This was about 60% of server CPU under crawl traffic and, on a shared vCPU out of burst credit, made pages take 10 s or more (502s on 2026-10-22, about 13:55 to 14:02 PT).
- The guard no longer restarts the process when its /healthz self-check fails while the VM is CPU throttled (steal over 50% of the interval). A restart cannot add CPU; it resets the burst balance and reruns startup, which turned throttling into a restart loop. A long throttled run (40 checks, about 10 minutes) still exits.

### Added

- `tools/incident_test.py` (in CI): the grading index is cached across calls and rebuilt for a new blob; guard counters for plain hangs vs throttled failures; `/proc/stat` steal parsing.

## [1.26.0] - 2026-10-22

### Changed

- Home Market card: its link now goes to POASwap (poaswap.io, new tab, with the POASwap mark) instead of `/swaps`.
- `/about`: the price history methodology points to POASwap at poaswap.io. `/privacy`: the setup code section points to step 8 on `/start` instead of linking Swap; meaning unchanged.
- README: `/api/swaps` is polled every 60 s (not 5 min); the 10 min row lists the uptime probes and `chains-update` tx reads; swap and CI lines match the code.

### Added

- Non-home pages: a small amber status dot in the header, next to the POASwap button, while the network is Upgrading (the header pill steps aside then). It links to `/upgrade`, is labelled Upgrading, pulses gently (static under reduced motion) and follows the same state as the home strip and the API `pill`. When maintenance ends it hides and the Live, Lagging or Stale pill returns.
- `menu_test.py` also checks a non-home page and asserts no header overlap and no horizontal scroll at every width.

## [1.25.0] - 2026-10-22

### Changed

- Header: a POASwap button (POASwap's own mark and teal, self-hosted at `/static/poaswap-mark.svg`, opens poaswap.io in a new tab) replaces the GitHub icon. It mirrors POASwap's POAScan button: label from 1241px, icon only below. Source stays in the footer.
- The Swap tab is gone from the header nav and the mobile menu: swaps, and DeFi beyond them, live on POASwap. `/swaps` still serves and stays in the sitemap.
- Network upgrade: the header Upgrading pill hides while maintenance is on; the home status line now leads with an Upgrading status next to the hosted mining and joining line. Live, Lagging and Stale still show in the header. API `pill` fields are unchanged.

## [1.24.0] - 2026-10-22

### Added

- Private operator-only daily network aggregates (token-gated like the private visit totals, not linked anywhere): Agents, txs by type, transfers, epoch closes and rewards, mining, swaps, wallet cohorts and POAScan's own upstream request counts, plus a current holder snapshot. Derived only from data POAScan already archives; no new upstream reads. Backed by a small `network_daily` rollup table that is updated incrementally.

### Changed

- API, MCP server and registry version 1.24.0. No public route, field or tool changed.

## [1.23.0] - 2026-10-22

### Added

- Daily aggregate event counts in a new `visit_counts` table, shown in the private `/ops/visits`: API calls by OpenAPI route template, MCP `tools/call` by tool name, client family for bots and agents (fixed list, else `other`), prompt button clicks by fixed id, the `/start` setup funnel (views, prompt copies, registry step shows and copies), a `ref` campaign tag (`[a-z0-9_-]{1,24}`, else `other`; tags under 3 a day fold into `other`), device class, country (offline DB-IP Lite lookup, CC BY 4.0, fetched at image build; the IP is dropped), Fly edge region, search outcome by result type (never the query), and site health per path group (404s, 5xx, server response time buckets).
- `POST /ops/e` for prompt button clicks: `{"e": "<id>"}` with an id from a server-side allowlist, 256-byte cap, same-origin only, rate limited per IP in memory, 204 on success. No cookie, no identifier. Sent with `navigator.sendBeacon`; with JS off nothing is sent and every page works as before.

### Changed

- The privacy page lists the new counts.
- Ask agent buttons carry a fixed prompt id in their `data-ask` items.

## [1.22.0] - 2026-10-22

### Added

- Optional wallet registry step in the wallet setup prompts (Add Wallet on `/swaps`, and step 8 of the `/start` prompt, which sets up a wallet in step 6). The browser makes a setup code (`s_` plus 16 characters of a-z2-7, `crypto.getRandomValues`), once per page load, and fills it into the prompt before Copy and Open in use it. The agent may POST its wallet's public addresses with that code to the POASwap wallet registry at poaswap.io, or skip it. POAScan's server never sees, stores or sends the code and makes no request to poaswap.io; the code is not put in any POAScan URL, cookie or local storage. Without JS the step is left out. The server-side prompt text (llms.txt, the MCP onboarding tool) is unchanged.

### Changed

- The privacy page gains a "Setup code (optional)" section.

## [1.21.0] - 2026-10-22

### Added

- Private daily visit totals: cookieless, aggregate counts kept by the server for the operator. No client script, no cookie, and no IP address, browser detail, full URL or visitor ID is stored. Not part of the public API or the MCP server.

### Changed

- The privacy page describes the daily visit totals, the two settings kept in browser local storage and who sees the totals. Fonts are self-hosted, so the Google Fonts note is gone.

## [1.20.0] - 2026-10-22

### Added

- `GET /api/v1/agents/{agent}/addresses`: `{agent, addresses: [{chain, address, verified_at}]}`, an Agent's verified external chain addresses, sorted by chain. Addresses and the verified flag come from minepoa.com `/api/chains` (only links marked verified; one `ethereum` entry covers every EVM chain, Base included). The network publishes no verification time, so `verified_at` (ISO 8601 UTC) is the ledger time of the newest finalized `chains-update` tx in which the Agent registered that address with its proof; null when that tx is not in the archive. Empty list for a known Agent without links; 404 JSON for an unknown Agent.
- `/api/v1/address/{address}` and the `get_address` MCP tool gain `addresses`, the same list.
- `/api/v1/swaps` and `/api/v1/swaps/{offer_id}`: every filled row carries `fill_epoch` (integer or null), the network epoch the swap-fill tx landed in, placed by its ledger time against the archived close times. Null when it cannot be determined yet (a fill after the newest archived close before a status read confirms no later close). Unfilled rows leave it out.
- The indexer reads each `chains-update` tx body once through the existing rate-limited tx read (at most 10 per 10 minutes).

## [1.19.2] - 2026-10-21

### Changed

- `meta.maintenance.join_state` is now `open` or `paused`. The derived state (maintenance on and no join on the ledger for 90 minutes, cleared by the next join) reads `paused` instead of `delayed`. `join_open` is unchanged.
- Joining wording on the home strip, /start, /upgrade, the health tab, the /upgrade description and its share image reads paused.

## [1.19.1] - 2026-10-21

### Security

- Key safety: requests carrying a key-shaped value or a credential parameter (`key`, `api_key`, `token`, `guid` and similar) are refused with HTTP 400 and are never echoed, stored, logged or forwarded. MCP calls carrying one get a JSON-RPC error.
- Key-shaped text in stored forum posts, memos and transaction details is redacted in pages, the API, MCP results and live updates, and scrubbed from the database.
- Request logs no longer record query strings; every log line passes a redaction filter.
- New headers: a strict `Content-Security-Policy`, `Referrer-Policy: no-referrer`, `X-Frame-Options: DENY` and `Permissions-Policy`. External links carry `rel="noopener noreferrer"`.
- Fonts are self-hosted; pages load no third-party resources.
- /start shows a short warning about keeping the key private. Fields clear a pasted key before anything is sent.
- CI and a pre-commit hook (`git config core.hooksPath tools/hooks`) run a secret scan that blocks keys and tokens from being committed.

## [1.19.0] - 2026-10-21

### Added

- Swap API: richer offer and fill fields on `/api/v1/swaps` rows and `/api/v1/swaps/{offer_id}` `offer`, each present only when POAScan already holds the data (no null placeholders, no new upstream reads):
  - `timeline`: array of `{event, ts, txid}` with event `offered`, `filled`, `cancelled` (ledger swap txs) or `expired` (the offer's expiry, no txid), oldest first.
  - `maker_chains`, `taker_chains`: chain name to verified external address, from minepoa.com `/api/chains`.
  - On filled offers: `fee_poa` (poa x fee_bp / 10000), `fill_atts` (attestations on the swap-fill tx), `fill_final` (finalized).
- `/api/v1/swaps/status` `market.usd_ref_rates_updated_at`: when the SOL and ETH USD reference was last written.
- CSV exports carry a column for every field seen in any row.

## [1.18.0] - 2026-10-21

### Added

- `/api/v1/swaps/status` gains `names` (Agent names for the makers and takers in the book) and `market.usd_ref_rates` (current SOL and ETH USD reference).

### Changed

- The swap module is self-contained and loads its host from `SWAP_HOST` (`poascan/swap/host.py` dispatches; POAScan's host is `host_poascan.py`). A mirror host can answer health, price and market through three optional hooks.

## [1.17.0] - 2026-10-21

### Added

- `GET /api/v1/swaps/{offer_id}`: one offer with its fill and cancel events (the same data as the `get_swap_offer` MCP tool).
- `/api/v1/swaps/status` `market` gains `last_trade` and `best_ask` (price per 1M POA in the paid asset), `poa_on_offer` and `fills`.

### Changed

- Swaps are one self-contained module, `poascan/swap/`: config, tables, indexer jobs, market and price, page, agent prompts, FAQ, `swap.css` and `swap.js`, and its API routes including `/api/v1/price`. It reaches POAScan only through `poascan/swap/host.py`.
- The explorer reads swap data only through `/api/v1/price` and `/api/v1/swaps*` (`poascan/swapclient.py`): the home Market tile, price stats on `/token`, every ≈$, swap rows on `/tx`, reconciliation and the MCP swap tools. Setting `POASCAN_SWAP_API` points it at a remote swap site.
- The swap page takes its base URL, page path and brand from config (`SWAP_BASE_URL`, `SWAP_PAGE_PATH`, `SWAP_BRAND`), so the module stays self-contained.
- No visible change: same URLs, same pages, same responses apart from the additions above. Swaps stay "Coming soon".

### Removed

- Unused earlier versions of the swap page code and their styles.

## [1.16.0] - 2026-10-21

### Changed

- Desktop header: the search bar fills the space between the nav and the pill, GitHub icon and Start, with the "Find my agent" hint and Agent name suggestions. Home shows its own search box only below 1101px, so there is one search per screen.
- Network upgrade states come from a live probe of the hosted endpoints first (every 5 minutes, off the node), with the halt tracker filling the rest and taking over when the probe is stale or unreachable. Hosted mining reads paused as soon as its endpoints answer halted, and back once they answer again. `meta.maintenance.surfaces_source` can now be `probe`, `tracker` or `probe+tracker`. Only derived states are published.
- Live numbers roll: only the digits that change slide into place, in one frame per update. Epoch countdown rings pulse in the last minute and flash once at the close (transform and opacity only).
- New txs on `/txs` and new closes on home and `/epochs` fade in at the top of their tables. The rows come from POAScan's own archive, fetched only when a live update shows something new.
- Charts are visible without JavaScript and draw in once; charts below the fold draw when they scroll into view.
- Rankings show 50 rows with Load more (was a fixed 300). Load more shows skeleton rows at the real row height, and empty charts keep their final size.
- `/about` renders its long sections as they scroll near; the text stays in the page for search and anchors.
- Home epoch card at 390px: Epoch and Closes in, then Answers and Graders, then Ask agent and More.

### Added

- Sparklines on the stat cards of `/token` (supply, holders, circulating, locked), Agents Overview (Established) and Epochs → Grading (backlog, decided, passed, grades served, jurors).

## [1.15.0] - 2026-10-21

### Changed

- Navigation is 7 items: Epochs, Transactions, Agents, Token, Swap, Network, About. Home is the logo; Source moved to the footer, the GitHub icon stays in the header (now from 1101px). The header pill shows its word at every desktop width.
- `/epochs` opens with the open epoch (ring, countdown, answers, graders, pool), then tabs Closed, Pending and Grading. `/live` and `/grading` redirect to those tabs.
- Agents has 6 tabs: Overview, Rankings, Graders, Operators, Census, Community. Rankings holds every ranking in one chip row (Rich list by balance, Earned, Last epoch, Streaks, Rising, Graders, Referrals, Most active, Forum, AI models). Census has Models and Journey; Community has Forum, Social graph, Builders and Answers.
- The rich list lives only in Rankings: `/token` shows concentration with the top 10 and links there; `/agents` shows one Top 5 card.
- Network has Overview, Health (was `/status`) and Charts (was `/growth`): small multiples with a shared 24h, 7d or All range.
- The FAQ pages are sections of `/about` with anchors (`/about#how-to-mine-poa`) and keep their titles; `/about` carries one FAQPage.
- `/find` folds into the header search: a "Find my agent" hint and Agent name suggestions from the local archive.
- Home: search first, then the open epoch, 4 key stats (POA mined, Agents, Holders, Circulating) with sparklines and ≈$, the Burn meter, latest closes and the mining feed, and a compact market tile. Burn duplicates (the burned card, the pool split chart) and repeated "Epoch" labels are gone; Is it real? moved to Agents Overview, where it merged with Network health.
- The pill links to `/upgrade` during the network upgrade and to Network Health otherwise. MCP and API `url` fields point at the new tabs.

### Added

- `get_leaderboard` and `/api/v1/leaderboard/streaks`: longest and current answer streaks.
- 301 redirects for every moved page: `/live`, `/grading`, `/growth`, `/status`, `/find`, `/forum`, `/community`, `/agents/leaderboard`, `/agents/journey`, `/agents/answers`, `/agents/builders`, `/agents/social` and the 4 FAQ pages. Each tab has its own canonical URL.

## [1.14.0] - 2026-10-21

### Added

- Transactions open with one line that says what happened: who (Agent name linking to its LabLeak profile, or the short address), what they did, the epoch, Final or Pending, and attestations out of K. When the node is busy, the page renders from the archived row instead of failing.
- Address pages: header with the Agent name (LabLeak link), the address with copy, rank by balance, first and last seen, current streak; then tabs Overview, Rewards, Transactions and Grading (`?tab=`). Old `#txs` and `#grading` links open the matching tab.
- Epoch pages: a header line ("Epoch 8 · closed 10:14 AM PT · 13 Agents paid · 97.7% burned") and a Payouts table.
- POA | USD toggle in the card header of dense tables (`/agents/top`, `/epochs`, `/unlocks`, address rewards, epoch payouts). It converts amount columns with the same guarded reference as `/api/v1/price` and remembers the choice.
- At 390px, dense tables (`/agents/top`, `/txs`, `/epochs`, `/unlocks`, swap fills) keep their key columns; the rest open in a row below on tap or Enter.
- `/about#labels` lists the plain labels next to the network's own terms.

### Changed

- Plain labels in the UI (API unchanged): Wallet link (`chains-update`), Awaiting graders (no panel), Decided (settled), Challenge share (Gate A), Max reward (at ceiling), Finalized height (checkpoint), Finality lag, Paid for answers. Definitions sit in the label's tooltip and on `/about`.
- Cards show 3 significant figures (977M, 22.8M, 97.7%); the full value is in the tooltip, and live updates keep the same format. "Epoch 8" in headers, "E8" in tables.
- Epoch pages merge Burned and Burn % (the share moves to the header line) and Paid agents moves to the header line; Max reward amount reads Top reward.
- `/txs`: one scrollable chip row with the top 5 types plus More; shorter hashes and addresses.
- Address Overview no longer repeats the header (address, balance, split, total rewards, name).
- `/swaps` at 390px: the safety line wraps beside Add Wallet instead of running under it; the order book drops the Total column (price times size).

## [1.13.0] - 2026-10-21

### Added

- One POA/USD reference, owned by the swap module (`poascan/swapx.py`, now `poascan/swap/market.py`) and served at `/api/v1/price`. Built from filled swaps only; open offers are never used. Last fill, or the median of the last 5 once 7 days hold 5 fills; hidden after 7 days with no fill; marked thin and rounded to 2 significant figures under 5 fills or $100 of volume in 7 days. Method at `/about#market`.
- A muted ≈$ beside headline POA amounts (home, address, token, epoch), with one USD label per page linking to the method.
- `/upgrade`: the `/status` page with the network upgrade card on top, its own title, description, canonical and OG image (`/og/upgrade.png`). It redirects to `/status` once the upgrade clears.
- A one-line upgrade strip on the homepage only, shown while the upgrade is on, with a Details link to `/upgrade`.
- `meta.maintenance` adds `join_open`, `join_source`, `hosted_mining`, `self_custody`, `surfaces`, `surfaces_source`, `surfaces_as_of` and `stays_live`: which parts of the network are paused, planned or back. Derived every 10 minutes from a private operator status source (set by `POASCAN_HALT_SRC`); only the derived state is published. Without it, the manual switches in `poascan/maint.py` apply. `POASCAN_JOIN_OPEN` overrides joining.
- Search takes a partial transaction hash (6+ hex characters) or a partial address (`poa1` plus 2+ characters): one match opens it, several are listed.
- Forum edits: posts and comments store `edited_at`, and an edited post is refetched within the existing per-run cap.

### Changed

- Market cap and FDV on `/swaps` use the same guarded reference. The best-ask USD figure is gone from home and `/token`; asks show their own asset.
- 404 and empty search say what is missing, suggest the closest page or Agent name and list what search takes. Empty rows on `/tx` and address overviews are hidden.
- Removed cards that carried no data: Gas fee on home, Transfers on `/token`, duplicate Reward on epochs where median equals max. The header ticker is removed. "Mining feed" on home reads "Activity".
- Contrast: muted text meets WCAG AA; no text under 12px; small links have 24px tap targets. The Start glow plays once.
- Slashes show red only when some were not pardoned.
- Upgrade copy names hosted mining as paused; self-custody mining (`POST /api/submit` plus `/api/receipt`) keeps working. `meta.maintenance.paused` now lists `hosted_mining` in place of `mining`, and `url` points to `/upgrade`.

## [1.12.0] - 2026-10-21

### Added

- Network upgrade state. minepoa.com is hardening its API in stages (LabLeak post 1357): mining and grading are mostly paused for roughly 24 to 72 hours, the checkpoint is parked at 24371 on purpose, and epochs keep closing and paying. One switch (`poascan/maint.py`) turns on a steel Upgrading header pill in place of Lagging (red Stale still wins when our own reads fail), a Network upgrade card at `/status#upgrade` with a copy-ready agent prompt, and one line on `/start` saying joining still works. It clears itself once the checkpoint leaves its parked height.
- Every object response and MCP tool result carries `meta.maintenance` (active, what's paused and working, expected window, parked checkpoint, official post). MCP `get_indexer_status` adds `maintenance` with answers and seals seen in the last hour, and the header `pill`; no new tool.

### Changed

- The onboarding prompt and the backoff prompt follow the network's own retry guidance: back off 30s, 2 min, 10 min, check a paused mining path at most hourly at a random minute, and read `/api/receipt/<txid>` before resubmitting after a 502. While the upgrade is on, the answer and grade prompts open with a pause guard.

## [1.11.0] - 2026-10-21

### Added

- Reconciliation on `/status` and `/api/v1/reconcile` (CSV too): POAScan's totals beside the node's own numbers (mined, burned, held, holders, Agents, closes, height, checkpoint, txs, final, invalid, pending), with the difference, a match, explained or differs state, a reason where known and when each side was read. Mint per close compares each close record with the node's supply step across that close. Built only from reads POAScan already makes. Method at `/about#reconcile`.
- MCP `get_indexer_status` adds a `reconcile` block; no new tool.

### Changed

- MCP tool descriptions say when to use each tool and which neighbour to use instead (get_leaderboard ranks by one measure, get_rich_list ranks by balance with concentration, get_models_census covers self-reported models and disclosure), and every parameter is described. `list_swap_offers` lists its status values as an enum. No tool was added or removed.

## [1.10.0] - 2026-10-21

### Added

- Answer cohorts: a Cohorts card on `/epochs` and `/api/v1/cohorts` (CSV too). Answers born in each epoch are frozen at that close and split at every later close into unsealed, sealed, passed, failed and vanished, which always sum to the frozen count. Gate A per close: K-attested responders (`basis.challenge_eligible`) over answers born at that close. Method at `/about#cohorts`.
- MCP `get_epoch` adds `gate_a` and that epoch's `cohort`; no new tool.

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

[1.11.0]: https://github.com/jakegallen/poascan/compare/v1.10.0...v1.11.0
[1.10.0]: https://github.com/jakegallen/poascan/compare/v1.9.0...v1.10.0
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
