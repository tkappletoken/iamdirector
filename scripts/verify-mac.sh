#!/usr/bin/env bash
set -euo pipefail
dist="${1:-dist}"
team="${EXPECT_TEAM_ID:-Q5988V8U8D}"
app="$(find "${dist}" -maxdepth 2 -name '*.app' -type d -print -quit)"
test -n "${app}" || { echo "verify-mac: ${dist} 底下沒有 .app"; exit 1; }
echo "verify-mac: ${app}"

codesign --verify --deep --strict --verbose=2 "${app}"

info="$(codesign --display --verbose=2 "${app}" 2>&1)"
grep -q "^TeamIdentifier=${team}$" <<<"${info}" || { echo "verify-mac: TeamIdentifier 不是 ${team}"; grep -E 'Authority|TeamIdentifier' <<<"${info}"; exit 1; }
grep -q '^Authority=Developer ID Application:' <<<"${info}" || { echo "verify-mac: 不是 Developer ID Application 簽的"; exit 1; }

bad=0; count=0
while IFS= read -r -d '' f; do
  file -b "${f}" | grep -q 'Mach-O' || continue
  count=$((count + 1))
  d="$(codesign --display --verbose=2 "${f}" 2>&1 || true)"
  if ! grep -q 'flags=.*runtime' <<<"${d}" || ! grep -q "^TeamIdentifier=${team}$" <<<"${d}"; then
    echo "verify-mac: 沒有 hardened runtime 或 Team 不對：${f#"${app}"/}"; bad=1
  fi
done < <(find "${app}/Contents" -type f \( -perm -u+x -o -name '*.dylib' -o -name '*.node' -o -name '*.so' \) -print0)
test "${count}" -gt 0 || { echo "verify-mac: 一個 Mach-O 都沒找到（檢查器沒在檢查）"; exit 1; }
test "${bad}" -eq 0
echo "verify-mac: ${count} 個 Mach-O 都有 hardened runtime"

spctl -a -vv -t exec "${app}"

xcrun stapler validate "${app}"

zip="$(find "${dist}" -maxdepth 1 -name '*.zip' -print -quit)"
if [ -n "${zip}" ]; then
  work="$(mktemp -d)"; trap 'rm -rf "${work}"' EXIT
  ditto -x -k "${zip}" "${work}"
  x="$(find "${work}" -maxdepth 1 -name '*.app' -type d -print -quit)"
  test -n "${x}" || { echo "verify-mac: zip 解不出 .app"; exit 1; }
  codesign --verify --deep --strict --verbose=2 "${x}"
  xcrun stapler validate "${x}"
  echo "verify-mac: 更新 zip 解開後簽章與 staple 都正常"
fi
echo "verify-mac: 全部通過"
