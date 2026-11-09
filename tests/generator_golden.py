"""Exact generator JSON, deterministic seeds, validation and failure semantics."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
checks = 0

def cmd(*args, returncode=0):
    global checks
    proc = subprocess.run([binary, *map(str,args)], text=True, capture_output=True)
    assert proc.returncode == returncode, (args, proc.returncode, proc.stdout, proc.stderr)
    checks += 1
    return proc

for difficulty in ('easy','medium','hard'):
    for symmetry in ('none','rotational'):
        args = ('generate','--seed','42','--difficulty',difficulty,'--symmetry',symmetry,'--format','json')
        a=cmd(*args)
        b=cmd(*args)
        assert a.stdout == b.stdout and a.stderr == b.stderr, (args,a,b)
        obj=json.loads(a.stdout)
        assert obj['schema_version']==1 and obj['command']=='generate' and obj['status']=='unique'
        assert obj['difficulty']==difficulty and obj['symmetry']==symmetry
        assert obj['solutions_found']==1 and obj['seed']==42
        puzzle=obj['puzzle']; solution=obj['solution']
        assert len(puzzle)==81 and len(solution)==81 and set(solution)<=set('123456789')
        assert obj['clues']==sum(c!='0' for c in puzzle)
        assert obj['attempts']>=1 and obj['checks']>=1
        assert all(a=='0' or a==b for a,b in zip(puzzle,solution))
        if difficulty == 'medium': assert obj['hidden_singles']>0
        if difficulty == 'easy': assert obj['hidden_singles']==0
        if symmetry == 'rotational':
            assert all((puzzle[i]=='0')==(puzzle[80-i]=='0') for i in range(81))
        counted=cmd('count','--puzzle',puzzle,'--format','compact')
        assert counted.stdout=='1\n'
        solved=cmd('solve','--puzzle',puzzle,'--format','compact')
        assert solved.stdout==solution+'\n'
        compact=cmd('generate','--seed','42','--difficulty',difficulty,'--symmetry',symmetry,'--format','compact')
        assert compact.stdout==puzzle+'\n'
        checks+=9

for args in [
    ('generate','--seed','42'),
    ('generate','--difficulty','easy'),
    ('generate','--seed','-1','--difficulty','easy'),
    ('generate','--seed','4294967296','--difficulty','easy'),
    ('generate','--seed','42x','--difficulty','easy'),
    ('generate','--seed','42','--difficulty','invalid'),
    ('generate','--seed','42','--difficulty','easy','--symmetry','vertical'),
    ('generate','--seed','42','--difficulty','easy','--max-checks','0'),
    ('generate','--seed','42','--difficulty','easy','--max-nodes','1000001'),
    ('generate','--seed','42','--difficulty','easy','--max-attempts','101'),
    ('generate','--seed','42','--difficulty','easy','--max-ms','60001'),
    ('generate','--seed','42','--difficulty','easy','--seed','4'),
    ('generate','--seed','42','--difficulty','easy','--puzzle','0'*81),
    ('solve','--puzzle','0'*81,'--difficulty','easy'),
]:
    p=cmd(*args,returncode=2)
    assert p.stdout=='' and 'Usage error:' in p.stderr

budget=cmd('generate','--seed','42','--difficulty','hard','--max-checks','1','--format','json',returncode=6)
assert budget.stdout=='' and 'budget exhausted' in budget.stderr

with tempfile.TemporaryDirectory() as temp:
    output=Path(temp)/'puzzle with spaces.json'
    p=cmd('generate','--seed','42','--difficulty','easy','--format','json','--output',output)
    assert p.stdout=='' and json.loads(output.read_text())['clues']==40
    original=output.read_bytes()
    p=cmd('generate','--seed','42','--difficulty','easy','--format','json','--output',output,returncode=4)
    assert output.read_bytes()==original and p.stdout==''
    other=Path(temp)/'budget.txt'
    p=cmd('generate','--seed','42','--difficulty','hard','--max-checks','1','--output',other,returncode=6)
    assert not other.exists() and p.stdout==''
    checks+=3

print(f'GENERATOR GOLDEN PASS: {checks} seeded CLI / JSON / uniqueness / budget assertions')
