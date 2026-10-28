# Local results: division-scoped Q&A (DAR-587)

Real questions sent to the hosted app running locally (`uvicorn index:app --app-dir hosted`) on 2026-10-10, through OpenRouter's free `nvidia/nemotron-3-ultra-550b-a55b:free`, which answered all 24 (no fallback was needed). Retrieval: bge-small (fastembed) filtered to the asked division, cross-encoder rerank of 20 down to 5, plus the next chunk of the top 2 hits, with consecutive chunks merged. Reasoning was off and temperature was 0.1.

Ground truth comes from the verified answers in `ncdot-agentic-ai/docs/source-documents/SOURCES.md` (Utilities Accommodation Manual, "UAM") and `ncdot-agentic-ai/evaluation/tmp_manual_test_set_v1.md` (TMP Design Manual). I checked that every cited page contains the stated fact. Pages are physical PDF pages; the citation links open `#page=N`. "Partly" means correct and cited but missing part of the expected answer. No answer in this run was wrong.

## Division B (Utilities) documents, asked by a Division A (Work Zone Traffic Control) user

| # | Question | Answer (shortened) | Cited | Expected | Correct? | Time |
|---|---|---|---|---|---|---|
| B1 | At what distance from a travel lane does utility work require a lane closure? | Utility work requires a lane closure when equipment or personnel are within 5 feet of the edge of any travel lane on an undivided facility, or within 10 feet of the edge of any travel lane on a divided facility [1]. | [1] p. 126 | 5 ft undivided / 10 ft divided; UAM 3.6.4.1, PDF p. 126 | Yes | 4.3 s |
| B2 | If utility work blocks a sidewalk for 7 work days or more, what is required? | A Traffic Management Plan designed by a licensed North Carolina Professional Engineer is required to address pedestrian and ADA access issues [1]. | [1] p. 127 | TMP by a licensed NC PE for pedestrian/ADA access; 3.6.4.2, p. 127 | Yes | 1.8 s |
| B3 | Who pays for a detour when a utility closes a road? | The encroaching party shall reimburse NCDOT for any costs incurred in developing, improving, signing, marking, and maintaining a detour route. [1] | [1] p. 127 | Encroaching party reimburses NCDOT for detour costs (NCDOT approves the route first); 3.6.4.1, p. 127 | Yes: answers who pays; doesn't mention NCDOT approving the route | 3.4 s |
| B4 | What is the minimum cover for a utility installed by bore and jack? | The minimum cover for a utility installed by bore and jack is 3 feet. [1] | [1] pp. 100-101 | 3 feet; Table 3-1, p. 101 | Yes | 2.6 s |
| B5 | What is the maximum depth of an open-cut trench without extra approval, and what compaction is required for backfill? | Open cuts shall not exceed 10 feet in depth without approval from the State Utilities Manager, and backfill must be compacted to at least 95 percent of standard density per AASHTO T-99 [1]. | [1] p. 132 | 10 ft (deeper needs State Utilities Manager approval); 95% of standard density, AASHTO T-99, 6-in layers; 3.6.9.1, p. 132 | Yes: omits the 6-inch layer detail | 2.9 s |
| B6 | How much advance notice does NCDOT need before a utility owner does maintenance work in right of way? | NCDOT must be notified a minimum of 3 days in advance of maintenance activity. [1] | [1] p. 18 | 3 days; Section 1.4, p. 18 | Yes | 4.3 s |
| B7 | How must pavement be repaired after an open cut across an asphalt road? | Pavement shall be repaired with a minimum of 3 inches of surface course (S9.5B or S9.5C) and asphalt base course (B25.0C) to the original subgrade, or a minimum of 8 inches, whichever is greater [1]. Asphalt surface course shall … | [1] p. 133 | Min. 3 in surface (S9.5B/C) + base (B25.0C) to subgrade, or 8 in, whichever is greater; extends 1 ft each side; p. 133 | Yes: long, but every point is from p. 133 | 8.3 s |
| B8 | Can a utility owner work in a median? | New utility installations are not allowed longitudinally within the median area, except for irrigation or other utilities serving the highway, or on roadways that are not fully or limited controlled access where it is impractical … | [1] p. 100 | No utility work in medians narrower than twice the clear zone + work width; 3.1.2.1, p. 75 | Partly: correct and cited, but gives the median installation rule (3.4.1.4, p. 100), not the p. 75 work rule | 3.1 s |

