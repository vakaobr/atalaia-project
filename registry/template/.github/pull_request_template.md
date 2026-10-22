## What does this pull request do?

<!-- One of: a new mode, a new version of a mode, a new author key, the verified badge,
     a revocation, a takedown, a change to the registry itself. -->

**Mode id and version:**

**What the game is** (as you would brief players):

## The author

- [ ] I wrote this mode, or have the right to share it under the licence in its `mode.yaml`
- [ ] Nothing in it comes from a commercial product (Atalaia's clean-room policy)
- [ ] Every commit is signed off (`git commit -s`)
- [ ] A new key in `keys/authors/` is mine, and its `owner` is the account opening this pull request

## The checks (the CI does these)

- [ ] `registry_check.py lint` passes: signatures, the source packs to the archive, licence headers, no names the sandbox removes, assets size, `i18n:` keys
- [ ] `registry_check.py test` passes: the mode's own tests in the simulator

## For the reviewer (review checklist items 6, 7, 8, 10)

- [ ] 6. No hard-coded team names, node counts or language strings; player texts in `mode.yaml` and its `i18n:`
- [ ] 7. Parameters have sensible defaults, `min`/`max` and labels
- [ ] 8. Standard events for standard things, `x.<author>.<name>` for custom ones
- [ ] 10. Nothing offensive, misleading or trademarked in the name, description or assets; the id does not imitate another mode's
- [ ] Verified badge only: the tests show the game working; the Lua uses the script API as documented; the reviewer is not the author
