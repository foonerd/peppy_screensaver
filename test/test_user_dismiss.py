#!/usr/bin/env python3
"""Real finger/click writes the dismiss marker. Remote, stop_watcher, and a missing runFlag do not.

Loads should_mark_user_dismiss from volumio_peppymeter.py without importing pygame.

Run: python3 test/test_user_dismiss.py
"""

import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / 'volumio_peppymeter' / 'volumio_peppymeter.py'
tree = ast.parse(SRC.read_text(encoding='utf-8'))
func = next(
    (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'should_mark_user_dismiss'),
    None,
)
if func is None:
    print('FAIL: should_mark_user_dismiss not found')
    sys.exit(1)
namespace = {}
exec(compile(ast.Module(body=[func], type_ignores=[]), str(SRC), 'exec'), namespace)
should_mark_user_dismiss = namespace['should_mark_user_dismiss']

passed = 0
failed = 0


def test(name, dismiss_path, external_stop, runflag_exists, expected):
    global passed, failed
    result = should_mark_user_dismiss(dismiss_path, external_stop, runflag_exists)
    if result is expected:
        passed += 1
        print('PASS: ' + name)
    else:
        failed += 1
        print('FAIL: ' + name + ' — expected ' + str(expected) + ', got ' + str(result))


print('Testing user-dismiss marker gate...\n')

test('finger while screensaver is up', '/tmp/peppy_user_dismiss', False, True, True)
test('remote launcher, env unset', '', False, True, False)
test('remote launcher, env missing', None, False, True, False)
test('stop_watcher synthetic button-up', '/tmp/peppy_user_dismiss', True, True, False)
test('runFlag already removed', '/tmp/peppy_user_dismiss', False, False, False)
test('external stop and runFlag gone', '/tmp/peppy_user_dismiss', True, False, False)

print('\n---')
print('Results: ' + str(passed) + ' passed, ' + str(failed) + ' failed')
sys.exit(1 if failed else 0)
