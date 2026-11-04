# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later
#
# The module core: the expansion port's protocol for a module's firmware (README.md).
#
# On its own (host tests, as CI runs them):
#   cmake -S firmware/module-core -B build/module-core && cmake --build build/module-core
#   ctest --test-dir build/module-core --output-on-failure
#
# From a module's firmware (pico-sdk or any CMake build):
#   add_subdirectory(<path to firmware/module-core> module-core)
#   target_link_libraries(<your firmware> PRIVATE atalaia_module_core)

cmake_minimum_required(VERSION 3.13)
project(atalaia_module_core LANGUAGES C)

add_library(atalaia_module_core STATIC src/module_core.c)
target_include_directories(atalaia_module_core PUBLIC include)
set_target_properties(atalaia_module_core PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON
                                                     C_EXTENSIONS OFF)

# The host tests, only when this folder is the top of the build (never inside a module's firmware).
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(atalaia_module_core PRIVATE -Wall -Wextra -Wpedantic -Wconversion
                                                           -Wshadow -Werror)
    endif()
    enable_testing()
    add_executable(test_module_core test/test_module_core.c)
    target_link_libraries(test_module_core PRIVATE atalaia_module_core)
    set_target_properties(test_module_core PROPERTIES C_STANDARD 11 C_STANDARD_REQUIRED ON
                                                      C_EXTENSIONS OFF)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
        target_compile_options(test_module_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
    endif()
    add_test(NAME module_core COMMAND test_module_core)
endif()
