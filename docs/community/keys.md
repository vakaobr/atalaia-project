<!--
SPDX-FileCopyrightText: 2026 The Atalaia contributors
SPDX-License-Identifier: CC-BY-SA-4.0
-->

# Mode keys

A mode key is an Ed25519 key pair made by `tools/mode_package.py keygen`
(decision P5C-12). Its private half signs packages and never goes into any
repository (the tools refuse a key inside one); its public half goes into the
registry's `keys/` and into the configuration of whoever trusts it. Decisions
P5G-2, P5G-3 and P5G-7.

## Kinds of key

| Key | Held by | Signs | Trusted by |
| --- | --- | --- | --- |
| An **author key** | the author (a person or a club) | the author's own packages (`.release.json`) | fields that choose to (`[modes] keys`) |
| The **project's registry key** | the maintainer (P5G-3) | the verified badge (`.verified.json`) | fields that trust the project, and every Field Box (`CONFIG_ATALAIA_MODE_KEYS`) |
| A **firmware release key** | the maintainer | firmware releases; it may sign modes (P5B-9), but the registry uses its own key | boxes, for updates |

The project's registry key is a separate key from the firmware release keys, so
day-to-day reviews never need the key that can replace a box's firmware.

## The project's keys

Since 2026-10-28 the project has **two** registry keys, both listed in the
registry's `keys/project/` and built into the Field Box firmware's default
`CONFIG_ATALAIA_MODE_KEYS` and the Android app's default mode keys:

| Key | Key id | Public key (base64) | Where it lives | Used for |
| --- | --- | --- | --- | --- |
| **Root** | `d9521a79030ce544` | `I+m3rO++TcVNhvDHzI28pkNA8UGoTJSi84IWQguq4Mo=` | offline, with the maintainer only (as below); its passphrase kept apart | signing by hand when the CI key cannot be used, and re-signing every badge if the CI key is ever revoked |
| **CI** | `7275108d2e3fe583` | `0nMp0OGboGJZUMsbc/ykqkxQFNdmI/a2k4nQ6YsdTIY=` | the registry's GitHub secrets `ATALAIA_PROJECT_CI_KEY` (encrypted PEM) and `ATALAIA_PROJECT_CI_KEY_PASSPHRASE` | the verified badge, from the registry's *Verified badge* workflow, which a maintainer starts by hand and which opens a pull request |

Hex, for `--mode-keys` and `CONFIG_ATALAIA_MODE_KEYS`:
`23e9b7acefbe4dc54d86f0c7cc8dbca64340f141a84c94a2f38216420baae0ca`
(root) and
`d27329d0e19ba0625950cb1b73fca4aa4c5014d76623f6b69389d0e98b1d4c86` (CI).

This is a deliberate exception to "never in a CI secret" below, chosen by the
maintainer (2026-10-28) so that badges can be signed without the root key
leaving its offline media. What it means:

- **Who can sign with the CI key:** whoever can start the registry's workflows
  (write access to `vakaobr/atalaia-modes`) or change them, and whoever takes
  over such an account. Pull requests from forks never see the secret.
- **If the CI key may be exposed:** add it to the registry's `keys/revoked.json`
  (field controllers then refuse what it signed, and a box only gets modes from
  its controller), delete both secrets, make a new CI key and sign the badges
  again with it (or with the root key). The next firmware and app releases drop
  the old CI key from their defaults; until a box runs that firmware it still
  trusts the old key, but only for packages its own controller offers.
- **The root key** never goes into a secret, a repository or a chat. If both
  keys were lost, boxes would need a firmware release with new keys.

A field controller trusts the project's packages for its own installs only by
listing these keys in `[modes] keys` (`controller/controller.example.toml`);
`[modes] box_keys` defaults to them, as the firmware does.

## Making and keeping a key

```sh
python3 tools/mode_package.py keygen --out ~/atalaia-keys/my-modes.pem
```

It asks for a passphrase (PKCS#8, encrypted), writes the private key with mode
0600, and prints the key's id and public halves. Then:

- **Back it up** offline (a USB stick in a drawer, a password manager's file
  store). A lost key cannot sign a new version of your modes: you would add a
  new key (below).
- **Never** put it in a repository, a CI secret, a chat or a ticket. Signing
  happens on your own computer. (The project's CI key is the one exception,
  above.)
- **The project's registry key** lives only on offline media held by the
  maintainer, with a second copy in a separate place, and is used on a computer
  that is not the maintainer's daily one where possible. Its passphrase is not
  stored with it. Whether a second maintainer holds a copy is for the
  maintainer to decide (P5G-3).

Add your public key to the registry in your first pull request:

```sh
python3 tools/mode_package.py pubkey --key ~/atalaia-keys/my-modes.pem    # prints the base64 public key
python3 tools/registry_check.py key ../atalaia-modes --public <base64> --owner <your GitHub handle> \
    --name "Your name or club" --added 2026-10-22
```

## A new key (rotation)

Make a new key, add it with the same `--owner`, and sign new versions with it.
Older versions keep the old key's signature; that is fine while the old key is
not revoked. A key can be added at any time; keys are never deleted, only
revoked, so the history stays checkable.

## Revoking a key

A key is revoked when its private half may be known to someone else (lost
laptop, leaked file, a passphrase seen), when its owner asks, or as a
moderation decision ([`moderation.md`](moderation.md)).

1. **Who asks.** The owner opens an issue with the *Revoke a key* template
   (from the account named in the key file), or, if the key is being misused,
   reports it privately (`SECURITY.md`). A maintainer can revoke any key.
2. **One pull request, by a maintainer**, that:
   - adds `{"key_id": "...", "reason": "...", "date": "YYYY-MM-DD"}` to
     `keys/revoked.json`;
   - for every version the key signed: removes it from the index (and its files
     from `packages/`), or, if the author has a new key, replaces the author's
     signature with one by the new key (`registry_check.py add` again for the
     newest; for older ones `tools/mode_package.py sign --out ...` over the
     unchanged archive). The CI refuses a registry that still lists a version
     whose signature depends on a revoked key, so nothing is forgotten.
3. Merged, the published `revoked.json` changes at once. A field controller
   reading the index refuses anything the key signed, even if the key is in its
   own list (decision P5C-18: packages it already installed stay, marked
   *revoked*, until the GM replaces them).
4. Fields that listed the key in `[modes] keys` should remove it; the
   maintainer says so in the release notes and on the project page.

**The project's registry key.** If it is compromised, the steps above happen
for it too (every verified version loses its badge until it is signed by a new
project key), and, because boxes trust only keys built into their firmware, the
next signed firmware release removes it from `CONFIG_ATALAIA_MODE_KEYS` and adds
the new one; a box that boots with the new firmware drops the packages the old
key signed (`protocol/mode-packages.md`, "On the box"). Until then a box would
still take a package the stolen key signed, but only from its own field
controller, which refuses revoked keys: the window is the controllers that have
not read the new `revoked.json`.
