<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Vendored Blockly

The mode editor has no build step and must work with no network (ADR-P5-1 as amended 2026-10-22, decision P5R-4): these files are copied byte for byte from the npm package **blockly 13.3.0** (published 2026-09-10), whose tarball was checked against the `integrity` (SHA-512) and `shasum` (SHA-1) that registry.npmjs.org publishes. `simulator/tests/test_editor_files.py` checks the SHA-256 below, so a changed file fails CI. Blockly's licence is Apache-2.0 ([`LICENSES/Apache-2.0.txt`](../../../../../LICENSES/Apache-2.0.txt), [`REUSE.toml`](../../../../../REUSE.toml)).

| Tarball | npm `shasum` (SHA-1) | npm `integrity` |
| --- | --- | --- |
| blockly-13.3.0.tgz | `18947fe0f4992bbf1ee5051e2d18dabee7ee9581` | `sha512-qAHFGMGTSF67Lupr3pjZz9LQu4JCFdN76CMZxegBKiveZreK08yXhaCz0g9q9/xe5GEdoeFT3POAlQavPIRPEw==` |

| File | From the package | SHA-256 |
| --- | --- | --- |
| `blockly_compressed.js` | `blockly_compressed.js` (the core, UMD: `window.Blockly`) | `d3f46af56951a7aed27f09f872dca66ed70a932ca8be9aade3d9df06ceacd078` |
| `blocks_compressed.js` | `blocks_compressed.js` (Blockly's own blocks: logic, loops, math, text, lists, variables, functions) | `25284edec82c518a4699a6c2e763f6a47ba863e93327c7c9685bd9a5c6edc812` |
| `lua_compressed.js` | `lua_compressed.js` (the Lua generator the editor's generator extends: `window.lua`) | `7426d6fb2686e5c3009bdcf078ab946e1bc3151ba2a40b82f37bb7cac3436d4a` |
| `msg/en.js` | `msg/en.js` (Blockly's own texts in English) | `155b0e29ad2bd59ad463ebde5c3ace7685ea5c25d019e950aab625b3259d7e02` |
| `msg/pt.js` | `msg/pt.js` (in European Portuguese; `pt-br.js` is not used) | `6ff9ce8534c68b16c3ff463d598a7bd1b6d28c534e9eec038d349f13f9478579` |
| `msg/de.js` | `msg/de.js` (in German, decision P5H-2) | `dfddfebd68232fcb47771881e57c99f9fe5514bfbf33ed4a9036007508f5e0d4` |
| `msg/zh-hant.js` | `msg/zh-hant.js` (in Traditional Chinese, for the editor's `zh-tw`; `zh-hans.js` is not used) | `4a952c0c38abfaa27be00d2adbd02ddb989e1ddbf078d6057b0927f50d76de81` |
| `media/1x1.gif` | `media/` | `a1d88b2c952b790f5f23473c63ef99473327d02e11ebe174799ad912db08f629` |
| `media/click.mp3` | `media/` | `1048f2539ac47e4eaa4bd1688968c0d7b9956bd6fef507644ee5131924c6517c` |
| `media/delete-icon.svg` | `media/` | `3eee02b06f476ce746566808178543389e53cd4e9d7fd32b69e329eff4fc71ef` |
| `media/delete.mp3` | `media/` | `6ea0afab062cb3ba5409dc65d7a9fdf85d602b1870d231d80bdf3cc5b32432b6` |
| `media/disconnect.mp3` | `media/` | `849465a8968836ab5b24b68a7289ee76ca1a6a50ba87a295a32efe1e507e3451` |
| `media/drop.mp3` | `media/` | `6c76cac85b42494683549938729f9994eec9ce03a940e5b4e1ef18279dea01ff` |
| `media/dropdown-arrow.svg` | `media/` | `bc3873b086b25a01c417cb3b5fe61fd7eef360b8f7c85c2c7f7b802a2626faf9` |
| `media/foldout-icon.svg` | `media/` | `0ac7478b56f5e5cc583c26710cb7ee5edcedb563cde65cd2385f4dd3e9e08c64` |
| `media/handclosed.cur` | `media/` | `4a1637e16f33e1b02f96f699ada695edededfd089530372126d375ad9ed2f0a5` |
| `media/handdelete.cur` | `media/` | `e53ef200d76fef617bd2e307a100d778834ad49784f80c1abc6da547e50b8040` |
| `media/handopen.cur` | `media/` | `d2ec9a81d9a76b0f64b7168e5f05ee660ffb6ba7e35695caaf9851e6b01a04fd` |
| `media/pilcrow.png` | `media/` | `4e4aa37ce0c162b0239203e538a7ae8eee706554514ff611cfb3a94baaa66167` |
| `media/quote0.png` | `media/` | `a06f7a05d9c86851266e55357090d3af37ff24e116258c94d52c4f436c614c7c` |
| `media/quote1.png` | `media/` | `56c52fc75cf7d2926d7502aaa7e95efb46c229aa266306d932795325722aba35` |
| `media/resize-handle.svg` | `media/` | `c95d07b3fb3aaa088e6665061b01952e7ea9dda462b7032a85e095bf8a12855b` |
| `media/sprites.svg` | `media/` | `862de0ee081fa9baf504e673736d7446439c15246452258cab964a82566ef40f` |

Notes:

- Why 13.3.0 and not the 11.x the design named: 13 is the current major (keyboard navigation and screen-reader support by default, no `jsdom` dependency), and 13.3.0 was the newest release more than four weeks old when it was vendored; 13.4.0 (2026-10-13) was nine days old.
- The `.js` files end with a `sourceMappingURL` comment for a `.map` file that is not vendored; browsers fetch it only while their developer tools are open.
- The editor sets `media` to this folder (Blockly 13's default is blockly.com) and turns sounds off; the sounds stay so that the folder is the package's.
- To update: download the new tarball, check it against the registry metadata, copy the same files, update this table and the checksums in `simulator/tests/test_editor_files.py`, then run `python tools/docker_editor.py` (the generator and the round trip of every example).
