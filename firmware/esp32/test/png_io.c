/*
 * SPDX-FileCopyrightText: 2026 The Atalaia contributors
 * SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Holds the stb implementations. Built without the project's warning
 * flags (see CMakeLists.txt), like the vendored Lua.
 */
#include "png_io.h"

#define STBI_ONLY_PNG
#define STB_IMAGE_IMPLEMENTATION
#include "third_party/stb/stb_image.h"

#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "third_party/stb/stb_image_write.h"

bool png_write_rgb(const char *path, int w, int h, const uint8_t *rgb)
{
    return stbi_write_png(path, w, h, 3, rgb, w * 3) != 0;
}

uint8_t *png_read_rgb(const char *path, int *w, int *h)
{
    int channels;
    return stbi_load(path, w, h, &channels, 3);
}

void png_free(uint8_t *pixels)
{
    stbi_image_free(pixels);
}
