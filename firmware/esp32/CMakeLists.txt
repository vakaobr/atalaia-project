# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS components)

# The firmware's version (esp_app_desc_t, HELLO's fw_version, a firmware update's
# anti-rollback check): the core's version from core/include/atalaia/version.h, or
# ATALAIA_FW_VERSION when given (tools/docker_fw.py --fw-version, for a release
# candidate or a bench test of an update), MAJOR.MINOR.PATCH[-pre-release].
file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/../../core/include/atalaia/version.h" ATALAIA_VERSION_LINES
     REGEX "#define ATALAIA_VERSION_(MAJOR|MINOR|PATCH) ")
foreach(line ${ATALAIA_VERSION_LINES})
    string(REGEX MATCH "ATALAIA_VERSION_(MAJOR|MINOR|PATCH) +([0-9]+)" _ "${line}")
    set(ATALAIA_VERSION_${CMAKE_MATCH_1} ${CMAKE_MATCH_2})
endforeach()
set(ATALAIA_FW_VERSION "" CACHE STRING "Firmware version; empty: the core's version")
if(ATALAIA_FW_VERSION)
    if(NOT ATALAIA_FW_VERSION MATCHES "^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.]*)?$")
        message(FATAL_ERROR "ATALAIA_FW_VERSION=${ATALAIA_FW_VERSION}: MAJOR.MINOR.PATCH[-pre-release]")
    endif()
    set(PROJECT_VER "${ATALAIA_FW_VERSION}")
else()
    set(PROJECT_VER "${ATALAIA_VERSION_MAJOR}.${ATALAIA_VERSION_MINOR}.${ATALAIA_VERSION_PATCH}")
endif()

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(atalaia_esp32)
