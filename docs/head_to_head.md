# Head-to-head: LLM verdict vs execution verdict (wallet, run on 26 Oct 2026)

Question: if you just ask an LLM "is this fix correct?", does it approve fixes that are actually broken? Harness: `python -m orchestrator.head_to_head` (and `--naive`).

## Setup
- 7 candidate fixes for `/withdraw`, **hand-written by us**: 3 intended correct (`for_update`, `atomic_update`, `advisory_lock`) and 4 intended wrong (`check_before_lock`, `lock_wrong_row`, `advisory_key_per_request`, `decrement_without_guard`). "Intended" is our label from how each was built, not a measurement.
- Execution verdict: the validator in `controller/validate.py` (regression cases, replay of the failing schedule, 30 fresh simultaneous trials at 0 ms and 30 ms) with two rules: conservation and "total withdrawn is at most the starting balance".
- LLM verdict: one reply per fix. Model that answered: `gemini-3.5-flash-lite` (the larger models returned 429 during the run).

## Results (one run each)

| Judge | Matched our intended label | Wrong fixes it approved |
|---|---|---|
| Execution (validator) | 7 of 7 | 0 of 4 |
| LLM, careful prompt ("reason about every interleaving") | 7 of 7 | 0 of 4 |
| LLM, lazy prompt ("is the fix correct?") | 6 of 7 | **1 of 4** (`decrement_without_guard`: it said the atomic decrement fixed the race, but the earlier separate check still lets both pass, so the balance goes negative) |

## What this does and does not show
- With a careful prompt, a small LLM judged these 7 fixes as well as execution did. **We did not find the hoped-for gap.** The claim "an LLM approves broken fixes" is NOT supported by this set.
- With a lazy prompt, one subtle overdraft fix got through. One case out of four wrong fixes, one sample, one model: an anecdote, not a rate.
- The set is small, hand-written by us, and all on the simplest app. Harder cases (multi-endpoint transfers, ORM code, isolation-level effects) are untested.
- The remaining case for execution-based validation is evidence rather than detection accuracy: a replayable failing run, a regression test that was seen failing and then passing (`tests/generated/`), and a verdict that does not depend on how the question was phrased.
