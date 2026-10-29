/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Memory monitor: periodically logs heap usage to the serial console.
 */
#ifndef ATALAIA_MEM_MONITOR_H
#define ATALAIA_MEM_MONITOR_H

/* Start the memory monitor (low-priority task, 10 s interval). */
void mem_monitor_start(void);

/* One log line with the internal and DMA-capable RAM free, the largest free block of each, the
 * lowest internal free since boot and the PSRAM free, tagged with `when` ("boot", "join", "Wi-Fi
 * starting"...): the figures the memory budget is read from (README.md, "Memory budget"). */
void mem_monitor_log(const char *when);

#endif /* ATALAIA_MEM_MONITOR_H */
