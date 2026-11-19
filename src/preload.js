'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('iamdirectorDesktop', Object.freeze({
  isDesktop: true,
  platform: process.platform,
  notify: (kind, text) => ipcRenderer.send('desktop:notify', {
    kind: String(kind), text: String(text == null ? '' : text).slice(0, 200),
  }),
  onOpenKey: (fn) => { ipcRenderer.on('desktop:open-key', () => { try { fn(); } catch (_) {} }); },
  onOpenApproval: (fn) => {
    ipcRenderer.on('desktop:open-approval', (_e, id) => { try { fn(String(id)); } catch (_) {} });
  },
  takeStartAction: () => ipcRenderer.invoke('desktop:take-start-action'),
  cloud: Object.freeze({
    status: () => ipcRenderer.invoke('desktop:cloud-status'),
    link: (provider) => ipcRenderer.invoke('desktop:cloud-link', String(provider || '')),
    sync: (projectId) => ipcRenderer.invoke('desktop:cloud-sync', String(projectId || '')),
    list: () => ipcRenderer.invoke('desktop:cloud-list'),
    pull: (localId) => ipcRenderer.invoke('desktop:cloud-pull', String(localId || '')),
    onLinked: (fn) => { ipcRenderer.on('desktop:cloud-linked', () => { try { fn(); } catch (_) {} }); },
    logout: () => ipcRenderer.invoke('desktop:cloud-logout'),
    openWeb: () => ipcRenderer.send('desktop:cloud-open-web'),
  }),
  h264: Object.freeze({ ensure: () => ipcRenderer.invoke('desktop:h264-ensure') }),
  revealPath: (p) => ipcRenderer.send('desktop:reveal', String(p || '').slice(0, 1024)),
  liveJobs: (n) => ipcRenderer.sendSync('desktop:live-jobs', Math.max(0, Math.min(9999, Number(n) || 0))),
}));

const ZONES = '#assetBox, .castbar, .cv-top';
const MAX_FILES = 200;
let redispatching = false;

function hasFiles(e) {
  return !!e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
}

window.addEventListener('dragover', (e) => {
  if (hasFiles(e)) e.preventDefault();
}, true);

window.addEventListener('drop', (e) => {
  if (redispatching || !hasFiles(e)) return;
  const zone = e.target instanceof Element ? e.target.closest(ZONES) : null;
  const entries = Array.from(e.dataTransfer.items || [])
    .filter((it) => it.kind === 'file')
    .map((it) => (it.webkitGetAsEntry ? it.webkitGetAsEntry() : null));
  const hasDir = entries.some((en) => en && en.isDirectory);
  if (zone && !hasDir) return;

  e.preventDefault();
  e.stopImmediatePropagation();
  const target = zone || document.querySelector('#assetBox');
  if (!target) return;
  const plain = Array.from(e.dataTransfer.files || []);
  const { clientX, clientY } = e;
  expand(entries, plain).then((files) => {
    if (!files.length) return;
    const dt = new DataTransfer();
    files.slice(0, MAX_FILES).forEach((f) => dt.items.add(f));
    redispatching = true;
    try {
      target.dispatchEvent(new DragEvent('drop', {
        bubbles: true, cancelable: true, dataTransfer: dt, clientX, clientY,
      }));
    } finally { redispatching = false; }
  });
}, true);

async function expand(entries, plain) {
  const out = [];
  for (let i = 0; i < entries.length; i++) {
    const en = entries[i];
    if (en && en.isDirectory) await walk(en, out);
    else if (en && en.isFile) out.push(await fileOf(en));
    else if (plain[i]) out.push(plain[i]);
    if (out.length >= MAX_FILES) break;
  }
  return out.filter((f) => f && !f.name.startsWith('.'));
}

async function walk(dir, out) {
  const reader = dir.createReader();
  for (;;) {
    const batch = await new Promise((ok, bad) => reader.readEntries(ok, bad)).catch(() => []);
    if (!batch.length) return;
    for (const en of batch) {
      if (out.length >= MAX_FILES) return;
      if (en.name.startsWith('.')) continue;
      if (en.isDirectory) await walk(en, out);
      else out.push(await fileOf(en));
    }
  }
}

function fileOf(entry) {
  return new Promise((ok) => entry.file(ok, () => ok(null)));
}
