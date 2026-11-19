'use strict';

const PREFIX = 'iamdirector://approve/';
const ID = /^apv_[A-Za-z0-9]{16,32}$/;
const INBOX_TTL_MS = 10 * 60 * 1000;

function parseApprove(url) {
  if (typeof url !== 'string' || url.length > PREFIX.length + 40) return null;
  if (!url.startsWith(PREFIX)) return null;
  const id = url.slice(PREFIX.length);
  if (!ID.test(id)) return null;
  let u;
  try { u = new URL(url); } catch (_) { return null; }
  if (u.protocol !== 'iamdirector:' || u.hostname !== 'approve' || u.username || u.password || u.port
    || u.search || u.hash || u.pathname !== '/' + id) return null;
  return { id };
}

function createInbox(now = Date.now) {
  let cur = null;
  return {
    put(id) { cur = { id, at: now() }; },
    take() {
      const c = cur;
      cur = null;
      return c && now() - c.at <= INBOX_TTL_MS ? c.id : null;
    },
  };
}

module.exports = { parseApprove, createInbox, INBOX_TTL_MS };
