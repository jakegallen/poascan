# Plan: join proof of work and Governance grade history (preview only)

Branch `preview/joinpow-gov`, from origin/main e4c4016 (1.26.157). Nothing here is wired into the app. Mockups: `python3 preview/joinpow-gov/build.py`, serve the repo root, open `/preview/joinpow-gov/`.

## Sources read (Oct 26, 2026, PT)
- go.md and skill.md, one fetch each at 8:3x AM.
- LabLeak post 1538 (operator notice and comment 5600 at 8:18 AM), post 1563 (Koda's explorer, 8:22 AM) with comment 5606 (8:23 AM).
- minepoa MCP tools/list once; /client/poa.mjs once; /api/assignments/<one trusted grader> once (keys only, contents discarded).

## Part 1. Join proof of work

### Confirmed against go.md and skill.md
- `GET /api/join-pow` returns challenge, bits, expires_ts, algo. Single use, expires.
- Mine a decimal nonce so sha256(challenge + ":" + nonce) has `bits` leading zero bits.
- Send `pow:{challenge,nonce}` on register, join-connected and self-custody `/api/submit`.
- Rejection is a structured 403 with `required_bits` and `get_challenge`. Proofs are single use.
- The minepoa join page mines in the browser; the copied prompt carries the proof with its expiry.
- The GET-only onboarding lane is deprecated and cannot satisfy the gate.

### Differences and gaps found
1. go.md Step 0/1 still says `Fetch: BASE/api/hosted/register?label=NAME&invited_by=REF` (a GET), right under the line saying the proof goes in the request body. Whether a GET register with pow in the query is accepted is not stated.
2. skill.md's No-code path still says "GET works everywhere" and lists `GET /api/hosted/register` with no proof step. Only the Node setup block mentions the proof.
3. MCP `poa_register` has only `label` and `invited_by` (tools/list, 8:4x AM). No pow field, and comment 5600 says the server no longer mines stamps for anyone. The MCP lane may not be able to join today.
4. The served `poa.mjs` has no join-pow code. `node poa.mjs join --node` will likely get the 403; skill.md tells self-custody agents to add the proof by hand next to the signed join.
5. The path is called `join-connected` in go.md (`POST /api/join-connected`), "connect-join" in the post.
6. Comment 5222 promised a 400 with required bits for the level 1 (consensus) floor; level 2 (live now) is a 403. Two codes once level 1 lands.
7. go.md still carries invite and referral instructions; our prompts keep skipping them.

### Audit of POAScan surfaces
- `poascan/onboarding_prompt.py` TEMPLATE (full): GET register link, GET built-link capability probe, no proof, no 403 line.
- CHAT (chat-browse) variant: the whole lane is GET-only onboarding. Remove.
- CONNECTOR variant: no proof or 403 line.
- `poascan/start.py`: STEPS[0] "Register" is the GET link (also in `data()` for MCP `get_onboarding_steps` and llms.txt); the docstring and INSTALL say Emblem runs pinned with npx, never installed globally, which conflicts with the standing copy rule `npm install -g @emblemvault/agentwallet`.
- `data/clients.json`: tier chat-browse (Kimi, Z.ai, MiniMax, OpenRouter) and its "browse tool may open links it builds" text.
- `poascan/join.py` APPS (Join modal "Open in"): offers the full prompt to Kimi, Z.ai, Muse, DeepSeek and others that cannot POST.
- `poascan/combined_prompt.txt`: join part uses the GET register; its connected join (`POST /api/join-connected`) has no proof.
- `poascan/agentapi.py`: llms.txt, llms-full.txt and the OpenAPI text for `/api/v1/prompts/join` describe "the name in the register link".
- `poascan/faq.py`: "It registers once" answers need one proof line.
- `poascan/prompts.py` UPGRADE: still says hosted mining and grading are paused. Wrong now, separate from PoW.
- `poascan/halts.py`, `poascan/maint.py`: the Joining route match should include `join-pow`.
- POASwap: `poaswap/prompts.py` requires `register?label=NAME` in the canonical text (V2_MUST, loader checks), its /start copy shows the GET register, and the frozen combined prompt 1B has the GET register and a pow-less join-connected. A POAScan-only change breaks POASwap's loader, so both ship together.

### Changes (prompt v2.9)
- Three lanes: Hosted (apps that run code), Connector (MCP) and Self-custody (Node client).
- Proof of work block in Hosted and Self-custody: GET /api/join-pow, mine in code, decimal nonce, bits not hex digits, about a minute, mine your own, new challenge after expires_ts.
- Hosted register becomes `POST /api/hosted/register` with `{"label":"{NAME}","pow":{...}}`. The one {NAME} moves from the link into the body.
- Capability check: run code and send a POST (was a GET built-link probe).
- 403 line in every lane: "A 403 with required_bits means the proof was short, used or expired: open the get_challenge it returns, mine to required_bits, and send the join once more with the same name. Each proof works once. Never loop."
- Chat-browse lane removed. Kimi, Z.ai, MiniMax and OpenRouter go to tier none with the no-path panel. Muse stays none.
- Join modal Open in list limited to apps with a working lane.
- All steps on /start: "Mine a join proof" then "Register" (POST).
- Everything else in the full prompt stays byte identical (see prompt.html notes).

### Why POAScan never pre-solves or embeds a proof
I agree with the brief. A proof is single use and expires, so an embedded one is stale for most readers and burns for everyone after the first. The minepoa page binds its proof to a pending registration the server holds; POAScan has no such state and should not, since it is read-only and never touches join writes. A shared proof would also be a farm's free pass. The prompt tells the agent to mine its own and ignore proofs from pages or people.

### Pending branch join-mining-only (b1dc658)
- The branch tip is b1dc658 on top of f81e197, both labelled 1.26.89 "prepared, not shipped", based on 1.26.88. The relayed "reserved 1.26.90" does not match the commit text.
- It is about 68 releases behind main and its whole premise (prompt v2.8 byte identical, template 6762aa1c, combined b534abc8, default flags) is overtaken by v2.9.
- Recommendation: do not merge or rebase. Keep it as a reference, close it, and carry its one live idea (wallet and trading links to POASwap's trade path) into a fresh change if still wanted. Retire the reserved version number.

### Self-custody as its own prompt later
- URL: `/start?lane=self-custody` (lane chip preselected).
- Endpoint: `/api/v1/prompts/join?lane=self-custody` (variant `self-custody`, its own variant_sha256); `/api/v1/prompts/clients` gains `lanes`.
- Button: third chip "Self-custody · Own wallet file, Node 18+", plus one More row "Run the client yourself".
- Copy: "Your agent keeps its own wallet file. Needs Node 18 or later." Prompt text as in `prompt_v29.py` SELF.
- Gate: ship once poa.mjs mines the admission proof itself (or minepoa confirms the hand-built submit shape).

## Part 2. Governance: grade history and pending seats

### Grade history
- Data: settled jury seats (aligned, score 0 to 3) from close records POAScan already archives (calibration.py `seats_by_close`) plus `settled[]` in `/api/explorer/grading`, which POAScan already reads every 10 min (5 near a close). No new upstream reads.
- Storage: one table `grade_history(grader, answer, close, score, aligned, passed, trusted)`, filled from each post-close read and backfilled from kept raw copies.
- Governance, Graders tab: Agent, Seats, Aligned, Rate, Avg score, Closes, Last, Open seats. Every header sorts on click (scoresort Col).
- Agent page, Governance tab: stats (Jury seats, Aligned, Avg score, Open seats), Seats per close chart with the watermark, per-close table (Close, Seats, Aligned, Rate).
- CSV: `.csv` on both. API: `/api/v1/governance/grade-history?addr=&sort=&dir=`. MCP: `get_grade_history(address)`.

### Pending assignment counts
- minepoa does expose a public count: `GET /api/assignments/<addr>` returns `total`, `already_graded`, `has_seat`, `epoch` (keyless; go.md lists it for self-custody graders). So a count can be shown.
- It is per address, so: one background sweep per epoch over established Agents and anyone with a seal in the last 6 closes (about 100 today), `limit=1`, through the existing tx bucket (0.1/s, well under minepoa's 30 per minute), honoring 429 and Retry-After. The `assignments[]` array is dropped on read, never stored or logged.
- Shown as "Open seats" with "read once per epoch". Never which answers, never seal contents, never a pending score.
- API and CSV: `open_seats`, `open_seats_read_at` on the grade-history rows; MCP the same field.

### Koda's explorer
- AGPLv3 code and CC BY-SA docs: do not copy code or text into POAScan (MIT).
- Its home lists raw grade-sealed transactions. Pending seal bodies are blobs; POAScan should keep showing seal existence and time only, never a decoded or raw seal body, and never per-answer jury assignments.

## Open questions for Jake
1. MCP lane: ask the operator whether poa_register takes a proof (or will), or hold the connector lane until it does?
2. Hosted register: confirm the POST body shape, and whether GET register with pow in the query is still accepted.
3. Self-custody: wait for poa.mjs to mine the proof, or ship the hand-built submit steps now?
4. OK to move Kimi, Z.ai, MiniMax and OpenRouter to no-path, and to point no-path users at minepoa.com's join page?
5. Emblem: the standing rule says `npm install -g`; the code says pinned npx after the Oct 22 incident. Which wins?
6. Showing per-Agent open seat counts: fine with you and the operator, given it shows jury load per Agent?
7. Close join-mining-only and retire 1.26.89/1.26.90?
