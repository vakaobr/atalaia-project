

## How the parts talk to each other: docs/architecture.md and its page (ARCH-1 to ARCH-3, SITEARCH-1 to SITEARCH-6, 2026-10-28)

The maintainer asked for Mermaid diagrams of how the parts talk (radio, app, controller, site server) and then for SVG versions on the project page. Seven diagrams, checked against the code; the differences between the older design text and the code are a table at the end of docs/architecture.md. The page "How it fits together" shows them in four languages (German and Chinese labels are drafts). The Portuguese version of docs/architecture.md follows.

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| ARCH-1 | Where do docs and code differ, and which wins? | Code and protocol docs win; the differences are a table at the end of architecture.md. | Avoids repeating spec text the code no longer matches. | built (2026-10-28); open for the maintainer's review |
| ARCH-2 | Show the "hub" as a node? | As a note on the site server node ("self-hosted, or hosted by the hub"), with a paragraph saying it is not a separate program. | Only hosted mode exists, in the site server. | built (2026-10-28); open for the maintainer's review |
| ARCH-3 | NFC and BLE beacons in the whole-system diagram? | No; in the link legend and sections 4 and 6. | Not device-to-device links; keeps the diagram within ~15 nodes. | built (2026-10-28); open for the maintainer's review |

| # | Question | Answer chosen | Why | Status |
| --- | --- | --- | --- | --- |
| SITEARCH-1 | Where do the diagrams go? | A new page "How it fits together" (/como-se-liga/, /en/how-it-fits/, /de/zusammenspiel/, /zh-tw/how-it-fits/), a nav entry, links from the roadmap and build pages. | Seven diagrams make a long page; roadmap and build stay short. | built (2026-10-28); open for the maintainer's review |
| SITEARCH-2 | How are the labels translated? | .mmd templates with {{ arch.tNNN }} keys in the four yaml files; identical texts share a key; the English fill must equal the doc's block (--check). | Written once; cannot drift per language or from the GitHub version. | built (2026-10-28); open for the maintainer's review |
| SITEARCH-3 | Bold box titles without HTML labels? | Mermaid markdown strings (**x** and a newline), in the doc too. | With htmlLabels off, HTML tags show as text. | built (2026-10-28); open for the maintainer's review |
| SITEARCH-4 | Light and dark? | Each SVG has its own --ad-* colour variables from the site palette plus a prefers-color-scheme: dark override; shown as <img>. | Self-contained, no JavaScript; the site itself only follows prefers-color-scheme. | built (2026-10-28); open for the maintainer's review |
| SITEARCH-5 | How does CI know an SVG is stale? | A SHA-256 fingerprint of the filled source plus render_diagrams.py in each SVG; build_site --check compares it. | CI cannot run Mermaid. | built (2026-10-28); open for the maintainer's review |
| SITEARCH-6 | Wide diagrams? | Shown at 0.8 of drawn size in a horizontally scrolling box, with an "open full size" link. | Shrinking a 2,400 px diagram makes the text unreadable. | built (2026-10-28); open for the maintainer's review |
