import * as THREE from './vendor/three.module.min.js';
import { OrbitControls } from './vendor/OrbitControls.js';
import { TransformControls } from './vendor/TransformControls.js';
import * as C from './core.js';

const RAD = Math.PI / 180;
const $h = (tag, cls, txt) => { const e = document.createElement(tag); if (cls) e.className = cls; if (txt != null) e.textContent = txt; return e; };
const btn = (cls, txt, title, fn) => { const b = $h('button', cls, txt); b.type = 'button'; if (title) b.title = title; if (fn) b.onclick = fn; return b; };
const shade = (hex, k) => { const c = new THREE.Color(hex); c.multiplyScalar(k); return c; };

const CSS = `
.pv{position:fixed;inset:0;z-index:400;display:grid;grid-template-rows:56px 1fr 196px;grid-template-columns:232px 1fr 288px;
  grid-template-areas:"top top top" "left view right" "tl tl tl";background:#0b0d10;color:#e4e7eb;
  font:13px/1.45 -apple-system,BlinkMacSystemFont,"Noto Sans TC","PingFang TC",sans-serif;--a:#e8a33d;--line:#232931;--line2:#323a45;
  --mute:#8c949f;--faint:#5f6873;--panel:#111418;--panel2:#161a1f;--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace;animation:pvIn .28s cubic-bezier(.2,.7,.2,1)}
@keyframes pvIn{from{transform:scale(.99)}to{transform:none}}
@media (prefers-reduced-motion:reduce){.pv{animation:none}}
.pv *{box-sizing:border-box}
.pv button{font:inherit;color:inherit;cursor:pointer;width:auto;margin:0;padding:0;border:0;border-radius:0;background:none;min-width:0;text-align:center}
.pv label{margin:0;text-transform:none;letter-spacing:normal}
.pv input,.pv select{font:inherit;color:#e4e7eb;background:#0e1114;border:1px solid var(--line2);border-radius:6px;height:28px;padding:0 8px;width:100%;margin:0}
.pv input:focus,.pv select:focus{outline:none;border-color:var(--a)}
.pv-top{grid-area:top;display:flex;align-items:center;gap:14px;padding:0 14px 0 18px;border-bottom:1px solid var(--line);background:linear-gradient(#101317,#0c0e11)}
.pv-brand{display:flex;align-items:baseline;gap:10px;white-space:nowrap}
.pv-brand b{font:700 10px/1 var(--mono);letter-spacing:.28em;color:var(--a)}
.pv-brand span{font-weight:600;font-size:15px;letter-spacing:.02em}
.pv-shots{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;min-width:0;flex:1}
.pv-shot{flex:none;display:flex;align-items:center;gap:7px;height:32px;padding:0 11px 0 8px;border-radius:8px;border:1px solid transparent;background:transparent;color:var(--mute);max-width:230px}
.pv-shot .n{font:600 10px/1 var(--mono);width:20px;height:20px;border-radius:5px;display:grid;place-items:center;background:#1b1f26;color:var(--mute)}
.pv-shot .p{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:12px}
.pv-shot .dot{width:6px;height:6px;border-radius:50%;background:#5bc8d8;flex:none}
.pv-shot:hover{background:#151920;color:#e4e7eb}
.pv-shot.on{border-color:var(--line2);background:#171b21;color:#e4e7eb}
.pv-shot.on .n{background:var(--a);color:#16110a}
.pv-meta{display:flex;align-items:center;gap:8px;white-space:nowrap}
.pv-chip{display:inline-flex;align-items:center;gap:6px;height:30px;padding:0 11px;border-radius:999px;border:1px solid var(--line2);background:#12161b;font:500 11.5px/1 var(--mono);color:#c9ced5}
.pv-chip:hover{border-color:#4a5462}
.pv-chip i{font-style:normal;color:var(--faint)}
.pv-save{font:500 11px/1 var(--mono);color:var(--faint);min-width:92px;text-align:right}
.pv-save.dirty{color:var(--mute)}.pv-save.err{color:#ff8b8e}
.pv-go{height:34px;padding:0 16px;border-radius:9px;border:0;background:var(--a);color:#16110a;font-weight:700;letter-spacing:.02em;box-shadow:0 0 0 1px rgba(232,163,61,.4),0 6px 22px -8px rgba(232,163,61,.65)}
.pv-go:hover{filter:brightness(1.08)}
.pv-x{width:34px;height:34px;border-radius:9px;border:1px solid var(--line2);background:transparent;color:var(--mute);font-size:15px}
.pv-x:hover{color:#fff;border-color:#4a5462}
.pv-left,.pv-right{background:var(--panel);overflow:auto;scrollbar-width:thin}
.pv-left{grid-area:left;border-right:1px solid var(--line)}
.pv-right{grid-area:right;border-left:1px solid var(--line)}
.pv-sec{padding:14px 14px 12px;border-bottom:1px solid var(--line)}
.pv-h{display:flex;align-items:center;justify-content:space-between;font:700 9.5px/1 var(--mono);letter-spacing:.22em;color:var(--faint);margin-bottom:10px;text-transform:uppercase}
.pv-h em{font-style:normal;letter-spacing:.04em;color:var(--mute);font-weight:500}
.pv-add{display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px}
.pv-add button{height:52px;border-radius:9px;border:1px solid var(--line2);background:var(--panel2);display:flex;flex-direction:column;align-items:center;justify-content:center;gap:4px;font-size:11.5px;color:#c9ced5}
.pv-add button:hover{border-color:var(--a);color:#fff}
.pv-add button svg{width:18px;height:18px;opacity:.9}
.pv-list{display:flex;flex-direction:column;gap:2px}
.pv-item{display:flex;align-items:center;gap:9px;height:34px;padding:0 8px;border-radius:7px;border:1px solid transparent;background:transparent;text-align:left;width:100%;color:#c9ced5}
.pv-item:hover{background:#171b21}
.pv-item.on{background:#1c2128;border-color:#3a4350;color:#fff}
.pv-item .sw{width:14px;height:14px;border-radius:4px;flex:none;box-shadow:inset 0 0 0 1px rgba(255,255,255,.12)}
.pv-item .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pv-item .k{font:500 10px/1 var(--mono);color:var(--faint)}
.pv-item .kf{color:var(--a);font-size:10px}
.pv-item img{width:22px;height:22px;border-radius:5px;object-fit:cover;flex:none}
.pv-view{grid-area:view;position:relative;overflow:hidden;background:#0b0d10}
.pv-view canvas.main{position:absolute;inset:0;width:100%;height:100%;display:block;outline:none}
.pv-tools{position:absolute;left:14px;top:14px;display:flex;flex-direction:column;gap:2px;padding:4px;border-radius:11px;background:rgba(16,19,23,.82);backdrop-filter:blur(10px);border:1px solid var(--line2)}
.pv-tools button{width:36px;height:36px;border-radius:8px;border:0;background:transparent;color:var(--mute);display:grid;place-items:center;position:relative}
.pv-tools button svg{width:18px;height:18px}
.pv-tools button:hover{color:#fff;background:#1b2027}
.pv-tools button.on{background:#262c35;color:var(--a)}
.pv-tools button kbd{position:absolute;right:3px;bottom:2px;font:600 8px/1 var(--mono);color:var(--faint)}
.pv-tools hr{border:0;border-top:1px solid var(--line2);margin:3px 4px}
.pv-viewsw{position:absolute;left:50%;top:14px;transform:translateX(-50%);display:flex;padding:3px;border-radius:999px;background:rgba(16,19,23,.82);backdrop-filter:blur(10px);border:1px solid var(--line2)}
.pv-viewsw button{background:transparent;height:28px;padding:0 14px;border-radius:999px;border:0;background:transparent;color:var(--mute);font-size:12px;white-space:nowrap}
.pv-viewsw button.on{background:#e4e7eb;color:#0d0f13;font-weight:600}
.pv-pip{position:absolute;right:14px;top:14px;border-radius:9px;box-shadow:0 0 0 1px rgba(255,255,255,.14),0 16px 40px -12px rgba(0,0,0,.7);cursor:pointer;overflow:hidden;pointer-events:auto}
.pv-pip .lb{position:absolute;left:0;right:0;bottom:0;display:flex;justify-content:space-between;padding:5px 8px;font:600 9.5px/1 var(--mono);letter-spacing:.08em;color:#fff;background:linear-gradient(transparent,rgba(0,0,0,.6))}
.pv-pip .rec{color:var(--a)}
.pv-pip.narrow .rec{display:none}
.pv-pip.narrow .lb{font-size:9px;letter-spacing:.02em;padding:5px 6px}
.pv-frame{position:absolute;pointer-events:none;box-shadow:0 0 0 1px rgba(255,255,255,.5),0 0 0 9999px rgba(5,6,8,.72)}
.pv-frame i{position:absolute;background:rgba(255,255,255,.14)}
.pv-frame .tc{position:absolute;left:10px;top:9px;font:600 10px/1 var(--mono);letter-spacing:.1em;color:rgba(255,255,255,.85);text-shadow:0 1px 2px rgba(0,0,0,.6)}
.pv-frame .tr{position:absolute;right:10px;top:9px;font:600 10px/1 var(--mono);color:rgba(255,255,255,.85);text-shadow:0 1px 2px rgba(0,0,0,.6)}
.pv-vig{position:absolute;inset:0;pointer-events:none;background:radial-gradient(120% 90% at 50% 40%,transparent 55%,rgba(4,5,7,.55) 100%)}
.pv-tags{position:absolute;inset:0;pointer-events:none;overflow:hidden}
.pv-tag{position:absolute;transform:translate(-50%,-100%);display:flex;align-items:center;gap:5px;padding:3px 8px 3px 6px;border-radius:999px;background:rgba(12,14,18,.78);backdrop-filter:blur(6px);border:1px solid rgba(255,255,255,.1);font:600 10.5px/1 -apple-system,"PingFang TC",sans-serif;color:#e4e7eb;white-space:nowrap}
.pv-tag i{width:7px;height:7px;border-radius:50%}
.pv-tag.on{border-color:var(--a);color:#fff}
.pv-read{position:absolute;pointer-events:none;padding:5px 9px;border-radius:7px;background:#e8a33d;color:#16110a;font:600 10.5px/1 var(--mono);white-space:nowrap;transform:translate(14px,14px);display:none}
.pv-lbl{font:600 9px/1 var(--mono);letter-spacing:.16em;color:var(--faint);margin:10px 0 5px}
.pv-hud{position:absolute;left:14px;bottom:12px;display:flex;gap:12px;align-items:center;padding:6px 10px;border-radius:8px;background:rgba(12,14,18,.7);backdrop-filter:blur(6px);font:500 10.5px/1 var(--mono);color:#8c949f;pointer-events:none}
.pv-hud b{color:#e4e7eb;font-weight:600;margin-right:3px}
.pv-coach{position:absolute;left:66px;bottom:44px;width:300px;padding:14px 16px 12px;border-radius:12px;background:rgba(18,22,27,.94);border:1px solid var(--line2);box-shadow:0 18px 50px -18px rgba(0,0,0,.8)}
.pv-coach h4{margin:0 0 8px;font-size:13px;letter-spacing:.02em}
.pv-coach ol{margin:0;padding-left:18px;color:#bfc5cd;font-size:12px;line-height:1.75}
.pv-coach ol b{color:#fff;font-weight:600}
.pv-coach .row{display:flex;justify-content:flex-end;margin-top:8px}
.pv-coach button{height:26px;padding:0 12px;border-radius:7px;border:1px solid var(--line2);background:transparent;font-size:11.5px}
.pv-toast{position:absolute;left:50%;bottom:16px;transform:translateX(-50%);padding:8px 14px;border-radius:9px;background:#e4e7eb;color:#0d0f13;font-size:12px;font-weight:500;box-shadow:0 10px 30px -10px rgba(0,0,0,.6);pointer-events:none;opacity:0;transition:opacity .18s}
.pv-toast.on{opacity:1}
.pv-f{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
.pv-f label{display:flex;flex-direction:column;gap:3px;font:600 9px/1 var(--mono);letter-spacing:.14em;color:var(--faint)}
.pv-f label input{font:500 12px/1 var(--mono);padding:0 6px;height:28px}
.pv-f2{display:grid;grid-template-columns:1fr 1fr;gap:6px}
.pv-row{display:flex;gap:6px;align-items:center;margin-top:8px}
.pv-row>*{flex:1}
.pv-sws{display:flex;gap:6px;flex-wrap:wrap}
.pv-sws button{width:26px;height:26px;border-radius:7px;border:0;position:relative;box-shadow:inset 0 0 0 1px rgba(255,255,255,.15)}
.pv-sws button.on{box-shadow:0 0 0 2px #0b0d10,0 0 0 4px #e4e7eb}
.pv-sws button.clash::after{content:"";position:absolute;right:-3px;top:-3px;width:9px;height:9px;border-radius:50%;background:#e8a33d;box-shadow:0 0 0 2px #111418}
.pv-sws button:disabled{opacity:.25;cursor:not-allowed}
.pv-note{font-size:11.5px;color:var(--mute);margin-top:8px;line-height:1.55}
.pv-note.warn{color:#e8a33d}
.pv-card{display:flex;gap:10px;align-items:center;padding:8px;border-radius:9px;background:var(--panel2);border:1px solid var(--line);margin-bottom:10px}
.pv-card img{width:44px;height:44px;border-radius:7px;object-fit:cover}
.pv-card .t{font-weight:600}.pv-card .s{font-size:11px;color:var(--mute)}
.pv-btn{height:30px;padding:0 12px;border-radius:8px;border:1px solid var(--line2);background:var(--panel2);font-size:12px;color:#d7dbe0;white-space:nowrap}
.pv-btn:hover{border-color:#4a5462;color:#fff}
.pv-btn.pri{border-color:rgba(232,163,61,.6);color:var(--a)}
.pv-btn.pri:hover{background:rgba(232,163,61,.1)}
.pv-btn.dng:hover{border-color:#e0705c;color:#ff8b8e}
.pv-focal{display:flex;gap:3px;margin-top:6px}
.pv-focal button{flex:1;height:26px;border-radius:6px;border:1px solid var(--line2);background:transparent;font:500 10.5px/1 var(--mono);color:var(--mute);padding:0}
.pv-focal button.on{border-color:var(--a);color:var(--a)}
.pv input[type=range]{height:22px;padding:0;border:0;background:transparent;accent-color:#e8a33d}
.pv-cam{padding:10px;border-radius:9px;background:var(--panel2);border:1px solid var(--line)}
.pv-cam .mv{font-weight:600;font-size:13px}
.pv-cam .sub{font:500 10.5px/1.5 var(--mono);color:var(--mute);margin-top:2px}
.pv-empty{padding:24px 16px;color:var(--faint);font-size:12px;line-height:1.7}
.pv-tl{grid-area:tl;border-top:1px solid var(--line);background:#0e1013;display:grid;grid-template-rows:42px 1fr;min-height:0}
.pv-tr{display:flex;align-items:center;gap:8px;padding:0 14px;border-bottom:1px solid var(--line)}
.pv-tr .tb{width:32px;height:30px;border-radius:7px;border:1px solid transparent;background:transparent;color:#c9ced5;display:grid;place-items:center}
.pv-tr .tb:hover{background:#1a1e24}
.pv-tr .tb.play{background:#e4e7eb;color:#0d0f13;width:38px}
.pv-tr .tb svg{width:15px;height:15px}
.pv-time{font:600 13px/1 var(--mono);letter-spacing:.04em;margin:0 6px;min-width:118px}
.pv-time i{font-style:normal;color:var(--faint)}
.pv-sp{flex:1}
.pv-tg{display:inline-flex;align-items:center;gap:7px;height:30px;padding:0 11px;border-radius:8px;border:1px solid var(--line2);background:transparent;font-size:12px;color:var(--mute)}
.pv-tg .lt{width:8px;height:8px;border-radius:50%;background:#3a414b}
.pv-tg.on{color:#fff}.pv-tg.on .lt{background:#e0505c;box-shadow:0 0 8px #e0505c}
.pv-key{display:inline-flex;align-items:center;gap:7px;height:30px;padding:0 12px;border-radius:8px;border:1px solid rgba(232,163,61,.55);background:rgba(232,163,61,.08);color:var(--a);font-size:12px;font-weight:600}
.pv-key:hover{background:rgba(232,163,61,.16)}
.pv-tracks{position:relative;overflow:auto;min-height:0;scrollbar-width:thin}
.pv-ruler{position:sticky;top:0;z-index:2;height:24px;display:flex;background:#0e1013;border-bottom:1px solid var(--line)}
.pv-ruler .lab{width:180px;flex:none;border-right:1px solid var(--line)}
.pv-ruler .sc{position:relative;flex:1;cursor:ew-resize;margin-right:18px}
.pv-ruler .tick{position:absolute;bottom:0;width:1px;background:#2b323b}
.pv-ruler .tick.big{background:#465060}
.pv-ruler .tick span{position:absolute;bottom:9px;left:4px;font:500 9.5px/1 var(--mono);color:var(--faint);white-space:nowrap}
.pv-trk{display:flex;height:30px;border-bottom:1px solid #171b20}
.pv-trk .lab{width:180px;flex:none;display:flex;align-items:center;gap:8px;padding:0 12px;border-right:1px solid var(--line);font-size:12px;color:#aeb4bc;cursor:pointer;overflow:hidden;white-space:nowrap}
.pv-trk .lab .sw{width:10px;height:10px;border-radius:3px;flex:none}
.pv-trk.on .lab{color:#fff;background:#151920}
.pv-trk .ln{position:relative;flex:1;margin-right:18px;cursor:crosshair}
.pv-trk:hover .lab{color:#fff}
.pv-trk:hover .ln{background:rgba(255,255,255,.018)}
.pv-trk.on .ln{background:linear-gradient(rgba(232,163,61,.05),rgba(232,163,61,.05))}
.pv-trk .seg{position:absolute;top:13px;height:4px;border-radius:2px;background:#2a313a}
.pv-trk.on .seg{background:rgba(232,163,61,.35)}
.pv-dia{position:absolute;top:8px;width:14px;height:14px;margin-left:-7px;border:0;padding:0;background:transparent!important;cursor:grab}
.pv-dia::before{content:"";position:absolute;inset:2px;transform:rotate(45deg);border-radius:2px;background:#c9ced5;box-shadow:0 0 0 1.5px #0e1013}
.pv-trk.on .pv-dia::before{background:var(--a)}
.pv-dia.sel::before{background:#fff;box-shadow:0 0 0 1.5px #0e1013,0 0 0 3px var(--a)}
.pv-dia.io::before{border-radius:50%}
.pv-ph{position:absolute;top:0;bottom:0;width:0;z-index:3;pointer-events:none}
.pv-ph::before{content:"";position:absolute;top:0;bottom:0;left:-.5px;width:1px;background:var(--a)}
.pv-ph::after{content:"";position:absolute;top:0;left:-6px;width:12px;height:10px;background:var(--a);clip-path:polygon(0 0,100% 0,100% 55%,50% 100%,0 55%)}
.pv-pop{position:absolute;z-index:20;min-width:220px;max-height:360px;overflow:auto;padding:6px;border-radius:11px;background:#151a20;border:1px solid var(--line2);box-shadow:0 22px 60px -18px rgba(0,0,0,.85)}
.pv-pop .gh{font:700 9px/1 var(--mono);letter-spacing:.2em;color:var(--faint);padding:8px 8px 6px}
.pv-pop button{display:flex;align-items:center;gap:9px;width:100%;height:34px;padding:0 9px;border-radius:7px;border:0;background:transparent;text-align:left;font-size:12.5px;color:#d7dbe0}
.pv-pop button:hover{background:#20262e}
.pv-pop button .d{margin-left:auto;font:500 10.5px/1 var(--mono);color:var(--faint)}
.pv-pop button img{width:24px;height:24px;border-radius:5px;object-fit:cover}
.pv-pop button .sw{width:14px;height:14px;border-radius:4px}
.pv-pop button.on{color:var(--a)}
.pv-modal{position:absolute;inset:0;z-index:30;display:grid;place-items:center;background:rgba(5,6,8,.66);backdrop-filter:blur(6px)}
.pv-dlg{width:min(760px,92vw);border-radius:16px;background:#12161b;border:1px solid var(--line2);box-shadow:0 40px 120px -30px rgba(0,0,0,.9);overflow:hidden}
.pv-dlg .hd{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--line)}
.pv-dlg .hd b{font-size:15px}
.pv-dlg .bd{display:grid;grid-template-columns:1.35fr 1fr;gap:18px;padding:18px 20px}
.pv-dlg video{width:100%;border-radius:10px;background:#000;display:block}
.pv-dlg dl{margin:0;display:grid;grid-template-columns:auto 1fr;gap:7px 12px;font-size:12px}
.pv-dlg dt{color:var(--faint);font:600 10px/1.6 var(--mono);letter-spacing:.12em}
.pv-dlg dd{margin:0;font:500 12px/1.5 var(--mono);color:#d7dbe0;word-break:break-all}
.pv-dlg .ft{display:flex;gap:8px;justify-content:flex-end;padding:14px 20px;border-top:1px solid var(--line);background:#0f1216}
.pv-bar{height:6px;border-radius:3px;background:#20262e;overflow:hidden;margin-top:14px}
.pv-bar i{display:block;height:100%;background:var(--a);width:0;transition:width .1s}
.pv-prog{padding:28px 24px}
.pv-prog .st{font:500 12px/1.6 var(--mono);color:var(--mute);margin-top:8px}
.pv-kn{margin-top:12px;padding:10px 12px;border-radius:9px;background:#0d1013;border:1px solid var(--line);font-size:12px;line-height:1.6;color:#c9ced5}
.pv-kn b{display:block;font:700 9px/1 var(--mono);letter-spacing:.2em;color:var(--faint);margin-bottom:6px}
@media (max-width:1100px){.pv{grid-template-columns:200px 1fr 252px}}
`;

