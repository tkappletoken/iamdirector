'use strict';

const APP_NAME = '我是導演';

const DOWNLOAD_PAGE = 'https://iamdirector.app';

function updateUnavailableText(version) {
  return {
    message: '這個安裝方式不會自動更新',
    detail: `目前版本 ${version}；這個安裝方式不會自動更新，請到官網下載新版：${DOWNLOAD_PAGE}`,
  };
}

function buildTemplate({ isMac, dev, version, askEveryDownload, downloadDir, updateConfigured, autoInstallOnQuit, actions }) {
  const a = actions;
  return [
    ...(isMac ? [{
      label: APP_NAME,
      submenu: [
        { role: 'about', label: `關於${APP_NAME}` },
        { type: 'separator' },
        { role: 'services', label: '服務' },
        { type: 'separator' },
        { role: 'hide', label: `隱藏${APP_NAME}` },
        { role: 'hideOthers', label: '隱藏其他' },
        { role: 'unhide', label: '顯示全部' },
        { type: 'separator' },
        { role: 'quit', label: `結束${APP_NAME}` },
      ],
    }] : []),
    {
      label: '檔案',
      submenu: [
        { label: '回到工作台', accelerator: 'CmdOrCtrl+Shift+H', click: a.goHome },
        ...(a.openKey ? [{ label: 'AppleToken 金鑰…', click: a.openKey }] : []),
        { type: 'separator' },
        { label: '設定成片下載資料夾…', click: a.chooseDownloadDir },
        {
          label: '每次下載都詢問存放位置', type: 'checkbox', checked: !!askEveryDownload,
          click: a.toggleAskEveryDownload,
        },
        { label: '打開下載資料夾', enabled: !!downloadDir, click: a.openDownloadDir },
        { type: 'separator' },
        isMac ? { role: 'close', label: '關閉視窗' } : { role: 'quit', label: '結束' },
      ],
    },
    {
      label: '編輯',
      submenu: [
        { role: 'undo', label: '還原' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪下' },
        { role: 'copy', label: '拷貝' },
        { role: 'paste', label: '貼上' },
        ...(isMac ? [{ role: 'pasteAndMatchStyle', label: '貼上並符合樣式' }] : []),
        { role: 'delete', label: '刪除' },
        { role: 'selectAll', label: '全選' },
      ],
    },
    {
      label: '顯示',
      submenu: [
        { role: 'reload', label: '重新載入' },
        { role: 'forceReload', label: '強制重新載入' },
        ...(dev ? [{ role: 'toggleDevTools', label: '開發者工具' }] : []),
        { type: 'separator' },
        { role: 'resetZoom', label: '實際大小' },
        { role: 'zoomIn', label: '放大' },
        { role: 'zoomOut', label: '縮小' },
        ...(isMac ? [] : [{ type: 'separator' }, { role: 'togglefullscreen', label: '全螢幕' }]),
      ],
    },
    {
      label: '前往',
      submenu: [
        { label: '上一頁', accelerator: 'CmdOrCtrl+[', click: a.goBack },
        { label: '下一頁', accelerator: 'CmdOrCtrl+]', click: a.goForward },
        { type: 'separator' },
        { label: '工作台', accelerator: 'CmdOrCtrl+1', click: a.goHome },
      ],
    },
    {
      label: '視窗', role: 'window',
      submenu: [
        { role: 'minimize', label: '縮到最小' },
        { role: 'zoom', label: '縮放' },
        ...(isMac ? [{ type: 'separator' }, { role: 'front', label: '將所有視窗移至最前' }] : [{ role: 'close', label: '關閉' }]),
      ],
    },
    {
      role: 'help', label: '說明',
      submenu: [
        { label: '在瀏覽器開啟目前頁面', click: a.openInBrowser },
        { label: '檢查更新…', click: updateConfigured ? a.checkUpdatesNow : a.showUpdateInfo },
        ...(a.openh264Settings ? [{ label: 'H.264 編碼器（OpenH264）…', click: a.openh264Settings }] : []),
        ...(updateConfigured ? [{ label: '結束時自動安裝更新', type: 'checkbox', checked: autoInstallOnQuit !== false, click: a.toggleAutoInstallOnQuit }] : []),
        { label: `版本 ${version}`, enabled: false },
      ],
    },
  ];
}

module.exports = { APP_NAME, DOWNLOAD_PAGE, buildTemplate, updateUnavailableText };
