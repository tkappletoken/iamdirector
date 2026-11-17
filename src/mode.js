'use strict';
const MODES = ['local', 'cloud'];

function decide({ saved, envUrl, hasCloudSession }) {
  if (MODES.includes(saved)) return saved;
  if (envUrl) return 'cloud';
  if (hasCloudSession) return 'cloud';
  return 'local';
}

module.exports = { decide, MODES };