## Division A (Work Zone Traffic Control) documents, asked by a Division B (Utilities) user

| # | Question | Answer (shortened) | Cited | Expected | Correct? | Time |
|---|---|---|---|---|---|---|
| A1 | What counts as intermediate-term stationary work? | Intermediate-term stationary work is defined as work that occupies a location more than one daylight period up to three days, or nighttime work lasting more than one hour. [1] | [1] pp. 12-13 | More than one daylight period up to 3 days, or night work over 1 hour; TMP 2.2 (PDF p. 12) | Yes | 2.1 s |
| A2 | What lane width is used in a freeway or divided highway work zone? | For freeways, expressways and other divided highways, maintain a minimum of 11 foot lanes with a 2 foot shoulder or 2 foot offset to positive protection. [1] | [1] p. 22 | 11 ft lanes + 2 ft shoulder or 2 ft offset to positive protection; TMP 3.3 (p. 22) | Yes | 2.2 s |
| A3 | What is the minimum acceleration lane for an interstate entrance ramp in a work zone? | The minimum acceleration lane is 400 feet of full acceleration lane followed by a 300-foot merge taper [1]. | [1] p. 72 | 400 ft acceleration lane + 300 ft merge taper, else close the ramp; TMP 7.1 (p. 72) | Yes | 2.3 s |
| A4 | What are the dimensions of the NC-PCB concrete barrier? | The NC Standard Portable Concrete Barrier (NC-PCB) is 10 ft. long, 24 in. wide at the base, and 32 in. high [1]. | [1] pp. 32-34 | 10 ft long, 24 in base, 32 in high, New Jersey shape, about 3,900 lb; TMP 5.4.1 (pp. 32-33) | Yes: dimensions right; shape and weight not given | 3.9 s |
| A5 | When must portable concrete barrier on a bridge deck be anchored? | Portable concrete barrier on a bridge deck must be anchored when the clearance from the back of the barrier to the edge of the deck is 6 feet or less [1]. | [1] p. 46 | Anchored when back of barrier to deck edge is 6 ft or less; TMP 5.8.4 (p. 46) | Yes | 2.0 s |
| A6 | How long can a work zone speed reduction using portable devices stay in place? | A work zone speed reduction using portable devices can stay in place for up to 30 days. [1][2][3] | [1] p. 75; [2] pp. 81-82; [3] p. 85 | Up to 30 days; TMP 8.2 (p. 75) | Yes | 2.2 s |
| A7 | What is the run-out length at 55 mph with 2,000 to 6,000 vpd? | 345 ft [1] | [1] p. 53 | 345 ft; TMP Fig 17 (p. 53) | Yes | 1.7 s |
| A8 | What are the flare rates at 55 mph for anchored and unanchored barrier? | At 55 mph, the flare rate is 16:1 for anchored barrier and 12:1 for unanchored barrier [1]. | [1] p. 54 | 16:1 anchored, 12:1 unanchored; TMP Fig 18 (p. 54) | Yes | 5.1 s |
| A9 | Can I use an anchored water-filled barrier at 55 mph? | No. Water-filled barrier is approved only for speed zones of 45 mph or less [1], and it does not have an anchoring system [2]. | [1] pp. 34-35; [2] p. 49 | No: water-filled barrier is for 45 mph or less and has no anchoring system; TMP 5.4.3 (p. 34), 5.8.9 (p. 49) | Yes | 2.3 s |

## Cross-division questions

