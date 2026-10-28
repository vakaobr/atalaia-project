<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# The field's privacy notice

Put the notice the field adopted here, one Markdown file per language and version:

    privacy-notice-pt-<version>.md
    privacy-notice-en-<version>.md
    privacy-notice-de-<version>.md
    privacy-notice-zh-tw-<version>.md

`<version>` is the value of `ATALAIA_PRIVACY_NOTICE_VERSION` in `.env` (for example `campo-tejo-2026-11`). Start from
[`docs/templates/privacy-notice-pt.md`](../../docs/templates/privacy-notice-pt.md) and
[`privacy-notice-en.md`](../../docs/templates/privacy-notice-en.md): fill in and remove every mark, and keep Part A
(the full notice) as the file's text. The text is the operator's; the server only serves it.

The server shows the files of the current version at `/privacy` and, as JSON, at `GET /api/v1/privacy-notice`. When
the notice changes, add the new files and raise `ATALAIA_PRIVACY_NOTICE_VERSION`: every account is then asked to
consent again at its next sign-in (the old files can stay as the record). The folder is mounted read-only in the
server's container; files your own copy of this repository adds here are not committed (`.gitignore`).
