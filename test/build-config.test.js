'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '..');
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'));
const mac = pkg.build.mac;
const WF = path.join(root, '.github', 'workflows', 'release.yml');
const wf = fs.existsSync(WF) ? fs.readFileSync(WF, 'utf8') : null;
const REL = { skip: !wf && '這個 repo 沒有 release.yml' };

test('mac：hardened runtime、兩份 entitlements 都存在、有 zip（自動更新要用）', () => {
  assert.equal(mac.hardenedRuntime, true);
  for (const k of ['entitlements', 'entitlementsInherit']) assert.ok(fs.existsSync(path.join(root, mac[k])), mac[k]);
  assert.ok(mac.target.some((t) => t.target === 'zip'));
  assert.ok(!('identity' in mac), 'identity 不寫死：有憑證時由 CSC_LINK 決定，沒有時 dist-mac.mjs 給 "-"');
});

test('entitlements 不開會削弱 hardened runtime 的權限', () => {
  for (const k of ['entitlements', 'entitlementsInherit']) {
    const x = (fs.readFileSync(path.join(root, mac[k]), 'utf8').match(/<key>[^<]*<\/key>/g) || []).join('\n');
    for (const bad of ['disable-library-validation', 'allow-dyld-environment-variables', 'get-task-allow']) {
      assert.ok(!x.includes(bad), `${mac[k]} 開了 ${bad}`);
    }
  }
});

test('dmg 外殼不簽', () => assert.equal(pkg.build.dmg.sign, false));

test('dist:mac 走 dist-mac.mjs（沒憑證時關掉鑰匙圈自動尋找）', () => {
  assert.match(pkg.scripts['dist:mac'], /dist-mac\.mjs/);
  const s = fs.readFileSync(path.join(root, 'scripts', 'dist-mac.mjs'), 'utf8');
  assert.match(s, /CSC_IDENTITY_AUTO_DISCOVERY = 'false'/);
});

test('workflow：只引用 Secrets 名稱、不含任何值；正式版強制公證；三項驗證都在', REL, () => {
  for (const k of ['CSC_LINK', 'CSC_KEY_PASSWORD', 'APPLE_API_KEY', 'APPLE_API_KEY_ID', 'APPLE_API_ISSUER']) {
    assert.ok(wf.includes(`secrets.${k}`), k);
  }
  assert.ok(!/BEGIN [A-Z ]*PRIVATE KEY-----\n[A-Za-z0-9+/]/.test(wf));
  assert.ok(!/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/.test(wf), 'Issuer ID 不寫死');
  assert.match(wf, /REQUIRE_NOTARIZE: '1'/);
  assert.match(fs.readFileSync(path.join(root, 'scripts', 'dist-mac.mjs'), 'utf8'), /'--publish', 'never'/);
  const v = fs.readFileSync(path.join(root, 'scripts', 'verify-mac.sh'), 'utf8');
  for (const c of ['codesign --verify --deep --strict', 'spctl -a -vv', 'stapler validate', 'flags=.*runtime']) assert.ok(v.includes(c), c);
});

