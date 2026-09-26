#!/usr/bin/env python3
"""YouTube.svg is 900x336 and named with capitals. The icon must fit the type box.

Run: python3 test/test_icon_fit.py
"""

import ast
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent.parent / 'volumio_peppymeter' / 'volumio_typeformat.py'
tree = ast.parse(SRC.read_text(encoding='utf-8'))
wanted = {'match_icon_name', 'fit_icon_size'}
funcs = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
if len(funcs) != 2:
    print('FAIL: expected match_icon_name and fit_icon_size')
    sys.exit(1)
namespace = {}
exec(compile(ast.Module(body=funcs, type_ignores=[]), str(SRC), 'exec'), namespace)
match_icon_name = namespace['match_icon_name']
fit_icon_size = namespace['fit_icon_size']

passed = 0
failed = 0


def test(name, result, expected):
    global passed, failed
    if result == expected:
        passed += 1
        print('PASS: ' + name)
    else:
        failed += 1
        print('FAIL: ' + name + ' — expected ' + repr(expected) + ', got ' + repr(result))


print('Testing format icon fit...\n')

names = ['YouTube.svg', 'flac.svg', 'mp3.svg']
test('exact name wins', match_icon_name(['youtube.svg', 'YouTube.svg'], 'youtube.svg'), 'youtube.svg')
test('YouTube.svg satisfies youtube.svg', match_icon_name(names, 'youtube.svg'), 'YouTube.svg')
test('lowercase flac stays flac', match_icon_name(names, 'flac.svg'), 'flac.svg')
test('missing icon', match_icon_name(names, 'youtube.png'), None)

test('stock youtube fits a square box', fit_icon_size(900, 336, 53, 53), (53, 19))
test('already the box size', fit_icon_size(53, 53, 53, 53), (53, 53))
test('small icon still meets the box', fit_icon_size(10, 20, 40, 40), (20, 40))
test('zero source', fit_icon_size(0, 336, 53, 53), None)
test('zero box', fit_icon_size(900, 336, 0, 53), None)

print('\n---')
print('Results: ' + str(passed) + ' passed, ' + str(failed) + ' failed')
sys.exit(1 if failed else 0)
