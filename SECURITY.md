# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in ContextBridge, please do **not** open a public GitHub Issue.

Instead, use GitHub's private vulnerability reporting:

**[Report a vulnerability](../../security/advisories/new)** — this keeps the report private until it is resolved.

Please include:
- A description of the vulnerability
- Steps to reproduce it
- Potential impact

I will respond as quickly as possible and work with you to address the issue before any public disclosure.

---

## Scope

ContextBridge is a local-first tool that runs entirely on your own machine. It does not transmit your codebase or query data to any external server unless you explicitly configure a cloud-based analysis provider (e.g. Anthropic, OpenAI, OpenRouter) in your config file.

Security concerns most relevant to this project:
- The MCP server runs locally on `127.0.0.1:8755` — ensure it is not exposed to external networks
- API keys configured in `config.hybrid.json` are stored locally and never logged by CB
- Graphify data and CB index files are local only
