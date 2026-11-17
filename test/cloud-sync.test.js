'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { syncWork, pullNew, hashOf } = require('../src/cloud-sync');

const sha = (b) => crypto.createHash('sha256').update(b).digest('hex');
const PID = '11111111-2222-4333-8444-555555555555';
const LID = PID.replace(/-/g, '');

function world() {
  const vid = Buffer.from('video-bytes');
  const L = {
    media: { [sha(vid)]: vid },
    manifest: { version: 1, pid: PID, name: '貓咪上班記', work: { step: 4 }, media: [{ sha: sha(vid), mime: 'video/mp4' }] },
    state: {},
    imported: [],
  };
  const C = { media: {}, works: {}, uploads: 0 };
  const local = {
    bundle: async () => ({ local_id: LID, name: L.manifest.name, manifest: JSON.parse(JSON.stringify(L.manifest)) }),
    getState: async () => JSON.parse(JSON.stringify(L.state)),
    saveState: async (s) => { L.state = JSON.parse(JSON.stringify(s)); },
    media: async (s) => L.media[s],
    mediaReader: async (s) => ({ size: L.media[s].length, read: async (off, len) => L.media[s].subarray(off, off + len) }),
    hasMedia: async (s) => !!L.media[s],
    putMedia: async (s, _m, data) => { L.media[s] = data; },
    importWork: async (man, asNew) => {
      L.imported.push({ man, asNew });
      if (!asNew) L.manifest = JSON.parse(JSON.stringify(man));
      return { project_id: asNew ? 'new-pid' : PID, name: asNew ? man.name + '（雲端版）' : man.name };
    },
  };
  const cloud = {
    works: async () => Object.values(C.works).map((w) => ({ local_id: w.local_id, rev: w.rev, updated_at: 't' })),
    check: async (shas) => shas.filter((s) => !C.media[s]),
    upload: async (s, _m, reader) => {
      const data = await reader.read(0, reader.size);
      assert.equal(sha(data), s); C.media[s] = data; C.uploads += 1;
    },
    put: async (b) => {
      const cur = C.works[b.local_id];
      if (cur && cur.rev !== b.base_rev && !b.force) return { conflict: true, cloud_rev: cur.rev };
      const rev = (cur ? cur.rev : 0) + 1;
      C.works[b.local_id] = { local_id: b.local_id, rev, manifest: b.manifest, name: b.name };
      return { rev };
    },
    get: async (id) => C.works[id],
    media: async (s) => C.media[s],
  };
  return { L, C, local, cloud };
}

test('第一次：上傳媒體與清單；再按一次是「已是最新」、不重傳', async () => {
  const { C, local, cloud } = world();
  let r = await syncWork({ pid: PID, local, cloud, ask: async () => assert.fail('不該問') });
  assert.deepEqual([r.result, r.rev, r.uploaded], ['pushed', 1, 1]);
  r = await syncWork({ pid: PID, local, cloud, ask: async () => assert.fail('不該問') });
  assert.equal(r.result, 'uptodate');
  assert.equal(C.uploads, 1, '同一個檔不重傳');
});

test('只有本機改：上傳；只有雲端改：拉回來', async () => {
  const { L, C, local, cloud } = world();
  await syncWork({ pid: PID, local, cloud, ask: async () => null });
  L.manifest.work.step = 5;
  let r = await syncWork({ pid: PID, local, cloud, ask: async () => assert.fail() });
  assert.deepEqual([r.result, r.rev], ['pushed', 2]);
  C.works[LID].rev = 3; C.works[LID].manifest = Object.assign({}, C.works[LID].manifest, { work: { step: 6 } });
  r = await syncWork({ pid: PID, local, cloud, ask: async () => assert.fail('只有雲端改，不該問') });
  assert.deepEqual([r.result, r.rev], ['pulled', 3]);
  assert.equal(L.manifest.work.step, 6);
});

test('兩邊都改：問使用者；留本機版＝覆蓋雲端，留雲端版＝覆蓋本機，兩份都留＝另存新作品', async () => {
  for (const [choice, expect] of [['local', 'pushed'], ['cloud', 'pulled'], ['both', 'kept-both'], [null, 'cancelled']]) {
    const { L, C, local, cloud } = world();
    await syncWork({ pid: PID, local, cloud, ask: async () => null });
    L.manifest.work.step = 5;
    C.works[LID].rev = 7;
    let asked = null;
    const r = await syncWork({ pid: PID, local, cloud, ask: async (q) => { asked = q; return choice; } });
    assert.equal(r.result, expect, String(choice));
    assert.equal(asked.cloudRev, 7);
    if (choice === 'local') assert.equal(C.works[LID].manifest.work.step, 5);
    if (choice === 'both') assert.equal(L.imported.at(-1).asNew, true);
    if (choice === null) assert.equal(C.works[LID].rev, 7, '取消就什麼都不動');
  }
});

test('只開啟、沒修改：同步是「已是最新」，不多出雲端版本', async () => {
  const { L, C, local, cloud } = world();
  await syncWork({ pid: PID, local, cloud, ask: async () => null });
  L.manifest.work.t = Date.now(); L.manifest.work.sum = { n: 1, filled: 1, gen: 0, sec: 5 };
  let r = await syncWork({ pid: PID, local, cloud, ask: async () => assert.fail('不該問') });
  assert.equal(r.result, 'uptodate');
  assert.equal(C.works[LID].rev, 1, '只開啟就多了一個雲端版本');
  L.manifest.work.step = 5;
  r = await syncWork({ pid: PID, local, cloud, ask: async () => assert.fail() });
  assert.deepEqual([r.result, r.rev], ['pushed', 2]);
});

test('這一版之前記下的雜湊（整份清單算的）也認得：升級後不會每部作品都多傳一版', async () => {
  const { L, C, local, cloud } = world();
  await syncWork({ pid: PID, local, cloud, ask: async () => null });
  L.manifest.work.t = 123;
  const crypto2 = require('node:crypto');
  const { canonical } = require('../src/cloud-sync');
  L.state[LID].hash = crypto2.createHash('sha256').update(canonical(L.manifest)).digest('hex');
  const r = await syncWork({ pid: PID, local, cloud, ask: async () => assert.fail() });
  assert.equal(r.result, 'uptodate');
  assert.equal(C.works[LID].rev, 1);
});

test('雜湊與欄位順序無關', () => {
  assert.equal(hashOf({ a: 1, b: [2, { c: 3, d: 4 }] }), hashOf({ b: [2, { d: 4, c: 3 }], a: 1 }));
});

test('從雲端下載作品：這台沒有的整部拉回來、記下同步狀態；已經有的不覆蓋', async () => {
  const { L, C, local, cloud } = world();
  await syncWork({ pid: PID, local, cloud, ask: async () => null });
  L.media = {}; L.state = {}; L.imported = [];
  let r = await pullNew({ localId: LID, local, cloud, existing: new Set() });
  assert.deepEqual([r.result, r.rev, r.fetched], ['downloaded', 1, 1]);
  assert.equal(L.imported[0].asNew, false);
  assert.equal(L.state[LID].rev, 1);
  r = await pullNew({ localId: LID, local, cloud, existing: new Set([LID]) });
  assert.equal(r.result, 'exists');
});
