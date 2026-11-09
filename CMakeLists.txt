cmake_minimum_required(VERSION 3.16)
project(Sudoku VERSION 0.1.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

option(SUDOKU_ENABLE_SANITIZERS "Enable address and undefined-behavior sanitizers (GCC/Clang)" OFF)

add_executable(sudoku sudoku.c puzzle.c square.c box.c row.c)
target_include_directories(sudoku PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

if(MSVC)
    target_compile_options(sudoku PRIVATE /W4)
else()
    target_compile_options(sudoku PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(SUDOKU_ENABLE_SANITIZERS)
    if(CMAKE_C_COMPILER_ID MATCHES "GNU|Clang" AND NOT WIN32)
        target_compile_options(sudoku PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer)
        target_link_options(sudoku PRIVATE -fsanitize=address,undefined)
    else()
        message(FATAL_ERROR "Sanitizers are currently supported for GCC/Clang on non-Windows hosts")
    endif()
endif()

include(CTest)
if(BUILD_TESTING)
    add_test(NAME sudoku_help COMMAND sudoku --help)
    add_test(NAME sudoku_version COMMAND sudoku --version)
    add_test(NAME sudoku_demo_smoke COMMAND sudoku --demo)
    set_tests_properties(sudoku_demo_smoke PROPERTIES PASS_REGULAR_EXPRESSION "Puzzle:")
endif()

install(TARGETS sudoku RUNTIME DESTINATION bin)
