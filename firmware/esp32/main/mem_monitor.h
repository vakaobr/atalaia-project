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

#endif /* ATALAIA_MEM_MONITOR_H */
