execute_process(COMMAND "${SUDOKU_BIN}" validate --stdin --format compact
    INPUT_FILE "${FIXTURE}"
    RESULT_VARIABLE code OUTPUT_VARIABLE output ERROR_VARIABLE errors)
if(NOT code EQUAL 0)
    message(FATAL_ERROR "stdin validation failed: ${code} ${errors}")
endif()
string(STRIP "${output}" output)
string(LENGTH "${output}" digits)
if(NOT digits EQUAL 81)
    message(FATAL_ERROR "Expected 81 compact digits but got ${digits}")
endif()
