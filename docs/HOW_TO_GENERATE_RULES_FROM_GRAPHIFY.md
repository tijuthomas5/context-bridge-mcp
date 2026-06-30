# How to Generate Profile Rules from Graphify Data

If Graphify has already indexed your project, the AI can read that data
and write the ContextBridge profile rules for you automatically.
No manual guessing needed — the rules come from your actual codebase.

---

## What Graphify Data Gives the AI

| Graphify file | What the AI extracts from it |
|---|---|
| `GRAPH_REPORT.md` | Module names, feature areas, pack groupings |
| `graph.json` | File paths, ownership, dependency edges |
| `scope-summary.md` | Which files own which features |
| `source-files.txt` | All file names (for `expand_query_tokens` aliases) |
| `manifest.json` | Pack structure, area names |

---

## The Prompt to Give the AI

Copy this prompt and fill in the `[ ]` sections for your project:

---

```
I want to create a ContextBridge profile for my project so CB can retrieve
the right files when I ask questions about the codebase.

PROJECT NAME: [your project name, e.g. "ecomm", "crm", "inventory"]

GRAPHIFY DATA LOCATION: [path to your graphify-out folder]
  e.g. graphify-out/GRAPH_REPORT.md
       graphify-out/graph.json
       graphify-out/scope-summary.md
       graphify-out/source-files.txt

Please do the following:

1. Read the Graphify data to understand the project structure —
   modules, packs, file paths, and ownership.

2. Create the file:
   context_bridge/rules/projects/[name]_profile.py

3. Implement these hooks using ONLY real file paths and real module names
   from the Graphify data — do not invent anything:

   pinned_owner_files(query_tokens)
     - For each major feature/module, list the 1-2 files that own it
     - Trigger on the vocabulary words users would use when asking about it
     - Use the exact workspace-relative path from source-files.txt

   expand_query_tokens(query, tokens)
     - For each module, add the lowercase filename tokens that match it
     - Example: if module has "OrderService.cs", add "orderservice"
     - Cover the gap between plain English words and actual file names

   module_intent_tokens()
     - Map each module/pack name to the English words that describe it
     - Use the pack names from manifest.json as the keys
     - Use plain English vocabulary as the values

   gap_queries()
     - For each major module, write one (trigger_words, cb_query) entry
     - The cb_query should match real file names and symbols in the index

4. After writing the file, show me:
   - The 5 most important pin entries you added and why
   - Any modules where you were uncertain and I should review
   - The command to test it:
     python context_bridge/tests/verify_extraction_modes.py

DO NOT invent file paths. Every path in pinned_owner_files must come
verbatim from the Graphify source-files.txt or graph.json.
```

---

## What to Check After the AI Writes the Rules

Run the regression gate with a few queries that cover your main features:

```bash
python context_bridge/tests/verify_extraction_modes.py
```

Then ask CB a question about each major module and check if the right files
come back. If a file is missing, add it to `pinned_owner_files` manually.

### Signs the rules are working

- The file you expect for a query appears in position 1-3
- The `primary_owner` field in the CB result matches the right controller/service
- Qwen's `summary` names the correct file and method

### Signs something needs fixing

| Symptom | Fix |
|---|---|
| Wrong module's files appear | Add `pinned_owner_files` entry for the right module |
| Right files appear but ranked low | Add `adjust_document_score` boost for that file |
| CB returns files from an unrelated area | Add the noisy file path to a penalty in `adjust_document_score` (score -= 300) |
| User words don't match file names | Add more aliases in `expand_query_tokens` |
| Multi-symptom queries miss a module | Add entry to `gap_queries` |

---

## Example — What the AI Reads vs What It Writes

**Graphify data the AI reads:**
```
# from scope-summary.md
Pack: order-management
  Owns: OrderService.cs, OrderController.cs, OrderDto.cs
  Vocabulary: place order, checkout, purchase, cart

Pack: payment-processing
  Owns: PaymentGateway.cs, PaymentService.cs, RefundController.cs
  Vocabulary: payment, invoice, refund, charge, billing
```

**Profile rules the AI writes:**
```python
def pinned_owner_files(query_tokens):
    tokens = set(query_tokens)
    pins = []
    if {"order", "checkout", "purchase", "cart"}.intersection(tokens):
        pins.append("src/Orders/OrderService.cs")
        pins.append("src/Orders/OrderController.cs")
    if {"payment", "invoice", "refund", "charge"}.intersection(tokens):
        pins.append("src/Payments/PaymentGateway.cs")
    return pins

def module_intent_tokens():
    return {
        "order-management":   {"order", "checkout", "purchase", "cart", "place"},
        "payment-processing": {"payment", "invoice", "refund", "charge", "billing"},
    }
```

The AI is just translating Graphify's ownership map into CB's hook format.

---

## Tips for a Better Result

**Tell the AI how many modules you have.**
"The project has 6 main modules: orders, payments, shipping, inventory, users, notifications."
This stops the AI from collapsing everything into 2-3 generic entries.

**Give the AI a test query for each module.**
"After writing the rules, check that 'payment gateway timeout error' returns PaymentGateway.cs in position 1."
This gives the AI a concrete correctness target.

**Tell the AI your file naming convention.**
"All services end in Service.cs, all controllers end in Controller.cs, all React pages end in Page.tsx."
This helps it write better `expand_query_tokens` aliases.

**Tell the AI which modules matter most.**
"The most important modules are orders and payments — make sure those pins are bulletproof."
The AI will spend more care on those entries.

---

## Quick Reference

```
Step 1:  Make sure Graphify has indexed your project
Step 2:  Give the AI the prompt above (fill in project name + paths)
Step 3:  AI reads Graphify data → writes rules/projects/myapp_profile.py
Step 4:  Set CONTEXT_BRIDGE_PROFILE=myapp in your OS start script (setup/windows|mac|linux/1. start_Context_Bridge.*)
Step 5:  Restart the server
Step 6:  Run verify_extraction_modes.py to confirm files are returned
Step 7:  Test with real queries — tune any pins that are off
```
