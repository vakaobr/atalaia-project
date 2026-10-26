/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The bench test of listen-before-talk's gate (decision SL-25; docs/runbooks/lbt-bench-gate.md).
 * Bench images only (Kconfig ATALAIA_LBT_BENCH). The arithmetic is lbt_stats.h's.
 */
#ifndef ATALAIA_LBT_BENCH_H
#define ATALAIA_LBT_BENCH_H

/*
 * The console line "@lbt <args>": "tx [frames]" (this board sends frames of a STATE's length at
 * random 300-700 ms gaps), "probe [frames [gap_min_us gap_max_us]]" (this board probes the channel
 * every few milliseconds and receives them), "stop", "status". The answer goes to the log.
 * Add "proxy=as923 [peak=N] [min=N] [power=dBm]" to tx or probe to run AS923-TW's modulation
 * (SF9/500 kHz, its CAD settings, peak/min overridable for a sweep) on 868.3 MHz under EU868
 * sub-band g's limits (1 %, 25 mW ERP); see radio/lbt_profile.h.
 */
void lbt_bench_command(const char *args);

#endif /* ATALAIA_LBT_BENCH_H */
