# Architecture

adsharness uses Python 3.11+ and static HTML, CSS, and JavaScript. The server provides assets and a same-origin API bound to 127.0.0.1.

- `core.py`: explicit source discovery, TOML/JSON parsing, allowed-field projection, documents, and metadata.
- `server.py`: HTTP transport, origin/token validation, request size limits, and error handling.
- `documents.py`: lossless configuration masking, protected-path checks, and JSON/TOML syntax validation.
- `agents.py`: CLI discovery, native sign-in, bounded background operations, structured proposals, and explicit apply.
- `static/`: interface, filters, editor, and interaction states.
- `tests/`: synthetic files and HTTP requests on an ephemeral port.

IDs derive from type, agent, path, and name. Cards group sources by kind, case-insensitive name, and global/project scope. Provider filters select matching groups and open a matching source. Each source retains its own ID, tags, revision, and file; the detail selector chooses which source to read or edit. Grouping does not assert identical contents or synchronize edits. Card favorites apply to every source in the group; tags remain source-specific.

Document writes validate revisions, create backups, and atomically replace files within the same directory. A lock serializes operations within an instance. External edits made before the check are detected; there is no cooperative lock with other editors, so a concurrent change after the check can still occur. Editing through symbolic links is blocked. Metadata uses the same atomic write mechanism; multiple instances should not share a data directory.

All project-owned text is in English. Provider and scope values use English identifiers (`shared`, `project`, and `global`). External skill content and user-authored tags are displayed without translation.

## Planned capabilities

- Explicit MCP connection tests and complete provider-specific schema validation.
- Model and permission profiles with harness-version-specific validation.
- Duplicate detection with explicit source selection and synchronization.
- Backup restoration in the interface and automated accessibility tests.

These planned capabilities are not implemented in 0.2.0.

## Editing flow

The catalog maps inventory IDs to discovered source files; the browser cannot supply arbitrary filesystem paths. Default configuration reads replace recognized secret values with unique placeholders while preserving lexical formatting. Semantic-path probes prevent masking unrelated repeated values. A bounded parsing budget makes complicated or unsupported files fail closed for protected previews; users can still explicitly reveal originals locally. Applying protected edits verifies that original sensitive paths retain their values.

Agent requests snapshot the saved document revision, send a protected copy via stdin, and require a complete structured response. The provider never receives an original path from the application prompt. A background job returns a unified diff; an explicit apply operation passes through the same catalog validation and backup path as manual editing. Job states include running, ready, completed, failed, cancelled, and applied. Worker exceptions always terminate the job state; raw CLI diagnostics are not returned to the browser.

Authentication and proposal endpoints require the same per-run token and origin validation as document writes. Network and provider failures do not imply that the user is logged out. Codex login status and Antigravity model listing are used as connection checks, not as quota or model-generation guarantees.
