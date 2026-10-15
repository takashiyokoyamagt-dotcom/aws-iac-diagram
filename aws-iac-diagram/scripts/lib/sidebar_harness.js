// Sidebar-AWS4.js を draw.io 本体なしで実行し、パレットのエントリを JSON で標準出力に書き出す。
// build_icon_catalog.py から呼ばれる。使い方: node sidebar_harness.js <Sidebar-AWS4.js>
'use strict';
const fs = require('fs');
const vm = require('vm');

const src = fs.readFileSync(process.argv[2], 'utf8');
const entries = [];
let palette = null;
let library = null;

function Sidebar() {}
Sidebar.prototype.setCurrentSearchEntryLibrary = function (id, lib) { library = lib || null; };
Sidebar.prototype.getTagsForStencil = function (gn, name, dt) {
  return ((dt || '') + ' ' + (name || '')).split(' ').filter(Boolean);
};
Sidebar.prototype.createVertexTemplateEntry = function (style, w, h, value, title, a, b, tags) {
  return { kind: 'vertex', style, w, h, value, title, tags };
};
Sidebar.prototype.createEdgeTemplateEntry = function (style, w, h, value, title, a, tags) {
  return { kind: 'edge', style, w, h, value, title, tags };
};
Sidebar.prototype.addPaletteFunctions = function (id, title, expanded, fns) {
  palette = { id, title };
  for (const e of fns) entries.push(Object.assign({ palette: id, paletteTitle: title, library }, e));
};

const ctx = { Sidebar, mxConstants: { STYLE_SHAPE: 'shape' } };
vm.createContext(ctx);
vm.runInContext(src, ctx, { filename: 'Sidebar-AWS4.js' });

const sb = new Sidebar();
sb.addAWS4Palette();
sb.addAWS4RetiredPalette();
process.stdout.write(JSON.stringify(entries));
