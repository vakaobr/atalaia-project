# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The host pod: the I/O pod's code with real AES-CCM (mbedtls), for the
# app's Dart tests and the field controller's tests (see pod_host.c).
#   cmake -S firmware/esp32/test/pod_host -B build/pod_host
#   cmake --build build/pod_host
# mbedtls is linked statically when its static library is there (Ubuntu's
# libmbedtls-dev has it), so the binary also runs in the Flutter image,
# which has no mbedtls (tools/docker_app.py, CI's flutter-test).
cmake_minimum_required(VERSION 3.18)
project(atalaia_pod_host LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

get_filename_component(CORE_DIR "${CMAKE_CURRENT_LIST_DIR}/../../../../core" ABSOLUTE)
get_filename_component(MAIN_DIR "${CMAKE_CURRENT_LIST_DIR}/../../main" ABSOLUTE)

find_library(MBEDCRYPTO_LIB NAMES libmbedcrypto.a mbedcrypto)
find_path(MBEDTLS_INCLUDE_DIR mbedtls/ccm.h)
if(NOT MBEDCRYPTO_LIB OR NOT MBEDTLS_INCLUDE_DIR)
    message(FATAL_ERROR "The host pod needs mbedtls for real AES-CCM "
        "(Debian/Ubuntu: apt install libmbedtls-dev; the atalaia-dev image has it).")
endif()

add_executable(pod_host
    pod_host.c
    ${MAIN_DIR}/pod/pod.c
    ${MAIN_DIR}/pod/pod_caps.c
    ${MAIN_DIR}/pod/pod_json.c
    ${MAIN_DIR}/pod/pod_ble.c
    ${MAIN_DIR}/key_filter.c
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
    ${CORE_DIR}/src/proxy.c
    ${CORE_DIR}/src/tag.c
    ${CORE_DIR}/src/join.c
)
target_include_directories(pod_host PRIVATE
    ${CORE_DIR}/include ${CORE_DIR}/src ${MAIN_DIR} ${MBEDTLS_INCLUDE_DIR})
target_compile_definitions(pod_host PRIVATE ATALAIA_HAVE_MBEDTLS)
target_link_libraries(pod_host PRIVATE ${MBEDCRYPTO_LIB})
if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(pod_host PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()
