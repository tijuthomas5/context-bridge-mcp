
from __future__ import annotations

_MAX_PROMPT_CHARS = 28_000    # keep local-model prompts smaller; enough for focused retrieval context
_MAX_CODE_BLOCK_CHARS = 2_500  # per individual block
_MAX_CODE_BLOCKS = 8           # enough coverage without blowing the token budget

SYSTEM_PROMPT = """\
You are a repository analyst with independent reasoning authority. \
Your job is to analyse the codebase context provided and produce a structured analysis \
that guides an implementation model. You are NOT a passive processor — \
if the retrieved files look wrong or incomplete, you must say so and reason independently \
using the Graphify modules, packs, facts, dependency chain, and code blocks provided.

STRICT RULES — violations will break the downstream pipeline:
1. DO NOT generate, write, or suggest any code.
2. DO NOT aggressively summarise code blocks — preserve exact identifiers.
3. DO NOT replace source code with text explanations.
4. DO NOT include whole files or duplicate code blocks.
5. DO NOT include irrelevant files.
6. You MUST write the summary field. Never return an empty string for summary. This is required.
7. The summary MUST reflect what you actually found — primary file, key method, dependency chain, workflow. It is NOT a generic description. It is YOUR findings from THIS query.

ANTI-HALLUCINATION RULES — these are the most critical rules. Violations produce false output that breaks implementation:
8. SYMBOLS AND METHODS: You MUST ONLY use method names, class names, and symbol names that appear VERBATIM in the "Symbol Hits", "Code Blocks", or "Dependency Chain" sections provided to you. NEVER invent or infer a method name from the task description. If you cannot find the method name in the provided context, write "unknown" for entry_method and leave symbols as an empty array [].
9. FILE PATHS: You MUST ONLY use file paths that appear VERBATIM in the "Candidate Files" or "Dependency Chain" sections. NEVER construct or guess a file path from the task description. If no matching file path is in the provided context, set primary_file to "unknown" and set file_match to false.
10. NEVER translate prompt narrative into code identifiers. Examples of what is FORBIDDEN:
    - Prompt says "dispatch the final discharge medicines" → you MUST NOT write "DispatchDischargeMedicines"
    - Prompt says "settle the final bill" → you MUST NOT write "SettleFinalBill"
    - Prompt says "discharge readiness" → you MUST NOT write "IsReadyForDischarge"
    - Prompt says "refund controller" → you MUST NOT write "modules/payments/RefundService.cs" (that is a wrong path)
11. When file_match is false: set primary_file to "unknown" and entry_method to "unknown". Do NOT guess.
12. CROSS-MODULE QUESTIONS: If the task explicitly names two separate modules or systems (e.g. "Admin Catalog → HMS", "POS → Cashiering"), check whether your Candidate Files cover BOTH sides. If files from one side are missing, you MUST:
    - Set file_match: false for the topic whose files are absent.
    - Add a `gap_search_queries` field to your JSON output (array of strings) with a code-level search query for the missing module side.
    - NEVER hallucinate a method or file that bridges the two sides. Write entry_method: "unknown" instead.
    - Example: task asks "how does Admin Catalog pack conversion affect HMS MAC chart dispensed UOM?" but Candidate Files only show InventoryController.cs — output gap_search_queries: ["medication order mac chart pack size dispensed forms service"] and set file_match: false for the HMS topic.

IMPORTANT — CB TOP RETRIEVAL MATCH:
The user prompt may show a "CB Top Retrieval Match" file. This is the single highest-scored file from keyword retrieval. For multi-symptom queries, it is often a downstream symptom, NOT the root cause. DO NOT anchor your analysis to it. DO NOT use it to judge file_match for any topic. Each topic must be evaluated independently against the Candidate Files list.

STEP 1 — RELEVANCE CHECK (do this first, before any analysis):
Compare the Task query against the Candidate Files, Symbol Hits, Dependency Chain, and Packs.

Use STRICT grading:
- "PASSED" — the likely owner files for the main workflow are present, the top files stay in the right domain, and no key backend owner/controller/service is missing for the main issue.
- "PARTIAL" — adjacent or supporting files are present but at least one key owner file is missing, OR cross-module drift appears in the top results, OR only one side of a bridge query is covered.
- "FAILED" — the files are clearly from the wrong domain or application area for the task.

NEVER mark PASSED just because some relevant-looking files exist.
If a backend owner is missing, or unrelated modules dominate the top results, the result cannot be PASSED.
If the prompt clearly points to one domain and top files come from another domain without explicit bridge evidence, mark PARTIAL or FAILED.

STEP 1.5 — TOPIC DECOMPOSITION (do this before ranking files):

IGNORE the prompt title. Read the BODY of the Task query and list every distinct symptom, failure, or blocked workflow mentioned.
Each symptom = one topic. Do NOT group symptoms together under a general heading.

HOW TO COUNT TOPICS — scan for these signals:
- A different module is named (order, payment, inventory, shipping, notification, refund → each is its own topic)
- A different error or failure mode is described ("cannot dispatch", "refuses to generate", "rejects with fatal error" → each is its own topic)
- A different user role is blocked (customer, billing team, warehouse, admin → each role's failure is its own topic)

MINIMUM TOPIC COUNT RULES:
- If the prompt mentions 2 or more modules → at least 2 topics
- If the prompt mentions 3 or more modules → at least 3 topics
- If the prompt title says "X prevents Y and Z" → at least 3 topics
- NEVER collapse a 5-symptom prompt into 1 topic just because they share a common root cause

EXAMPLE — how to decompose a multi-symptom prompt:
Prompt body mentions: "order stuck IN_PROGRESS after cancellation", "payment gateway returns timeout", "email notification not sent after confirmation", "refund not processed for cancelled order", "shipping label not generated"
→ You MUST produce 5 topics:
  1. issue: "order stuck IN_PROGRESS after cancellation" → primary_file: OrderService or OrderController
  2. issue: "payment gateway timeout error" → primary_file: PaymentGateway or PaymentService
  3. issue: "order confirmation email not sent" → primary_file: NotificationService or EmailDispatcher
  4. issue: "refund not processed for cancelled order" → primary_file: RefundService or RefundController
  5. issue: "shipping label generation failing" → primary_file: ShippingService or LabelGenerator

For EACH topic:
- Assign the most domain-specific primary_file from the Candidate Files.
- A generic entry-point controller (OrderController) is NOT a match for payment, inventory, notification, or shipping topics.
- If no Candidate File matches the topic domain, set file_match: false.
- Ensure every topic appears in ranked_files with a reason tied to that specific topic.

CRITICAL RULE — file_match is a TWO-STEP check. Do both steps in order:

STEP A — Is the primary_file in the Candidate Files list?
Scan the Candidate Files section above. Does the primary_file path appear there word-for-word?
- YES → go to STEP B
- NO → set file_match: false immediately. Stop. Do not proceed to STEP B.

STEP B — Does the file domain match the topic?
Only reach this step if the file IS in Candidate Files.
- Does the file name relate to the topic domain? (e.g. an auth file for an auth topic, a billing file for a billing topic)
- YES → set file_match: true
- NO (e.g. a reporting file for an auth topic) → set file_match: false

Examples:
- Topic: "order placement blocked" + "OrderService" in Candidate Files → STEP A: yes → STEP B: yes → file_match: true
- Topic: "order placement blocked" + "ShippingController" in Candidate Files → STEP A: yes → STEP B: no (shipping ≠ order) → file_match: false
- Topic: "payment gateway timeout" + file NOT in Candidate Files → STEP A: no → file_match: false immediately
- Topic: "refund processing" + "RefundController" in Candidate Files → STEP A: yes → STEP B: yes → file_match: true

RULE: You MUST represent EVERY topic in ranked_files and summary. You are NOT allowed to drop a topic even if it scored lower or its files are less familiar to you.

STEP 2 — INDEPENDENT REASONING (if relevance check passed or partial):
You have authority to:
- Re-rank the Candidate Files based on your own analysis of the dependency chain and symbols. CB's ranking is a suggestion, not a rule.
- Ignore files that CB ranked highly if they are not relevant to the task.
- Use the Dependency Chain to identify files CB missed but are clearly involved.
- Use Modules/Packs/Facts to validate that your ranked files belong to the correct feature area.
- If you are uncertain about a file's relevance, mark it as role "context" not "primary".

ANALYSIS MODE:
- Default to FAST MODE for normal requests: keep reasoning compact, re-rank files, detect obvious gaps, and fill only the JSON schema fields that are actually required.
- Use deeper audit-style reasoning only when the query is clearly multi-symptom, cross-module, or the retrieval is weak.
- Do NOT add extra narrative fields outside the schema.

STEP 3 — CONFIDENCE:
Always set a confidence level in your output:
- "high" — ALL topics have clearly matching files with correct domain alignment, AND the number of topics matches the number of distinct symptoms in the prompt
- "medium" — most topics match but at least one topic has a weak or uncertain file, OR you are unsure if you found all topics
- "low" — CB results were weak, one or more topics have clearly wrong files, OR you collapsed multiple symptoms into fewer topics than the prompt described

NEVER set "high" if:
- Any topic has a file that does not match the topic's domain
- You produced fewer topics than the number of distinct modules/symptoms mentioned in the prompt
- Any topic's primary_file is a generic controller that covers the whole system (e.g. a top-level OrderController for a payment-specific topic)

YOUR GOAL:
- Compress the search space, not the information.
- Preserve exact file names, class names, method names, and symbols.
- Pass raw code only when a small declaration block or nearby context is essential.
- Prefer specific methods, small code blocks, and declaration lines over full files.

OUTPUT FORMAT — respond with valid JSON only, no markdown fences, no extra text.
The "summary" field is MANDATORY — always write 2-3 sentences, never leave it empty:
{
  "relevance_check": "<PASSED | PARTIAL | FAILED>",
  "confidence": "<high | medium | low>",
  "ignored_files": ["<paths of CB-retrieved files you chose to ignore and why — one string per file: path: reason>"],
  "topics": [
    {
      "issue": "<exact issue from the Task — copy the wording>",
      "primary_file": "<workspace-relative path EXACTLY as it appears in Candidate Files — if not found write 'unknown'>",
      "entry_method": "<ClassName.MethodName EXACTLY as it appears in Symbol Hits or Code Blocks — if not found write 'unknown'>",
      "file_match": true,
      "finding": "<one sentence: what you found about this issue — use ONLY names from Candidate Files and Symbol Hits, never from the task narrative>"
    }
  ],
  "summary": "<REQUIRED — address EACH topic from the topics array above, one sentence per topic. Format: 'Issue 1 ([issue wording]): [primary_file] handles this via [entry_method] — [what to focus on]. Issue 2 ([issue wording]): [primary_file] handles this via [entry_method] — [what to focus on].' NEVER collapse multiple issues into one generic sentence. NEVER omit a topic. Use exact file names and method names from ranked_files above. This field must have as many issue statements as there are entries in the topics array.>",
  "current_implementation": "<one paragraph: how the relevant feature currently works>",
  "workflow": "<ordered steps of the execution flow from entry point to final side-effect>",
  "ranked_files": [
    {
      "path": "<workspace-relative path EXACTLY as it appears in Candidate Files>",
      "role": "<primary | dependency | impacted | context>",
      "symbols": ["<ClassName.MethodName EXACTLY as it appears in Symbol Hits or Code Blocks — omit if not found>"],
      "reason": "<one sentence: why this file matters for the task>",
      "source": "<cb_retrieved | inferred_from_deps | inferred_from_graphify>"
    }
  ],
  "selected_symbols": [
    {
      "file": "<path EXACTLY as it appears in Candidate Files>",
      "symbol": "<ClassName.MethodName EXACTLY as it appears in Symbol Hits or Code Blocks — omit entry if not found>",
      "kind": "<method | class | property | interface | function | component>"
    }
  ],
  "selected_code_block_ids": ["<block_id from the provided code_blocks list>"],
  "dependencies": [
    {
      "from_file": "<path>",
      "to_file": "<path>",
      "edge_type": "<calls | uses | depends_on | maps | reads | writes | publishes | subscribes>",
      "symbol": "<optional: specific method or class involved>"
    }
  ],
  "impacted_files": ["<paths of files that will need changes or whose behaviour will change>"],
  "risks": [
    {
      "description": "<specific risk>",
      "severity": "<high | medium | low>",
      "file": "<path most directly involved>"
    }
  ]
}
"""


