'use strict';
const crypto = require('node:crypto');

function canonical(v) {
  if (Array.isArray(v)) return '[' + v.map(canonical).join(',') + ']';
  if (v && typeof v === 'object') {
    return '{' + Object.keys(v).sort().map((k) => JSON.stringify(k) + ':' + canonical(v[k])).join(',') + '}';
  }
  return JSON.stringify(v === undefined ? null : v);
}

function hashOf(manifest) {
  return crypto.createHash('sha256').update(canonical(manifest)).digest('hex');
}

async function push({ b, remote, local, cloud, state, force }) {
  const shas = (b.manifest.media || []).map((m) => m.sha);
  const missing = shas.length ? await cloud.check(shas) : [];
  for (const sha of missing) {
    const m = b.manifest.media.find((x) => x.sha === sha);
    await cloud.upload(sha, m.mime || 'application/octet-stream', await local.mediaReader(sha));
  }
  const r = await cloud.put({
    local_id: b.local_id, name: b.name, manifest: b.manifest,
    base_rev: remote ? remote.rev : 0, force: !!force,
  });
  if (r.conflict) return { result: 'conflict-again' };
  state[b.local_id] = { rev: r.rev, hash: hashOf(b.manifest) };
  await local.saveState(state);
  return { result: 'pushed', rev: r.rev, uploaded: missing.length };
}

async function pull({ b, pid, local, cloud, state, asNew }) {
  const w = await cloud.get(b.local_id);
  let fetched = 0;
  for (const m of w.manifest.media || []) {
    if (await local.hasMedia(m.sha)) continue;
    await local.putMedia(m.sha, m.mime || 'application/octet-stream', await cloud.media(m.sha));
    fetched += 1;
  }
  const r = await local.importWork(w.manifest, !!asNew);
  if (asNew) return { result: 'kept-both', project_id: r.project_id, name: r.name, fetched };
  const again = await local.bundle(pid);
  state[b.local_id] = { rev: w.rev, hash: hashOf(again.manifest) };
  await local.saveState(state);
  return { result: 'pulled', rev: w.rev, fetched };
}

async function syncWork({ pid, local, cloud, ask }) {
  const b = await local.bundle(pid);
  const state = (await local.getState()) || {};
  const st = state[b.local_id] || null;
  const h = hashOf(b.manifest);
  const remote = (await cloud.works()).find((w) => w.local_id === b.local_id) || null;
  const localChanged = !st || st.hash !== h;
  const cloudChanged = !!remote && (!st || remote.rev !== st.rev);
  if (!localChanged && !cloudChanged) return { result: 'uptodate', rev: remote ? remote.rev : 0 };
  if (cloudChanged && !localChanged) return pull({ b, pid, local, cloud, state });
  if (cloudChanged) {
    const choice = await ask({ name: b.name, cloudRev: remote.rev, cloudUpdatedAt: remote.updated_at });
    if (choice === 'local') return push({ b, remote, local, cloud, state, force: true });
    if (choice === 'cloud') return pull({ b, pid, local, cloud, state });
    if (choice === 'both') return pull({ b, pid, local, cloud, state, asNew: true });
    return { result: 'cancelled' };
  }
  return push({ b, remote, local, cloud, state });
}

async function pullNew({ localId, local, cloud, existing }) {
  if (existing.has(localId)) return { result: 'exists' };
  const w = await cloud.get(localId);
  let fetched = 0;
  for (const m of w.manifest.media || []) {
    if (await local.hasMedia(m.sha)) continue;
    await local.putMedia(m.sha, m.mime || 'application/octet-stream', await cloud.media(m.sha));
    fetched += 1;
  }
  const r = await local.importWork(w.manifest, false);
  const state = (await local.getState()) || {};
  const again = await local.bundle(r.project_id);
  state[localId] = { rev: w.rev, hash: hashOf(again.manifest) };
  await local.saveState(state);
  return { result: 'downloaded', project_id: r.project_id, name: r.name, rev: w.rev, fetched };
}

module.exports = { syncWork, pullNew, hashOf, canonical };
