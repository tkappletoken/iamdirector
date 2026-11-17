'use strict';

const DEFAULT = { width: 1440, height: 900 };
const MIN = { width: 1100, height: 700 };

function fitBounds(saved, workArea) {
  const wa = workArea;
  const minWidth = Math.min(MIN.width, wa.width);
  const minHeight = Math.min(MIN.height, wa.height);
  const ok = saved && [saved.width, saved.height].every((n) => Number.isFinite(n) && n > 0);
  const width = clamp(ok ? saved.width : DEFAULT.width, minWidth, wa.width);
  const height = clamp(ok ? saved.height : DEFAULT.height, minHeight, wa.height);

  const hasPos = ok && Number.isFinite(saved.x) && Number.isFinite(saved.y);
  const x = hasPos ? clamp(saved.x, wa.x, wa.x + wa.width - width) : wa.x + Math.round((wa.width - width) / 2);
  const y = hasPos ? clamp(saved.y, wa.y, wa.y + wa.height - height) : wa.y + Math.round((wa.height - height) / 2);
  return { x, y, width, height, minWidth, minHeight };
}

function clamp(n, lo, hi) { return Math.max(lo, Math.min(hi, Math.round(n))); }

module.exports = { fitBounds, DEFAULT, MIN };
