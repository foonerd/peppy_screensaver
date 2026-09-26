#!/usr/bin/env python3
"""Duration, not the service name, decides whether a countdown remains.

Loads seconds_remaining from volumio_peppymeter.py without importing pygame.

Run: python3 test/test_seconds_remaining.py
"""

import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / 'volumio_peppymeter' / 'volumio_peppymeter.py'
tree = ast.parse(SRC.read_text(encoding='utf-8'))
func = next(
    (node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'seconds_remaining'),
    None,
)
if func is None:
    print('FAIL: seconds_remaining not found')
    sys.exit(1)
namespace = {}
exec(compile(ast.Module(body=[func], type_ignores=[]), str(SRC), 'exec'), namespace)
seconds_remaining = namespace['seconds_remaining']

passed = 0
failed = 0


def test(name, duration, seek_ms, expected):
    global passed, failed
    result = seconds_remaining(duration, seek_ms)
    if result == expected and isinstance(result, int):
        passed += 1
        print('PASS: ' + name)
    else:
        failed += 1
        print('FAIL: ' + name + ' — expected ' + str(expected) + ', got ' + str(result))


print('Testing seconds remaining...\n')

test('file mid-track', 180, 30000, 150)
test('file at start', 1, 0, 1)
test('webradio duration 0', 0, 0, -1)
test('webradio duration string 0', '0', 0, -1)
test('missing duration', None, 5000, -1)
test('empty duration', '', 0, -1)
test('same service, duration dropped', 0, 120000, -1)
test('seek past end clamps at 0', 10, 20000, 0)
test('bad seek', 90, 'nope', 90)
test('rp2 fractional duration and seek', 193.747, 4983.569000000018, 189)
test('rp2 fractional seek past one second', 193.747, 125129.48800000001, 68)
test('result is an int for fractional input', 193.747, 16792.684999999998, 177)

print('\n---')
print('Results: ' + str(passed) + ' passed, ' + str(failed) + ' failed')
sys.exit(1 if failed else 0)