function scoped(css) {
  return css.split('\n').map(line => {
    if (!line.startsWith('.pv-')) return line;
    const i = line.indexOf('{');
    return line.slice(0, i).split(',').map(x => '.pv ' + x.trim()).join(',') + line.slice(i);
  }).join('\n');
}

const ICON = {
  sel: '<path d="M5 3l13 7-6 1.6L9.5 18z"/>',
  move: '<path d="M12 3v18M3 12h18M12 3l-3 3M12 3l3 3M12 21l-3-3M12 21l3-3M3 12l3-3M3 12l3 3M21 12l-3-3M21 12l-3 3"/>',
  rot: '<path d="M20 12a8 8 0 1 1-3-6.2"/><path d="M20 4v5h-5"/>',
  scl: '<rect x="4" y="10" width="10" height="10" rx="1"/><path d="M13 4h7v7M20 4l-8 8"/>',
  focus: '<circle cx="12" cy="12" r="3"/><path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  char: '<rect x="9" y="2.5" width="6" height="5" rx="1"/><rect x="7.5" y="8.5" width="9" height="6" rx="1"/><rect x="8.5" y="15.5" width="7" height="6" rx="1"/>',
  prop: '<path d="M4 8l8-4 8 4v8l-8 4-8-4z"/><path d="M4 8l8 4 8-4M12 12v8"/>',
  set: '<path d="M3 20h18M5 20V8l7-4 7 4v12"/><path d="M9 20v-6h6v6"/>',
  play: '<path d="M7 4.5v15l12-7.5z" fill="currentColor" stroke="none"/>',
  pause: '<rect x="6" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/><rect x="14" y="4.5" width="4" height="15" rx="1" fill="currentColor" stroke="none"/>',
  first: '<path d="M6 5v14M18 5l-9 7 9 7z"/>',
  last: '<path d="M18 5v14M6 5l9 7-9 7z"/>',
  prev: '<path d="M15 5l-7 7 7 7"/>', next: '<path d="M9 5l7 7-7 7"/>',
};
const svg = k => '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">' + ICON[k] + '</svg>';

let CUR = null;

export async function open(ctx, sid) {
  if (CUR) { CUR.switchShot(sid); return CUR; }
  CUR = new Editor(ctx);
  await CUR.mount(sid);
  return CUR;
}
export function close() { if (CUR) CUR.close(); }

class Editor {
  constructor(ctx) {
    this.ctx = ctx;
    this.t = 0; this.playing = false; this.loop = true;
    this.sel = null; this.selKey = null;
    this.mode = 'translate'; this.view = 'work'; this.autokey = true;
    this.undo = []; this.redo = [];
    this.meshes = new Map();
    this.saveTimer = null; this.dirty = false;
  }

  async mount(sid) {
    if (!document.getElementById('pvCss')) { const s = document.createElement('style'); s.id = 'pvCss'; s.textContent = scoped(CSS); document.head.append(s); }
    const root = this.root = $h('div', 'pv');
    root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', '3D 預演');
    root.tabIndex = -1;
    root.innerHTML = '<header class="pv-top"></header><aside class="pv-left"></aside><section class="pv-view"></section><aside class="pv-right"></aside><footer class="pv-tl"></footer>';
    document.body.append(root);
    this.$top = root.querySelector('.pv-top'); this.$left = root.querySelector('.pv-left'); this.$view = root.querySelector('.pv-view');
    this.$right = root.querySelector('.pv-right'); this.$tl = root.querySelector('.pv-tl');
    this.prevOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden';
    this.initThree();
    this.buildViewOverlay();
    this.buildTimelineShell();
    this.onKey = e => this.key(e);
    window.addEventListener('keydown', this.onKey, true);
    window.__PREVIS__ = this;
    await this.loadShot(sid);
    this.raf = requestAnimationFrame(this.frame.bind(this));
    root.focus();
  }

