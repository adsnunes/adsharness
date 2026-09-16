# adsharness contributor guide

- Python 3.11+, standard library runtime. Start with `python3 -m adsharness`.
- Run `python3 -m unittest discover -s tests -v` and `node --check adsharness/static/app.js`.
- Use English for all interface copy, source code, comments, documentation, tests, and repository templates. Keep the product identifier lowercase: adsharness.
- Never add real provider configs, credentials, local paths, transcripts, or runtime metadata to fixtures or git.
- Use temporary synthetic homes for tests. Never mutate the developer home during verification.
- Provider readers must not execute configured MCP commands. Inventory responses must omit credentials, arguments, and environment values. Source previews must mask recognized secrets unless the user explicitly reveals the original locally. Never send revealed configuration values to an agent.
- Bind only to loopback; preserve Host, Origin and token checks on local APIs.
- Document writes require revision validation and backups. Preserve unknown provider fields.
- Prefer small modules and explicit errors. Do not claim configured MCPs are connected.
- Delegate a bounded review using the antigravity-delegate skill when available; review-only, no recursive delegation. Implementation delegation requires an isolated linked worktree.

- Agent integrations must use official CLI authentication, native sandbox flags, bounded cancellable processes, structured proposals, explicit apply, and synthetic test runners. Never add permission-bypass flags.