| # | Question | Answer (shortened) | Cited | Expected | Correct? | Time |
|---|---|---|---|---|---|---|
| X1 | My TMP closes the shoulder for 3 days for a utility crossing. What lane closure, notification, and pedestrian rules apply to the utility owner, and who pays for a detour? | The utility owner must provide traffic control per MUTCD and NCDOT MUTCG, and is responsible for safe movement of traffic and pedestrians [1]. For a 3‑day sidewalk closure, the owner must close the sidewalk and detour or divert … | [1] p. 126; [2] p. 127 | UAM: lane closure within 5/10 ft (p. 126); notify the Division Engineer unless under a blanket agreement (3.6.3, p. 126); 1-7 work days: close the sidewalk and detour/divert with ADA barricades (p. 127); the encroaching party pays for a detour (p. 127) | Partly: notification, pedestrian and detour rules right; doesn't state the 5 ft / 10 ft lane-closure distances | 6.5 s |
| X2 | Can a utility owner's crew park equipment in the clear zone overnight inside my work zone, and what must they do with equipment outside working hours? | No, equipment must be properly barricaded outside of the clear zone and as close to the right of way line as possible during non-working hours [1]. | [1] p. 127 | No; outside working hours, equipment is barricaded outside the clear zone near the R/W line; UAM 3.6.5, p. 127 | Yes | 2.5 s |
| X3 | Our utility crew will leave a drop-off of more than 12 inches within 10 feet of the travel lane for 5 days on a road under 45 mph. What does the work zone manual require? | For a drop-off greater than 12 inches within 10 feet of the travelway on a road with a posted speed limit less than 45 mph, the drop-off must be protected by one of the following: traffic barrier (concrete or water-filled barrier … | [1] pp. 14-17 | TMP 2.4 D (pp. 16-17): barrier, or 6:1 wedge, or shift traffic 6 ft; over 3 days requires barrier; W8-9a signs 500 ft ahead and every half mile | Yes: cited range pp. 14-17 is wider than needed | 7.2 s |

## Not in the asked division's documents

| # | Question | Answer (shortened) | Cited | Expected | Correct? | Time |
|---|---|---|---|---|---|---|
| N1 | What is the hourly rate for law enforcement? | I couldn't find an answer to that in the Work Zone Traffic Control documents (Work Zone Traffic Control Design Manual (TMP Design Manual)). Try rephrasing the question, or ask the division that owns the topic. | none (refusal) | Not in the TMP manual | Yes: refused, no sources | 2.6 s |
| N2 | What are the HAWKS scoring criteria and threshold? | The documents state that potential HAWKS projects are scored based on 4 or 5 criteria, but they do not list the specific criteria or any threshold for eligibility [1]. | [1] p. 70 | Not in the TMP manual (test set negative) | Yes: the manual says HAWKS projects are scored on 4 or 5 criteria (p. 70) but lists none; the answer says exactly that. A qualified answer, not a refusal | 2.4 s |
| N3 | What is the hourly rate for law enforcement? | I couldn't find an answer to that in the Utilities documents (Utilities Accommodation Manual, Version 2.0 (July 2022)). Try rephrasing the question, or ask the division that owns the topic. | none (refusal) | Not in the UAM | Yes: refused, no sources | 2.5 s |
| N4 | What is the minimum cover for a utility installed by bore and jack? | I couldn't find an answer to that in the Work Zone Traffic Control documents (Work Zone Traffic Control Design Manual (TMP Design Manual)). The Utilities documents look more relevant: try asking Utilities instead. | none (refusal) | Bore-and-jack cover is a Utilities rule, not in the TMP manual | Yes: refused and offered "Ask Utilities instead" | 2.4 s |

## Summary

| Group | Questions | Correct | Partly | Wrong |
|---|---|---|---|---|
| Utilities asked by WZTC | 8 | 7 | 1 | 0 |
| WZTC asked by Utilities | 9 | 9 | 0 | 0 |
| Cross-division | 3 | 2 | 1 | 0 |
| Not in documents | 4 | 4 | 0 | 0 |
| **All** | 24 | 22 | 2 | 0 |

Latency (server time, models already loaded): median 2.6 s, range 1.7-8.3 s. Retrieval (embed, search, rerank) takes about 0.7 s; the rest is the model. In earlier runs the free model occasionally took 15-44 s for one answer (upstream load), so the page warns that a question can take a while. Loading the models from a disk cache took 1.3 s; a first start with no cache downloads about 150 MB of model files first.

## What changed while testing

1. **512-token chunks** instead of the chat app's 1024. With 1024-token chunks, the UAM lane-closure rule (end of p. 126) fell past bge-small's 512-token window and ranked below 40th. At 512, all eight verified UAM answers are in the top 5.
2. **Reasoning off** (`LLM_REASONING=off`). With reasoning on, Nemotron 3 Ultra took 23-64 s on multi-part questions, and on X1 it spent the whole token budget reasoning and returned its notes as the answer. With reasoning off, answers take 2-8 s and are the same. A cut-off answer is now reported as an error instead of being shown.
3. **Next chunk, and consecutive passages merged.** The TMP drop-off rule D runs from p. 16 onto p. 17. As separate passages, the model mixed rule C's "10 feet" into rule D (X3 was wrong in 3 runs). Merged, it answers correctly. Each citation is then narrowed back to the pages the answer drew on.
4. I tried a prompt rule against assuming conditions the question didn't state, then reverted it: in that run X1 still assumed a blanket agreement, and B4 refused 2 of 4 times.

Answers vary between runs: in earlier runs X1 sometimes assumed the crossing was under a blanket agreement (so no notice needed).

## Third division: Transportation Mobility and Safety (DAR-622, 2026-10-27)

TMSD's two documents (the TODS Procedures Manual and the Guidelines for Investigation of Fatal Crashes) were added with the offline workflow: rows in `divisions.py` and `docs/source-documents/SOURCES.md`, `fetch_documents.py`, then `prototype.ingest`. The index went from 758 to 839 chunks (TMSD 81: TODS 74, fatal crash guidelines 7); the 758 Work Zone and Utilities chunks and their vectors are unchanged.

Asked by a Work Zone Traffic Control user through `POST /api/ask/stream` on the local app, answered by `nvidia/nemotron-3-ultra-550b-a55b:free` (no fallback, no retry). Expected pages were checked against the PDFs (physical pages; the TODS manual's printed page numbers are 3 lower).

| # | Question | Answer (shortened) | Cited | Expected | Correct? | Time |
|---|---|---|---|---|---|---|
| T1 | How many TODS panels can go on one intersection approach? | A maximum of six TODS panels may be installed on a single intersection approach, with only one attraction per panel. If only one TODS assembly can fit on the approach, the limit is three panels. [1][2] | [1] TODS p. 7; [2] TODS pp. 25-27 | Six per approach, one business each; three if there is room for only one assembly; TODS manual V.A (p. 7), G.S. 136-140.19(5) quoted on p. 25 | Yes | 2.1 s |
| T2 | What fees does an attraction pay for a TODS sign? | A non-refundable $200 fee covering the application and first annual fee, due before the field investigation [1]. A $200 construction cost for each TODS panel, due within 30 days of contract approval [2]. An annual maintenance fee of $200 per contract, due each July 1 [1][2]. A $200 service charge per panel for a sign change [1]. | [1] TODS pp. 8-9; [2] TODS p. 18 | $200 initial non-refundable fee per contract (p. 8); $200 annual maintenance fee per contract, July 1 (p. 9, agreement p. 18); $200 per panel for replacement or a design change (p. 9); construction costs due within 30 days of approval (p. 18) | Partly: every fee is right except "$200 construction cost for each panel": p. 18 says construction costs are due within 30 days but gives no amount (p. 27 says only "a one-time fee per TODS panel") | 2.0 s |
| T3 | How long does a regional office have to complete a fatal crash investigation? | The regional office is expected to complete a fatal crash investigation within 60 calendar days (45 business days) from the start of Step 4 in the Workflow Tracker. [1] | [1] Fatal crash guidelines p. 5 | 60 calendar days (45 business days), counted from step 4 of the Workflow Tracker; the RTE may waive it; p. 5 | Yes | 3.3 s |

All three answers cite the right document and the page with the answer. T2 also shows the free model filling in an amount the manual leaves out; it is the kind of detail the "check the linked page" note on the page is for.

"How far from the attraction can a TODS sign be placed?" (five miles, PDF p. 6) was dropped as an example question: its answer page ranked only 5th, behind the statute and form pages. "How long does an attraction have to change its operation to qualify for TODS?" (30 days, p. 8, reranker score 7.56) replaced it.
