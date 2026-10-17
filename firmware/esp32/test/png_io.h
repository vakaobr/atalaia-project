/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * PNG files for the screen tests, through the vendored stb headers.
 */
#ifndef ATALAIA_FW_PNG_IO_H
#define ATALAIA_FW_PNG_IO_H

#include <stdbool.h>
#include <stdint.h>

/* Write 8-bit RGB pixels as a PNG file. */
bool png_write_rgb(const char *path, int w, int h, const uint8_t *rgb);

/* Read a PNG file as 8-bit RGB. Returns NULL if it cannot be read; free with png_free(). */
uint8_t *png_read_rgb(const char *path, int *w, int *h);
void png_free(uint8_t *pixels);

#endif /* ATALAIA_FW_PNG_IO_H */
