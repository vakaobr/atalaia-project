// SPDX-FileCopyrightText: 2026 The Atalaia contributors
// SPDX-License-Identifier: AGPL-3.0-or-later
//
// A field's roles (GET, PUT /api/v1/fields/{field}/roles; DELETE .../roles/{user_id}/{role}): who holds which
// role at the field, for its admin (every role) and its gm (player, squad leader, VIP, spectator).

import { boot, fieldApi } from './staff.js';
import { mount } from './rolestable.js';

async function main() {
    const ctx = await boot();
    if (ctx) await mount(fieldApi('/roles'), ctx.zone);
}

main();
