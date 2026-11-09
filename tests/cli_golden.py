"""Portable golden CLI tests (Python stdlib only).

Runs a built binary, normalizes Windows CRLF, and checks byte-accurate JSON,
exit codes, output file behavior, stdout/stderr separation and input paths.
"""
import json
import pathlib
import subprocess
import sys
import tempfile

EXE = pathlib.Path(sys.argv[1]).resolve()
FIX = pathlib.Path(sys.argv[2]).resolve()
GIVENS = "530070000600195000098000060800060003400803001700020006060000280000419005000080079"
SOLUTION = "534678912672195348198342567859761423426853791713924856961537284287419635345286179"
EMPTY = "0" * 81
checks = 0


def run(*args, input_bytes=None, code=0, stdout=None, stderr_contains=None):
    global checks
    p = subprocess.run([str(EXE), *map(str, args)], input=input_bytes, capture_output=True, check=False)
    out = p.stdout.decode("utf-8").replace("\r\n", "\n")
    err = p.stderr.decode("utf-8").replace("\r\n", "\n")
    assert p.returncode == code, (args, p.returncode, code, out, err)
    if stdout is not None:
        assert out == stdout, (args, out, stdout)
    if stderr_contains is not None:
        assert stderr_contains in err, (args, err, stderr_contains)
    checks += 1
    return out, err


def json_exact(action, arg, expected, **kwargs):
    out, err = run(action, *arg, "--format", "json", **kwargs)
    assert out == json.dumps(expected, separators=(",", ":")) + "\n", (out, expected)
    assert json.loads(out) == expected
    checks_add()
    return out, err


def checks_add():
    global checks
    checks += 1


puzzle_json = {"schema_version": 1, "command": "validate", "status": "valid", "puzzle": GIVENS}
solve_json = {"schema_version": 1, "command": "solve", "status": "unique", "puzzle": GIVENS,
              "solution": SOLUTION, "solutions_found": 1}
count_json = {"schema_version": 1, "command": "count", "status": "unique", "puzzle": GIVENS,
              "solutions_found": 1, "capped": False}

json_exact("validate", ["--puzzle", GIVENS], puzzle_json)
json_exact("solve", ["--file", FIX / "unique.txt"], solve_json)
json_exact("count", ["--stdin"], count_json, input_bytes=(GIVENS + "\r\n").encode())
json_exact("count", ["--puzzle", EMPTY], {"schema_version": 1, "command": "count",
           "status": "multiple", "puzzle": EMPTY, "solutions_found": 2, "capped": True})
json_exact("count", ["--file", FIX / "unsolvable.txt"], {"schema_version": 1, "command": "count",
           "status": "none", "puzzle": (FIX / "unsolvable.txt").read_text().replace("\n", ""),
           "solutions_found": 0, "capped": False})
run("solve", "--puzzle", GIVENS, "--format", "compact", stdout=SOLUTION + "\n")
run("count", "--puzzle", GIVENS, "--format", "compact", stdout="1\n")
run("count", "--puzzle", EMPTY, "--format", "compact", stdout="2+\n")
run("count", "--file", FIX / "unsolvable.txt", "--format", "compact", stdout="0\n")
run("validate", "--puzzle", GIVENS, "--format", "compact", stdout=GIVENS + "\n")
run("validate", "--stdin", "--format", "compact", input_bytes=(GIVENS + "\r\n").encode(), stdout=GIVENS + "\n")
run("validate", "--file", "-", "--format", "compact", input_bytes=GIVENS.encode(), stdout=GIVENS + "\n")
run("solve", "--file", FIX / "unsolvable.txt", "--format", "json", code=5,
    stdout="", stderr_contains="no solution")
run("validate", "--file", FIX / "invalid_row.txt", "--format", "json", code=3,
    stdout="", stderr_contains="duplicate given in row")
run("validate", "--puzzle", GIVENS[:-1], code=3, stdout="", stderr_contains="81 digits")
run("validate", "--puzzle", GIVENS + "1", code=3, stdout="", stderr_contains="81 digits")
run("validate", "--stdin", "--format", "json", input_bytes=(GIVENS[:1] + "." + GIVENS[2:]).encode(),
    code=3, stdout="", stderr_contains="non-digit")
run("validate", "--stdin", "--format", "json", input_bytes=b"\xff" + GIVENS[1:].encode(),
    code=3, stdout="", stderr_contains="non-digit")
run("validate", "--stdin", input_bytes=b"0" * (1024 * 1024 + 1),
    code=3, stdout="", stderr_contains="1 MiB")
