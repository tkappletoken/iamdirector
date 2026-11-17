'use strict';
const MODES = ['local', 'cloud'];

function decide({ envUrl, packaged } = {}) {
  if (!packaged && envUrl) return 'cloud';
  return 'local';
}

function moveNotice({ saved, hasCloudSession, noticed } = {}) {
  if (noticed) return false;
  if (saved === 'cloud') return true;
  return !MODES.includes(saved) && !!hasCloudSession;
}

module.exports = { decide, moveNotice, MODES };
