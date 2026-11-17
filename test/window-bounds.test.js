'use strict';
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const { fitBounds } = require('../src/window-bounds');

const SMALL = { x: 0, y: 25, width: 1024, height: 700 };
const BIG = { x: 0, y: 25, width: 1920, height: 1055 };

const inside = (b, wa) => b.x >= wa.x && b.y >= wa.y
  && b.x + b.width <= wa.x + wa.width && b.y + b.height <= wa.y + wa.height;

test('第一次開：1024 寬的螢幕上整個視窗在可用範圍內，最小寬度也不超過螢幕', () => {
  const b = fitBounds(undefined, SMALL);
  assert.ok(inside(b, SMALL), JSON.stringify(b));
  assert.strictEqual(b.width, 1024);
  assert.ok(b.minWidth <= SMALL.width && b.minHeight <= SMALL.height);
});

test('第一次開：大螢幕維持 1440×900，置中', () => {
  const b = fitBounds(undefined, BIG);
  assert.deepStrictEqual([b.width, b.height, b.minWidth, b.minHeight], [1440, 900, 1100, 700]);
  assert.strictEqual(b.x, 240);
  assert.ok(inside(b, BIG));
});

test('記住的大小與位置放得下就原樣使用', () => {
  const saved = { x: 100, y: 80, width: 1300, height: 820 };
  assert.deepStrictEqual(fitBounds(saved, BIG), { ...saved, minWidth: 1100, minHeight: 700 });
});

test('記住的是大螢幕上的大小，換到小螢幕時收進可用範圍', () => {
  const b = fitBounds({ x: 600, y: 200, width: 1440, height: 900 }, SMALL);
  assert.ok(inside(b, SMALL), JSON.stringify(b));
});

test('記住的位置跑到螢幕外面時推回來', () => {
  const b = fitBounds({ x: -3000, y: 5000, width: 1200, height: 800 }, BIG);
  assert.ok(inside(b, BIG), JSON.stringify(b));
  assert.deepStrictEqual([b.width, b.height], [1200, 800]);
});

test('設定檔壞掉（缺欄位、非數字）時退回預設', () => {
  for (const saved of [{}, { width: 'x', height: null }, { width: 0, height: 0 }]) {
    const b = fitBounds(saved, BIG);
    assert.deepStrictEqual([b.width, b.height], [1440, 900]);
  }
});

test('main.js 在 app ready 之前把語言設成繁中（頁面不跟系統語言走英文）', () => {
  const src = fs.readFileSync(path.join(__dirname, '..', 'src', 'main.js'), 'utf8');
  const i = src.indexOf("app.commandLine.appendSwitch('lang', 'zh-TW')");
  assert.ok(i > 0, '找不到 --lang zh-TW');
  assert.ok(i < src.indexOf('app.whenReady('), '--lang 要在 whenReady 之前設');
  assert.ok(/windowBounds\.fitBounds\(/.test(src), '建立視窗要經過 fitBounds');
});
