/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * The I2C output module's pins on an RP2040 board (a Raspberry Pi Pico or an
 * RP2040-Zero: every pin here is on both boards' headers).
 * hardware/output-module/BUILD.md's pin table lists each of them, and
 * tools/check_wiring.py fails when the two disagree: change both together.
 */
#ifndef ATALAIA_OUTPUT_BOARD_H
#define ATALAIA_OUTPUT_BOARD_H

#define OUT_PIN_JUMPER_A0    2  /* address jumper: closed to GND adds 1 */
#define OUT_PIN_JUMPER_A1    3  /* address jumper: closed to GND adds 2 */
#define OUT_PIN_SDA          4  /* i2c0 SDA, the I2C target, to the isolator's side 2 */
#define OUT_PIN_SCL          5  /* i2c0 SCL */
#define OUT_PIN_CH0          6  /* channel 0's relay or MOSFET input (high: on) */
#define OUT_PIN_CH1          7  /* channel 1 */
#define OUT_PIN_CH2          8  /* channel 2 */
#define OUT_PIN_CH3          9  /* channel 3 */
#define OUT_PIN_LED          14 /* the status LED (LOCATE, a fault) */
#define OUT_PIN_SUPPLY_SENSE 26 /* ADC0: the load supply's divider */

#endif /* ATALAIA_OUTPUT_BOARD_H */
