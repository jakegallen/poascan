# Proposed fixes to the v2.8 mining-only join prompt (not served)

join-v2.8-fixed.txt is a proposal only. POAScan still serves v2.8 byte identical (5,539 bytes, sha256 6762aa1cb3bf173a20f6d25af3045b10ef4463a962754e8f1f58dc28878b5cdd).

- Proposed full template: 5,748 bytes, sha256 fde6f03c3c0d18c9784301863c2319d1b151671627e22af1f51b755038b37b13 (UTF-8, LF, no BOM, no trailing newline).
- Checked against https://minepoa.com/go.md fetched 2026-10-24 (skill.md timed out and was not checked).
- Changes: key out of every link (X-Api-Key header, then token=AUTH_TOKEN, key= last since go.md calls it legacy); balance reported as spendable and locked (vesting); grading points to go.md's GRADE section, one at a time; the paused route line reads as conditional now that go.md says the hardening pause is over.
- Before shipping: confirm with the minepoa operators that /api/hosted/challenge, /answer and /mine accept X-Api-Key (only /api/hosted/me is known to). The chat-browse and connector variants need the same edits, then a new prompt version (v2.9), new hashes, and POASwap's combined prompt would need a new join core.
