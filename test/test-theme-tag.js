#!/usr/bin/env node
/**
 * Edition tags select a theme folder. Empty rules do nothing.
 * Run: node test/test-theme-tag.js
 */

'use strict';

var fs = require('fs');
var path = require('path');

var src = fs.readFileSync(path.join(__dirname, '..', 'index.js'), 'utf8');
var start = src.indexOf('// theme-tag-contract:start');
var end = src.indexOf('// theme-tag-contract:end');
if (start < 0 || end < start) {
  console.error('FAIL: theme-tag contract block not found');
  process.exit(1);
}
var themeFolderForEdition = new Function(src.slice(start, end) + '\nreturn themeFolderForEdition;')();

var passed = 0;
var failed = 0;
var rules = 'Vinyl=1920x1080_g5_Vinyl, Tape=1920x1080_g5_Tape, SACD=1920x1080_g5_Sacd';

function test(name, album, uri, rulesText, expected) {
  var result = themeFolderForEdition(album, uri, rulesText);
  if (result === expected) {
    passed++;
    console.log('PASS: ' + name);
  } else {
    failed++;
    console.log('FAIL: ' + name + ' — expected ' + JSON.stringify(expected) + ', got ' + JSON.stringify(result));
  }
}

console.log('Testing edition theme tags...\n');

test('empty rules leave the theme alone', 'Dark Side [Vinyl]', '/music/[Vinyl]/a.flac', '', null);
test('plain Vinyl does not match', 'Dark Side Vinyl', '/music/Dark Side Vinyl/a.flac', rules, '');
test('album bracket', 'The Dark Side Of The Moon [Vinyl]', '', rules, '1920x1080_g5_Vinyl');
test('year after the bracket', 'Meddle [Tape] 1971', '', rules, '1920x1080_g5_Tape');
test('leading year bracket is not the edition', '[1973] Dark Side [SACD] MCH', '', rules, '1920x1080_g5_Sacd');
test('folder tag when the album has none', 'The Dark Side Of The Moon', '/mnt/NAS/Pink Floyd/[1973] The Dark Side Of The Moon [Vinyl] 2016/01.flac', rules, '1920x1080_g5_Vinyl');
test('album tag wins over a different folder tag', 'Animals [Tape]', '/mnt/NAS/Animals [Vinyl]/01.flac', rules, '1920x1080_g5_Tape');
test('album year-only falls through to the folder', '[1973] The Dark Side Of The Moon', '/mnt/NAS/[1973] The Dark Side Of The Moon [Vinyl] 2016/01.flac', rules, '1920x1080_g5_Vinyl');
test('encoded folder', 'Dark Side', '/mnt/NAS/Pink%20Floyd/%5B1973%5D%20Dark%20Side%20%5BVinyl%5D%202016/01.flac', rules, '1920x1080_g5_Vinyl');
test('no tag with rules uses home', 'Wish You Were Here', '/mnt/NAS/Wish You Were Here/01.flac', rules, '');
test('a path rule is ignored', 'X [Vinyl]', '', 'Vinyl=../secret', null);
test('case insensitive tag', 'meddle [tape]', '', rules, '1920x1080_g5_Tape');

console.log('\n---');
console.log('Results: ' + passed + ' passed, ' + failed + ' failed');
process.exit(failed > 0 ? 1 : 0);
