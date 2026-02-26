#!/usr/bin/env node
/**
 * Test script for pushState volatile logic.
 * Verifies that persist file is only written for genuine pause/stop,
 * not during track/album transitions (getEmptyState with undefined volatile).
 *
 * Run: node test-volatile-logic.js
 */

'use strict';

// Core logic extracted from index.js pushState handler
// We only write persist when: lastStateIsPlaying AND genuine pause/stop
// Genuine stop requires: volatile===false AND NOT getEmptyState (empty uri/title)
function wouldWritePersist(state, lastStateIsPlaying) {
  if (!lastStateIsPlaying) return false;
  if (state.status === 'play') return false;
  if (state.status === 'pause') return true;
  if (state.status === 'stop') {
    var isGetEmptyState = ((state.uri || '') === '' && (state.title || '') === '');
    if (state.volatile === false && !isGetEmptyState) return true;
  }
  return false;
}

var passed = 0;
var failed = 0;

function test(name, state, lastStateIsPlaying, expected) {
  var result = wouldWritePersist(state, lastStateIsPlaying);
  var ok = result === expected;
  if (ok) {
    passed++;
    console.log('PASS: ' + name);
  } else {
    failed++;
    console.log('FAIL: ' + name + ' — expected persist=' + expected + ', got ' + result);
  }
}

console.log('Testing pushState volatile logic...\n');

// lastStateIsPlaying = false: never persist (wasn't playing)
test('not playing, stop', { status: 'stop', volatile: false }, false, false);
test('not playing, pause', { status: 'pause' }, false, false);

// play: never persist (we're in play branch, clear persist)
test('play', { status: 'play' }, true, false);

// pause: always persist (genuine pause)
test('pause (genuine)', { status: 'pause' }, true, true);

// stop with volatile=false but no uri/title: treat as getEmptyState, NO persist
test('stop, volatile=false, no uri/title', { status: 'stop', volatile: false }, true, false);

// stop with volatile=true: NO persist (transitional - track change)
test('stop, volatile=true (transition)', { status: 'stop', volatile: true }, true, false);

// stop with volatile=undefined: NO persist (getEmptyState - album change)
test('stop, volatile=undefined (getEmptyState)', { status: 'stop' }, true, false);

// stop with volatile=null: NO persist (falsy but not === false)
test('stop, volatile=null', { status: 'stop', volatile: null }, true, false);

// stop with volatile=false but empty uri/title (getEmptyState): NO persist
test('stop, volatile=false, getEmptyState (empty uri/title)', { status: 'stop', volatile: false, uri: '', title: '' }, true, false);

// stop with volatile=false, has uri: persist (genuine stop)
test('stop, volatile=false, has uri (genuine)', { status: 'stop', volatile: false, uri: 'music-library/album/track.mp3', title: 'Track' }, true, true);

console.log('\n---');
console.log('Results: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed > 0 ? 1 : 0);
