'use strict';
const path = require('node:path');

const FILE = path.join('secrets', 'appletoken.bin');
const WEAK_BACKENDS = new Set(['basic_text', 'unknown']);

function last4(key) {
  return typeof key === 'string' && key.length >= 8 ? key.slice(-4) : '';
}

function create({ safeStorage, fs, userData, platform }) {
  const file = path.join(userData, FILE);
  let memory = null;

  function canPersist() {
    if (!safeStorage.isEncryptionAvailable()) return { ok: false, reason: 'encryption_unavailable' };
    if (platform === 'linux' && typeof safeStorage.getSelectedStorageBackend === 'function') {
      const b = safeStorage.getSelectedStorageBackend();
      if (WEAK_BACKENDS.has(b)) return { ok: false, reason: 'no_keyring' };
    }
    return { ok: true };
  }

  function load() {
    if (memory) return memory;
    try {
      const buf = fs.readFileSync(file);
      if (!canPersist().ok) return null;
      return safeStorage.decryptString(buf);
    } catch (_) {
      return null;
    }
  }

  function save(key) {
    if (typeof key !== 'string' || !/^[\x21-\x7e]{8,512}$/.test(key)) throw new Error('金鑰格式不對');
    const c = canPersist();
    if (!c.ok) {
      memory = key;
      try { fs.rmSync(file, { force: true }); } catch (_) {}
      return { persisted: false, reason: c.reason, last4: last4(key) };
    }
    const enc = safeStorage.encryptString(key);
    fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
    fs.writeFileSync(file + '.tmp', enc, { mode: 0o600 });
    fs.renameSync(file + '.tmp', file);
    memory = null;
    return { persisted: true, last4: last4(key) };
  }

  function clear() {
    memory = null;
    try { fs.rmSync(file, { force: true }); } catch (_) {}
  }

  return { load, save, clear, canPersist, file };
}

module.exports = { create, last4, WEAK_BACKENDS };
