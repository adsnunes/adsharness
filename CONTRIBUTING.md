# Contributing to adsharness

1. Open an issue describing the problem and expected behavior without personal settings.
2. Create a focused branch and follow the existing conventions.
3. Add tests for parsing, writes, and security boundaries using synthetic data.
4. Run the README checks and describe validation in the pull request.

Use English throughout the project: interface copy, code, comments, documentation, tests, and templates. Keep the product name lowercase: adsharness.

Write clear commits, such as `feat: add provider adapter`, `fix: preserve document edits`, and `docs: explain setup`. Do not publish environment dumps, authentication files, or screenshots containing private data.

Schema changes must preserve existing local data. New adapters must state supported versions, paths, and limitations. Avoid unnecessary runtime dependencies.
