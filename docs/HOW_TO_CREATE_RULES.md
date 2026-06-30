# How to Create Rules for Any Project

ContextBridge works for any codebase. You just need one file that tells it
about your domain. This guide shows you how to create it.

---

## Step 1 — Create Your Profile File

Create this file:

```
context_bridge/rules/projects/myapp_profile.py
```

Replace `myapp` with your project name (e.g. `ecomm`, `crm`, `erp`).

---

## Step 2 — Tell the Server to Use It

In your OS-specific start script (e.g. `setup\windows\1.  start_Context_Bridge.bat`), add this line:

```bat
set CONTEXT_BRIDGE_PROFILE=myapp
```

That's all the wiring needed. Restart the server and your rules are live.

---

## Step 3 — Write Your Rules

Copy this starter template into your profile file and fill in what applies
to your project. **You do not need all hooks — skip any you don't need.**

```python
# context_bridge/rules/projects/myapp_profile.py

profile_name = "myapp"


def pinned_owner_files(query_tokens):
    """
    Force specific files to always appear at the top for certain queries.
    This is the most powerful hook — pinned files get score = 100,000,000
    and will always beat everything else.

    Use when: you know exactly which file owns a feature/domain.
    """
    pins = []
    token_set = set(query_tokens)

    if {"order", "checkout", "cart"}.intersection(token_set):
        pins.append("src/orders/OrderService.cs")
        pins.append("src/orders/OrderController.cs")

    if {"payment", "invoice", "billing"}.intersection(token_set):
        pins.append("src/billing/PaymentGateway.cs")

    if {"shipment", "delivery", "tracking"}.intersection(token_set):
        pins.append("src/shipping/ShipmentService.cs")

    return pins


def expand_query_tokens(query, tokens):
    """
    Add extra search tokens so the engine finds more relevant files.

    Use when: your file names don't match plain English words.
    Example: user says "order" but your file is "PurchaseOrderHandler.cs"
    """
    expanded = []

    if "order" in tokens:
        expanded += ["orderservice", "ordercontroller", "purchaseorder"]

    if "payment" in tokens:
        expanded += ["paymentgateway", "paymentservice", "paymenthandler"]

    if "refund" in tokens:
        expanded += ["refundservice", "refundcontroller", "returnorder"]

    return expanded


def module_intent_tokens():
    """
    Map your module/feature names to the words users use when asking about them.
    The engine uses this to understand which part of your codebase a query targets.

    Use when: your project has clearly separated modules/domains.
    """
    return {
        "orders":   {"order", "orders", "checkout", "cart", "basket", "purchase"},
        "billing":  {"billing", "payment", "invoice", "refund", "receipt", "charge"},
        "shipping": {"shipping", "shipment", "delivery", "tracking", "courier", "label"},
        "users":    {"user", "users", "account", "profile", "login", "auth", "role"},
    }


def gap_queries():
    """
    When a user describes a bug in plain English, rewrite it into a clean
    CB query that matches your file names and symbols.

    Format: list of (trigger_words_tuple, clean_query_string)
    The first match wins.

    Use when: users describe issues in business language, not code language.
    """
    return [
        (("checkout", "basket", "cart"),         "order checkout cart service controller"),
        (("payment", "gateway", "failed", "timeout"), "payment gateway error handler retry"),
        (("refund", "return", "cancelled"),       "refund service return order processing"),
        (("shipping", "label", "generate"),       "shipment label generation service"),
        (("login", "auth", "access", "denied"),   "authentication authorization user role"),
    ]


def adjust_document_score(score, query_tokens, doc_path, doc_pack, doc_title, doc_text):
    """
    Fine-tune the score of individual files based on query context.

    Use when: certain files should rank higher or lower for specific queries,
    beyond what pins already handle.

    Must return: (score, reasons_list)
    """
    reasons = []
    path = doc_path.lower()
    token_set = set(query_tokens)

    if "payment" in token_set and "paymentgateway" in path:
        score += 500.0
        reasons.append("boosted payment gateway for payment query")

    if "refund" in token_set and "refundservice" in path:
        score += 400.0
        reasons.append("boosted refund service for refund query")

    return score, reasons


def adjust_owner_score(score, normalized, query_tokens, result=None, top_specific_packs=None):
    """
    Adjust score during the owner-file ranking pass.

    Use when: you want to boost/penalise files based on the full result context,
    not just the path. Less commonly needed than adjust_document_score.
    """
    return score


def adjust_primary_owner_score(score, normalized, query_distinctive):
    """
    Fine-tune scores for the single best-match (primary owner) candidate.

    Use when: you have one file that should dominate for a specific query pattern.
    Example: PermissionEvaluator should always win for permission-related queries.
    """
    if "permission" in query_distinctive and "permissionservice" in normalized:
        score += 1800.0
    return score


def extra_owner_file_patterns():
    """
    Add filename patterns that mark a file as a high-priority source file.
    Core already includes: controller.cs, service.cs, .tsx, etc.

    Use when: your project has specific file naming conventions that should
    always be treated as owner files.
    """
    return ("myapi.ts", "my.types.ts")


def analysis_prompt_override():
    """
    Return a custom system prompt for the analysis LLM (Qwen/GPT/Claude).
    Return None to use the built-in generic prompt.

    Use when: the generic prompt's examples confuse the LLM for your domain.
    Tip: copy analysis/prompt.py SYSTEM_PROMPT, keep the structure/rules,
    replace only the EXAMPLE section with examples from your domain.
    """
    return None
```

