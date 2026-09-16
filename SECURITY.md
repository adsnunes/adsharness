# Security

adsharness 0.2.x is a local tool for a single user account. Do not expose it to the network. It does not execute MCP commands or scripts included in skills.

Organization data and backups are stored outside the repository. Edited documents are personal data and may contain sensitive information. The inventory does not expose MCP authentication or environment values.

To report a vulnerability, use GitHub private vulnerability reporting when enabled by the maintainer. If unavailable, open an issue requesting a private channel without publishing exploit details or secrets.

Before making the repository public, enable private vulnerability reporting, secret scanning where available, and protection for the main branch. The application does not implement user authentication or isolation from local processes. Any process able to connect to its loopback port, potentially including another local account, can obtain the session token and use the API. The token protects browser requests against cross-origin access; it is not a password or an operating-system user check. Use this application only on a trusted personal machine. There is no guarantee against a malicious local process replacing files during a write.

## Agent integration and source files

Authentication uses the official CLI's credential store. Codex device URLs and short-lived user codes are exposed only to the local same-origin browser session. Antigravity login launches the native interactive CLI on macOS; its terminal remains under user control.

Agent proposals are generated in temporary working directories with native sandbox flags. Codex runs read-only with user configuration disabled; Antigravity runs in plan mode with its sandbox enabled. Prompts instruct agents not to use tools. These flags and instructions are not an OS-wide isolation guarantee: installed CLI behavior, global instructions, hooks, provider policies, and retention rules still apply. No permission-bypass flags are used.

The application applies a proposal only after an explicit user action, revision checks, syntax validation for configurations, and backup creation. Configuration masking recognizes specific sensitive keys and preserves protected values. Unsupported masking cases fail closed. It does not classify secrets embedded in arbitrary prose or unconventional configuration keys. Original-file reveal intentionally exposes the exact local file to the browser; do not share screenshots containing its values.

CLI operations are cancellable and bounded by time and output size. POSIX cancellation terminates the managed process group; on Windows it terminates the immediate process. Proposals are kept only in application memory. Local backups and the provider CLI's own state may still contain document content.

## Workspace boundaries

Project sources that resolve outside the selected workspace through symbolic links are excluded from the inventory and source viewer. Global provider sources are still intentionally discovered outside that workspace. In-bound symbolic links remain read-only. These checks do not prevent races caused by a malicious local process replacing paths during a read or write.

See [the publication review](docs/security-review.md) for the scope and limits of the current local review.