test('workflow 安全：只有 tag 與手動補發觸發、頂層權限全關、兩組 Secrets 各在自己那一步', REL, () => {
  const on = wf.slice(wf.indexOf('\non:'), wf.indexOf('\npermissions:'));
  assert.match(on, /tags:\s*\n\s*- 'desktop-v\*'/);
  for (const t of ['pull_request', 'pull_request_target', 'workflow_run', 'issue_comment', 'repository_dispatch']) {
    assert.ok(!new RegExp(`^\\s+${t}:`, 'm').test(on), `不准有 ${t} 觸發`);
  }
  assert.match(wf, /^permissions: \{\}$/m);
  assert.ok(!/^\s+contents: write/m.test(wf), '發佈靠 RELEASES_TOKEN，本 repo 的 token 不需要寫入權');
  assert.ok(!/run:[^\n]*\$\{\{\s*inputs\./.test(wf), 'inputs 不准直接插進 run');
  assert.match(wf, /\^desktop-v\[0-9\]\+/);
  const steps = wf.split(/\n      - /).filter((s) => s.includes('secrets.'));
  assert.equal(steps.length, 2, 'Secrets 只准出現在「打包、簽章、公證」與「發佈」兩步');
  assert.match(steps[0], /^name: 打包、簽章、公證/);
  assert.ok(!steps[0].includes('RELEASES_TOKEN'), '打包那一步拿不到發佈權杖');
  assert.match(steps[1], /^name: 發佈到公開 repo/);
  assert.deepEqual(steps[1].match(/secrets\.[A-Z_]+/g), ['secrets.RELEASES_TOKEN'], '發佈那一步只拿得到 RELEASES_TOKEN');
});

test('發佈：不覆蓋已發佈的版本、三平台全成功才發、先 draft 全部上傳核對才公開、latest*.yml 一起發', REL, () => {
  const pub = wf.slice(wf.indexOf('name: 發佈到公開 repo'));
  assert.match(wf, /PUBLIC_REPO: tkappletoken\/iamdirector-releases/);
  assert.ok(wf.indexOf('不能已經有這個版本') < wf.indexOf('npm ci'), '打包前先確認公開 repo 沒有這個版本');
  assert.match(pub, /gh release view "\$\{TAG\}"[^\n]*\n\s*echo "::error::[^\n]*不覆蓋"; exit 1/);
  assert.ok(!/--clobber/.test(wf), '上傳不准覆蓋既有檔案');
  const c = pub.indexOf('--draft '), u = pub.indexOf('gh release upload'), e = pub.indexOf('--draft=false');
  assert.ok(c > 0 && c < u && u < e, '順序要是：建 draft → 上傳 → 核對 → 公開');
  assert.match(pub, /--latest/);
  assert.match(pub, /latest\*\.yml/);
  assert.ok(wf.indexOf('release-manifest.mjs') > 0 && wf.indexOf('release-manifest.mjs') < wf.indexOf('gh release create'));
  assert.match(wf, /needs: \[mac, linux, windows\]/);
});

test('自動更新：發佈來源是公開的 iamdirector-releases（只認正式 release），設定裡沒有 token', () => {
  assert.deepEqual(pkg.build.publish, [{ provider: 'github', owner: 'tkappletoken', repo: 'iamdirector-releases', releaseType: 'release' }]);
  for (const pub of pkg.build.publish) assert.ok(!Object.keys(pub).some((k) => /token/i.test(k)), 'publish 設定不能帶 token（會被打進 app-update.yml）');
});

test('測試版（prerelease）只能從 workflow_dispatch 勾選，發佈時不設 Latest，並讀回 /releases/latest 驗證', REL, () => {
  assert.match(wf, /PRERELEASE: \$\{\{ github\.event_name == 'workflow_dispatch' && inputs\.prerelease == true && 'true' \|\| 'false' \}\}/);
  assert.ok(!/PRERELEASE:.*(ref_name|TAG|contains|startsWith)/.test(wf), 'prerelease 不能從 tag 名稱推出來');
  assert.match(wf, /--prerelease --latest=false/);
  assert.match(wf, /releases\/latest/);
  assert.match(wf, /內部測試用，請勿下載/);
  assert.match(wf, /PRERELEASE}" != true \] && grep -q '內部測試用'/, '測試版推 tag 觸發時要在預檢擋下');
});

test('CI 打包一律 --publish never（上傳只由 release.yml 的發佈 job 做）', REL, () => {
  const bc = fs.readFileSync(path.join(root, '.github', 'workflows', 'build-check.yml'), 'utf8');
  const dm = fs.readFileSync(path.join(root, 'scripts', 'dist-mac.mjs'), 'utf8');
  for (const [name, s] of [['release.yml', wf], ['build-check.yml', bc]]) {
    const calls = s.match(/npx electron-builder[^\n]*/g) || [];
    assert.ok(calls.length > 0, name);
    for (const c of calls) assert.match(c, /--publish never/, `${name}: ${c}`);
  }
  assert.match(dm, /'--publish', 'never'/);
});

test('mac：electronLanguages 只留 zh_TW、zh_CN、en（en 是英文系統的退路）', () => {
  assert.deepEqual(mac.electronLanguages, ['zh_TW', 'zh_CN', 'en']);
});

test('build-check.yml（分支上的打包檢查）不准碰任何 Secrets、不准發佈', () => {
  const bc = fs.readFileSync(path.join(root, '.github', 'workflows', 'build-check.yml'), 'utf8');
  assert.ok(!bc.includes('secrets.'), '打包檢查不讀 Secrets');
  assert.ok(!/gh release|--publish always|--publish onTag/.test(bc), '打包檢查不發佈');
  assert.ok(!/^\s+(tags|pull_request_target|workflow_dispatch):/m.test(bc));
});

test('Windows 上傳不帶 __uninstaller.exe（不然 release-manifest 會數到 4 個 exe 而擋下發佈）', REL, () => {
  assert.match(wf, /!dist\/\*__uninstaller\*/);
});
