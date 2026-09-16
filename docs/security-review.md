# Local publication security review

## Decision and scope

The reviewed source is suitable for publication as a local, single-user preview, subject to the runtime limitations below. This is a bounded code and publication-content review, not a penetration test or a guarantee that no vulnerability exists. No repository was published by this review.

The local repository had no commits, staged files, or configured remote. The audit enumerated 26 non-ignored candidate files before this report was added. Pattern checks found no real credentials, private keys, personal home paths, or host identifiers in those files. One email-like match was a synthetic credential URL on an invalid example domain in a test fixture. No remote repository history, GitHub settings, releases, or previously uploaded artifacts were available for review.

Ignore checks confirmed exclusion of local environment files, provider configuration directories, credential files, runtime screenshots, backups, the virtual environment, and build output. Ignored files were not copied into this report. Pattern matching cannot detect every secret; review the actual staged diff before pushing, and do not force-add ignored files.

## Findings addressed

- **Credential URL masking:** default previews previously protected only lowercase HTTP/HTTPS URLs. Credentials in WebSocket or other connection URLs could reach the provider during a requested proposal. Masking now recognizes scheme-qualified connection URLs, including uppercase schemes, and protects user information, query strings, and fragments. Synthetic round-trip tests cover these cases.
- **Project symlink escape:** an instruction or skill in a selected workspace could point outside it and expose the target in the source viewer. Project source discovery and lookup now reject resolved paths outside the selected workspace. Tests cover instruction files, skill directories, and provider configuration links. This does not remove intentionally discovered global sources.
- **Local authorization wording:** security documentation now explicitly states that the session token is browser request protection, not OS-user authentication. Other local processes or accounts able to access the loopback port can obtain it.

## Remaining runtime limitations

- Do not deploy the running application on a public server or expose its port through a tunnel or reverse proxy. Use a trusted personal machine; the app does not isolate different local users.
- CLI authentication remains in the official provider credential stores. Requested proposals transmit selected content and prompts to a provider. Masking is not a universal secret detector, especially for prose, unusual keys, or credentials embedded in URL paths.
- Native sandbox flags, temporary working directories, and prompt instructions are not a complete OS isolation boundary. Installed CLI tools, global configuration, and provider retention behavior still matter. Only request edits for content and tools you trust.
- Backups contain original, potentially secret values and have no automatic expiry. They remain outside the repository by default and are ignored by Git. Do not publish them. No existing backups were deleted during this review.
- Symlink checks and revision validation do not eliminate races from concurrent external filesystem changes. No guarantee is made against a hostile local process.

## Verification

The Python suite passed after the fixes (41 tests). JavaScript syntax validation passed. The browser smoke test passed during the review using synthetic files and simulated CLI responses. No real login or model-generated edit was used for verification.

An independent Antigravity review supplied findings; the coordinator inspected them, applied the confirmed fixes, and ran the regression tests. Suggested replacement authentication schemes were not adopted: injecting the same token into a publicly accessible page or cookie would not authenticate local users.

Before an eventual public push, inspect the staged diff and enable GitHub secret scanning and private vulnerability reporting where available. These remote settings have not been verified or changed.
