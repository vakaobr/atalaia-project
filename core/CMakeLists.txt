# SPDX-FileCopyrightText: 2026 The Atalaia contributors
# SPDX-License-Identifier: GPL-3.0-or-later

cmake_minimum_required(VERSION 3.16)
project(atalaia_core VERSION 0.0.1 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

add_library(atalaia_core
    src/version.c
    src/event.c
)
target_include_directories(atalaia_core PUBLIC include)

if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang")
    target_compile_options(atalaia_core PRIVATE -Wall -Wextra -Wpedantic -Werror)
endif()

include(CTest)
if(BUILD_TESTING)
    add_executable(test_core tests/test_core.c)
    target_link_libraries(test_core PRIVATE atalaia_core)
    add_test(NAME core COMMAND test_core)
endif()