---

## Which Hooks to Start With

You do not need all eight hooks. Start small:

| Priority | Hook | When to add it |
|---|---|---|
| **Start here** | `pinned_owner_files` | You know which file owns which feature |
| **Start here** | `expand_query_tokens` | Your file names don't match plain English |
| Add next | `module_intent_tokens` | Your project has clear feature modules |
| Add next | `gap_queries` | Users describe bugs in business language |
| Add later | `adjust_document_score` | You need fine-grained score tuning |
| Rarely needed | `adjust_owner_score` | Advanced: context-aware owner scoring |
| Rarely needed | `adjust_primary_owner_score` | One file must dominate for a query type |
| Rarely needed | `extra_owner_file_patterns` | Custom file naming convention |
| Optional | `analysis_prompt_override` | LLM gives wrong results for your domain |

**`pinned_owner_files` + `expand_query_tokens` alone give you 80% of the benefit.**

---

## Real Example — E-Commerce Project

```python
profile_name = "ecomm"

def pinned_owner_files(query_tokens):
    tokens = set(query_tokens)
    pins = []
    if {"order", "place", "create"}.intersection(tokens):
        pins.append("src/Orders/OrderService.cs")
    if {"cart", "basket", "add", "item"}.intersection(tokens):
        pins.append("src/Cart/CartService.cs")
    if {"payment", "charge", "stripe"}.intersection(tokens):
        pins.append("src/Payments/StripeGateway.cs")
    return pins

def expand_query_tokens(query, tokens):
    out = []
    if "order" in tokens:
        out += ["orderservice", "orderrepository", "ordercontroller"]
    if "cart" in tokens:
        out += ["cartservice", "cartitem", "cartcontroller"]
    return out

def module_intent_tokens():
    return {
        "orders":   {"order", "orders", "purchase", "checkout"},
        "cart":     {"cart", "basket", "item", "quantity"},
        "payments": {"payment", "charge", "stripe", "refund", "invoice"},
        "users":    {"user", "account", "login", "register", "profile"},
    }

def gap_queries():
    return [
        (("cart", "empty", "lost"),      "cart session persistence service"),
        (("payment", "failed", "retry"), "payment gateway retry handler"),
        (("order", "stuck", "pending"),  "order state machine status transition"),
    ]
```

---

## Testing Your Rules

After creating your profile, run the regression gate to confirm files are returned:

```bash
python context_bridge/tests/verify_extraction_modes.py
```

To capture a baseline before and compare after changes:

```bash
# capture baseline
python context_bridge/tests/verify_extraction_modes.py

# compare after a change
python context_bridge/tests/verify_extraction_modes.py --compare context_bridge/tests/modes_baseline.json
```

---

## Quick Reference

```
One file to create:   context_bridge/rules/projects/myapp_profile.py
One line to set:      set CONTEXT_BRIDGE_PROFILE=myapp   (in start script)
Restart server:       run your OS start script (setup/windows|mac|linux/1. start_Context_Bridge.*)
Test it:              python context_bridge/tests/verify_extraction_modes.py
```
