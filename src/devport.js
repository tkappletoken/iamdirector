'use strict';

const HOST = '127.0.0.1';
const SWITCHES = ['remote-debugging-port', 'remote-debugging-pipe', 'remote-debugging-address', 'remote-allow-origins'];

function parsePort(raw) {
  if (typeof raw !== 'string' || !/^\d{1,5}$/.test(raw.trim())) return null;
  const n = Number(raw.trim());
  return n >= 1024 && n <= 65535 ? n : null;
}

function decide({ isPackaged, env }) {
  if (isPackaged !== false) return { open: false, reason: 'packaged' };
  const raw = env && env.IAMDIRECTOR_DEV_PORT;
  if (raw === undefined || raw === '') return { open: false, reason: 'no-env' };
  const port = parsePort(raw);
  if (port === null) throw new Error('IAMDIRECTOR_DEV_PORT 要是 1024–65535 的整數：' + raw);
  return { open: true, host: HOST, port, reason: 'dev' };
}

function apply({ isPackaged, env, commandLine, log = console }) {
  const present = SWITCHES.filter((s) => commandLine.hasSwitch(s));
  for (const s of present) commandLine.removeSwitch(s);
  const d = decide({ isPackaged, env });
  if (isPackaged !== false && present.length) {
    return { ...d, refused: true, present };
  }
  if (d.open) {
    commandLine.appendSwitch('remote-debugging-address', d.host);
    commandLine.appendSwitch('remote-debugging-port', String(d.port));
    log.warn(`⚠ 開發除錯埠已開啟 ${d.host}:${d.port}（打包版不會有）`);
  }
  return d;
}

function devUserDataSuffix({ isPackaged }) {
  return isPackaged === false ? '-dev' : null;
}

module.exports = { decide, apply, parsePort, devUserDataSuffix, HOST, SWITCHES };
