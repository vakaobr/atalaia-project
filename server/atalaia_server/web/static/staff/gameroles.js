// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// One game's roles (GET, PUT /api/v1/games/{game}/roles; DELETE .../roles/{user_id}/{role}): the roles an
// account holds in that game only, by the same rules as the field's.

import { boot, page } from './staff.js';
import { mount } from './rolestable.js';

async function main() {
    const ctx = await boot();
    if (ctx) await mount(`/api/v1/games/${encodeURIComponent(page.game)}/roles`, ctx.zone);
}

main();
