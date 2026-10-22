# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The host modem: the USB radio modem's logic with real AES-CCM (mbedtls),
# for the field controller's integration tests (controller/tests/).
#   cmake -S firmware/esp32/test/modem_host -B build/modem_host
#   cmake --build build/modem_host
cmake_minimum_required(VERSION 3.18)
project(atalaia_modem_host LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

get_filename_component(CORE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../../core" ABSOLUTE)
get_filename_component(MAIN_DIR "${CMAKE_CURRENT_LIST_DIR}/../../main" ABSOLUTE)

# Static when there is a static library, so the binary also runs where mbedtls is
# not installed (the Flutter image: the app's radio-link tests use it too).
find_library(MBEDCRYPTO_LIB NAMES libmbedcrypto.a mbedcrypto)
find_path(MBEDTLS_INCLUDE_DIR mbedtls/ccm.h)
if(NOT MBEDCRYPTO_LIB OR NOT MBEDTLS_INCLUDE_DIR)
    message(FATAL_ERROR "The host modem needs mbedtls for real AES-CCM "
        "(Debian/Ubuntu: apt install libmbedtls-dev; the atalaia-dev image has it).")
endif()

add_executable(modem_host
    modem_host.c
    ${MAIN_DIR}/modem/modem.c
    ${MAIN_DIR}/modem/modem_framing.c
    ${MAIN_DIR}/radio/radio_protocol.c
    ${MAIN_DIR}/radio/radio_task.c
    ${MAIN_DIR}/radio/radio_limits.c
    ${MAIN_DIR}/radio/noise_stats.c
    ${CORE_DIR}/src/packet.c
    ${CORE_DIR}/src/crypto_mbedtls.c
    ${CORE_DIR}/src/codec.c
    ${CORE_DIR}/src/event.c
    ${CORE_DIR}/src/protocol.c
    ${CORE_DIR}/src/msg_codec.c
    ${CORE_DIR}/src/version.c
    ${CORE_DIR}/src/duty_cycle.c
    ${CORE_DIR}/src/join.c # atalaia_hmac_sha256: the epoch store tag (radio_protocol.c)
)
target_include_directories(modem_host PRIVATE
    ${CORE_DIR}/include ${CORE_DIR}/src ${MAIN_DIR} ${MBEDTLS_INCLUDE_DIR})
target_compile_definitions(modem_host PRIVATE ATALAIA_HAVE_MBEDTLS)
target_link_libraries(modem_host PRIVATE ${MBEDCRYPTO_LIB})
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(modem_host PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()
