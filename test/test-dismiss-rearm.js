#!/usr/bin/env node
/**
 * User dismiss re-arms the full screensaver timeout.
 * Loads meterExitAction from index.js without executing the plugin.
 *
 * Run: node test/test-dismiss-rearm.js
 */

'use strict';

var fs = require('fs');
var path = require('path');

var src = fs.readFileSync(path.join(__dirname, '..', 'index.js'), 'utf8');
var match = src.match(/function meterExitAction\(cleanExit, timeoutArmed, dismissMarkerPresent\) \{\n    if \(!timeoutArmed\) return 'idle';\n    if \(cleanExit && dismissMarkerPresent\) return 'rearm';\n    return 'restart';\n\}/);
if (!match) {
  console.error('FAIL: meterExitAction not found in index.js');
  process.exit(1);
}
var meterExitAction = new Function('return ' + match[0])();

var passed = 0;
var failed = 0;

function test(name, cleanExit, timeoutArmed, dismissMarkerPresent, expected) {
  var result = meterExitAction(cleanExit, timeoutArmed, dismissMarkerPresent);
  if (result === expected) {
    passed++;
    console.log('PASS: ' + name);
  } else {
    failed++;
    console.log('FAIL: ' + name + ' — expected ' + expected + ', got ' + result);
  }
}

console.log('Testing meter exit action...\n');

test('user dismiss while playing', true, true, true, 'rearm');
test('settings reload while playing', true, true, false, 'restart');
test('crash while playing, stale marker', false, true, true, 'restart');
test('crash while playing, no marker', false, true, false, 'restart');
test('dismiss after pause cleared the interval', true, false, true, 'idle');
test('clean exit with interval already cleared', true, false, false, 'idle');
test('crash with interval already cleared', false, false, true, 'idle');

console.log('\n---');
console.log('Results: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed > 0 ? 1 : 0);
