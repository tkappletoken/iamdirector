'use strict';
const crypto = require('node:crypto');
const path = require('node:path');

const VERSION = '2.6.0';
const SO_NAME = 'libopenh264.so.8';
const URL = `https://ciscobinary.openh264.org/libopenh264-${VERSION}-linux64.8.so.bz2`;
const BZ2_SHA256 = '27ab53323c110b76214c1c72222f459d17febbcd1e252136cadc292b0308d75b';
const SO_SHA256 = '2f0cde7c6a6abcf5cae76942894ea42897fa677bce4ed6c91a24dd1b041d5f04';
const MAX_BYTES = 8 * 1024 * 1024;
const NOTICE = 'OpenH264 Video Codec provided by Cisco Systems, Inc.';

const sha256 = (buf) => crypto.createHash('sha256').update(buf).digest('hex');

function applies({ fs, platform, ffmpegDir }) {
  return platform === 'linux' && !!ffmpegDir && fs.existsSync(path.join(ffmpegDir, SO_NAME));
}

function dirOf(userData) {
  return path.join(userData, 'openh264', VERSION);
}

function verifyInstalled({ fs, userData }) {
  const d = dirOf(userData);
  const f = path.join(d, SO_NAME);
  let buf;
  try { buf = fs.readFileSync(f); } catch (_) { return null; }
  if (sha256(buf) === SO_SHA256) return d;
  try { fs.unlinkSync(f); } catch (_) {}
  return null;
}

async function install({ fs, userData, download, bunzip2 }) {
  const bz = await download(URL);
  if (!Buffer.isBuffer(bz) || bz.length > MAX_BYTES) throw new Error('下載的檔案大小不對');
  if (sha256(bz) !== BZ2_SHA256) throw new Error('下載的檔案比對不符（不是 Cisco 發布的那一份）');
  const so = await bunzip2(bz);
  if (!Buffer.isBuffer(so) || so.length > MAX_BYTES || sha256(so) !== SO_SHA256) {
    throw new Error('解壓後的檔案比對不符');
  }
  const d = dirOf(userData);
  fs.mkdirSync(d, { recursive: true, mode: 0o700 });
  const tmp = path.join(d, SO_NAME + '.part');
  fs.writeFileSync(tmp, so, { mode: 0o644 });
  fs.renameSync(tmp, path.join(d, SO_NAME));
  return d;
}

function remove({ fs, userData }) {
  try { fs.rmSync(dirOf(userData), { recursive: true, force: true }); } catch (_) {}
}

const ASK = {
  title: 'H.264 編碼器',
  message: '要從 Cisco 下載免費的 H.264 編碼器嗎？',
  detail: '匯出 MP4 需要 H.264 編碼器。為了專利授權，安裝檔裡沒有附，'
    + '要由這台電腦直接從 Cisco 的伺服器（ciscobinary.openh264.org）下載，約 1MB，免費。\n\n'
    + NOTICE + '\n\n'
    + '不下載的話，這次改匯出 WebM（VP9／Opus），大部分影片平台和瀏覽器都能播。'
    + '之後可以在「說明 → H.264 編碼器（OpenH264）…」啟用或停用。',
  buttons: ['下載並匯出 MP4', '改匯出 WebM'],
  remember: '記住我的選擇',
};

module.exports = {
  VERSION, SO_NAME, URL, BZ2_SHA256, SO_SHA256, MAX_BYTES, NOTICE, ASK,
  applies, dirOf, verifyInstalled, install, remove, sha256,
};
