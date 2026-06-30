# Prompt Routing Rules — For Any AI (Claude, Codex, Antigravity, etc.)

Copy this into your AI's system prompt to enable routing tag support.

---

## Routing Tags

| Tag | What it does |
|---|---|
| `>>SEARCH: <text>` | **Required to fire CB.** Send this text to CB → Qwen analyzes → result comes back to AI |
| `>>TASK: <text>` | What you must do using the CB result. Answered after CB returns |
| No tag | **Default — CB is skipped. AI answers directly from its own knowledge.** |

> `[NO-CB]` tag is retired. No tag = no CB is the new default.

---

## Rules to Follow

1. If `>>SEARCH:` is present:
   - Send **only** the `>>SEARCH:` value to `search_context_hybrid()`
   - Answer using the CB + Qwen result

2. If `>>SEARCH:` and `>>TASK:` are both present:
   - Send **only** the `>>SEARCH:` value to `search_context_hybrid()`
   - Answer the `>>TASK:` using the CB result

3. If **no tag** is present:
   - Skip `search_context_hybrid()` entirely
   - Answer directly from your own knowledge
   - This is the default — conversational messages, general questions, config changes never fire CB

4. If CB is unreachable:
   - Skip CB entirely
   - Answer directly
   - Warn the user: "CB is offline — this answer is not grounded in codebase context, results may miss project-specific files"

5. Never truncate or rephrase the `>>SEARCH:` value — send it to CB exactly as written

---

## Example Usage

**Codebase query (fires CB):**
```
>>SEARCH: OrdersList customer order recent list
>>TASK: why is the order not showing after checkout, trace the full data flow
```
CB receives: `OrdersList customer order recent list`
AI answers: `why is the order not showing after checkout, trace the full data flow`

**Search only (no task override):**
```
>>SEARCH: order checkout blocked cart
```
CB + Qwen run, AI uses the result to answer.

**Conversational / general (no CB):**
```
check the logs
what did you change?
explain what a service is
```
CB is skipped. AI answers directly. Zero latency from Qwen.

---

## Why This Changed

Previously, every prompt went to CB by default — including conversational messages like
"check the logs" or "what did you change?" This wasted CB searches and added Qwen latency
(90–235 seconds) to questions that don't need codebase context.

Now CB only fires when you deliberately tag a prompt with `>>SEARCH:`.
This makes CB+Qwen a deliberate, high-signal tool rather than a default tax on every message.
