/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The radio task's transmit stage (radio_lbt.h).
 */
#include "radio_lbt.h"

#include <string.h>

void radio_txs_init(radio_txs_t *t, const hal_radio_ops_t *radio, bool enabled,
                    atalaia_lbt_rand_fn rand, void *rand_ctx)
{
    memset(t, 0, sizeof(*t));
    t->radio = radio;
    t->enabled = enabled;
    atalaia_lbt_init(&t->lbt, rand, rand_ctx);
}

bool radio_txs_busy(const radio_txs_t *t)
{
    return t->has;
}

bool radio_txs_load(radio_txs_t *t, const radio_tx_msg_t *msg, uint32_t now_ms)
{
    if (t->has) return false;
    t->msg = *msg;
    t->has = true;
    t->due_ms = now_ms;
    atalaia_lbt_reset(&t->lbt);
    return true;
}

uint32_t radio_txs_wait_ms(const radio_txs_t *t, uint32_t now_ms)
{
    if (!t->has) return 0;
    int32_t left = (int32_t)(t->due_ms - now_ms);
    return left > 0 ? (uint32_t)left : 0;
}

/* The send itself, as the radio task always did it: the duty-cycle budget is looked at here. */
static radio_tx_status_t do_send(radio_txs_t *t)
{
    const hal_radio_ops_t *radio = t->radio;
    if (radio->duty_cycle_remaining_ms() == 0) return RADIO_TX_RESULT_DUTY_CYCLE;
    int rc = radio->send(t->msg.data, t->msg.len);
    if (rc == -3) return RADIO_TX_RESULT_DUTY_CYCLE; /* its time on air does not fit what is left */
    if (rc != 0) return RADIO_TX_RESULT_ERROR;
    return RADIO_TX_RESULT_OK;
}

radio_txs_state_t radio_txs_step(radio_txs_t *t, uint32_t now_ms, uint32_t *tag,
                                 radio_tx_status_t *status)
{
    if (!t->has) return RADIO_TXS_IDLE;
    if ((int32_t)(now_ms - t->due_ms) < 0) return RADIO_TXS_WAITING;

    if (t->enabled && t->radio->channel_busy != NULL && t->radio->duty_cycle_remaining_ms() > 0) {
        bool busy;
        if (atalaia_lbt_should_listen(&t->lbt)) {
            hal_radio_busy_t info;
            busy = hal_radio_channel_busy(t->radio, &info);
            if (info.cad_us != 0) t->stats.cads++;
        } else {
            busy = true; /* eight waits spent: the frame goes without another look */
        }
        uint32_t wait_ms = 0;
        atalaia_lbt_verdict_t v = atalaia_lbt_decide(&t->lbt, busy, &wait_ms);
        if (v == ATALAIA_LBT_WAIT) {
            t->stats.deferrals++;
            t->due_ms = now_ms + wait_ms;
            return RADIO_TXS_WAITING;
        }
        if (v == ATALAIA_LBT_SEND_ANYWAY) t->stats.gave_up++;
    }

    *tag = t->msg.tag;
    *status = do_send(t);
    t->has = false;
    return RADIO_TXS_DONE;
}
