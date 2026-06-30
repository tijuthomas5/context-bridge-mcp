# CB Gauge

CB Gauge is a manual evaluation tool for ContextBridge. You give it a JSON file of questions, it sends each one to CB's `search_context_hybrid` tool one by one, and saves the results so you can review what CB returned for each query.

Use it to spot-check retrieval quality, test after config changes, or verify CB is returning the right files for your common queries.

---

## Running CB Gauge

Pick the scripts for your OS and you can delete the rest:

| OS | Start | Stop |
|---|---|---|
| **Windows** | `Start_CB_Gauge.bat` | `Stop_CB_Gauge.bat` |
| **macOS** | `Start_CB_Gauge_mac.sh` | `Stop_CB_Gauge_mac.sh` |
| **Linux** | `Start_CB_Gauge_linux.sh` | `Stop_CB_Gauge_linux.sh` |

Make sure ContextBridge is already running before starting CB Gauge.

---

## Questions File Format

CB Gauge expects a `.json` file — an array of question objects, each with an `id` and a `question` field.

```json
[
  {
    "id": "Q1",
    "question": "Where is the user authentication logic handled and which files are involved?"
  },
  {
    "id": "Q2",
    "question": "How does the order submission flow work from the API endpoint to the database?"
  }
]
```

- `id` — any unique label; used to identify the result in the output file
- `question` — the plain-English query sent to CB, exactly as you would ask your AI

Results are saved to a `cb_test_results/` folder next to your questions file.
