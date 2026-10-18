/* SPDX-FileCopyrightText: 2026 The Atalaia contributors */
/* SPDX-License-Identifier: GPL-3.0-or-later */

/*
 * The radio front-end module (FEM) of the Heltec WiFi LoRa 32 V4 boards,
 * from Heltec's public V4 pinout:
 *
 *   both revisions: GPIO 7 (VFEM_Ctrl) switches the FEM's LDO on (HIGH),
 *                   GPIO 2 (FEM_EN) is the FEM's chip enable (HIGH = on);
 *                   the SX1262's DIO2 drives the TX/RX switch.
 *   V4.2, GC1109:   GPIO 46 selects the PA (HIGH = full PA, LOW = bypass).
 *   V4.3, KCT8103L: GPIO 5 selects the receive path (LOW = LNA, HIGH = bypass).
 *
 * This file only plans the pin steps (which pin, which level, in which
 * order), so the order is tested on the host; hal_esp_radio.c applies
 * them, and only after the SX1262 has answered its probe (the Wokwi
 * emulator has no SX1262 and uses GPIO 7 for its keypad).
 */
#ifndef BOARD_FEM_H
#define BOARD_FEM_H

#include <stddef.h>
#include <stdint.h>

typedef enum {
    BOARD_FEM_NONE = 0,     /* no FEM: nothing to drive */
    BOARD_FEM_GC1109 = 1,   /* Heltec V4.2 */
    BOARD_FEM_KCT8103L = 2, /* Heltec V4.3 */
} board_fem_t;

typedef struct {
    board_fem_t fem;
    int power_pin;  /* FEM LDO enable (VFEM_Ctrl), HIGH = powered; -1 = none */
    int enable_pin; /* FEM chip enable (FEM_EN), HIGH = on; -1 = none */
    int pa_pin;     /* GC1109 PA select, HIGH = full PA; -1 = none */
    int ctx_pin;    /* KCT8103L receive path, LOW = LNA; -1 = none */
} board_fem_pins_t;

typedef struct {
    int pin;
    uint8_t level;
    uint16_t delay_us; /* wait after setting it */
} board_pin_step_t;

#define BOARD_FEM_MAX_STEPS     4
#define BOARD_FEM_LDO_SETTLE_US 1000 /* the LDO's output settles before the FEM is enabled */

/*
 * The steps that power the FEM for normal use: LDO on, then the mode pin
 * (PA on the GC1109, LNA on the KCT8103L), then the chip enable. Pins set
 * to -1 are skipped. Returns the number of steps written (at most max).
 */
size_t board_fem_power_on(const board_fem_pins_t *pins, board_pin_step_t *steps, size_t max);

/* The reverse: chip enable off, mode pin low, LDO off. */
size_t board_fem_power_off(const board_fem_pins_t *pins, board_pin_step_t *steps, size_t max);

/*
 * The first of pins[0..n) (others' GPIOs, e.g. the team buttons) that the
 * FEM also drives, or -1. Unassigned pins (-1) never conflict.
 */
int board_fem_conflict(const board_fem_pins_t *fem, const int *pins, size_t n);

/* "GC1109 (Heltec V4.2)", "KCT8103L (Heltec V4.3)" or "none". */
const char *board_fem_name(board_fem_t fem);

#endif /* BOARD_FEM_H */
