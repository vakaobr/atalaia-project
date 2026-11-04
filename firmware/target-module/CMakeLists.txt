# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The target module's firmware (README.md): an RP2040 board on the expansion port.
#
# The UF2 (pico-sdk 2.2.0 and picotool, as tools/docker_module.py's image has them):
#   PICO_SDK_PATH=/opt/pico-sdk cmake -S firmware/target-module -B build/target-module
#   cmake --build build/target-module        -> build/target-module/atalaia_target_module.uf2
#   (-DTARGET_PLATES=2: the two-plate module, atalaia_target_module_2.uf2)
#
# Its portable parts on the host (the peak detector, the I2C events, the module core under them):
#   cmake -S firmware/target-module -B build/target-module-host -DTARGET_MODULE_HOST_TESTS=ON
#   cmake --build build/target-module-host && ctest --test-dir build/target-module-host
cmake_minimum_required(VERSION 3.13)

option(TARGET_MODULE_HOST_TESTS "Build the host tests instead of the RP2040 firmware" OFF)
set(TARGET_PLATES 1 CACHE STRING "Hit plates on the module: 1 or 2")

if(NOT TARGET_MODULE_HOST_TESTS)
    if(NOT DEFINED PICO_SDK_PATH AND DEFINED ENV{PICO_SDK_PATH})
        set(PICO_SDK_PATH $ENV{PICO_SDK_PATH})
    endif()
    if(NOT DEFINED PICO_SDK_PATH)
        message(FATAL_ERROR "PICO_SDK_PATH is not set: build with python3 tools/docker_module.py build")
    endif()
    set(PICO_BOARD pico CACHE STRING "")
    include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)
endif()

project(atalaia_target_module LANGUAGES C CXX ASM VERSION 1.0.0)

add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../module-core module-core)

add_library(atalaia_target_portable STATIC src/peak.c src/target.c)
target_include_directories(atalaia_target_portable PUBLIC src)
target_link_libraries(atalaia_target_portable PUBLIC atalaia_module_core)
set_target_properties(atalaia_target_portable PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON)

if(TARGET_MODULE_HOST_TESTS)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(atalaia_target_portable PRIVATE -Wall -Wextra -Wpedantic
                                                               -Wconversion -Werror)
    endif()
    enable_testing()
    add_executable(test_target_module test/test_target_module.c)
    target_link_libraries(test_target_module PRIVATE atalaia_target_portable)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(test_target_module PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME target_module COMMAND test_target_module)
    return()
endif()

pico_sdk_init()

if(TARGET_PLATES EQUAL 1)
    set(TARGET_MODULE_NAME atalaia_target_module)
else()
    set(TARGET_MODULE_NAME atalaia_target_module_${TARGET_PLATES})
endif()
add_executable(${TARGET_MODULE_NAME} src/main.c)
target_compile_definitions(${TARGET_MODULE_NAME} PRIVATE TARGET_PLATES=${TARGET_PLATES})
target_compile_options(${TARGET_MODULE_NAME} PRIVATE -Wall -Wextra -Werror)
target_link_libraries(${TARGET_MODULE_NAME} PRIVATE atalaia_target_portable pico_stdlib
    pico_i2c_slave pico_unique_id hardware_adc hardware_dma hardware_i2c hardware_irq
    hardware_watchdog hardware_clocks hardware_sync)
# No USB stdio: the port's 25 mA, and nothing to say over it.
pico_enable_stdio_usb(${TARGET_MODULE_NAME} 0)
pico_enable_stdio_uart(${TARGET_MODULE_NAME} 0)
pico_add_extra_outputs(${TARGET_MODULE_NAME})
