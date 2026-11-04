# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The I2C output module's firmware (README.md): an RP2040 board on the expansion port, behind an
# I2C isolator, switching up to 4 relays or MOSFETs from its own supply.
#
# The UF2 (pico-sdk 2.2.0 and picotool, as increment 8's tools/docker_module.py image has them):
#   PICO_SDK_PATH=/opt/pico-sdk cmake -S firmware/output-module -B build/output-module
#   cmake --build build/output-module        -> build/output-module/atalaia_output_module.uf2
#   (-DOUTPUT_CHANNELS="relay:siren:60:0,relay:strobe:120:0,relay:smoke:30:30:sense": what is
#    fitted; README.md, "The channel list")
#
# Its portable parts on the host (the channel list, the guard, the watchdog's policy, the supply
# sense, the I2C events, the module core under them):
#   cmake -S firmware/output-module -B build/output-module-host -DOUTPUT_MODULE_HOST_TESTS=ON
#   cmake --build build/output-module-host && ctest --test-dir build/output-module-host
cmake_minimum_required(VERSION 3.13)

option(OUTPUT_MODULE_HOST_TESTS "Build the host tests instead of the RP2040 firmware" OFF)
set(OUTPUT_CHANNELS "" CACHE STRING
    "The channel list (README.md); empty: four relay channels, generic, 30 s max on")

if(NOT OUTPUT_MODULE_HOST_TESTS)
    if(NOT DEFINED PICO_SDK_PATH AND DEFINED ENV{PICO_SDK_PATH})
        set(PICO_SDK_PATH $ENV{PICO_SDK_PATH})
    endif()
    if(NOT DEFINED PICO_SDK_PATH)
        message(FATAL_ERROR "PICO_SDK_PATH is not set: build in the pico-sdk image of increment 8 "
                            "(tools/docker_module.py)")
    endif()
    set(PICO_BOARD pico CACHE STRING "")
    include(${PICO_SDK_PATH}/external/pico_sdk_import.cmake)
endif()

project(atalaia_output_module LANGUAGES C CXX ASM VERSION 1.0.0)

add_subdirectory(${CMAKE_CURRENT_LIST_DIR}/../module-core module-core)

add_library(atalaia_output_portable STATIC src/output.c)
target_include_directories(atalaia_output_portable PUBLIC src)
target_link_libraries(atalaia_output_portable PUBLIC atalaia_module_core)
set_target_properties(atalaia_output_portable PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON
                                                         C_EXTENSIONS OFF)

if(OUTPUT_MODULE_HOST_TESTS)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(atalaia_output_portable PRIVATE -Wall -Wextra -Wpedantic
                                                               -Wconversion -Wshadow -Werror)
    endif()
    enable_testing()
    add_executable(test_output_module test/test_output_module.c)
    target_link_libraries(test_output_module PRIVATE atalaia_output_portable)
    set_target_properties(test_output_module PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON
                                                        C_EXTENSIONS OFF)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(test_output_module PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME output_module COMMAND test_output_module)
    return()
endif()

pico_sdk_init()

# A channel list the firmware would refuse fails the build here, not on the bench (the firmware
# checks it again at power-up: output_parse_channels).
if(NOT OUTPUT_CHANNELS STREQUAL "")
    string(REPLACE "," ";" _channels "${OUTPUT_CHANNELS}")
    list(LENGTH _channels _count)
    if(_count GREATER 4 OR OUTPUT_CHANNELS MATCHES ",$|^,")
        message(FATAL_ERROR "OUTPUT_CHANNELS: 1 to 4 channels joined by ',' (README.md)")
    endif()
    foreach(_channel IN LISTS _channels)
        if(NOT _channel MATCHES
           "^(relay|solid):(generic|siren|strobe|smoke|light|horn):([0-9]+):([0-9]+)(:sense)?$")
            message(FATAL_ERROR "OUTPUT_CHANNELS: '${_channel}' is not "
                                "type:hint:max_on:min_off[:sense] (README.md)")
        endif()
        if(CMAKE_MATCH_3 LESS 1 OR CMAKE_MATCH_3 GREATER 255 OR CMAKE_MATCH_4 GREATER 255)
            message(FATAL_ERROR "OUTPUT_CHANNELS: '${_channel}': max on 1-255, min off 0-255")
        endif()
    endforeach()
endif()

add_executable(atalaia_output_module src/main.c)
if(NOT OUTPUT_CHANNELS STREQUAL "")
    target_compile_definitions(atalaia_output_module PRIVATE OUTPUT_CHANNELS="${OUTPUT_CHANNELS}")
endif()
target_compile_options(atalaia_output_module PRIVATE -Wall -Wextra -Werror)
target_link_libraries(atalaia_output_module PRIVATE atalaia_output_portable pico_stdlib
    pico_i2c_slave pico_unique_id hardware_adc hardware_i2c hardware_irq hardware_watchdog)
# No USB stdio: a module on the field has nothing to say over it, and its USB is for flashing only.
pico_enable_stdio_usb(atalaia_output_module 0)
pico_enable_stdio_uart(atalaia_output_module 0)
pico_add_extra_outputs(atalaia_output_module)