for invalid in [
    ("", 2), ("validate", 2), ("missing-command", 2),
    ("solve --format xml --puzzle " + GIVENS, 2),
    ("count --puzzle " + GIVENS + " --format compact --format json", 2),
    ("count --puzzle " + GIVENS + " --file " + str(FIX / "unique.txt"), 2),
    ("count --puzzle " + GIVENS + " --quiet --quiet", 2),
    ("count --puzzle " + GIVENS + " --output", 2),
]:
    # invalid is a tuple of command-line text and expected code.
    args = invalid[0].split()
    run(*args, code=invalid[1], stdout="", stderr_contains="Usage error")
run("--help", stderr_contains="" if False else None)
run("--version", stdout="Sudoku 0.8.3 (experimental)\n")
run("solve", "--help")
run("--demo")

with tempfile.TemporaryDirectory() as tmp:
    temp = pathlib.Path(tmp)
    output = temp / "result.json"
    run("solve", "--file", FIX / "unique.txt", "--format", "json", "--output", output,
        stdout="")
    assert output.read_text() == json.dumps(solve_json, separators=(",", ":")) + "\n"
    checks_add()
    spaced_dir = temp / "space directory"
    spaced_dir.mkdir()
    spaced_out = spaced_dir / "unique solution.json"
    run("solve", "--file", FIX / "unique.txt", "--format", "json", "--output", spaced_out, stdout="")
    assert json.loads(spaced_out.read_text()) == solve_json
    checks_add()
    original = output.read_bytes()
    run("count", "--puzzle", EMPTY, "--format", "compact", "--output", output,
        code=4, stdout="", stderr_contains="never overwritten")
    assert output.read_bytes() == original
    checks_add()
    run("solve", "--file", FIX / "unsolvable.txt", "--output", temp / "not-created.txt",
        code=5, stdout="", stderr_contains="no solution")
    assert not (temp / "not-created.txt").exists()
    checks_add()
    run("validate", "--puzzle", GIVENS, "--format", "compact", "--output", temp / "compact.txt",
        stdout="")
    assert (temp / "compact.txt").read_text() == GIVENS + "\n"
    checks_add()
    run("validate", "--puzzle", GIVENS, "--output", temp / "not-a-directory" / "no.txt",
        code=4, stdout="", stderr_contains="Output create failed")
    # Input stream safety: successful EOF, binary bytes, limit boundary, and
    # missing files must not produce a success JSON document.
    empty_input = temp / "empty.txt"
    empty_input.write_bytes(b"")
    run("validate", "--file", empty_input, "--format", "json",
        code=3, stdout="", stderr_contains="81 digits")
    bad_binary = temp / "embedded-nul.txt"
    bad_binary.write_bytes(GIVENS[:41].encode() + b"\x00" + GIVENS[42:].encode())
    run("validate", "--file", bad_binary, "--format", "json",
        code=3, stdout="", stderr_contains="non-digit")
    max_len = temp / "exact-limit.txt"
    max_len.write_bytes(b" " * (1024 * 1024))
    run("validate", "--file", max_len, "--format", "json",
        code=3, stdout="", stderr_contains="81 digits")
    above_limit = temp / "above-limit.txt"
    above_limit.write_bytes(b"0" * (1024 * 1024 + 1))
    run("validate", "--file", above_limit, "--format", "json",
        code=3, stdout="", stderr_contains="1 MiB")
    run("validate", "--file", temp / "missing-input.txt", "--format", "json",
        code=4, stdout="", stderr_contains="Input open failed")
    run("solve", "--file", temp / "missing-input.txt", "--format", "json",
        "--output", temp / "must-not-be-created.json", code=4, stdout="",
        stderr_contains="Input open failed")
    assert not (temp / "must-not-be-created.json").exists()
    checks_add()
    crlf = temp / "crlf.txt"
    crlf.write_bytes((GIVENS[:9] + "\r\n" + GIVENS[9:] + "\r\n").encode())
    run("solve", "--file", crlf, "--format", "compact", stdout=SOLUTION + "\n")
    # Input file cannot be overwritten by --output even when same path.
    before = crlf.read_bytes()
    run("validate", "--file", crlf, "--output", crlf, code=4, stdout="")
    assert before == crlf.read_bytes()
    checks_add()
    if hasattr(pathlib.Path, "symlink_to"):
        link = temp / "existing-link"
        try:
            link.symlink_to(output)
        except (OSError, NotImplementedError):
            pass
        else:
            run("count", "--puzzle", GIVENS, "--output", link, code=4, stdout="")
            assert output.read_bytes() == original
            checks_add()

# Quiet should suppress non-unique warning and preserve machine result.
_, warning = run("solve", "--puzzle", EMPTY, "--format", "json")
assert "multiple" in warning
checks_add()
_, quiet = run("solve", "--puzzle", EMPTY, "--format", "json", "--quiet")
assert quiet == ""
checks_add()
print(f"CLI GOLDEN PASS: {checks} checks (JSON, input, output, errors, CRLF, stdout/stderr)")
