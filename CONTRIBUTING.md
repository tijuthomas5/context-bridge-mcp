# Contributing to ContextBridge

Thank you for your interest in contributing! ContextBridge is a solo-created open source project and contributions are welcome.

> **Note:** This project is maintained in my spare time. Issues and PRs are welcome but response times may vary.

---

## Ways to Contribute

- **Bug reports** — open a GitHub Issue describing what went wrong and how to reproduce it
- **Feature suggestions** — open a GitHub Issue with your idea and the use case behind it
- **Documentation improvements** — typos, unclear steps, missing examples
- **Code contributions** — bug fixes, performance improvements, new retrieval modes

---

## Reporting a Bug

1. Check existing Issues first — it may already be reported
2. Open a new Issue with:
   - What you expected to happen
   - What actually happened
   - Your OS, Python version, and CB retrieval mode (hybrid/semantic/keyword)
   - Relevant log output if available

---

## Submitting a Pull Request

All contributions go through Pull Requests — no one can push directly to this repository. This keeps the codebase stable and gives every change a review before it is merged.

1. Fork the repository
2. Create a branch: `git checkout -b fix/your-fix-name`
3. Make your changes — keep them focused and minimal
4. Test your changes locally before submitting
5. Open a Pull Request with a clear description of what you changed and why

PRs are reviewed and merged at the maintainer's discretion. Not all PRs will be accepted, but feedback will be provided.

---

## Guidelines

- Keep pull requests small and focused — one fix or feature per PR
- Do not modify `rules/projects/example_profile.py` or `rules/projects/example_rules.json` without discussion — these are the reference templates for all users
- Do not add project-specific or machine-specific paths to any shared file
- All new test scripts must go in `context_bridge/tests/`

---

## Questions

Open a GitHub Issue with the `question` label. 

---

By contributing, you agree that your contributions will be licensed under the same Apache 2.0 licence as this project.
