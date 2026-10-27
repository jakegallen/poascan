# Grader patterns: scope (Oct 27, 2026)

Source idea: LabLeak post 1595, comment 6021 (agent_1DxssgW6) and reply 6028 (POA3-ai-agent). Scope only; nothing wired into the app.

## Metrics

| Metric | Source | Now? | Caveats |
|---|---|---|---|
| Agreement (seat matched final outcome) | grade_history.aligned (close records basis.settled[].jury[]) | Yes, both segments | System graders sit on most panels, so their agreement is near 98 to 100% by construction; exclude from percentiles |
| Disagreement rate | 1 minus Agreement | Yes | Same number; show one |
| Peers (panel-mates' agreement on the same answers) | grade_history self-join on answer | Yes, both segments | Needs 2+ jurors per answer; 99 answers in seg 2 had 1 |
| Lone dissent (only non-aligned juror) / contested share | grade_history self-join | Yes, both segments | Small counts; n threshold |
| Score spread (stdev of 0 to 3) | grade_history.score (grading list settled[]) | Seg 2 only | Seg 1 has no scores (0 scored). Seg 2: 8,561 of 12,900 seats scored |
| Top score share, score mix | grade_history.score | Seg 2 only | Same |
| Distance (gap to panel-mates' mean score) | grade_history self-join | Seg 2 only | Same |
| Participation (seats, closes, seals per close, open seats) | grade_history, calibration, open_seats | Yes | Open seats current segment only |
| Answer-to-seal timing | grading_seals.ts (45 day keep) or close record pending grade ts, minus answer tx ts | Partly | Measures delivery and batching more than care (comment 6028); "attest" in PoA is node auto-mining, not grading. Not recommended per grader |
| Verdict or score on pending seals | none | No, never | Not public; never decode |
| Per-answer seat assignment time, effort | none | No | assignments endpoint gives counts only |

All from POAScan's own tables; zero new minepoa reads; available during the halt (data frozen until closes resume).
Cost: one GROUP BY plus one self-join over about 20k seats, cached 300 s.

## Fairness default
n 20 scored settled seats minimum (others hidden behind an All chip); distributions in charts, no names; table default A to Z, never "worst first"; percentiles on hover; system graders tagged and left out of percentiles; neutral labels; Advisory tag; no flagging words.

## Placement
Governance > Graders, new card "Grader patterns" below Calibration. API GET /api/v1/governance/grader-patterns (+ .csv), MCP get_grader_patterns.
