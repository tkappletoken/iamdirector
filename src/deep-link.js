'use strict';

const PREFIX = 'iamdirector://approve/';
const ID = /^apv_[A-Za-z0-9]{16,32}$/;
const INBOX_TTL_MS = 10 * 60 * 1000;

function parseApprove(url) {
  if (typeof url !== 'string' || url.length > PREFIX.length + 40) return null;
  if (!url.startsWith(PREFIX)) return null;
  const rest = url.slice(PREFIX.length);
  const slash = rest.endsWith('/') ? '/' : '';
  const id = rest.slice(0, rest.length - slash.length);
  if (!ID.test(id)) return null;
  let u;
  try { u = new URL(url); } catch (_) { return null; }
  if (u.protocol !== 'iamdirector:' || u.hostname !== 'approve' || u.username || u.password || u.port
    || u.search || u.hash || u.pathname !== '/' + id + slash) return null;
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

function createDelivery({ inbox, isAppPage, trace = () => {} }) {
  function deliver(wc) {
    if (!wc || wc.isDestroyed() || wc.isLoading()) return false;
    if (!isAppPage(wc.getURL())) return false;
    const id = inbox.take();
    if (!id) return false;
    trace('approve-link-delivered', {});
    wc.send('desktop:open-approval', id);
    return true;
  }
  function attach(wc) {
    wc.on('did-stop-loading', () => deliver(wc));
  }
  return { deliver, attach };
}

module.exports = { parseApprove, createInbox, createDelivery, INBOX_TTL_MS };