  close() {
    this.flushSave();
    cancelAnimationFrame(this.raf);
    window.removeEventListener('keydown', this.onKey, true);
    if (this.ro) this.ro.disconnect();
    try { this.tc.detach(); this.tc.dispose(); this.orbit.dispose(); this.orbitCam.dispose(); } catch (e) {}
    this.scene3.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) [].concat(o.material).forEach(m => { if (m.map) m.map.dispose(); m.dispose(); }); });
    this.renderer.dispose();
    this.root.remove();
    document.body.style.overflow = this.prevOverflow || '';
    if (window.__PREVIS__ === this) delete window.__PREVIS__;
    CUR = null;
    try { this.ctx.onClose && this.ctx.onClose(); } catch (e) {}
  }

  async switchShot(sid) {
    if (sid && this.sid === sid) return;
    this.flushSave();
    await this.loadShot(sid);
  }

  async loadShot(sid) {
    const shots = this.ctx.shots();
    let sh = shots.find(s => s.sid === sid) || shots[0];
    if (!sh) { this.toast('分鏡表還沒有任何一鏡：先到分鏡工作區加一鏡'); return; }
    this.sid = sh.sid;
    this.shot = sh;
    const want = C.alignDur(Number(sh.seconds) > 0 ? sh.seconds : 5, n => this.ctx.align(n));
    const raw = await this.ctx.load(this.sid);
    this.scene = raw ? C.normalize(raw, { dur: want.dur, aspect: this.ctx.aspect() }) : this.starter(sh, want.dur);
    if (!raw) { this.dirty = true; this.queueSave(); }
    this.durNote = want.note;
    this.undo = []; this.redo = [];
    this.sel = null; this.selKey = null; this.t = 0; this.playing = false;
    this.rebuildMeshes();
    this.applyAspect();
    this.renderTop(); this.renderLeft(); this.renderRight(); this.renderTracks();
    this.applyTime();
    this.frameWork();
    this.coach();
  }

  starter(sh, dur) {
    const s = C.normalize({ dur, aspect: this.ctx.aspect() });
    const used = this.ctx.usedCards(sh).slice();
    this.ctx.cast().forEach(c => { if (c && c.name && (c.kind || 'char') === 'char' && !used.includes(c) && String(sh.prompt || '').includes(c.name)) used.push(c); });
    const chars = used.filter(c => (c.kind || 'char') === 'char').slice(0, 6);
    const place = used.find(c => c.kind === 'scene');
    s.objs.push(C.makeObj('floor', { name: '地板' }));
    s.objs.push(C.makeObj('wall', { name: place ? place.name + '（背牆）' : '背牆', p: [0, 0, -3.2] }));
    const taken = [];
    chars.forEach((c, i) => {
      const x = (i - (chars.length - 1) / 2) * 1.1;
      const color = C.pickColor(c.name, this.ctx.keys(), hx => this.ctx.clash(hx, c.name), taken);
      taken.push(color);
      s.objs.push(C.makeObj('char', { name: c.name, who: c.name, color, p: [x, 0, 0], r: [0, chars.length > 1 ? (i < chars.length / 2 ? 18 : -18) : 0, 0] }));
    });
    if (!chars.length) s.objs.push(C.makeObj('char', { name: '角色 A', color: C.pickColor('', this.ctx.keys(), hx => this.ctx.clash(hx, ''), []) }));
    used.filter(c => c.kind === 'prop').slice(0, 4).forEach((c, i) => {
      const color = C.pickColor(c.name, this.ctx.keys(), hx => this.ctx.clash(hx, c.name), taken);
      taken.push(color);
      s.objs.push(C.makeObj('prop', { name: c.name, who: c.name, color, cm: [40, 40, 40], p: [1.4 + i * 0.6, 0, 0.6] }));
    });
    s.cam.move = (sh.cam && sh.cam.move) || 'static';
    const path = C.camPath(sh.cam || {}, { target: C.subjectTarget(s, 0, (sh.cam || {}).size), dur: s.dur });
    s.cam.keys = path.keys.length > 1 ? path.keys : [];
    if (path.keys.length) Object.assign(s.cam.base, { p: path.keys[0].p, look: path.keys[0].look, mm: path.keys[0].mm, roll: path.keys[0].roll });
    this.pathNote = path.note;
    return s;
  }

  initThree() {
    const r = this.renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'high-performance' });
    r.setPixelRatio(Math.min(2, window.devicePixelRatio || 1));
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
    r.toneMapping = THREE.NeutralToneMapping;
    r.domElement.className = 'main'; r.domElement.tabIndex = 0;
    this.$view.append(r.domElement);

    const S = this.scene3 = new THREE.Scene();
    this.BG_WORK = new THREE.Color('#14171c'); this.BG_SHOT = new THREE.Color('#9da2a9');
    S.add(new THREE.HemisphereLight(0xffffff, 0x80868e, 1.25));
    const sun = this.sun = new THREE.DirectionalLight(0xffffff, 2.1);
    sun.position.set(5, 9, 6); sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    Object.assign(sun.shadow.camera, { left: -9, right: 9, top: 9, bottom: -9, near: 0.5, far: 40 });
    sun.shadow.bias = -0.0004; sun.shadow.radius = 4;
    S.add(sun);
    this.world = new THREE.Group(); S.add(this.world);
    this.helpers = new THREE.Group(); S.add(this.helpers);

    const g = new THREE.GridHelper(80, 80, 0x2a3038, 0x1c2128); g.position.y = -0.002; this.farGrid = g; this.helpers.add(g);

    this.workCam = new THREE.PerspectiveCamera(42, 1, 0.05, 400);
    this.workCam.position.set(7.5, 5.2, 9.5);
    this.shotCam = new THREE.PerspectiveCamera(40, 16 / 9, 0.05, 400);

    this.camRig = new THREE.Group();
    const body = new THREE.Mesh(new THREE.BoxGeometry(0.22, 0.16, 0.3), new THREE.MeshBasicMaterial({ color: 0xe8a33d }));
    body.position.z = 0.15; body.userData.pick = 'cam';
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.08, 0.12, 16), new THREE.MeshBasicMaterial({ color: 0x2a2f36 }));
    lens.rotation.x = Math.PI / 2; lens.position.z = -0.03; lens.userData.pick = 'cam';
    this.camRig.add(body, lens);
    this.helpers.add(this.camRig);
    this.vizCam = new THREE.PerspectiveCamera(40, 16 / 9, 0.12, 2.5);
    this.camHelper = new THREE.CameraHelper(this.vizCam);
    this.camHelper.setColors(new THREE.Color(0xe8a33d), new THREE.Color(0x8a5f22), new THREE.Color(0xe8a33d), new THREE.Color(0xe8a33d), new THREE.Color(0x8a5f22));
    this.helpers.add(this.camHelper);
    this.lookDot = new THREE.Mesh(new THREE.SphereGeometry(0.07, 16, 12), new THREE.MeshBasicMaterial({ color: 0xe8a33d, transparent: true, opacity: 0.85 }));
    this.lookDot.userData.pick = 'look';
    this.helpers.add(this.lookDot);
    this.camPathLine = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineDashedMaterial({ color: 0xe8a33d, dashSize: 0.18, gapSize: 0.1, transparent: true, opacity: 0.8 }));
    this.helpers.add(this.camPathLine);
    this.trail = new THREE.Line(new THREE.BufferGeometry(), new THREE.LineBasicMaterial({ color: 0x1fb5c9, transparent: true, opacity: 0.95, depthTest: false }));
    this.trail.renderOrder = 5;
    this.ghosts = new THREE.Group(); this.helpers.add(this.ghosts);
    this.trailDots = new THREE.Group();
    this.helpers.add(this.trail, this.trailDots);
    this.selBox = new THREE.BoxHelper(undefined, 0xe8a33d); this.selBox.visible = false; this.helpers.add(this.selBox);

    const dom = r.domElement;
    this.orbit = new OrbitControls(this.workCam, dom);
    this.orbit.enableDamping = true; this.orbit.dampingFactor = 0.12; this.orbit.target.set(0, 0.9, 0);
    this.orbit.maxPolarAngle = Math.PI * 0.495;
    this.orbitCam = new OrbitControls(this.shotCam, dom);
    this.orbitCam.enabled = false; this.orbitCam.enableDamping = false;
    this.orbitCam.addEventListener('start', () => { this.pilot = true; this.beginEdit(); this.camBefore = C.sampleCam(this.scene.cam, this.t); });
    this.orbitCam.addEventListener('change', () => { if (this.pilot) this.camFromPilot(); });
    this.orbitCam.addEventListener('end', () => { this.pilot = false; this.commit(); });

    const tc = this.tc = new TransformControls(this.workCam, dom);
    tc.setSize(0.9);
    this.helpers.add(tc.getHelper());
    tc.addEventListener('dragging-changed', e => {
      this.orbit.enabled = !e.value && this.view === 'work';
      this.orbitCam.enabled = !e.value && this.view === 'cam';
      if (e.value) { this.pause(); this.beginEdit(); this.dragBefore = this.poseOfSel(); }
      else this.commit();
    });
    tc.addEventListener('objectChange', () => { this.fromGizmo(); this.paintRead(); });
    tc.addEventListener('mouseUp', () => { this.$read.style.display = 'none'; });
    r.domElement.addEventListener('pointermove', e => { const b = r.domElement.getBoundingClientRect(); this.ptr = [e.clientX - b.left, e.clientY - b.top]; });

    dom.addEventListener('pointerdown', e => { this.down = [e.clientX, e.clientY]; });
    dom.addEventListener('pointerup', e => {
      if (!this.down || tc.dragging) return;
      const moved = Math.hypot(e.clientX - this.down[0], e.clientY - this.down[1]);
      this.down = null;
      if (moved < 4) this.pick(e);
    });
    dom.addEventListener('dblclick', () => { if (this.sel) this.focusSel(); });
    this.ro = new ResizeObserver(() => this.resize());
    this.ro.observe(this.$view);

    const cv = document.createElement('canvas'); cv.width = cv.height = 256;
    const g2 = cv.getContext('2d');
    g2.fillStyle = '#b9bdc3'; g2.fillRect(0, 0, 256, 256);
    g2.strokeStyle = 'rgba(70,76,86,.35)'; g2.lineWidth = 3; g2.strokeRect(0, 0, 256, 256);
    g2.strokeStyle = 'rgba(70,76,86,.14)'; g2.lineWidth = 1.5;
    g2.beginPath(); g2.moveTo(128, 0); g2.lineTo(128, 256); g2.moveTo(0, 128); g2.lineTo(256, 128); g2.stroke();
    this.gridTex = new THREE.CanvasTexture(cv);
    this.gridTex.wrapS = this.gridTex.wrapT = THREE.RepeatWrapping;
    this.gridTex.colorSpace = THREE.SRGBColorSpace;
    this.gridTex.anisotropy = 8;
  }

  resize() {
    const w = this.$view.clientWidth, h = this.$view.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h, false);
    this.workCam.aspect = w / h; this.workCam.updateProjectionMatrix();
    this.layoutFrame();
  }

  buildMesh(o) {
    const grp = new THREE.Group();
    grp.userData.id = o.id;
    const mat = (hex, k) => new THREE.MeshStandardMaterial({ color: shade(hex, k), roughness: 0.82, metalness: 0 });
    const faces = hex => [mat(hex, 0.74), mat(hex, 0.74), mat(hex, 0.92), mat(hex, 0.5), mat(hex, 1), mat(hex, 0.38)];
    const add = (geo, m, y) => { const ms = new THREE.Mesh(geo, m); ms.position.y = y; ms.castShadow = true; ms.receiveShadow = true; ms.userData.pick = o.id; grp.add(ms); return ms; };
    if (o.kind === 'char') {
      const P = C.figureParts(o.size[1]);
      ['lower', 'upper', 'head'].forEach(k => add(new THREE.BoxGeometry(P[k].w, P[k].h, P[k].d), faces(o.color), P[k].y));
    } else if (o.kind === 'floor') {
      const m = new THREE.MeshStandardMaterial({ map: this.gridTex.clone(), roughness: 0.95 });
      m.map.repeat.set(o.size[0], o.size[2]); m.map.needsUpdate = true;
      const side = new THREE.MeshStandardMaterial({ color: '#9ea3aa', roughness: 0.95 });
      const ms = add(new THREE.BoxGeometry(o.size[0], o.size[1], o.size[2]), [side, side, m, side, side, side], -o.size[1] / 2);
      ms.castShadow = false;
    } else if (o.kind === 'cyl') {
      add(new THREE.CylinderGeometry(o.size[0] / 2, o.size[0] / 2, o.size[1], 32), mat(o.color, 1), o.size[1] / 2);
    } else if (o.kind === 'ramp') {
      const sh = new THREE.Shape(); sh.moveTo(-o.size[2] / 2, 0); sh.lineTo(o.size[2] / 2, 0); sh.lineTo(o.size[2] / 2, o.size[1]); sh.lineTo(-o.size[2] / 2, 0);
      const geo = new THREE.ExtrudeGeometry(sh, { depth: o.size[0], bevelEnabled: false });
      geo.translate(0, 0, -o.size[0] / 2); geo.rotateY(-Math.PI / 2);
      add(geo, mat(o.color, 1), 0);
    } else {
      const m = o.kind === 'prop' && o.who ? faces(o.color) : mat(o.color, 1);
      add(new THREE.BoxGeometry(o.size[0], o.size[1], o.size[2]), m, o.size[1] / 2);
    }
    return grp;
  }
  rebuildMeshes() {
    this.meshes.forEach(g => { this.world.remove(g); g.traverse(x => { if (x.geometry) x.geometry.dispose(); if (x.material) [].concat(x.material).forEach(m => { if (m.map && m.map !== this.gridTex) m.map.dispose(); m.dispose(); }); }); });
    this.meshes.clear();
    this.scene.objs.forEach(o => { const g = this.buildMesh(o); this.meshes.set(o.id, g); this.world.add(g); });
    if (this.sel && this.sel !== 'cam' && !this.meshes.has(this.sel)) this.sel = null;
    this.attachGizmo();
  }
  rebuildOne(o) {
    const old = this.meshes.get(o.id);
    if (old) { this.world.remove(old); old.traverse(x => { if (x.geometry) x.geometry.dispose(); }); }
    const g = this.buildMesh(o); this.meshes.set(o.id, g); this.world.add(g);
    if (this.sel === o.id) this.attachGizmo();
    this.applyTime();
  }

  applyAspect() {
    const m = String(this.scene.aspect).split(':').map(Number);
    this.ar = m[0] && m[1] ? m[0] / m[1] : 16 / 9;
    this.shotCam.aspect = this.ar; this.shotCam.updateProjectionMatrix();
    this.resize();
  }

  applyTime() {
    const t = this.t;
    this.scene.objs.forEach(o => {
      const g = this.meshes.get(o.id); if (!g) return;
      if (this.tc.dragging && this.sel === o.id) return;
      const s = C.sampleObj(o, t);
      g.position.set(s.p[0], s.p[1], s.p[2]);
      g.rotation.set(s.r[0] * RAD, s.r[1] * RAD, s.r[2] * RAD);
      g.scale.set(s.s[0], s.s[1], s.s[2]);
    });
    if (!(this.tc.dragging && (this.sel === 'cam' || this.sel === 'look')) && !this.pilot) this.applyCam(C.sampleCam(this.scene.cam, t));
    if (this.sel && this.sel !== 'cam' && this.sel !== 'look') { const g = this.meshes.get(this.sel); if (g) this.selBox.setFromObject(g); }
  }
  applyCam(c) {
    const k = this.shotCam;
    k.position.set(c.p[0], c.p[1], c.p[2]);
    k.up.set(0, 1, 0);
    k.lookAt(c.look[0], c.look[1], c.look[2]);
    if (c.roll) k.rotateZ(c.roll * RAD);
    k.fov = C.vfov(c.mm); k.updateProjectionMatrix(); k.updateMatrixWorld();
    this.camRig.position.copy(k.position); this.camRig.quaternion.copy(k.quaternion);
    this.lookDot.position.set(c.look[0], c.look[1], c.look[2]);
    this.syncViz();
    if (!this.pilot) this.orbitCam.target.set(c.look[0], c.look[1], c.look[2]);
    this.curCam = c;
  }

  syncViz() {
    const k = this.shotCam, v = this.vizCam;
    v.position.copy(k.position); v.quaternion.copy(k.quaternion);
    v.fov = k.fov; v.aspect = k.aspect; v.updateProjectionMatrix(); v.updateMatrixWorld();
    this.camHelper.update();
  }
  frame(now) {
    this.raf = requestAnimationFrame(this.frame.bind(this));
    if (this.playing) {
      const dt = Math.min(0.1, (now - (this.lastNow || now)) / 1000);
      let t = this.t + dt;
      if (t >= this.scene.dur) { if (this.loop) t = t % this.scene.dur; else { t = this.scene.dur; this.pause(); } }
      this.t = t;
      this.applyTime(); this.paintTime();
    }
    this.lastNow = now;
    if (this.view === 'work') this.orbit.update();
    this.draw();
    this.paintTags();
  }
  paintTags() {
    const show = this.view === 'work';
    const w = this.$view.clientWidth, h = this.$view.clientHeight;
    const live = new Set();
    if (show) this.scene.objs.forEach(o => {
      if (o.kind !== 'char' && !(o.kind === 'prop' && o.who)) return;
      const g = this.meshes.get(o.id); if (!g) return;
      const v = new THREE.Vector3(0, (o.kind === 'char' ? C.figureParts(o.size[1]).top : o.size[1]) + 0.14, 0);
      g.localToWorld(v); v.project(this.workCam);
      if (v.z > 1) return;
      const x = (v.x + 1) / 2 * w, y = (1 - v.y) / 2 * h;
      const pr = this.pipRect;
      if (pr && x > pr.x - 10 && x < pr.x + pr.w + 10 && y > pr.y - 10 && y < pr.y + pr.h + 26) return;
      let t = this.$tags.querySelector('[data-id="' + o.id + '"]');
      if (!t) { t = $h('div', 'pv-tag'); t.dataset.id = o.id; t.append($h('i'), $h('span')); this.$tags.append(t); }
      t.firstChild.style.background = o.color;
      t.lastChild.textContent = o.name || (o.kind === 'char' ? '角色' : '道具');
      t.classList.toggle('on', this.sel === o.id);
      t.style.left = x.toFixed(1) + 'px'; t.style.top = y.toFixed(1) + 'px';
      live.add(o.id);
    });
    [...this.$tags.children].forEach(t => { if (!live.has(t.dataset.id)) t.remove(); });
  }
  draw() {
    const r = this.renderer, S = this.scene3;
    const w = this.$view.clientWidth, h = this.$view.clientHeight;
    if (!w || !h) return;
    r.setScissorTest(false);
    if (this.view === 'work') {
      this.helpers.visible = true; this.camHelper.visible = this.camRig.visible = true;
      S.background = this.BG_WORK;
      r.setViewport(0, 0, w, h); r.render(S, this.workCam);
      const pr = this.pipRect;
      if (pr) {
        r.setScissorTest(true);
        r.setScissor(pr.x, h - pr.y - pr.h, pr.w, pr.h); r.setViewport(pr.x, h - pr.y - pr.h, pr.w, pr.h);
        this.helpers.visible = false; S.background = this.BG_SHOT;
        r.render(S, this.shotCam);
        this.helpers.visible = true; r.setScissorTest(false);
      }
    } else {
      const f = this.frameRect;
      S.background = new THREE.Color('#07080a');
      r.setViewport(0, 0, w, h); r.clear();
      r.setScissorTest(true);
      r.setScissor(f.x, h - f.y - f.h, f.w, f.h); r.setViewport(f.x, h - f.y - f.h, f.w, f.h);
      this.helpers.visible = true;
      this.camHelper.visible = false; this.camRig.visible = false; this.farGrid.visible = false;
      this.camPathLine.visible = false; this.lookDot.visible = false;
      S.background = this.BG_SHOT;
      r.render(S, this.shotCam);
      this.farGrid.visible = true; this.camPathLine.visible = true; this.lookDot.visible = true;
      r.setScissorTest(false);
    }
  }

  buildViewOverlay() {
    const v = this.$view;
    const tools = $h('div', 'pv-tools');
    const tool = (k, mode, tip, key) => { const b = btn('', '', tip + '（' + key + '）', () => this.setMode(mode)); b.innerHTML = svg(k) + '<kbd>' + key + '</kbd>'; b.dataset.mode = mode; tools.append(b); };
    tool('move', 'translate', '移動', 'W'); tool('rot', 'rotate', '旋轉', 'E'); tool('scl', 'scale', '縮放', 'R');
    tools.append($h('hr'));
    const f = btn('', '', '對準選取的物件（F）', () => this.focusSel()); f.innerHTML = svg('focus') + '<kbd>F</kbd>'; tools.append(f);
    const u = btn('', '', '復原（⌘Z）', () => this.doUndo()); u.innerHTML = svg('undo'); tools.append(u);
    v.append(tools); this.$tools = tools;
    const sw = $h('div', 'pv-viewsw');
    sw.append(btn('', '工作視角', '自由轉動、擺位置（C 切換）', () => this.setView('work')), btn('', '鏡頭視角', '透過攝影機看，拖曳就是在運鏡（C 切換）', () => this.setView('cam')));
    v.append(sw); this.$viewsw = sw;
    this.$pip = $h('div', 'pv-pip'); this.$pip.title = '點一下：切到鏡頭視角';
    this.$pip.onclick = () => this.setView('cam');
    this.$pip.innerHTML = '<div class="lb"><span class="mm"></span><span class="rec">● REC 預覽</span></div>';
    v.append(this.$pip);
    this.$frame = $h('div', 'pv-frame');
    this.$frame.innerHTML = '<i style="left:33.33%;top:0;bottom:0;width:1px"></i><i style="left:66.66%;top:0;bottom:0;width:1px"></i><i style="top:33.33%;left:0;right:0;height:1px"></i><i style="top:66.66%;left:0;right:0;height:1px"></i><span class="tc"></span><span class="tr"></span>';
    v.append(this.$frame);
    v.insertBefore($h('div', 'pv-vig'), tools);
    this.$tags = $h('div', 'pv-tags'); v.insertBefore(this.$tags, tools);
    this.$read = $h('div', 'pv-read'); v.append(this.$read);
    this.$hud = $h('div', 'pv-hud'); v.append(this.$hud);
    this.$toast = $h('div', 'pv-toast'); v.append(this.$toast);
    this.setMode('translate'); this.setView('work');
  }
  layoutFrame() {
    const w = this.$view.clientWidth, h = this.$view.clientHeight;
    if (!w || !h || !this.ar) return;
    const padT = 62, padB = 44, padX = 70;
    let fw = w - padX * 2, fh = fw / this.ar;
    if (fh > h - padT - padB) { fh = h - padT - padB; fw = fh * this.ar; }
    this.frameRect = { x: Math.round((w - fw) / 2), y: Math.round(padT + (h - padT - padB - fh) / 2), w: Math.round(fw), h: Math.round(fh) };
    let pw = Math.round(Math.min(320, w * 0.3)), ph = Math.round(pw / this.ar);
    if (ph > h * 0.42) { ph = Math.round(h * 0.42); pw = Math.round(ph * this.ar); }
    this.pipRect = { x: w - pw - 14, y: 14, w: pw, h: ph };
    Object.assign(this.$pip.style, { left: this.pipRect.x + 'px', top: '14px', right: 'auto', width: pw + 'px', height: ph + 'px' });
    this.$pip.classList.toggle('narrow', pw < 220);
    const f = this.frameRect;
    Object.assign(this.$frame.style, { left: f.x + 'px', top: f.y + 'px', width: f.w + 'px', height: f.h + 'px' });
  }
  setMode(m) {
    this.mode = m;
    this.tc.setMode(m);
    const rot = m === 'rotate';
    this.tc.showX = !rot; this.tc.showZ = !rot; this.tc.showY = true;
    if (this.sel === 'cam' || this.sel === 'look') { this.tc.setMode('translate'); this.tc.showX = this.tc.showZ = true; }
    this.$tools.querySelectorAll('button[data-mode]').forEach(b => b.classList.toggle('on', b.dataset.mode === m));
  }
  setView(v) {
    this.view = v;
    this.$viewsw.querySelectorAll('button').forEach((b, i) => b.classList.toggle('on', (i === 0) === (v === 'work')));
    this.orbit.enabled = v === 'work'; this.orbitCam.enabled = v === 'cam';
    this.tc.camera = v === 'work' ? this.workCam : this.shotCam;
    this.$pip.style.display = v === 'work' ? '' : 'none';
    this.$frame.style.display = v === 'cam' ? '' : 'none';
    if (v === 'cam' && (this.sel === 'cam' || this.sel === 'look')) this.select(null);
    this.layoutFrame();
    this.paintHud();
  }
  paintHud() {
    if (!this.scene) return;
    const c = this.curCam || this.scene.cam.base;
    const mm = Math.round(c.mm) + 'mm';
    const exp = C.exportSize(this.scene.aspect);
    this.$pip.querySelector('.mm').textContent = (this.pipRect && this.pipRect.w < 220 ? '' : '鏡頭 · ') + mm + ' · ' + this.scene.aspect;
    this.$frame.querySelector('.tc').textContent = C.fmtT(this.t) + ' / ' + C.fmtT(this.scene.dur);
    this.$frame.querySelector('.tr').textContent = mm + ' · ' + exp.w + '×' + exp.h;
    this.$hud.innerHTML = this.view === 'work'
      ? '<span><b>拖曳</b> 轉動</span><span><b>右鍵</b> 平移</span><span><b>滾輪</b> 縮放</span><span><b>雙擊</b> 對準</span>'
      : '<span><b>拖曳</b> 繞著注視點運鏡</span><span><b>右鍵</b> 平移機位</span><span><b>滾輪</b> 推近拉遠</span><span>改了會' + (this.autokey ? '在播放頭打關鍵幀' : '整段平移') + '</span>';
  }
  toast(msg) {
    this.$toast.textContent = msg; this.$toast.classList.add('on');
    clearTimeout(this.toastT); this.toastT = setTimeout(() => this.$toast.classList.remove('on'), 2600);
  }
  coach() {
    let seen = false;
    try { seen = localStorage.getItem('previs-coach') === '1'; } catch (e) {}
    if (seen || this.$coach) return;
    const c = this.$coach = $h('div', 'pv-coach');
    c.innerHTML = '<h4>四步做出一支預演</h4><ol><li><b>點角色</b>，拖箭頭擺位置（E 轉向）</li><li><b>移動播放頭</b>再拖一次，自動打關鍵幀</li><li>右上角就是<b>鏡頭畫面</b>，可以切過去直接運鏡</li><li><b>匯出成動作來源</b>，放進這一鏡（不花點數）</li></ol>';
    const row = $h('div', 'row');
    row.append(btn('', '知道了', '', () => { c.remove(); this.$coach = null; try { localStorage.setItem('previs-coach', '1'); } catch (e) {} }));
    c.append(row); this.$view.append(c);
  }

  renderTop() {
    const T = this.$top; T.innerHTML = '';
    const b = $h('div', 'pv-brand'); b.append($h('b', null, 'PREVIS'), $h('span', null, '3D 預演'));
    T.append(b);
    const list = $h('div', 'pv-shots');
    this.ctx.shots().forEach((s, i) => {
      const it = btn('pv-shot' + (s.sid === this.sid ? ' on' : ''), '', s.prompt || '');
      it.append($h('span', 'n', String(i + 1)), $h('span', 'p', String(s.prompt || '（沒有描述）').replace(/\s+/g, ' ').slice(0, 26)));
      if (s.motion && s.motion.previs) { const d = $h('span', 'dot'); d.title = '這一鏡已經有 3D 預演的動作來源'; it.append(d); }
      it.onclick = () => this.switchShot(s.sid);
      list.append(it);
    });
    T.append(list);
    const meta = $h('div', 'pv-meta');
    const dur = btn('pv-chip', '', '預演長度＝送件長度（帶參考影片時成片跟著它的長度）。已對齊模型的秒數規則');
    dur.innerHTML = '<i>長度</i>' + this.scene.dur + 's';
    dur.onclick = e => this.durPop(e.currentTarget);
    const asp = btn('pv-chip', '', '畫面比例（跟著左欄的設定；匯出尺寸由它決定）');
    asp.innerHTML = '<i>比例</i>' + this.scene.aspect;
    asp.onclick = e => this.aspectPop(e.currentTarget);
    this.$save = $h('span', 'pv-save', '已存');
    meta.append(dur, asp, this.$save);
    T.append(meta);
    T.append(btn('pv-go', '匯出成動作來源', '在瀏覽器裡錄成 mp4，上傳成素材放進這一鏡的「動作來源」槽。不花生成費用', () => this.exportFlow()));
    T.append(btn('pv-x', '✕', '關閉（Esc）。改動會自動存', () => this.close()));
    this.paintSave();
  }
  pop(anchor, build) {
    this.closePop();
    const p = this.$pop = $h('div', 'pv-pop');
    build(p);
    this.root.append(p);
    const r = anchor.getBoundingClientRect(), R = this.root.getBoundingClientRect();
    const left = Math.min(r.left - R.left, R.width - p.offsetWidth - 10);
    p.style.left = Math.max(10, left) + 'px';
    if (r.top > R.height * 0.6) p.style.bottom = (R.bottom - r.top + 6) + 'px'; else p.style.top = (r.bottom - R.top + 6) + 'px';
    setTimeout(() => { this.popOff = e => { if (!p.contains(e.target)) this.closePop(); }; window.addEventListener('pointerdown', this.popOff, true); }, 0);
  }
  closePop() { if (this.$pop) { this.$pop.remove(); this.$pop = null; } if (this.popOff) { window.removeEventListener('pointerdown', this.popOff, true); this.popOff = null; } }
  durPop(anchor) {
    this.pop(anchor, p => {
      p.append($h('div', 'gh', '對齊 ' + (this.ctx.model() || '目前模型') + ' 的秒數'));
      const seen = new Set();
      for (let n = C.DUR_MIN; n <= C.DUR_MAX; n++) {
        const a = C.alignDur(n, k => this.ctx.align(k));
        if (seen.has(a.dur)) continue; seen.add(a.dur);
        const b = btn(a.dur === this.scene.dur ? 'on' : '', a.dur + ' 秒', '', () => { this.closePop(); this.setDur(a.dur); });
        if (Number(this.shot.seconds) === a.dur) b.append($h('span', 'd', '分鏡表'));
        p.append(b);
      }
      if (this.durNote) p.append($h('div', 'gh', this.durNote));
    });
  }
  aspectPop(anchor) {
    this.pop(anchor, p => {
      p.append($h('div', 'gh', '畫面比例'));
      ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9'].forEach(a => {
        const e = C.exportSize(a);
        const b = btn(a === this.scene.aspect ? 'on' : '', a, '', () => { this.closePop(); this.beginEdit(); this.scene.aspect = a; this.applyAspect(); this.commit(); this.renderTop(); });
        b.append($h('span', 'd', e.w + '×' + e.h)); p.append(b);
      });
    });
  }
  setDur(d) {
    this.beginEdit();
    this.scene.dur = d;
    this.scene.objs.forEach(o => { o.keys = C.fitKeys(o.keys, d); });
    this.scene.cam.keys = C.fitKeys(this.scene.cam.keys, d);
    if (this.t > d) this.t = d;
    this.commit(); this.renderTop(); this.renderTracks(); this.applyTime();
  }

  renderLeft() {
    const L = this.$left; L.innerHTML = '';
    const s1 = $h('div', 'pv-sec');
    s1.append($h('div', 'pv-h', '新增'));
    const add = $h('div', 'pv-add');
    const mk = (k, t, tip, fn) => { const b = btn('', '', tip, fn); b.innerHTML = svg(k) + '<span>' + t + '</span>'; add.append(b); return b; };
    mk('char', '角色', '三塊方塊的人偶（頭、上身、下身），綁定角色卡', e => this.charPop(e.currentTarget));
    mk('prop', '道具', '真實尺寸的方盒', e => this.propPop(e.currentTarget));
    mk('set', '場景', '地板、牆面、簡單幾何', e => this.setPop(e.currentTarget));
    s1.append(add); L.append(s1);
    const s2 = $h('div', 'pv-sec');
    const hd = $h('div', 'pv-h'); hd.append(document.createTextNode('場景'), $h('em', null, this.scene.objs.length + ' 個物件'));
    s2.append(hd);
    const list = $h('div', 'pv-list');
    const item = (id, sw, name, kind, kf, img) => {
      const b = btn('pv-item' + (this.sel === id ? ' on' : ''), '', '', () => this.select(id));
      if (img) { const im = $h('img'); im.src = img; im.alt = ''; b.append(im); } else { const s = $h('span', 'sw'); s.style.background = sw; b.append(s); }
      b.append($h('span', 'nm', name), $h('span', 'k', kind));
      if (kf) b.append($h('span', 'kf', '◆' + kf));
      list.append(b);
    };
    const cam = this.scene.cam;
    item('cam', '#e8a33d', '攝影機', Math.round((this.curCam || cam.base).mm) + 'mm', cam.keys.length);
    const KZ = { char: '角色', prop: '道具', floor: '地板', wall: '牆', box: '方塊', cyl: '圓柱', ramp: '斜坡' };
    this.scene.objs.forEach(o => item(o.id, o.color, o.name || KZ[o.kind], KZ[o.kind], o.keys.length, o.who && o.kind === 'char' ? this.ctx.thumb(o.who) : ''));
    s2.append(list); L.append(s2);
    const s3 = $h('div', 'pv-sec');
    s3.append($h('div', 'pv-h', '快捷鍵'));
    s3.append(Object.assign($h('div', 'pv-note'), { innerHTML: 'W 移動 · E 轉向 · R 縮放<br>K 打關鍵幀 · 空白鍵 播放<br>C 切換視角 · F 對準 · ⌘D 複製<br>Delete 刪除 · ⌘Z 復原' }));
    L.append(s3);
  }
  spot() {
    const T = this.curCam ? this.curCam.look : [0, 0, 0];
    const n = this.scene.objs.filter(o => o.kind !== 'floor').length;
    return [Math.round((T[0] + ((n % 5) - 2) * 0.9) * 100) / 100, 0, Math.round((T[2] + 0.6) * 100) / 100];
  }
  addObj(o) {
    if (this.scene.objs.length >= C.MAX_OBJS) { this.toast('一個場景最多 ' + C.MAX_OBJS + ' 個物件'); return; }
    this.beginEdit();
    this.scene.objs.push(o);
    const g = this.buildMesh(o); this.meshes.set(o.id, g); this.world.add(g);
    this.commit();
    this.select(o.id);
    this.applyTime();
  }
  takenColors() { return this.scene.objs.filter(o => o.who && (o.kind === 'char' || o.kind === 'prop')).map(o => o.color); }
  charPop(anchor) {
    this.pop(anchor, p => {
      const cards = this.ctx.cast().filter(c => c && c.name && (c.kind || 'char') === 'char');
      p.append($h('div', 'gh', cards.length ? '角色卡' : '素材庫還沒有角色卡'));
      cards.forEach(c => {
        const inScene = this.scene.objs.some(o => o.who === c.name && o.kind === 'char');
        const b = btn('', '', inScene ? '這個角色已經在場景裡（可以再放一個，但同一人同一色）' : '', () => {
          this.closePop();
          const color = C.pickColor(c.name, this.ctx.keys(), hx => this.ctx.clash(hx, c.name), this.takenColors());
          this.addObj(C.makeObj('char', { name: c.name, who: c.name, color, p: this.spot() }));
        });
        const th = this.ctx.thumb(c.name);
        if (th) { const im = $h('img'); im.src = th; b.append(im); } else { const s = $h('span', 'sw'); s.style.background = '#3a414b'; b.append(s); }
        b.append(document.createTextNode('@' + c.name));
        if (inScene) b.append($h('span', 'd', '已在場景'));
        p.append(b);
      });
      p.append($h('div', 'gh', '不綁角色卡'));
      p.append(btn('', '空白人偶', '', () => { this.closePop(); this.addObj(C.makeObj('char', { name: '角色', color: C.pickColor('', this.ctx.keys(), hx => this.ctx.clash(hx, ''), this.takenColors()), p: this.spot() })); }));
    });
  }
  propPop(anchor) {
    this.pop(anchor, p => {
      const cards = this.ctx.cast().filter(c => c && c.name && c.kind === 'prop');
      if (cards.length) {
        p.append($h('div', 'gh', '道具素材表（會加進分色對照）'));
        cards.forEach(c => p.append(btn('', '@' + c.name, '', () => {
          this.closePop();
          const color = C.pickColor(c.name, this.ctx.keys(), hx => this.ctx.clash(hx, c.name), this.takenColors());
          this.addObj(C.makeObj('prop', { name: c.name, who: c.name, color, cm: [40, 40, 40], p: this.spot() }));
        })));
      }
      p.append($h('div', 'gh', '真實尺寸（寬×高×深 公分）'));
      C.PROP_PRESETS.forEach(([id, zh, cm]) => {
        const b = btn('', zh, '', () => { this.closePop(); this.addObj(C.makeObj('prop', { name: zh, preset: id, cm, p: this.spot() })); });
        b.append($h('span', 'd', cm.join('×'))); p.append(b);
      });
    });
  }
  setPop(anchor) {
    this.pop(anchor, p => {
      p.append($h('div', 'gh', '場景元件（中性灰，不搶分色）'));
      [['wall', '牆面'], ['box', '方塊'], ['cyl', '圓柱'], ['ramp', '斜坡'], ['floor', '地板']].forEach(([k, zh]) => {
        const b = btn('', zh, '', () => { this.closePop(); const sp = this.spot(); this.addObj(C.makeObj(k, { name: zh, p: k === 'floor' ? [0, 0, 0] : [sp[0], 0, sp[2] - (k === 'wall' ? 2 : 0)] })); });
        b.append($h('span', 'd', C.SET_PIECES[k].join('×'))); p.append(b);
      });
    });
  }

  objOf(id) { return this.scene.objs.find(o => o.id === id); }
  select(id) {
    if (id && id !== 'cam' && id !== 'look' && !this.objOf(id)) id = null;
    this.sel = id; this.selKey = null;
    this.attachGizmo();
    this.renderLeft(); this.renderRight(); this.renderTracks(); this.paintTrail();
  }
  attachGizmo() {
    const id = this.sel;
    this.tc.detach();
    this.selBox.visible = false;
    if (!id) return;
    if (id === 'cam' || id === 'look') {
      if (this.view === 'cam') return;
      this.tc.attach(id === 'cam' ? this.camRig : this.lookDot);
      this.tc.setMode('translate'); this.tc.showX = this.tc.showY = this.tc.showZ = true;
      return;
    }
    const g = this.meshes.get(id); if (!g) return;
    const o = this.objOf(id);
    if (o && o.kind === 'floor') { this.selBox.setFromObject(g); this.selBox.visible = true; return; }
    this.tc.attach(g); this.setMode(this.mode);
    this.selBox.setFromObject(g); this.selBox.visible = true;
  }
  pick(e) {
    const r = this.renderer.domElement.getBoundingClientRect();
    let x = e.clientX - r.left, y = e.clientY - r.top, cam = this.workCam, W = r.width, H = r.height, ox = 0, oy = 0;
    if (this.view === 'work' && this.pipRect) {
      const p = this.pipRect;
      if (x >= p.x && x <= p.x + p.w && y >= p.y && y <= p.y + p.h) return;
    }
    if (this.view === 'cam') {
      const f = this.frameRect;
      if (x < f.x || x > f.x + f.w || y < f.y || y > f.y + f.h) return;
      cam = this.shotCam; ox = f.x; oy = f.y; W = f.w; H = f.h;
    }
    const nd = new THREE.Vector2(((x - ox) / W) * 2 - 1, -((y - oy) / H) * 2 + 1);
    const ray = new THREE.Raycaster(); ray.setFromCamera(nd, cam);
    const targets = [];
    this.world.traverse(o => { if (o.isMesh) targets.push(o); });
    if (this.view === 'work') { targets.push(this.camRig.children[0], this.camRig.children[1], this.lookDot); }
    const hits = ray.intersectObjects(targets, false);
    const hit = hits.find(h => { const o = this.objOf(h.object.userData.pick); return !o || o.kind !== 'floor'; }) || hits[0];
    this.select(hit ? hit.object.userData.pick : null);
  }
  focusSel() {
    let p;
    if (!this.sel) p = new THREE.Vector3(0, 0.9, 0);
    else if (this.sel === 'cam') p = this.camRig.position.clone();
    else if (this.sel === 'look') p = this.lookDot.position.clone();
    else { const g = this.meshes.get(this.sel); const b = new THREE.Box3().setFromObject(g); p = b.getCenter(new THREE.Vector3()); }
    const d = this.workCam.position.clone().sub(this.orbit.target);
    this.orbit.target.copy(p);
    this.workCam.position.copy(p.clone().add(d.setLength(Math.min(d.length(), 7))));
    if (this.view === 'cam') this.setView('work');
  }
  frameWork() {
    const b = new THREE.Box3();
    this.scene.objs.forEach(o => { if (o.kind !== 'floor') { const g = this.meshes.get(o.id); if (g) b.expandByObject(g); } });
    b.expandByPoint(this.shotCam.position);
    if (b.isEmpty()) return;
    const c = b.getCenter(new THREE.Vector3()); const s = b.getSize(new THREE.Vector3()).length();
    this.orbit.target.set(c.x, Math.max(0.6, c.y * 0.6), c.z);
    this.workCam.position.set(c.x + s * 0.75, Math.max(3, s * 0.55), c.z + s * 0.95);
    this.orbit.update();
  }

  beginEdit() {
    const snap = JSON.stringify(this.scene);
    if (this.undo[this.undo.length - 1] !== snap) this.undo.push(snap);
    if (this.undo.length > 60) this.undo.shift();
    this.redo = [];
  }
  commit() { this.dirty = true; this.queueSave(); this.renderTracks(); this.paintTrail(); this.paintCamPath(); this.renderLeft(); }
  doUndo() {
    if (!this.undo.length) { this.toast('沒有可以復原的步驟'); return; }
    this.redo.push(JSON.stringify(this.scene));
    this.scene = C.normalize(JSON.parse(this.undo.pop()));
    this.afterRestore();
  }
  doRedo() {
    if (!this.redo.length) return;
    this.undo.push(JSON.stringify(this.scene));
    this.scene = C.normalize(JSON.parse(this.redo.pop()));
    this.afterRestore();
  }
  afterRestore() {
    this.rebuildMeshes(); this.applyAspect();
    this.dirty = true; this.queueSave();
    this.renderTop(); this.renderLeft(); this.renderRight(); this.renderTracks(); this.applyTime(); this.paintTrail(); this.paintCamPath();
  }
  poseOfSel() {
    if (this.sel === 'cam' || this.sel === 'look') return C.sampleCam(this.scene.cam, this.t);
    const o = this.objOf(this.sel); return o ? C.sampleObj(o, this.t) : null;
  }
  writeObj(o, pose, before) {
    const t = C.snap(this.t);
    if (this.autokey && (o.keys.length || t > 0)) {
      o.keys = C.upsertKey(o.keys, t, { p: pose.p, r: pose.r, s: pose.s, e: (o.keys.find(k => Math.abs(k.t - t) < 1e-4) || {}).e || 'lin' }, before || o.base);
    } else if (o.keys.length) {
      const cur = C.sampleObj(o, t);
      const dp = [0, 1, 2].map(i => pose.p[i] - cur.p[i]), dr = [0, 1, 2].map(i => pose.r[i] - cur.r[i]);
      const ds = [0, 1, 2].map(i => (cur.s[i] ? pose.s[i] / cur.s[i] : 1));
      o.keys = o.keys.map(k => Object.assign({}, k, { p: k.p.map((v, i) => v + dp[i]), r: k.r.map((v, i) => v + dr[i]), s: k.s.map((v, i) => v * ds[i]) }));
    } else {
      o.base = { p: pose.p.slice(), r: pose.r.slice(), s: pose.s.slice() };
    }
  }
  writeCam(pose, before) {
    const c = this.scene.cam, t = C.snap(this.t);
    if (this.autokey && (c.keys.length || t > 0)) c.keys = C.upsertKey(c.keys, t, pose, before || c.base);
    else if (c.keys.length) {
      const cur = C.sampleCam(c, t);
      const dp = [0, 1, 2].map(i => pose.p[i] - cur.p[i]), dl = [0, 1, 2].map(i => pose.look[i] - cur.look[i]);
      c.keys = c.keys.map(k => Object.assign({}, k, { p: k.p.map((v, i) => v + dp[i]), look: k.look.map((v, i) => v + dl[i]), mm: k.mm + (pose.mm - cur.mm), roll: (k.roll || 0) + (pose.roll - cur.roll) }));
    } else c.base = { p: pose.p.slice(), look: pose.look.slice(), mm: pose.mm, roll: pose.roll || 0 };
  }
  fromGizmo() {
    const R3 = v => Math.round(v * 1000) / 1000;
    if (this.sel === 'cam' || this.sel === 'look') {
      const cur = C.sampleCam(this.scene.cam, this.t);
      const pose = Object.assign({}, cur);
      if (this.sel === 'cam') pose.p = this.camRig.position.toArray().map(R3); else pose.look = this.lookDot.position.toArray().map(R3);
      this.writeCam(pose, this.dragBefore);
      this.applyCam(C.sampleCam(this.scene.cam, this.t));
      this.paintCamPath(); this.paintInspectorLive();
      return;
    }
    const o = this.objOf(this.sel); if (!o) return;
    const g = this.meshes.get(o.id);
    const prev = C.sampleObj(o, this.t);
    const q = g.quaternion;
    let yaw = 2 * Math.atan2(q.y, q.w) / RAD;
    while (yaw - prev.r[1] > 180) yaw -= 360;
    while (yaw - prev.r[1] < -180) yaw += 360;
    const pose = { p: g.position.toArray().map(R3), r: [prev.r[0], R3(yaw), prev.r[2]], s: g.scale.toArray().map(v => R3(Math.max(0.05, v))) };
    if (o.kind !== 'char' && o.kind !== 'prop') pose.p[1] = Math.max(o.kind === 'floor' ? -5 : -0.5, pose.p[1]);
    this.writeObj(o, pose, this.dragBefore);
    this.selBox.setFromObject(g);
    this.paintTrail(); this.paintInspectorLive();
  }
  camFromPilot() {
    const k = this.shotCam, R3 = v => Math.round(v * 1000) / 1000;
    const cur = C.sampleCam(this.scene.cam, this.t);
    const pose = { p: k.position.toArray().map(R3), look: this.orbitCam.target.toArray().map(R3), mm: cur.mm, roll: cur.roll };
    this.writeCam(pose, this.camBefore);
    this.camRig.position.copy(k.position); this.camRig.quaternion.copy(k.quaternion); this.syncViz();
    this.lookDot.position.copy(this.orbitCam.target);
    this.curCam = pose;
  }
  keyNow() {
    const id = this.sel;
    if (!id) { this.toast('先選一個物件或攝影機，再打關鍵幀'); return; }
    this.beginEdit();
    const t = C.snap(this.t);
    if (id === 'cam' || id === 'look') { const c = this.scene.cam; c.keys = C.upsertKey(c.keys, t, C.sampleCam(c, t), null); }
    else { const o = this.objOf(id); const s = C.sampleObj(o, t); o.keys = C.upsertKey(o.keys, t, Object.assign({ e: 'lin' }, s), null); }
    this.selKey = { id: id === 'look' ? 'cam' : id, t };
    this.commit(); this.renderRight();
    this.toast('◆ ' + C.fmtT(t) + ' 打了一幀');
  }
  delSel() {
    if (this.selKey) {
      const { id, t } = this.selKey;
      this.beginEdit();
      if (id === 'cam') this.scene.cam.keys = this.scene.cam.keys.filter(k => Math.abs(k.t - t) > 1e-4);
      else { const o = this.objOf(id); if (o) { if (o.keys.length === 1) o.base = { p: o.keys[0].p, r: o.keys[0].r, s: o.keys[0].s }; o.keys = o.keys.filter(k => Math.abs(k.t - t) > 1e-4); } }
      if (id === 'cam' && !this.scene.cam.keys.length) { }
      this.selKey = null; this.commit(); this.applyTime(); this.renderRight();
      return;
    }
    const id = this.sel;
    if (!id || id === 'cam' || id === 'look') return;
    this.beginEdit();
    this.scene.objs = this.scene.objs.filter(o => o.id !== id);
    const g = this.meshes.get(id); if (g) this.world.remove(g); this.meshes.delete(id);
    this.sel = null; this.tc.detach(); this.selBox.visible = false;
    this.commit(); this.renderRight();
  }
  dupSel() {
    const o = this.objOf(this.sel); if (!o || o.kind === 'floor') return;
    const c = JSON.parse(JSON.stringify(o)); c.id = C.newId(o.kind[0]);
    c.base.p[0] += 0.6; c.keys.forEach(k => { k.p[0] += 0.6; });
    if (c.kind === 'char' && c.who) { c.who = ''; c.name = (o.name || '角色') + ' 2'; c.color = C.pickColor('', this.ctx.keys(), hx => this.ctx.clash(hx, ''), this.takenColors().concat([o.color])); }
    this.addObj(C.normalize({ objs: [c] }).objs[0]);
  }

  renderRight() {
    const R = this.$right; R.innerHTML = '';
    if (this.sel === 'cam' || this.sel === 'look') return this.camPanel(R);
    const o = this.objOf(this.sel);
    if (!o) {
      this.shotPanel(R); this.camPanel(R, true); return;
    }
    const KZ = { char: '角色', prop: '道具', floor: '地板', wall: '牆面', box: '方塊', cyl: '圓柱', ramp: '斜坡' };
    const s = $h('div', 'pv-sec');
    const hd = $h('div', 'pv-h'); hd.append(document.createTextNode(KZ[o.kind]), $h('em', null, o.keys.length ? o.keys.length + ' 個關鍵幀' : '靜止'));
    s.append(hd);
    if (o.kind === 'char' && o.who) {
      const card = $h('div', 'pv-card');
      const th = this.ctx.thumb(o.who);
      if (th) { const im = $h('img'); im.src = th; card.append(im); }
      const tx = $h('div'); tx.append($h('div', 't', '@' + o.who), $h('div', 's', '外觀照這張角色卡；預演只管走位'));
      card.append(tx); s.append(card);
    }
    s.append($h('div', 'pv-lbl', '名稱'));
    const nm = $h('input'); nm.value = o.name; nm.placeholder = '名稱'; nm.setAttribute('aria-label', '名稱');
    nm.onchange = () => { this.beginEdit(); o.name = nm.value.trim().slice(0, 40); this.commit(); };
    s.append(nm);
    if (o.kind === 'char' || o.kind === 'prop') {
      const bind = $h('select'); bind.setAttribute('aria-label', '綁定素材表');
      const cards = this.ctx.cast().filter(c => c && c.name && (o.kind === 'char' ? (c.kind || 'char') === 'char' : c.kind === 'prop'));
      const o0 = $h('option', null, o.kind === 'char' ? '— 不綁角色卡' : '— 不綁道具表'); o0.value = ''; bind.append(o0);
      cards.forEach(c => { const op = $h('option', null, '@' + c.name); op.value = c.name; if (c.name === o.who) op.selected = true; bind.append(op); });
      bind.onchange = () => {
        this.beginEdit();
        o.who = bind.value; if (o.who) o.name = o.who;
        o.color = o.who ? C.pickColor(o.who, this.ctx.keys(), hx => this.ctx.clash(hx, o.who), this.takenColors().filter(c => c !== o.color))
                        : (o.kind === 'prop' ? C.NEUTRAL.prop : o.color);
        this.rebuildOne(o); this.commit(); this.renderRight();
      };
      s.append($h('div', 'pv-lbl', o.kind === 'char' ? '綁定角色卡（外觀照這張）' : '綁定道具表'));
      s.append(bind);
    }
    R.append(s);

    if (o.kind === 'char' || (o.kind === 'prop' && o.who)) {
      const c = $h('div', 'pv-sec');
      const hh = $h('div', 'pv-h'); hh.append(document.createTextNode('分色'), $h('em', null, this.ctx.keyName(o.color)));
      c.append(hh);
      const sws = $h('div', 'pv-sws');
      const others = new Map(this.scene.objs.filter(x => x !== o && x.who && x.who !== o.who).map(x => [x.color, x.who]));
      const keyOwner = new Map(this.ctx.keys().filter(k => k.who && k.who !== o.who).map(k => [k.c.toLowerCase(), k.who]));
      C.KEY_HEX.forEach(hx => {
        const clash = this.ctx.clash(hx, o.who);
        const owner = others.get(hx) || keyOwner.get(hx);
        const b = btn((hx === o.color ? 'on' : '') + (clash.length ? ' clash' : ''), '', this.ctx.keyName(hx) + (owner ? '：已經是 ' + owner + ' 的顏色' : '') + (clash.length ? '：跟 ' + clash.map(x => x.who).join('、') + ' 的參考圖主色太接近' : ''));
        b.style.background = hx;
        if (owner) b.disabled = true;
        b.onclick = () => { this.beginEdit(); o.color = hx; this.rebuildOne(o); this.commit(); this.renderRight(); };
        sws.append(b);
      });
      c.append(sws);
      const keyed = o.who && this.ctx.keys().find(k => k.who === o.who);
      const note = $h('div', 'pv-note' + (keyed && keyed.c.toLowerCase() !== o.color ? ' warn' : ''));
      if (!o.who) note.textContent = '沒綁角色卡：匯出後提示詞不會說這個顏色是誰。';
      else if (!keyed) note.textContent = '匯出時會把「' + this.ctx.keyName(o.color) + '＝' + o.who + '」加進分色對照，送件提示詞自動帶上。';
      else if (keyed.c.toLowerCase() !== o.color) note.textContent = '分色對照裡 ' + o.who + ' 是' + this.ctx.keyName(keyed.c) + '：匯出時以這裡為準會造成兩色，建議改回' + this.ctx.keyName(keyed.c) + '。';
      else note.textContent = '跟分色對照一致：' + this.ctx.keyName(o.color) + '＝' + o.who + '。正面亮、背面暗，轉身看得出來。';
      c.append(note);
      R.append(c);
    }

    const tr = $h('div', 'pv-sec'); this.$live = tr;
    tr.append($h('div', 'pv-h', '位置與轉向 · ' + C.fmtT(this.t)));
    const pose = C.sampleObj(o, this.t);
    const f = $h('div', 'pv-f');
    const fld = (lab, v, set, step) => { const l = $h('label', null, lab); const i = $h('input'); i.type = 'number'; i.step = step || '0.05'; i.value = String(Math.round(v * 100) / 100); i.dataset.k = lab; i.onchange = () => { const n = Number(i.value); if (!Number.isFinite(n)) return; this.beginEdit(); set(n); this.commit(); this.applyTime(); }; l.append(i); f.append(l); };
    const upd = fn => { const p = C.sampleObj(o, this.t); const q = { p: p.p.slice(), r: p.r.slice(), s: p.s.slice() }; fn(q); this.writeObj(o, q, C.sampleObj(o, this.t)); };
    fld('X', pose.p[0], n => upd(q => { q.p[0] = n; })); fld('Y', pose.p[1], n => upd(q => { q.p[1] = n; })); fld('Z', pose.p[2], n => upd(q => { q.p[2] = n; }));
    fld('轉向°', pose.r[1], n => upd(q => { q.r[1] = n; }), '5'); fld('俯仰°', pose.r[0], n => upd(q => { q.r[0] = n; }), '5'); fld('側傾°', pose.r[2], n => upd(q => { q.r[2] = n; }), '5');
    tr.append(f);
    const kat = o.keys.find(k => Math.abs(k.t - C.snap(this.t)) < 1e-4);
    const row = $h('div', 'pv-row');
    row.append(btn('pv-btn pri', kat ? '◆ 更新這一幀' : '◆ 在 ' + C.fmtT(this.t) + ' 打一幀', 'K', () => this.keyNow()));
    if (kat) {
      const io = btn('pv-btn', kat.e === 'io' ? '緩入緩出 ✓' : '等速', '到這一幀的那一段：等速或緩入緩出', () => { this.beginEdit(); kat.e = kat.e === 'io' ? 'lin' : 'io'; this.commit(); this.renderRight(); });
      row.append(io);
    }
    tr.append(row);
    R.append(tr);

    const sz = $h('div', 'pv-sec');
    sz.append($h('div', 'pv-h', o.kind === 'char' ? '身高' : '尺寸（公分）'));
    const f2 = $h('div', o.kind === 'char' ? 'pv-f2' : 'pv-f');
    const cm = (lab, idx) => { const l = $h('label', null, lab); const i = $h('input'); i.type = 'number'; i.step = '1'; i.min = '1'; i.value = String(Math.round(o.size[idx] * 100)); i.onchange = () => { const n = Number(i.value); if (!(n > 0)) return; this.beginEdit(); o.size[idx] = C.clamp(n / 100, 0.01, 60); this.rebuildOne(o); this.commit(); }; l.append(i); f2.append(l); };
    if (o.kind === 'char') { cm('身高 cm', 1); const l = $h('label', null, '比例'); l.append(Object.assign($h('input'), { value: '頭 · 上身 · 下身', disabled: true })); f2.append(l); }
    else { cm('寬', 0); cm('高', 1); cm('深', 2); }
    sz.append(f2);
    if (o.kind === 'prop' && o.preset) sz.append($h('div', 'pv-note', '真實尺寸：' + (C.PROP_PRESETS.find(x => x[0] === o.preset) || [0, 0, []])[2].join('×') + ' 公分'));
    R.append(sz);

    const act = $h('div', 'pv-sec');
    const r2 = $h('div', 'pv-row');
    if (o.kind !== 'floor') r2.append(btn('pv-btn', '複製', '⌘D', () => this.dupSel()));
    if (o.keys.length) r2.append(btn('pv-btn', '清除動作', '拿掉這個物件的全部關鍵幀，停在目前的姿態', () => { this.beginEdit(); o.base = C.sampleObj(o, this.t); o.keys = []; this.commit(); this.applyTime(); this.renderRight(); }));
    r2.append(btn('pv-btn dng', '刪除', 'Delete', () => this.delSel()));
    act.append(r2); R.append(act);
  }
  shotPanel(R) {
    const sh = this.shot, n = this.ctx.shots().indexOf(sh) + 1;
    const s = $h('div', 'pv-sec');
    const hd = $h('div', 'pv-h'); hd.append(document.createTextNode('第 ' + n + ' 鏡'), $h('em', null, '分鏡表 ' + (Number(sh.seconds) > 0 ? sh.seconds + 's · ' : '') + (this.ctx.camMoves()[(sh.cam || {}).move] || { zh: '固定機位' }).zh));
    s.append(hd);
    s.append(Object.assign($h('div', 'pv-note'), { textContent: String(sh.prompt || '（這一鏡還沒有描述）').slice(0, 220) }));
    const m = $h('div', 'pv-cam'); m.style.marginTop = '12px';
    if (sh.motion && sh.motion.previs) { m.append($h('div', 'mv', '動作來源：3D 預演 ✓'), $h('div', 'sub', (sh.motion.dur || '') + 's · 改完再匯出一次就會換掉')); }
    else if (sh.motion) { m.append($h('div', 'mv', '動作來源：' + (sh.motion.name || '已附影片')), $h('div', 'sub', '匯出 3D 預演會換掉它')); }
    else m.append($h('div', 'mv', '還沒有動作來源'), $h('div', 'sub', '做完按右上「匯出成動作來源」'));
    s.append(m);
    const chars = this.scene.objs.filter(o => o.who && (o.kind === 'char' || o.kind === 'prop'));
    if (chars.length) {
      const k = $h('div', 'pv-kn');
      k.append($h('b', null, '分色'));
      chars.forEach(o => { const r = $h('div'); r.style.cssText = 'display:flex;align-items:center;gap:8px;margin-top:4px'; const sw = $h('span'); sw.style.cssText = 'width:12px;height:12px;border-radius:3px;background:' + o.color; r.append(sw, document.createTextNode(this.ctx.keyName(o.color) + '＝' + o.who)); k.append(r); });
      s.append(k);
    }
    s.append(Object.assign($h('div', 'pv-note'), { textContent: '在畫面或左邊清單點一個物件，這裡會出現它的位置、轉向與綁定的角色卡。' }));
    R.append(s);
  }
  paintRead() {
    if (!this.ptr || !this.tc.dragging) return;
    let txt = '';
    if (this.sel === 'cam' || this.sel === 'look') { const c = this.camRig.position, l = this.lookDot.position; const p = this.sel === 'cam' ? c : l; txt = (this.sel === 'cam' ? '機位 ' : '注視點 ') + p.x.toFixed(2) + ' · ' + p.y.toFixed(2) + ' · ' + p.z.toFixed(2) + ' m'; }
    else {
      const o = this.objOf(this.sel); if (!o) return;
      const q = C.sampleObj(o, this.t);
      txt = this.mode === 'rotate' ? '轉向 ' + Math.round(q.r[1]) + '°' : this.mode === 'scale' ? '縮放 ×' + q.s.map(v => v.toFixed(2)).join(' ') : 'X ' + q.p[0].toFixed(2) + ' · Y ' + q.p[1].toFixed(2) + ' · Z ' + q.p[2].toFixed(2) + ' m';
    }
    txt += this.autokey ? (C.snap(this.t) > 0 || this.keysOfSel().length ? '  ◆ ' + C.fmtT(this.t) : '') : '  整段';
    this.$read.textContent = txt;
    this.$read.style.display = 'block'; this.$read.style.left = this.ptr[0] + 'px'; this.$read.style.top = this.ptr[1] + 'px';
  }
  keysOfSel() { if (this.sel === 'cam' || this.sel === 'look') return this.scene.cam.keys; const o = this.objOf(this.sel); return o ? o.keys : []; }
  paintInspectorLive() {
    if (!this.$live || !this.$live.isConnected) return;
    const o = this.objOf(this.sel); if (!o) return;
    const p = C.sampleObj(o, this.t);
    const m = { 'X': p.p[0], 'Y': p.p[1], 'Z': p.p[2], '轉向°': p.r[1], '俯仰°': p.r[0], '側傾°': p.r[2] };
    this.$live.querySelectorAll('input[data-k]').forEach(i => { if (document.activeElement !== i) i.value = String(Math.round(m[i.dataset.k] * 100) / 100); });
  }
  camPanel(R, compact) {
    const cam = this.scene.cam;
    const cur = C.sampleCam(cam, this.t);
    const s = $h('div', 'pv-sec');
    const hd = $h('div', 'pv-h'); hd.append(document.createTextNode('攝影機'), $h('em', null, cam.keys.length ? cam.keys.length + ' 個關鍵幀' : '固定'));
    s.append(hd);
    if (compact) {
      const b = btn('pv-btn', '選取攝影機', '', () => this.select('cam'));
      s.append(b); R.append(s); return;
    }
    const lab = $h('div', 'pv-h'); lab.append(document.createTextNode('焦距'), $h('em', null, Math.round(cur.mm) + 'mm · 視角 ' + Math.round(C.vfov(cur.mm)) + '°'));
    s.append(lab);
    const rg = $h('input'); rg.type = 'range'; rg.min = '12'; rg.max = '200'; rg.step = '1'; rg.value = String(Math.round(cur.mm));
    rg.oninput = () => { if (!this.mmEdit) { this.beginEdit(); this.mmEdit = true; } const p = C.sampleCam(cam, this.t); p.mm = Number(rg.value); this.writeCam(p, C.sampleCam(cam, this.t)); this.applyTime(); lab.lastChild.textContent = rg.value + 'mm · 視角 ' + Math.round(C.vfov(Number(rg.value))) + '°'; this.paintHud(); };
    rg.onchange = () => { this.mmEdit = false; this.commit(); this.renderRight(); };
    s.append(rg);
    const fc = $h('div', 'pv-focal');
    C.FOCALS.forEach(mm => fc.append(btn(Math.round(cur.mm) === mm ? 'on' : '', String(mm), mm + 'mm', () => { this.beginEdit(); const p = C.sampleCam(cam, this.t); p.mm = mm; this.writeCam(p, C.sampleCam(cam, this.t)); this.commit(); this.applyTime(); this.renderRight(); this.paintHud(); })));
    s.append(fc);
    const kat = cam.keys.find(k => Math.abs(k.t - C.snap(this.t)) < 1e-4);
    const row = $h('div', 'pv-row');
    row.append(btn('pv-btn pri', kat ? '◆ 更新這一幀' : '◆ 在 ' + C.fmtT(this.t) + ' 打一幀', 'K', () => this.keyNow()));
    row.append(btn('pv-btn', '透過鏡頭看', 'C', () => this.setView('cam')));
    s.append(row);
    R.append(s);

    const m = $h('div', 'pv-sec');
    m.append($h('div', 'pv-h', '從運鏡產生'));
    const sc = this.shot.cam || {};
    const moves = this.ctx.camMoves();
    const box = $h('div', 'pv-cam');
    const zh = id => (moves[id] && moves[id].zh) || '固定機位';
    box.append($h('div', 'mv', '分鏡表：' + zh(sc.move || 'static')));
    box.append($h('div', 'sub', [this.ctx.camLabel('speed', sc.speed), this.ctx.camLabel('size', sc.size), this.ctx.camLabel('angle', sc.angle)].filter(Boolean).join(' · ') || '速度、景別、角度沒填：用中速、中景、平視'));
    m.append(box);
    const sel = $h('select'); sel.setAttribute('aria-label', '運鏡');
    this.ctx.camGroups().forEach(([g, list]) => {
      const og = document.createElement('optgroup'); og.label = g;
      list.forEach(([id, z]) => { const op = $h('option', null, z); op.value = id; if (id === (this.pickMove || sc.move || 'static')) op.selected = true; og.append(op); });
      sel.append(og);
    });
    sel.onchange = () => { this.pickMove = sel.value; };
    const r2 = $h('div', 'pv-row'); r2.append(sel); m.append(r2);
    const r3 = $h('div', 'pv-row');
    r3.append(btn('pv-btn pri', '產生攝影機路徑', '照上面的運鏡、景別、角度與速度，產生起始的攝影機關鍵幀（會取代目前的攝影機路徑，可以復原）', () => this.genPath(sel.value)));
    m.append(r3);
    if (this.pathNote) m.append($h('div', 'pv-note', this.pathNote));
    m.append($h('div', 'pv-note', '最後 1 秒停穩不動（研究：終點沒交代時最後一秒會晃）。產生之後可以在時間軸上拖關鍵幀、或在鏡頭視角直接修。'));
    if (cam.keys.length) {
      const r4 = $h('div', 'pv-row');
      r4.append(btn('pv-btn dng', '清除攝影機動作', '拿掉攝影機的關鍵幀，停在目前的機位', () => { this.beginEdit(); cam.base = C.sampleCam(cam, this.t); cam.keys = []; this.commit(); this.applyTime(); this.renderRight(); }));
      m.append(r4);
    }
    R.append(m);
  }
  genPath(move) {
    const sc = Object.assign({}, this.shot.cam || {}, { move });
    const fol = (() => {
      const ch = this.scene.objs.filter(o => o.kind === 'char' && o.keys.length);
      if (!ch.length) return null;
      return t => { const p = C.sampleObj(ch[0], t).p; return [p[0], ch[0].size[1] * 0.8 + p[1], p[2]]; };
    })();
    const res = C.camPath(sc, { target: C.subjectTarget(this.scene, 0, sc.size), dur: this.scene.dur, follow: fol });
    this.beginEdit();
    const c = this.scene.cam;
    c.move = move;
    c.keys = res.keys.length > 1 ? res.keys : [];
    const k0 = res.keys[0];
    if (k0) c.base = { p: k0.p, look: k0.look, mm: k0.mm, roll: k0.roll };
    this.pathNote = res.note;
    this.commit(); this.applyTime(); this.renderRight(); this.paintHud();
    this.toast('攝影機路徑：' + ((this.ctx.camMoves()[move] || {}).zh || move) + ' · ' + c.keys.length + ' 個關鍵幀');
  }

  buildTimelineShell() {
    const T = this.$tl;
    const tr = $h('div', 'pv-tr');
    const tb = (k, tip, fn, cls) => { const b = btn('tb' + (cls ? ' ' + cls : ''), '', tip, fn); b.innerHTML = svg(k); tr.append(b); return b; };
    tb('first', '回到開頭（Home）', () => this.seek(0));
    tb('prev', '上一個關鍵幀（,）', () => this.jumpKey(-1));
    this.$play = tb('play', '播放／暫停（空白鍵）', () => this.toggle(), 'play');
    tb('next', '下一個關鍵幀（.）', () => this.jumpKey(1));
    tb('last', '到結尾（End）', () => this.seek(this.scene.dur));
    this.$time = $h('span', 'pv-time'); tr.append(this.$time);
    this.$loop = btn('pv-tg' + (this.loop ? ' on' : ''), '', '播到結尾從頭再播', () => { this.loop = !this.loop; this.$loop.classList.toggle('on', this.loop); });
    this.$loop.innerHTML = '<span class="lt" style="background:' + '#5bc8d8' + ';box-shadow:none"></span>循環';
    tr.append(this.$loop);
    tr.append($h('span', 'pv-sp'));
    this.$auto = btn('pv-tg' + (this.autokey ? ' on' : ''), '', '開：拖動物件或攝影機時，在播放頭打關鍵幀。關：整段動作一起平移', () => { this.autokey = !this.autokey; this.$auto.classList.toggle('on', this.autokey); this.$auto.lastChild.textContent = this.autokey ? '自動打幀' : '整段平移'; this.paintHud(); });
    this.$auto.innerHTML = '<span class="lt"></span><span>' + (this.autokey ? '自動打幀' : '整段平移') + '</span>';
    tr.append(this.$auto);
    const k = btn('pv-key', '◆ 打關鍵幀', '在播放頭替選取的東西打一幀（K）', () => this.keyNow());
    tr.append(k);
    T.append(tr);
    this.$tracks = $h('div', 'pv-tracks'); T.append(this.$tracks);
  }
  laneX(t, w) { return (t / this.scene.dur) * w; }
  renderTracks() {
    if (!this.scene) return;
    const B = this.$tracks; B.innerHTML = '';
    const ru = $h('div', 'pv-ruler'); ru.append($h('div', 'lab'));
    const sc = $h('div', 'sc'); ru.append(sc); B.append(ru);
    const dur = this.scene.dur;
    for (let i = 0; i <= dur * 4 + 1e-6; i++) {
      const t = i / 4;
      const tk = $h('span', 'tick' + (i % 4 === 0 ? ' big' : ''));
      tk.style.left = (t / dur * 100) + '%'; tk.style.height = i % 4 === 0 ? '10px' : '5px';
      if (i % 4 === 0) tk.append($h('span', null, t + 's'));
      sc.append(tk);
    }
    this.scrub(sc);
    const rows = [{ id: 'cam', name: '攝影機', color: '#e8a33d', keys: this.scene.cam.keys }]
      .concat(this.scene.objs.filter(o => o.kind !== 'floor' || o.keys.length).map(o => ({ id: o.id, name: o.name || o.kind, color: o.color, keys: o.keys, o })));
    rows.forEach(r => {
      const on = this.sel === r.id || (r.id === 'cam' && this.sel === 'look');
      const row = $h('div', 'pv-trk' + (on ? ' on' : ''));
      const lab = $h('div', 'lab'); const sw = $h('span', 'sw'); sw.style.background = r.color;
      lab.append(sw, document.createTextNode(r.name)); lab.onclick = () => this.select(r.id);
      const ln = $h('div', 'ln');
      if (r.keys.length > 1) {
        const a = r.keys[0].t, b = r.keys[r.keys.length - 1].t;
        const sg = $h('span', 'seg'); sg.style.left = (a / dur * 100) + '%'; sg.style.width = ((b - a) / dur * 100) + '%'; ln.append(sg);
      }
      r.keys.forEach(k => {
        const d = btn('pv-dia' + (this.selKey && this.selKey.id === r.id && Math.abs(this.selKey.t - k.t) < 1e-4 ? ' sel' : '') + (k.e === 'io' ? ' io' : ''), '', C.fmtT(k.t) + '（拖曳移動、Delete 刪除）');
        d.style.left = (k.t / dur * 100) + '%';
        d.onpointerdown = e => this.dragKey(e, r, k, ln);
        ln.append(d);
      });
      this.scrub(ln, r.id);
      ln.addEventListener('dblclick', e => { if (e.target.closest('.pv-dia')) return; this.keyNow(); });
      ln.title = '點一下：跳到那個時間；雙擊：在那裡打一幀';
      row.append(lab, ln); B.append(row);
    });
    this.$ph = $h('div', 'pv-ph'); B.append(this.$ph);
    this.paintTime();
  }
  scrub(el, id) {
    el.addEventListener('pointerdown', e => {
      if (e.target.closest('.pv-dia')) return;
      if (id && this.sel !== id) this.select(id);
      const go = ev => { const r = el.getBoundingClientRect(); this.seek(C.clamp((ev.clientX - r.left) / r.width, 0, 1) * this.scene.dur, true); };
      this.pause(); go(e);
      const mv = ev => go(ev);
      const up = () => { window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up); this.seek(this.t); };
      window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
    });
  }
  dragKey(e, r, k, ln) {
    e.preventDefault(); e.stopPropagation();
    this.pause();
    if (this.sel !== r.id) { this.sel = r.id; this.attachGizmo(); this.renderLeft(); this.renderRight(); this.paintTrail(); }
    this.selKey = { id: r.id, t: k.t };
    const rect = ln.getBoundingClientRect(), x0 = e.clientX;
    let moved = false, from = k.t;
    const holder = () => (r.id === 'cam' ? this.scene.cam : this.objOf(r.id));
    const mv = ev => {
      const to = C.clamp(from + (ev.clientX - x0) / rect.width * this.scene.dur, 0, this.scene.dur);
      if (!moved && Math.abs(ev.clientX - x0) < 3) return;
      if (!moved) { moved = true; this.beginEdit(); }
      const h = holder(); const before = h.keys;
      h.keys = C.moveKey(h.keys, this.selKey.t, to, this.scene.dur);
      if (h.keys !== before) { const nk = h.keys.find(x => Math.abs(x.t - C.snap(to)) < 1e-3); if (nk) this.selKey.t = nk.t; }
      this.seek(this.selKey.t, true);
      this.renderTracks();
    };
    const up = () => {
      window.removeEventListener('pointermove', mv); window.removeEventListener('pointerup', up);
      if (moved) this.commit(); else { this.seek(k.t); this.renderTracks(); }
      this.renderRight();
    };
    window.addEventListener('pointermove', mv); window.addEventListener('pointerup', up);
  }
  paintTime() {
    if (!this.$time) return;
    this.$time.innerHTML = C.fmtT(this.t) + ' <i>/ ' + C.fmtT(this.scene.dur) + ' · ' + Math.round(this.t * C.FPS) + 'f</i>';
    if (this.$ph) {
      const sc = this.$tracks.querySelector('.pv-ruler .sc');
      if (sc) { const x = sc.offsetLeft + this.laneX(this.t, sc.clientWidth); this.$ph.style.left = x + 'px'; }
    }
    this.$play.innerHTML = svg(this.playing ? 'pause' : 'play');
    this.paintHud();
  }
  seek(t, live) {
    this.t = C.clamp(live ? C.snap(t) : C.snap(t), 0, this.scene.dur);
    this.applyTime(); this.paintTime(); this.paintInspectorLive();
    if (!live) this.renderRight();
  }
  jumpKey(dir) {
    const all = new Set();
    const add = ks => ks.forEach(k => all.add(k.t));
    if (this.sel && this.sel !== 'look') add(this.sel === 'cam' ? this.scene.cam.keys : (this.objOf(this.sel) || { keys: [] }).keys);
    else { add(this.scene.cam.keys); this.scene.objs.forEach(o => add(o.keys)); }
    const ts = [...all].sort((a, b) => a - b);
    const t = dir > 0 ? ts.find(x => x > this.t + 1e-4) : ts.reverse().find(x => x < this.t - 1e-4);
    if (t != null) this.seek(t);
  }
  toggle() { if (this.playing) this.pause(); else this.play(); }
  play() { if (this.t >= this.scene.dur - 1e-3) this.t = 0; this.playing = true; this.tc.enabled = false; this.paintTime(); }
  pause() { if (!this.playing) return; this.playing = false; this.tc.enabled = true; this.t = C.snap(this.t); this.applyTime(); this.paintTime(); this.renderRight(); }

  paintTrail() {
    this.trailDots.clear();
    this.ghosts.children.slice().forEach(g => { this.ghosts.remove(g); g.traverse(x => { if (x.material) x.material.dispose(); }); });
    const o = this.objOf(this.sel);
    if (!o || o.keys.length < 2) { this.trail.visible = false; return; }
    const src = this.meshes.get(o.id);
    if (src) o.keys.slice(0, 8).forEach(k => {
      const g = src.clone(true);
      g.traverse(x => { if (x.isMesh) { x.material = new THREE.MeshBasicMaterial({ color: new THREE.Color(o.color), transparent: true, opacity: 0.16, depthWrite: false }); x.castShadow = false; x.userData = {}; } });
      g.position.set(k.p[0], k.p[1], k.p[2]); g.rotation.set(k.r[0] * RAD, k.r[1] * RAD, k.r[2] * RAD); g.scale.set(k.s[0], k.s[1], k.s[2]);
      this.ghosts.add(g);
    });
    const pts = [];
    for (let i = 0; i <= 80; i++) { const p = C.sampleObj(o, this.scene.dur * i / 80).p; pts.push(new THREE.Vector3(p[0], p[1] + 0.02, p[2])); }
    this.trail.geometry.setFromPoints(pts); this.trail.visible = true;
    o.keys.forEach(k => { const d = new THREE.Mesh(new THREE.SphereGeometry(0.05, 12, 8), new THREE.MeshBasicMaterial({ color: 0x1fb5c9, depthTest: false })); d.renderOrder = 6; d.position.set(k.p[0], k.p[1] + 0.02, k.p[2]); this.trailDots.add(d); });
  }
  paintCamPath() {
    const c = this.scene.cam;
    if (c.keys.length < 2) { this.camPathLine.visible = false; return; }
    const pts = [];
    for (let i = 0; i <= 90; i++) { const p = C.sampleCam(c, this.scene.dur * i / 90).p; pts.push(new THREE.Vector3(p[0], p[1], p[2])); }
    this.camPathLine.geometry.setFromPoints(pts); this.camPathLine.computeLineDistances(); this.camPathLine.visible = true;
  }

  key(e) {
    if (!this.root.isConnected) return;
    const tag = (e.target && e.target.tagName) || '';
    const typing = /INPUT|SELECT|TEXTAREA/.test(tag) && e.target.type !== 'range';
    const mod = e.metaKey || e.ctrlKey;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); if (this.$pop) this.closePop(); else if (this.$modal) this.closeModal(); else this.close(); return; }
    if (this.$modal) return;
    if (typing) return;
    const k = e.key.toLowerCase();
    let used = true;
    if (mod && k === 'z') { if (e.shiftKey) this.doRedo(); else this.doUndo(); }
    else if (mod && k === 'y') this.doRedo();
    else if (mod && k === 'd') this.dupSel();
    else if (mod) used = false;
    else if (k === 'w') this.setMode('translate');
    else if (k === 'e') this.setMode('rotate');
    else if (k === 'r') this.setMode('scale');
    else if (k === 'k') this.keyNow();
    else if (k === 'f') this.focusSel();
    else if (k === 'c') this.setView(this.view === 'work' ? 'cam' : 'work');
    else if (e.key === ' ') this.toggle();
    else if (e.key === 'Delete' || e.key === 'Backspace') this.delSel();
    else if (e.key === 'Home') this.seek(0);
    else if (e.key === 'End') this.seek(this.scene.dur);
    else if (e.key === 'ArrowLeft') this.seek(this.t - (e.shiftKey ? 1 : 1 / C.FPS));
    else if (e.key === 'ArrowRight') this.seek(this.t + (e.shiftKey ? 1 : 1 / C.FPS));
    else if (k === ',') this.jumpKey(-1);
    else if (k === '.') this.jumpKey(1);
    else used = false;
    if (used) { e.preventDefault(); e.stopPropagation(); }
  }

  queueSave() {
    this.paintSave();
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(() => this.flushSave(), 700);
  }
  async flushSave() {
    clearTimeout(this.saveTimer); this.saveTimer = null;
    if (!this.dirty || !this.scene || !this.sid) return;
    this.dirty = false;
    const sid = this.sid, snap = JSON.parse(JSON.stringify(this.scene));
    const bytes = C.sceneBytes(snap);
    this.saving = true; this.paintSave();
    let ok = false;
    try { ok = await this.ctx.save(sid, snap); } catch (e) { ok = false; }
    this.saving = false; this.saveErr = !ok; this.savedAt = ok ? new Date() : this.savedAt;
    if (!ok) this.dirty = true;
    this.paintSave(bytes);
  }
  paintSave(bytes) {
    if (!this.$save) return;
    const el = this.$save;
    el.className = 'pv-save' + (this.saveErr ? ' err' : this.dirty || this.saving ? ' dirty' : '');
    el.textContent = this.saveErr ? '存不進去' : this.saving ? '儲存中…' : this.dirty ? '未存' : '已存' + (this.savedAt ? ' · ' + this.savedAt.toTimeString().slice(0, 5) : '');
    if (this.saveErr) el.title = '這個專案的預演存檔太大或伺服器沒回應：改動還在畫面上，稍後會再試';
    else if (bytes) el.title = '跟著專案與分鏡存在本站（' + Math.round(bytes / 1024) + ' KB）';
  }

  closeModal() { if (this.$modal) { const v = this.$modal.querySelector('video'); if (v && v.src) URL.revokeObjectURL(v.src); this.$modal.remove(); this.$modal = null; } }
  modal(build) {
    this.closeModal();
    const m = this.$modal = $h('div', 'pv-modal');
    const d = $h('div', 'pv-dlg'); build(d); m.append(d);
    this.root.append(m);
    return d;
  }
  async record(onProg) {
    const { w, h } = C.exportSize(this.scene.aspect);
    const N = C.frameCount(this.scene.dur, C.FPS);
    const cv = document.createElement('canvas'); cv.width = w; cv.height = h;
    const r = new THREE.WebGLRenderer({ canvas: cv, antialias: true, preserveDrawingBuffer: true });
    r.setPixelRatio(1); r.setSize(w, h, false);
    r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap; r.toneMapping = THREE.NeutralToneMapping;
    const cam = this.shotCam.clone(); cam.aspect = w / h; cam.updateProjectionMatrix();
    const t0 = this.t, was = this.playing; this.playing = false;
    const S = this.scene3;
    const renderAt = t => {
      this.t = t; this.applyTime();
      cam.position.copy(this.shotCam.position); cam.quaternion.copy(this.shotCam.quaternion); cam.fov = this.shotCam.fov; cam.updateProjectionMatrix();
      this.helpers.visible = false; S.background = this.BG_SHOT;
      r.render(S, cam);
      this.helpers.visible = true;
    };
    const why = [];
    try {
      const out = await this.recordCodecs(cv, renderAt, N, w, h, onProg, why);
      if (out) return Object.assign(out, { w, h, frames: N });
      onProg(0, '這個瀏覽器不能用 WebCodecs 錄 mp4（' + why.join('；') + '），改用即時錄影');
      const out2 = await this.recordLive(cv, renderAt, N, onProg, why);
      return Object.assign(out2, { w, h, frames: N, why: why.join('；') });
    } finally {
      r.dispose();
      this.t = t0; this.applyTime(); this.playing = was;
    }
  }
  async recordCodecs(cv, renderAt, N, w, h, onProg, why) {
    if (typeof window.VideoEncoder !== 'function' || typeof window.VideoFrame !== 'function') { why.push('沒有 VideoEncoder'); return null; }
    let codec = null;
    for (const c of C.AVC_CANDIDATES) {
      try { const s = await VideoEncoder.isConfigSupported({ codec: c, width: w, height: h, bitrate: C.bitrateFor(w, h), framerate: C.FPS }); if (s && s.supported) { codec = c; break; } } catch (e) {}
    }
    if (!codec) { why.push('H.264 編碼器不支援 ' + w + '×' + h); return null; }
    const { Muxer, ArrayBufferTarget } = await import('./vendor/mp4-muxer.mjs');
    const target = new ArrayBufferTarget();
    const mux = new Muxer({ target, video: { codec: 'avc', width: w, height: h, frameRate: C.FPS }, fastStart: 'in-memory', firstTimestampBehavior: 'offset' });
    let err = null;
    const enc = new VideoEncoder({ output: (chunk, meta) => mux.addVideoChunk(chunk, meta), error: e => { err = e; } });
    enc.configure({ codec, width: w, height: h, bitrate: C.bitrateFor(w, h), framerate: C.FPS, avc: { format: 'avc' }, latencyMode: 'quality' });
    const us = 1e6 / C.FPS;
    for (let i = 0; i < N; i++) {
      if (err) throw err;
      renderAt(i / C.FPS);
      const vf = new VideoFrame(cv, { timestamp: Math.round(i * us), duration: Math.round(us) });
      enc.encode(vf, { keyFrame: i % C.FPS === 0 });
      vf.close();
      while (enc.encodeQueueSize > 6) await new Promise(res => setTimeout(res, 4));
      if (i % 3 === 0) { onProg((i + 1) / N, '渲染與編碼 ' + (i + 1) + ' / ' + N + ' 幀'); await new Promise(res => setTimeout(res, 0)); }
    }
    onProg(1, '封裝 mp4…');
    await enc.flush(); enc.close();
    if (err) throw err;
    mux.finalize();
    return { blob: new Blob([target.buffer], { type: 'video/mp4' }), ext: 'mp4', mime: 'video/mp4', codec, via: 'WebCodecs ' + codec + ' → mp4-muxer' };
  }
  async recordLive(cv, renderAt, N, onProg, why) {
    if (typeof MediaRecorder !== 'function' || !cv.captureStream) throw new Error('這個瀏覽器也沒有 MediaRecorder，沒辦法在瀏覽器裡錄影（請換新版 Chrome、Edge 或 Safari）');
    const types = ['video/mp4;codecs=avc1', 'video/mp4', 'video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'];
    const mime = types.find(t => { try { return MediaRecorder.isTypeSupported(t); } catch (e) { return false; } }) || '';
    if (!mime.startsWith('video/mp4')) why.push('MediaRecorder 只能錄 webm');
    const stream = cv.captureStream(C.FPS);
    const rec = new MediaRecorder(stream, mime ? { mimeType: mime, videoBitsPerSecond: 5e6 } : undefined);
    const parts = [];
    rec.ondataavailable = e => { if (e.data && e.data.size) parts.push(e.data); };
    const done = new Promise(res => { rec.onstop = res; });
    rec.start(250);
    const dur = N / C.FPS, start = performance.now();
    await new Promise(res => {
      const tick = () => {
        const t = (performance.now() - start) / 1000;
        if (t >= dur) { renderAt(dur); res(); return; }
        renderAt(t); onProg(t / dur, '即時錄影 ' + t.toFixed(1) + ' / ' + dur.toFixed(1) + ' 秒（請不要切換分頁）');
        requestAnimationFrame(tick);
      };
      tick();
    });
    rec.stop(); await done;
    stream.getTracks().forEach(t => t.stop());
    const type = (rec.mimeType || mime || 'video/webm').split(';')[0];
    return { blob: new Blob(parts, { type }), ext: type === 'video/mp4' ? 'mp4' : 'webm', mime: type, via: 'MediaRecorder ' + (rec.mimeType || mime) };
  }
  async exportFlow() {
    this.flushSave();
    const n = this.ctx.shots().findIndex(s => s.sid === this.sid) + 1;
    let bar, st;
    this.modal(d => {
      d.innerHTML = '<div class="hd"><b>錄成動作來源 · 第 ' + n + ' 鏡</b><span class="pv-chip"><i>不花點數</i>瀏覽器本機錄影</span></div>';
      const p = $h('div', 'pv-prog');
      p.append($h('div', null, '依攝影機畫面逐幀渲染 ' + C.frameCount(this.scene.dur) + ' 幀（' + this.scene.dur + ' 秒 × ' + C.FPS + ' fps）'));
      const b = $h('div', 'pv-bar'); bar = $h('i'); b.append(bar); p.append(b);
      st = $h('div', 'st', '準備中…'); p.append(st);
      d.append(p);
    });
    let res;
    try {
      res = await this.record((f, msg) => { bar.style.width = Math.round(f * 100) + '%'; st.textContent = msg; });
    } catch (e) {
      st.textContent = '錄影失敗：' + (e && e.message || e); st.style.color = '#ff8b8e';
      const ft = $h('div', 'ft'); ft.append(btn('pv-btn', '關閉', '', () => this.closeModal())); this.$modal.querySelector('.pv-dlg').append(ft);
      return;
    }
    this.lastExport = res;
    this.showResult(res, n);
  }
  showResult(res, n) {
    const url = URL.createObjectURL(res.blob);
    const name = '3D預演-第' + n + '鏡-' + this.scene.dur + 's.' + res.ext;
    const keys = C.mergeKeys(this.ctx.keys(), this.scene.objs);
    const zhNote = this.ctx.colorPreview(keys.keys, this.scene.objs);
    const videoOk = this.ctx.videoOk();
    const big = res.blob.size > C.MAX_UPLOAD;
    this.modal(d => {
      d.innerHTML = '<div class="hd"><b>預演錄好了 · 第 ' + n + ' 鏡</b><span class="pv-chip"><i>' + res.ext.toUpperCase() + '</i>' + res.w + '×' + res.h + ' · ' + this.scene.dur + 's</span></div>';
      const bd = $h('div', 'bd');
      const v = $h('video'); v.src = url; v.controls = true; v.loop = true; v.muted = true; v.autoplay = true; v.playsInline = true;
      bd.append(v);
      const side = $h('div');
      const dl = $h('dl');
      const row = (k, val) => { dl.append($h('dt', null, k), $h('dd', null, val)); };
      row('格式', res.mime + (res.ext === 'mp4' ? ' · H.264' : ''));
      row('尺寸', res.w + '×' + res.h + ' · ' + C.FPS + ' fps');
      row('長度', this.scene.dur + ' 秒（' + res.frames + ' 幀）');
      row('大小', (res.blob.size / 1024 / 1024).toFixed(2) + ' MB');
      row('錄法', res.via);
      side.append(dl);
      if (res.ext !== 'mp4') side.append(Object.assign($h('div', 'pv-note warn'), { textContent: '退回 webm 的原因：' + (res.why || '瀏覽器不支援 mp4 編碼') + '。部分模型只收 mp4 參考影片；需要時用新版 Chrome／Edge 重錄。' }));
      if (/^MediaRecorder/.test(res.via)) side.append(Object.assign($h('div', 'pv-note warn'), { textContent: '這支是即時錄的：錄影時切到別的分頁會掉幀，長度可能比 ' + this.scene.dur + ' 秒短' + (res.ext === 'webm' ? '，而且 webm 檔不帶長度資訊' : '') + '。' }));
      if (big) side.append(Object.assign($h('div', 'pv-note warn'), { textContent: '超過 20 MB，上游收不了：縮短長度或改小比例後重錄。' }));
      if (!videoOk.ok) side.append(Object.assign($h('div', 'pv-note warn'), { textContent: videoOk.why + '：放進動作來源後，這個模型送件時不會附它（換一個收參考影片的模型就會附）。' }));
      const kn = $h('div', 'pv-kn'); kn.append($h('b', null, '送件時自動帶上的分色對照'));
      kn.append(document.createTextNode(zhNote || '這一鏡沒有綁角色卡的人偶：提示詞只說明這是積木預演、外觀照參考圖。'));
      if (keys.added.length) kn.append($h('div', 'pv-note', '會新增到專案分色對照：' + keys.added.map(k => this.ctx.keyName(k.c) + '＝' + k.who).join('、')));
      if (keys.conflicts.length) kn.append(Object.assign($h('div', 'pv-note warn'), { textContent: '要注意：' + keys.conflicts.join('；') }));
      side.append(kn);
      bd.append(side); d.append(bd);
      const ft = $h('div', 'ft');
      const a = $h('a', 'pv-btn'); a.href = url; a.download = name; a.textContent = '下載'; a.style.cssText = 'display:inline-flex;align-items:center;text-decoration:none';
      ft.append(btn('pv-btn', '回去調整', '', () => this.closeModal()), a);
      const go = btn('pv-go', '放進第 ' + n + ' 鏡的動作來源', '上傳成素材（走 /api/assets，原檔另存）並放進這一鏡的動作來源槽。上傳不花生成費用', async () => {
        go.disabled = true; go.textContent = '上傳中…';
        try {
          const file = new File([res.blob], name, { type: res.mime });
          const who = [...new Set((this.scene.objs || []).filter(o => o.who && (o.kind === 'char' || o.kind === 'prop')).map(o => o.who))];
          const meta = { dur: this.scene.dur, w: res.w, h: res.h, note: C.motionNote(this.scene), keys: keys.keys, added: keys.added, who };
          await this.ctx.attachMotion(this.sid, file, meta);
          this.closeModal();
          this.renderTop();
          this.toast('已放進第 ' + n + ' 鏡的動作來源：送件時排在參考包第一張');
        } catch (e) { go.disabled = false; go.textContent = '重試上傳'; this.toast('上傳失敗：' + (e && e.message || e)); }
      });
      if (big) go.disabled = true;
      ft.append(go); d.append(ft);
    });
  }
}
