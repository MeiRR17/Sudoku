cmake_minimum_required(VERSION 3.29)
project(Sudoku C)

set(CMAKE_C_STANDARD 11)

add_executable(Sudoku sudoku.c
        sudoku.h
        puzzle.c
        square.c)