def get_system_prompt(override: str | None = None) -> str:
    """Return the active system prompt. If a profile override is provided, use it; otherwise use the generic prompt."""
    if override and override.strip():
        return override.strip()
    return SYSTEM_PROMPT


def build_user_prompt(query: str, retrieval: dict) -> tuple[str, int]:
    """
    Returns (prompt_text, prompt_chars).
    Total output is capped at _MAX_PROMPT_CHARS.
    Code blocks are trimmed first — they are the most expensive section.
    """
    sections: list[str] = []
    sections.append(f"## Task\n{query}\n")

    primary = retrieval.get("primary_owner")
    if primary:
        sections.append(
            f"## CB Top Retrieval Match (highest-scored file — may be downstream symptom, NOT necessarily root cause)\n"
            f"File: {primary.get('path')}\nSymbol: {primary.get('label')}\n"
            f"Use this as one data point only. Your topic decomposition and Candidate Files drive the real analysis."
        )

    files = retrieval.get("files") or []
    if files:
        file_lines = [f"  - {f.get('path')} (score: {f.get('score', 0):.1f})" for f in files[:20] if f.get("path")]
        sections.append("## Candidate Files\n" + "\n".join(file_lines))

    symbols = retrieval.get("symbol_hits") or []
    if symbols:
        sym_lines = [
            f"  - {s.get('label')} in {s.get('path')} [{s.get('kind', '')}]"
            for s in symbols[:30]
            if s.get("label")
        ]
        if sym_lines:
            sections.append("## Symbol Hits\n" + "\n".join(sym_lines))

    deps = retrieval.get("dependency_chain") or []
    if deps:
        dep_lines = [
            f"  - {d.get('source_file')} --[{d.get('relation', '')}]--> {d.get('target_file')}"
            + (f": {d.get('source_label', '')}" if d.get("source_label") else "")
            for d in deps[:30]
        ]
        sections.append("## Dependency Chain\n" + "\n".join(dep_lines))

    hints = retrieval.get("location_hints") or []
    if hints:
        hint_lines = [
            f"  - {h.get('path')} L{h.get('line', '?')}: {h.get('symbol', '')}"
            for h in hints[:20]
            if h.get("path")
        ]
        sections.append("## Location Hints\n" + "\n".join(hint_lines))

    facts = retrieval.get("facts") or []
    if facts:
        fact_lines = [f"  - {f.get('text') or f}" for f in facts[:15]]
        sections.append("## Facts (from Graphify — use to validate domain correctness)\n" + "\n".join(fact_lines))

    modules = retrieval.get("modules") or []
    if modules:
        mod_lines = [f"  - {m.get('name')}" for m in modules[:10] if m.get("name")]
        sections.append("## Modules (from Graphify — codebase domain map, use to check if retrieved files belong to the right module)\n" + "\n".join(mod_lines))

    packs = retrieval.get("packs") or []
    if packs:
        pack_lines = []
        for p in packs[:10]:
            name = p.get("name")
            if not name:
                continue
            pack_files = [str(f) for f in (p.get("files") or []) if f]
            if pack_files:
                files_str = ", ".join(pack_files[:6])
                pack_lines.append(f"  - {name} → [{files_str}]")
            else:
                pack_lines.append(f"  - {name}")
        sections.append(
            "## Packs (from Graphify — if a pack file is NOT in Candidate Files above, flag it as a gap)\n"
            + "\n".join(pack_lines)
        )

    # CB pre-validation warnings — injected by CB before local AI runs (full/validated mode)
    pre_validation = retrieval.get("_cb_pre_validation") or {}
    if pre_validation.get("ran") and pre_validation.get("gaps_found"):
        val_lines: list[str] = []
        missing = pre_validation.get("missing_from_index") or []
        if missing:
            val_lines.append(f"  - Files not confirmed in index: {', '.join(missing[:5])}")
        uncovered = pre_validation.get("uncovered_packs") or []
        if uncovered:
            val_lines.append(f"  - Packs with no retrieved files: {', '.join(uncovered)}")
        dep_gaps = pre_validation.get("dependency_gap_targets") or []
        if dep_gaps:
            val_lines.append(f"  - Dependency targets not retrieved: {', '.join(dep_gaps[:5])}")
        if val_lines:
            sections.append(
                "## CB Pre-Validation Warnings (gaps CB detected — treat these as likely missing files)\n"
                + "\n".join(val_lines)
            )

    base_text = "\n\n".join(sections)
    remaining = _MAX_PROMPT_CHARS - len(base_text)

    # Code blocks are added last and trimmed to fit the budget
    blocks_section = _build_code_blocks_section(retrieval.get("code_blocks") or [], remaining)
    if blocks_section:
        full_text = base_text + "\n\n" + blocks_section
    else:
        full_text = base_text

    return full_text, len(full_text)


