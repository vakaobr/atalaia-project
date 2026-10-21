# Security policy

Atalaia is pre-alpha and not ready for production use.

## Reporting a vulnerability

Please do **not** open a public issue for security problems. Use GitHub's private vulnerability reporting ("Report a vulnerability" under the repository's Security tab), or contact the maintainers privately.

Useful reports include:

- the affected component (core, firmware, app, controller, site server, protocol),
- steps to reproduce,
- the impact you expect, for example spoofed captures, leaked positions or edited chrono records.

We aim to acknowledge reports within 7 days.

## In scope

Game integrity matters as much as data security. Issues such as forged Skirmesh-RF packets, replayed events, players seeing enemy positions, or editable chrono records are all in scope.

## The field join key is a field secret

Every controller and box of a field shares one 32-byte **field join key** ([protocol/join.md](protocol/join.md)). It authenticates join cards and QR codes, and since boxes can be invited into the next game over the radio it also keys the **field frames** ([protocol/field-frames.md](protocol/field-frames.md)): an invite carries the game's key, encrypted under a key derived from the join key. Whoever holds the join key and records the field's radio can therefore read the keys of the games joined by invite, and with them those games' traffic. The maintainer accepted this trade-off (decision RJ-2 in `docs/review/decisions-to-review.md`). Keep the join key only on the controllers (their store, `controller.toml`) and in the boxes' encrypted NVS, never in logs, screenshots or tickets, and change it on every controller and box if one is lost or leaves the field.
