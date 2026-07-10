# Advanced Tuning

These are the search-quality knobs added to fix real problems (slow queries, saturated confidence scores, wrong primary-owner picks). All three live in `settings.search` in your `config.*.json` file. Every default preserves the original CB behavior — nothing changes unless you edit the value yourself.

You will rarely need to touch these. Only change one if you see the matching symptom below, and change one value at a time so you can tell what actually helped.

```json
"settings": {
  "search": {
    "max_files_per_document_in_aggregation": 0,
    "confidence_score_scale": 45.0,
    "symbol_injection_window": 6
  }
}
```

---

## `max_files_per_document_in_aggregation`

**Default:** `0` (disabled — no cap)

**What it does:** When a single Graphify document lists a very large number of files, CB re-ranks that document's file list by how many query words each file actually matches, then keeps only the top N. Without this, a huge document forces CB to scan every file it lists on every query, even the irrelevant ones.

**Symptom that means you should raise it (set a number, e.g. 40):** Queries feel slow, especially in a large codebase with big Graphify packs.

**Tradeoff:** Set it too low and a real file living far down a large document's list can get cut before CB ever considers it. Start high (40+) and only lower it if speed is still a problem.

---

## `confidence_score_scale`

**Default:** `45.0`

**What it does:** Converts CB's internal raw ranking score into the 0–1 confidence number you see in results. This number needs to be in the same numeric neighborhood as your project's real scores, or confidence stops meaning anything.

**Symptom that means you should raise it:** Every result shows confidence near 0.95, even ones that are clearly wrong. That means your project's raw scores are much bigger than the default scale expects, so the formula is saturating instead of discriminating.

**How to pick a value:** Run a few real queries, look at the raw `top_score` values in the results, and set this roughly in the same range (a bit below the typical top_score). If typical top_score is in the tens of thousands, this value should be too — not 45.

**Tradeoff:** If you change this, also revisit any confidence thresholds you rely on elsewhere (dashboards, alerting, "low confidence" filters) — they were tuned against the old scale and will misfire until you retune them too.

---

## `symbol_injection_window`

**Default:** `6`

**What it does:** Before CB picks a primary-owner file for your answer, it only pulls in detailed symbol/method data for the top N ranked candidate files. Only files inside this window are eligible to be chosen as primary owner. This is a real-index resource limit, not a quality filter — it exists so CB doesn't do deep analysis on every candidate on every query.

**Symptom that means you should raise it:** CB consistently points to the wrong file as the answer, and the *actual* correct file shows up in the results list but ranked just outside the top 6 (e.g., rank 7 or 8). Raising this window (try 10–12) lets those near-miss files get a fair look.

**Tradeoff:** Every file inside the window costs a bit more per-query work. Going very high (20+) will slow queries down for little benefit — most correct answers already rank inside the top 6–10. Raise it modestly and re-test rather than maxing it out.

---

## General rule for all three

Change one value, rerun your real test queries, and compare before/after. If a saved regression test set exists for your project, use it — that is the only reliable way to know a change actually helped instead of just moving the problem somewhere else.
