# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS components)

# The firmware's version (esp_app_desc_t, HELLO's fw_version, a firmware update's
# anti-rollback check; decisions FV-1 to FV-6): ATALAIA_FW_VERSION when given, else the
# core's version from core/include/atalaia/version.h (0.3.0-dev while 0.3.0 is developed).
# tools/docker_fw.py always gives one: a development build's carries its commit
# (0.3.0-dev.412+g8560d54; ".dirty" with uncommitted changes), a release the exact
# --fw-version. A plain `idf.py build`, or a copy with no git history, gets the core's.
# MAJOR.MINOR.PATCH[-pre-release][+build], at most 31 characters (esp_app_desc_t).
file(STRINGS "${CMAKE_CURRENT_LIST_DIR}/../../core/include/atalaia/version.h" ATALAIA_VERSION_LINES
     REGEX "#define ATALAIA_VERSION_(MAJOR|MINOR|PATCH|PRERELEASE) ")
set(ATALAIA_VERSION_PRERELEASE "")
foreach(line ${ATALAIA_VERSION_LINES})
    if(line MATCHES "ATALAIA_VERSION_(MAJOR|MINOR|PATCH) +([0-9]+)")
        set(ATALAIA_VERSION_${CMAKE_MATCH_1} ${CMAKE_MATCH_2})
    elseif(line MATCHES "ATALAIA_VERSION_PRERELEASE +\"([0-9A-Za-z.]*)\"")
        set(ATALAIA_VERSION_PRERELEASE "${CMAKE_MATCH_1}")
    endif()
endforeach()
set(ATALAIA_CORE_VERSION "${ATALAIA_VERSION_MAJOR}.${ATALAIA_VERSION_MINOR}.${ATALAIA_VERSION_PATCH}")
if(ATALAIA_VERSION_PRERELEASE)
    string(APPEND ATALAIA_CORE_VERSION "-${ATALAIA_VERSION_PRERELEASE}")
endif()
set(ATALAIA_FW_VERSION "" CACHE STRING "Firmware version; empty: the core's version")
if(ATALAIA_FW_VERSION)
    string(LENGTH "${ATALAIA_FW_VERSION}" ATALAIA_FW_VERSION_LEN)
    if(NOT ATALAIA_FW_VERSION MATCHES
           "^[0-9]+\\.[0-9]+\\.[0-9]+(-[0-9A-Za-z][0-9A-Za-z.]*)?(\\+[0-9A-Za-z][0-9A-Za-z.]*)?$"
       OR ATALAIA_FW_VERSION_LEN GREATER 31)
        message(FATAL_ERROR "ATALAIA_FW_VERSION=${ATALAIA_FW_VERSION}: "
                            "MAJOR.MINOR.PATCH[-pre-release][+build], at most 31 characters")
    endif()
    set(PROJECT_VER "${ATALAIA_FW_VERSION}")
else()
    set(PROJECT_VER "${ATALAIA_CORE_VERSION}")
endif()
message(STATUS "Atalaia firmware version ${PROJECT_VER} (core ${ATALAIA_CORE_VERSION})")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(atalaia_esp32)
