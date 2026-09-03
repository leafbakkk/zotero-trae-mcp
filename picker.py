#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
可视化文献选择器（内嵌 HTTP 服务）
- 复用原型 v2 的 UI：实时搜索 + 可折叠分类树 + 标签选择器
- 选择回流：点「选定并返回 Trae」POST /api/select，pick_item_result 工具拿到结果返回给 agent
- 批量引用：勾选多条 → 复制 citekey / 文中注（POST /api/cite，服务端生成）
- 打开方式：由 agent 用 Trae 内置网页预览组件展示（pick_item 不再自动调用系统浏览器）
- 端口 8765 起自动向后寻找空闲端口，仅绑定 127.0.0.1
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import zotero_client as zc

BASE_PORT = 8765
PORT_RANGE = 12

HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Zotero 文献选择器</title>
<style>
  :root { --accent:#cc2936; --border:#dcdce1; }
  * { box-sizing:border-box; margin:0; padding:0; }
  html,body { height:100%; }
  body { font-family:-apple-system,"PingFang SC",system-ui,sans-serif;
         background:#e9e9ee; height:100vh; display:flex; align-items:center; justify-content:center; }
  .win { position:relative; width:800px; height:580px; background:#fff; border-radius:10px;
         box-shadow:0 14px 44px rgba(0,0,0,.20); display:flex; flex-direction:column; overflow:hidden; }
  header { padding:12px 16px 10px; border-bottom:1px solid var(--border); display:flex; gap:8px; }
  .searchbox { flex:1; display:flex; align-items:center; gap:8px; border:1.5px solid var(--accent);
               border-radius:7px; padding:6px 12px; }
  .searchbox:focus-within { box-shadow:0 0 0 3px rgba(204,41,54,.12); }
  .searchbox input { flex:1; border:none; outline:none; font-size:14px; background:transparent; color:#222; }
  .searchbox .icon { color:var(--accent); font-size:14px; }
  .btn { border:1px solid var(--border); background:#fff; border-radius:6px; padding:5px 12px;
         font-size:12px; cursor:pointer; color:#444; white-space:nowrap; }
  .btn:hover { border-color:var(--accent); color:var(--accent); }
  .btn.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  .btn.primary:hover { opacity:.88; color:#fff; }
  .btn.dark { background:#3a3a42; border-color:#4a4a52; color:#eee; }
  .btn.dark:hover { border-color:#fff; color:#fff; }
  .main { flex:1; display:flex; min-height:0; }
  aside { width:236px; border-right:1px solid var(--border); display:flex; flex-direction:column;
          background:#fafafb; min-height:0; }
  .col-title { padding:8px 14px 4px; font-size:11px; color:#999; letter-spacing:1px; flex:none; }
  #colwrap { flex:1; overflow-y:auto; padding-bottom:6px; }
  .col-row { display:flex; align-items:center; padding:4px 10px 4px 8px; cursor:pointer; font-size:13px; color:#333; }
  .col-row:hover { background:#f0f0f3; }
  .col-row.on { background:var(--accent); color:#fff; }
  .twist { width:16px; height:16px; line-height:16px; text-align:center; font-size:10px;
           color:#888; flex:none; cursor:pointer; border-radius:3px; }
  .twist:hover { background:rgba(0,0,0,.08); color:#333; }
  .col-row.on .twist { color:#fff; }
  .twist.ghost { visibility:hidden; cursor:default; }
  .cname { flex:1; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .ccnt { font-size:11px; color:#aaa; margin-left:6px; flex:none; }
  .col-row.on .ccnt { color:#ffd6d6; }
  #tagpanel { flex:none; height:208px; border-top:1px solid var(--border); display:flex;
              flex-direction:column; }
  #tagfilter { margin:5px 12px 2px; padding:5px 9px; border:1px solid var(--border); border-radius:6px;
               font-size:12px; outline:none; width:calc(100% - 24px); }
  #tagfilter:focus { border-color:var(--accent); }
  #taglist { flex:1; overflow-y:auto; padding:6px 10px 10px; display:flex; flex-wrap:wrap;
             gap:6px; align-content:flex-start; }
  .tagchip { display:inline-flex; align-items:center; gap:5px; font-size:12px; padding:3px 9px;
             border:1px solid var(--border); border-radius:20px; cursor:pointer; background:#fff; color:#333; }
  .tagchip:hover { border-color:var(--accent); }
  .tagchip.on { background:var(--accent); color:#fff; border-color:var(--accent); }
  .tagchip .dot { width:9px; height:9px; border-radius:50%; display:inline-block; flex:none; }
  .tagchip .cnt { font-size:10px; color:#aaa; }
  .tagchip.on .cnt { color:#ffd6d6; }
  section { flex:1; overflow-y:auto; min-width:0; }
  .item { display:flex; gap:9px; padding:10px 16px; border-bottom:1px solid #f0f0f2; cursor:pointer; }
  .item.active { background:#fdf1f2; box-shadow:inset 3px 0 0 var(--accent); }
  .item .ck { margin-top:4px; flex:none; accent-color:var(--accent); cursor:pointer; }
  .item .body { flex:1; min-width:0; }
  .t { font-size:14px; font-weight:600; color:#222; line-height:1.4; }
  .m { font-size:12px; color:#777; margin-top:3px; }
  .tag { font-size:11px; background:#f3eaea; color:#8a3a3a; border-radius:4px; padding:1px 6px;
         margin-left:5px; font-weight:400; vertical-align:1px; }
  .tag.hot { background:var(--accent); color:#fff; }
  .tag.on { outline:1.5px solid var(--accent); }
  footer { border-top:1px solid var(--border); padding:8px 14px; font-size:12px; color:#888;
           display:flex; justify-content:space-between; align-items:center; background:#fafafb; }
  .hint kbd { background:#ececef; border:1px solid #ccc; border-radius:3px; padding:1px 5px;
              font-size:11px; font-family:inherit; }
  .empty { color:#999; text-align:center; margin-top:90px; font-size:14px; padding:0 30px; line-height:1.8; }
  .picked, #batchbar { position:absolute; left:50%; transform:translateX(-50%);
            background:#232329; color:#fff; border-radius:9px; padding:10px 16px; font-size:13px;
            max-width:700px; box-shadow:0 10px 28px rgba(0,0,0,.35); display:none;
            align-items:center; gap:10px; z-index:5; }
  .picked { bottom:54px; flex-direction:column; gap:7px; }
  .prow { display:flex; align-items:center; gap:8px; }
  #batchbar { bottom:104px; padding:8px 14px; font-size:12px; white-space:nowrap; }
  #batchbar b { color:#ffd6d6; }
  .picked .pt, #batchbar .bt { max-width:340px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .picked .btn, #batchbar .btn { background:#3a3a42; border-color:#4a4a52; color:#eee; }
  .picked .btn:hover, #batchbar .btn:hover { border-color:#fff; color:#fff; }
  .picked .done { color:#7ee787; font-weight:600; }
  .offline { background:#fff3cd; color:#8a6d1a; font-size:12px; padding:6px 16px; display:none; }
</style>
</head>
<body>
<div class="win">
  <header>
    <div class="searchbox">
      <span class="icon">🔍</span>
      <input id="q" placeholder="搜索标题 / 作者 / 年份 / 标签……（实时，可随时修改关键词）" autofocus>
    </div>
    <button class="btn primary" id="sbtn">搜索</button>
  </header>
  <div class="offline" id="offline">⚠ 无法连接 Zotero 本地接口 —— 请确认 Zotero 桌面端已打开</div>
  <div class="main">
    <aside>
      <div class="col-title">分类</div>
      <div id="colwrap"></div>
      <div id="tagpanel">
        <div class="col-title">标签选择器（点选过滤当前列表）</div>
        <input id="tagfilter" placeholder="筛选标签…">
        <div id="taglist"></div>
      </div>
    </aside>
    <section id="list">
      <div class="empty" id="empty">← 从左侧选择分类浏览<br>或在上方输入关键词，边打字边出结果<br>勾选多条可批量复制引用</div>
      <div id="items"></div>
    </section>
  </div>
  <footer>
    <span class="hint">输入即搜索 · <kbd>↓</kbd> 进列表 · <kbd>↑</kbd><kbd>↓</kbd> 选择 · <kbd>⏎</kbd> 选定 · <kbd>esc</kbd> 清空</span>
    <span id="status"></span>
  </footer>
  <div id="batchbar">
    已选 <b id="bcount">0</b> 项
    <button class="btn" onclick="copyBatch('citekey')">复制 CiteKey</button>
    <button class="btn" onclick="copyBatch('in_text')">复制文中注</button>
    <button class="btn" onclick="clearBatch()">清空</button>
  </div>
  <div class="picked" id="picked">
    <div class="prow">
      <span>✓</span><span class="pt" id="ptitle"></span>
      <button class="btn primary" onclick="confirmPick()">选定并返回 Trae</button>
      <button class="btn" onclick="closePicked()">收起</button>
    </div>
    <div class="prow">
      <button class="btn" onclick="copyOne('citekey')">复制 CiteKey</button>
      <button class="btn" onclick="copyOne('in_text')">复制文中注</button>
      <button class="btn" onclick="openZotero()">在 Zotero 中打开</button>
      <button class="btn" onclick="openPdf()">打开 PDF 阅读器</button>
    </div>
  </div>
</div>
<script>
const $ = s => document.querySelector(s);
let raw = [], results = [], sel = -1, listMode = false;
let ctrl = null, tmr = null, curKey = null, curItem = null, curCol = null;
let colTree = [], expanded = new Set(), tagColorMap = {};
let allTags = [], activeTags = new Set();
const selStore = new Map();   // 批量选择：key -> item（跨搜索/分类累积）
const q = $('#q');

const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
try{ expanded = new Set(JSON.parse(localStorage.getItem('zp_expanded')||'[]')); }catch(e){}
function saveExpanded(){ try{ localStorage.setItem('zp_expanded', JSON.stringify([...expanded])); }catch(e){} }

async function jget(url, opt){ const r = await fetch(url, opt);
  const j = await r.json(); if(!r.ok) throw new Error(j.error||r.status); return j; }

/* ================= 搜索 ================= */
q.addEventListener('input', ()=>{ clearTimeout(tmr); tmr=setTimeout(doSearch, 180); });
$('#sbtn').onclick = ()=>doSearch();
async function doSearch(){
  const kw = q.value.trim();
  listMode = false; closePicked();
  if(!kw){ raw=[]; filterView(); $('#status').textContent=''; return; }
  if(ctrl) ctrl.abort(); ctrl = new AbortController();
  $('#empty').style.display='none';
  try{
    const data = await jget('/api/search?q='+encodeURIComponent(kw), {signal:ctrl.signal});
    if(q.value.trim() !== kw) return;   // 请求返回前关键词已改，丢弃过期结果
    raw = data.items || [];
    filterView();
    $('#status').textContent = raw.length + ' 条结果' + (activeTags.size ? '（标签过滤后 '+results.length+' 条）' : '');
  }catch(e){ if(e.name!=='AbortError') $('#status').textContent = '搜索失败：'+e.message; }
}

/* ================= 标签过滤 ================= */
function filterView(){
  results = activeTags.size
    ? raw.filter(it=>{ const ts=new Set(it.tags); for(const t of activeTags) if(!ts.has(t)) return false; return true; })
    : raw;
  sel = results.length ? 0 : -1;
  render();
}
function render(){
  const el = $('#items');
  if(!results.length){
    el.innerHTML = '';
    if(raw.length && activeTags.size){
      el.innerHTML = '<div class="empty">当前列表中没有同时带有所选标签的条目</div>';
    } else if(!raw.length && q.value.trim()){
      el.innerHTML = '<div class="empty">没有找到「'+esc(q.value.trim())+'」相关的文献<br>换个关键词试试？</div>';
    } else if(!raw.length){
      $('#empty').style.display = '';
    }
    return;
  }
  $('#empty').style.display = 'none';
  el.innerHTML = results.map((it,i)=>`
    <div class="item ${i===sel?'active':''}" data-i="${i}">
      <input type="checkbox" class="ck" data-k="${esc(it.key)}" ${selStore.has(it.key)?'checked':''}>
      <div class="body">
        <div class="t">${esc(it.title)}${it.tags.map(t=>`<span class="tag ${t.includes('🔥')?'hot':''} ${activeTags.has(t)?'on':''}">${esc(t)}</span>`).join('')}</div>
        <div class="m">${[it.creators, it.year, it.itemType].filter(Boolean).map(esc).join(' · ')}</div>
      </div>
    </div>`).join('');
  el.querySelectorAll('.item').forEach(n=>{
    const it = results[+n.dataset.i];
    n.onclick = ()=>{ sel=+n.dataset.i; paint(); pick(); };
    n.onmousemove = ()=>{ if(sel!==+n.dataset.i){ sel=+n.dataset.i; paint(); } };
    n.querySelector('.ck').onclick = e=>e.stopPropagation();
    n.querySelector('.ck').onchange = e=>{
      e.target.checked ? selStore.set(it.key, it) : selStore.delete(it.key);
      renderBatchbar();
    };
  });
  scrollSel();
}
function paint(){
  $('#items').querySelectorAll('.item').forEach(n=>n.classList.toggle('active', +n.dataset.i===sel));
  scrollSel();
}
function scrollSel(){
  const n = $('#items').querySelector('.item.active');
  if(n) n.scrollIntoView({block:'nearest'});
}

/* ================= 键盘（焦点感知） ================= */
q.addEventListener('keydown', e=>{
  if(e.isComposing || e.keyCode===229) return;   // 中文输入法组合期间不拦截
  if(e.key==='Escape'){ e.preventDefault(); q.value=''; doSearch(); return; }
  if(e.key==='Enter'){ e.preventDefault(); doSearch(); return; }
  if(e.key==='ArrowDown' && results.length){ e.preventDefault(); listMode=true; if(sel<0) sel=0; paint(); }
  /* 其余按键（←→↑、Home/End、退格、IME）全部交给输入框原生行为 */
});
document.addEventListener('keydown', e=>{
  if(document.activeElement===q) return;
  if(e.isComposing || e.keyCode===229) return;
  if(e.key==='Escape'){ closePicked(); return; }
  if(!results.length) return;
  if(e.key==='ArrowDown'){ e.preventDefault(); listMode=true; sel=Math.min(sel+1,results.length-1); paint(); }
  else if(e.key==='ArrowUp'){ e.preventDefault(); listMode=true; sel=Math.max(sel-1,0); paint(); }
  else if(e.key==='Enter' && sel>=0){ pick(); }
  else if(e.key.length===1 && !e.metaKey && !e.ctrlKey && !e.altKey){ q.focus(); }
});

/* ================= 单选回流 Trae ================= */
function pick(){
  if(sel<0||!results[sel]) return;
  const it = results[sel]; curKey = it.key; curItem = it;
  $('#ptitle').textContent = it.title;
  $('#picked').style.display = 'flex';
  $('#status').textContent = '已选定: ' + it.title;
}
function closePicked(){ $('#picked').style.display='none'; }
async function confirmPick(){
  if(!curItem) return;
  try{
    await fetch('/api/select', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(curItem)});
    $('#picked').innerHTML = '<span class="done">✓ 已选定并返回 Trae，可关闭此窗口</span>';
  }catch(e){ $('#status').textContent = '回流失败：'+e.message; }
}
async function openZotero(){ if(curKey) await jget('/api/open?key='+curKey); }
async function openPdf(){
  if(!curKey) return;
  try{ await jget('/api/open_pdf?key='+curKey); }
  catch(e){ alert(e.message); }
}

/* ================= 批量复制 ================= */
function renderBatchbar(){
  const n = selStore.size;
  $('#batchbar').style.display = n ? 'flex' : 'none';
  $('#bcount').textContent = n;
}
function clearBatch(){
  selStore.clear(); renderBatchbar(); render();
  $('#status').textContent = '已清空批量选择';
}
function fallbackCopy(text){
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.style.cssText = 'position:fixed;top:-999px;left:-999px;opacity:0';
  document.body.appendChild(ta);
  ta.focus(); ta.select();
  let ok = false;
  try{ ok = document.execCommand('copy'); }catch(e){}
  document.body.removeChild(ta);
  return ok;
}
async function copyText(text){
  /* Trae 预览等 webview 常拒绝 navigator.clipboard 写权限，降级 execCommand */
  try{ await navigator.clipboard.writeText(text); return true; }
  catch(e){ return fallbackCopy(text); }
}
async function copyBatch(fmt){
  const keys = [...selStore.keys()];
  if(!keys.length) return;
  try{
    const r = await fetch('/api/cite', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({keys, format: fmt})});
    const j = await r.json();
    if(!r.ok) throw new Error(j.error||r.status);
    if(!await copyText(j.text)) throw new Error('浏览器拒绝了剪贴板写入');
    $('#status').textContent = '✓ 已复制 '+keys.length+' 条'+(fmt==='citekey'?' CiteKey':'文中注')+'，可直接粘贴到 Trae 对话框';
  }catch(e){ $('#status').textContent = '复制失败：'+e.message; }
}
async function copyOne(fmt){
  if(!curKey) return;
  try{
    const r = await fetch('/api/cite', {method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify({keys:[curKey], format: fmt})});
    const j = await r.json();
    if(!r.ok) throw new Error(j.error||r.status);
    if(!await copyText(j.text)) throw new Error('浏览器拒绝了剪贴板写入');
    $('#status').textContent = '✓ 已复制'+(fmt==='citekey'?' CiteKey':'文中注')+'：'+j.text;
  }catch(e){ $('#status').textContent = '复制失败：'+e.message; }
}

/* ================= 可折叠分类树（按路径记忆折叠状态） ================= */
function renderCols(){
  const out = [];
  const walk = (n, depth)=>{
    const kids = n.children||[], hasKids = kids.length>0, open = expanded.has(n.path);
    out.push(`<div class="col-row ${curCol===n.path?'on':''}" data-path="${esc(n.path)}" style="padding-left:${8+depth*16}px">
      <span class="twist ${hasKids?'':'ghost'}" data-p="${esc(n.path)}">${hasKids?(open?'▾':'▸'):''}</span>
      <span class="cname">${esc(n.name)}</span>${n.numItems!=null?`<span class="ccnt">${n.numItems}</span>`:''}</div>`);
    if(hasKids && open) kids.forEach(k=>walk(k, depth+1));
  };
  colTree.forEach(n=>walk(n,0));
  $('#colwrap').innerHTML =
    `<div class="col-row ${curCol==='__all__'?'on':''}" data-path="__all__" style="padding-left:8px">
       <span class="twist ghost"></span><span class="cname">⌂ 我的文库（最近）</span></div>` + out.join('');
  $('#colwrap').querySelectorAll('.twist:not(.ghost)').forEach(t=>{
    t.onclick = e=>{ e.stopPropagation();
      const p = t.dataset.p; expanded.has(p) ? expanded.delete(p) : expanded.add(p);
      saveExpanded(); renderCols(); };
  });
  $('#colwrap').querySelectorAll('.col-row').forEach(n=> n.onclick = ()=>loadCol(n.dataset.path, n));
}
async function loadCols(){
  try{
    colTree = await jget('/api/collections');
    renderCols();
  }catch(e){ $('#status').textContent='分类加载失败：'+e.message; }
}
async function loadCol(path, node){
  $('#colwrap').querySelectorAll('.col-row').forEach(n=>n.classList.remove('on'));
  node.classList.add('on'); curCol = path;
  q.value=''; closePicked(); $('#empty').style.display='none';
  try{
    const data = path==='__all__' ? await jget('/api/recent') : await jget('/api/collection_items?path='+encodeURIComponent(path));
    raw = data.items || [];
    filterView();
    $('#status').textContent = (data.collection||'我的文库（最近）') + ' · ' + raw.length + ' 条' + (activeTags.size ? '（标签过滤后 '+results.length+' 条）' : '');
  }catch(e){ $('#status').textContent='加载失败：'+e.message; }
}

/* ================= 标签选择器 ================= */
function hashColor(s){ let h=0; for(let i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))>>>0;
  return `hsl(${h%360} 62% 50%)`; }
function tagColor(name){ return tagColorMap[name] || hashColor(name); }
function renderTags(f){
  const fstr = (f||'').toLowerCase();
  const list = allTags.filter(t=>!fstr||t.tag.toLowerCase().includes(fstr));
  $('#taglist').innerHTML = list.length ? list.map(t=>`
    <span class="tagchip ${activeTags.has(t.tag)?'on':''}" data-tag="${esc(t.tag)}">
      <span class="dot" style="background:${tagColor(t.tag)}"></span>${esc(t.tag)}
      ${t.count?`<span class="cnt">${t.count}</span>`:''}</span>`).join('')
    : '<span style="font-size:12px;color:#999;padding:6px">无匹配标签</span>';
  $('#taglist').querySelectorAll('.tagchip').forEach(n=>{
    n.onclick = ()=>{
      const t = n.dataset.tag;
      activeTags.has(t) ? activeTags.delete(t) : activeTags.add(t);
      renderTags($('#tagfilter').value); filterView();
      $('#status').textContent = activeTags.size ? '标签过滤：'+[...activeTags].join(' + ')+'（'+results.length+' 条）' : '';
    };
  });
}
$('#tagfilter').addEventListener('input', ()=>renderTags($('#tagfilter').value));
async function loadTags(){
  try{
    allTags = await jget('/api/tags');
    try{ tagColorMap = await jget('/api/tagcolors') || {}; }catch(e){ tagColorMap = {}; }
    renderTags('');
  }catch(e){ $('#taglist').innerHTML = '<span style="font-size:12px;color:#999;padding:6px">标签加载失败：'+esc(e.message)+'</span>'; }
}

/* ================= 自检与启动 ================= */
(async ()=>{ try{ await jget('/api/ping'); }catch(e){ $('#offline').style.display='block'; } })();
loadCols(); loadTags();
/* 支持 pick_item 传入的初始关键词：/?q=xxx */
const p0 = new URLSearchParams(location.search);
if(p0.get('q')){ q.value = p0.get('q'); doSearch(); }
</script>
</body>
</html>"""


class PickerHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    def do_GET(self):
        parsed = urlparse(self.path)
        params = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        p = parsed.path
        try:
            if p == "/":
                self._send(200, HTML, "text/html; charset=utf-8")
            elif p == "/api/ping":
                zc.ping()
                self._json({"ok": True})
            elif p == "/api/search":
                kw = params.get("q", "").strip()
                items = zc.search_library(kw, limit=30) if kw else []
                self._json({"items": items})
            elif p == "/api/recent":
                self._json({"collection": "我的文库（最近）", "items": zc.recent_items(limit=100)})
            elif p == "/api/collections":
                self._json(zc.list_collections())
            elif p == "/api/collection_items":
                path = params.get("path", "")
                if not path or path == "__all__":
                    self._json({"collection": "我的文库（最近）", "items": zc.recent_items(limit=100)})
                else:
                    self._json(zc.collection_items(path, max_items=300))
            elif p == "/api/tags":
                self._json(zc.all_tags())
            elif p == "/api/tagcolors":
                self._json(zc.tag_colors())
            elif p == "/api/open":
                self._json(zc.open_in_zotero(params.get("key", "")))
            elif p == "/api/open_pdf":
                self._json(zc.open_pdf_in_zotero(params.get("key", "")))
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 502)

    def do_POST(self):
        if self.path == "/api/select":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                picker.record_selection(payload)
                self._json({"ok": True})
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 400)
        elif self.path == "/api/cite":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                keys = (payload.get("keys") or [])[:50]
                fmt = payload.get("format", "citekey")
                out = []
                for k in keys:
                    raw = zc.get_item_raw(k)
                    if not raw:
                        continue
                    d = raw.get("data", {})
                    if fmt == "in_text":
                        out.append(zc.in_text_citation(d))
                    else:
                        out.append(zc.citekey_of(k, d) or k)
                sep = "；" if fmt == "in_text" else "\n"
                self._json({"text": sep.join(out), "count": len(out)})
            except Exception as e:  # noqa: BLE001
                self._json({"error": f"{type(e).__name__}: {e}"}, 502)
        else:
            self._json({"error": "not found"}, 404)


class PickerServer:
    """嵌入 MCP 进程的选择器 HTTP 服务 + 选择回流状态"""

    def __init__(self):
        self.httpd = None
        self.port = None
        self._lock = threading.Lock()
        self._selection = None
        self._seq = 0  # 每次选定 +1，供 pick_item / pick_item_result 两段式对齐

    # ---- HTTP 服务 ----
    def ensure_started(self):
        if self.httpd:
            return self.port
        last_err = None
        for port in range(BASE_PORT, BASE_PORT + PORT_RANGE):
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", port), PickerHandler)
                self.port = port
                break
            except OSError as e:
                last_err = e
        if not self.httpd:
            raise RuntimeError(f"无法启动选择器服务（{BASE_PORT}-{BASE_PORT + PORT_RANGE - 1} 端口均被占用）：{last_err}")
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    # ---- 选择回流 ----
    def current_seq(self):
        with self._lock:
            return self._seq

    def record_selection(self, payload):
        with self._lock:
            self._selection = payload
            self._seq += 1

    def wait_for_selection(self, since_seq, timeout_seconds):
        """阻塞直到出现 seq > since_seq 的选定，或超时（返回 None）"""
        import time
        deadline = time.time() + max(min(timeout_seconds, 600), 1)
        while time.time() < deadline:
            with self._lock:
                if self._seq > since_seq:
                    return self._selection
            time.sleep(0.4)
        return None


picker = PickerServer()
