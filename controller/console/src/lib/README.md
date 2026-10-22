<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Vendored libraries

The GM console has no build step (ADR-P2-10): these ES modules are copied byte for byte from their npm packages, whose tarballs were checked against the `integrity` (SHA-512) and `shasum` (SHA-1) that registry.npmjs.org publishes. `controller/tests/test_console.py` checks the SHA-256 below, so a changed file fails CI. Their licences are in [`LICENSES/`](../../../../LICENSES/) and [`REUSE.toml`](../../../../REUSE.toml).

| File | Package | From | Licence | SHA-256 |
| --- | --- | --- | --- | --- |
| `preact.module.js` | preact 10.24.3 | `dist/preact.module.js` | MIT, © 2015-present Jason Miller | `9ba8bb591b0c9a72132ff65a76e69c5a4e49cf71721b47b659f3243658bde05b` |
| `htm.module.js` | htm 3.1.1 | `dist/htm.module.js` | Apache-2.0, © 2018 Google Inc. | `ab33dd3f38059b9be4d5f5350128eefb2356639c4e0bbe9d9e8b3ba75847e9e4` |
| `qrcode.module.js` | qrcode-generator 2.0.4 | `dist/qrcode.mjs` (renamed: `.js` is served as JavaScript everywhere) | MIT, © 2009 Kazuhiko Arase | `ea91d7118a5395289170da848b7c6758b996163bfbccf312591ab65a4911b7c0` |

Package tarballs as checked:

| Tarball | npm `shasum` (SHA-1) | npm `integrity` |
| --- | --- | --- |
| preact-10.24.3.tgz | `086386bd47071e3b45410ef20844c21e23828f64` | `sha512-Z2dPnBnMUfyQfSQ+GBdsGa16hz35YmLmtTLhM169uW944hYL6xzTYkJjC07j+Wosz733pMWx0fgON3JNw1jJQA==` |
| htm-3.1.1.tgz | `49266582be0dc66ed2235d5ea892307cc0c24b78` | `sha512-983Vyg8NwUE7JkZ6NmOqpCZ+sh1bKv2iYTlUkzlWmA5JD2acKoxd4KVxbMmxX/85mtfdnDmTFoNKcg5DGAvxNQ==` |
| qrcode-generator-2.0.4.tgz | `e8b3f30922577eba52078aa9c0d5a2a74fe1fd94` | `sha512-mZSiP6RnbHl4xL2Ap5HfkjLnmxfKcPWpWe/c+5XxCuetEenqmNFf1FH/ftXPCtFG5/TDobjsjz6sSNL0Sr8Z9g==` |

Notes:

- `preact.module.js` ends with a `sourceMappingURL` comment for a `.map` file that is not vendored. Browsers only fetch it while their developer tools are open; the console works without it.
- `preact/hooks` is not used: it imports the bare specifier `preact`, which would need an inline import map, and the console's Content-Security-Policy allows no inline scripts. The components are class components.
- To update a library: download the new tarball, check it against the registry metadata, copy the same file, and update this table and the checksums in `controller/tests/test_console.py`.
