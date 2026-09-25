#!/usr/bin/env python3
"""A failing render frame is logged, rate-limited, and never ends the display loop.

Loads log_render_error from volumio_peppymeter.py without importing pygame.
PEPPY_SRC overrides the source file (used to test a patched copy).

Run: python3 test/test_render_guard.py
"""

import ast
import contextlib
import io
import os
import pathlib
import sys
import time
import traceback

SRC = pathlib.Path(os.environ.get('PEPPY_SRC') or
                   pathlib.Path(__file__).resolve().parent.parent / 'volumio_peppymeter' / 'volumio_peppymeter.py')
tree = ast.parse(SRC.read_text(encoding='utf-8'))
nodes = [
    node for node in tree.body
    if (isinstance(node, ast.FunctionDef) and node.name == 'log_render_error')
    or (isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_RENDER_ERROR' for t in node.targets))
]
if len(nodes) != 2:
    print('FAIL: log_render_error / _RENDER_ERROR not found in ' + str(SRC))
    sys.exit(1)

logged = []
namespace = {
    'traceback': traceback,
    'time': time,
    'sys': sys,
    'log_debug': lambda msg, level='basic', component=None: logged.append(msg),
}
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SRC), 'exec'), namespace)
log_render_error = namespace['log_render_error']
state = namespace['_RENDER_ERROR']

passed = 0
failed = 0


def test(name, ok):
    global passed, failed
    if ok:
        passed += 1
        print('PASS: ' + name)
    else:
        failed += 1
        print('FAIL: ' + name)


def make_exc(msg):
    try:
        raise ValueError(msg)
    except ValueError as e:
        return e


print('Testing render guard...\n')

with contextlib.redirect_stderr(io.StringIO()):
    log_render_error(make_exc("Unknown format code 'd' for object of type 'float'"))
    test('first failure is logged with its traceback', len(logged) == 1 and 'ValueError' in logged[0])
    log_render_error(make_exc("Unknown format code 'd' for object of type 'float'"))
    test('same failure within 10 s is not logged again', len(logged) == 1)
    test('every skipped frame is counted', state['count'] == 2)
    log_render_error(make_exc('a different failure'))
    test('a different failure is logged at once', len(logged) == 2 and 'different' in logged[1])
    state['ts'] -= 11
    log_render_error(make_exc('a different failure'))
    test('same failure is logged again after 10 s', len(logged) == 3)
    test('log carries the skipped-frame count', 'frames skipped' in logged[2])

print('\n---')
print('Results: ' + str(passed) + ' passed, ' + str(failed) + ' failed')
sys.exit(1 if failed else 0)