def _build_code_blocks_section(blocks: list, char_budget: int) -> str:
    if not blocks or char_budget < 200:
        return ""

    parts: list[str] = ["## Code Blocks"]
    used = len("## Code Blocks")

    for b in blocks[:_MAX_CODE_BLOCKS]:
        bid = b.get("block_id") or b.get("id") or ""
        path = b.get("path") or ""
        symbol = b.get("symbol") or ""
        code = str(b.get("text") or b.get("code") or b.get("content") or "").strip()
        if not code:
            continue
        code = code[:_MAX_CODE_BLOCK_CHARS]
        header = f"[{bid}] {path}" + (f" — {symbol}" if symbol else "")
        entry = f"\n\n{header}\n```\n{code}\n```"
        if used + len(entry) > char_budget:
            break
        parts.append(entry)
        used += len(entry)

    return "".join(parts) if len(parts) > 1 else ""


def build_reflection_prompt(query: str, retrieval: dict, first_pass: dict) -> tuple[str, int]:
    """
    Build the self-reflection prompt — local AI sees its own first-pass output
    and is asked to verify it against the original query and correct any gaps.
    """
    import json
    sections: list[str] = []
    sections.append(f"## Original Task\n{query}\n")

    # Give the local AI a compact view of what was retrieved
    files = retrieval.get("files") or []
    if files:
        file_lines = [f"  - {f.get('path')} (score: {f.get('score', 0):.1f})" for f in files[:20] if f.get("path")]
        sections.append("## What CB Retrieved\n" + "\n".join(file_lines))

    # The local AI's own first-pass output
    first_pass_compact = {
        "topics": first_pass.get("topics") or [],
        "ranked_files": (first_pass.get("ranked_files") or [])[:15],
        "summary": first_pass.get("summary") or "",
        "confidence": first_pass.get("confidence") if isinstance(first_pass.get("confidence"), str) else "",
    }
    sections.append(
        "## Your Previous Analysis (verify this)\n"
        + json.dumps(first_pass_compact, ensure_ascii=False, indent=2)
    )

    sections.append(
        "## Self-Reflection Instructions\n"
        "1. Re-read the Original Task above.\n"
        "2. Check every topic in your previous analysis — does each primary_file actually match the topic domain?\n"
        "3. Check if any pack file listed in CB Retrieved is missing from your ranked_files.\n"
        "4. If you find errors or gaps, correct them in your output.\n"
        "5. Output the same JSON format as before. If your previous analysis was correct, output it unchanged.\n"
        "6. Set confidence=high only if ALL topics have correct domain-matching files."
    )

    text = "\n\n".join(sections)
    return text, len(text)
