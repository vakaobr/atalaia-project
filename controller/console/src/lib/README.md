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

## Blockly, for the scenario blocks

The *Scenarios* tab's block view (phase 5 plan phase 7, decisions P5F-1 to P5F-12) uses **Blockly 13.3.0**, the same release as the mode editor (ADR-P5-1 as amended, decision P5R-4). The files in `blockly/` are copied byte for byte from the mode editor's copy, `simulator/atalaia_sim/editor/vendor/blockly/`, whose README has the npm tarball (blockly-13.3.0.tgz, `shasum` `18947fe0f4992bbf1ee5051e2d18dabee7ee9581`) they were checked against; the SHA-256 below are the same there. Only what the block view uses is here: the core (a UMD script that sets `window.Blockly`, loaded with a `<script>` element only when the block view opens), Blockly's own texts in English and European Portuguese, and the media its stylesheet and icons name. Not Blockly's own blocks, its Lua generator, its sounds (the view turns sounds off) or the text blocks' images. Licence: Apache-2.0, © 2011 Google LLC ([`REUSE.toml`](../../../../REUSE.toml)).

| File | SHA-256 |
| --- | --- |
| `blockly/blockly_compressed.js` | `d3f46af56951a7aed27f09f872dca66ed70a932ca8be9aade3d9df06ceacd078` |
| `blockly/msg/en.js` | `155b0e29ad2bd59ad463ebde5c3ace7685ea5c25d019e950aab625b3259d7e02` |
| `blockly/msg/pt.js` | `6ff9ce8534c68b16c3ff463d598a7bd1b6d28c534e9eec038d349f13f9478579` |
| `blockly/media/delete-icon.svg` | `3eee02b06f476ce746566808178543389e53cd4e9d7fd32b69e329eff4fc71ef` |
| `blockly/media/foldout-icon.svg` | `0ac7478b56f5e5cc583c26710cb7ee5edcedb563cde65cd2385f4dd3e9e08c64` |
| `blockly/media/handclosed.cur` | `4a1637e16f33e1b02f96f699ada695edededfd089530372126d375ad9ed2f0a5` |
| `blockly/media/handdelete.cur` | `e53ef200d76fef617bd2e307a100d778834ad49784f80c1abc6da547e50b8040` |
| `blockly/media/handopen.cur` | `d2ec9a81d9a76b0f64b7168e5f05ee660ffb6ba7e35695caaf9851e6b01a04fd` |
| `blockly/media/resize-handle.svg` | `c95d07b3fb3aaa088e6665061b01952e7ea9dda462b7032a85e095bf8a12855b` |
| `blockly/media/sprites.svg` | `862de0ee081fa9baf504e673736d7446439c15246452258cab964a82566ef40f` |

Blockly writes two stylesheets into the page as `<style>` elements: its own (with the media folder's path in it) and its renderer's (with the renderer's and the theme's names in it). The console's Content-Security-Policy still refuses inline styles; it allows exactly these two texts by their SHA-256 (`style-src 'self' 'sha256-...'`, `SECURITY_HEADERS` in `controller/atalaia_controller/api.py`, decision P5F-2). A comment's bubble would set an inline `style` attribute, so the view has no comments. When Blockly is updated, the browser test `test_scenario_blocks_styles_are_the_allowed_ones` fails and prints the new hashes.

## Notes

- `preact.module.js` ends with a `sourceMappingURL` comment for a `.map` file that is not vendored. Browsers only fetch it while their developer tools are open; the console works without it.
- `preact/hooks` is not used: it imports the bare specifier `preact`, which would need an inline import map, and the console's Content-Security-Policy allows no inline scripts. The components are class components.
- To update a library: download the new tarball, check it against the registry metadata, copy the same file, and update this table and the checksums in `controller/tests/test_console.py`.
