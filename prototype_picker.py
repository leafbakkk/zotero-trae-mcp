#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zotero × Trae 联动 · 搜索选择器原型 v2
仿 Zotero Word 引文插件：实时搜索 + 可折叠分类树 + 标签选择器 + 一键跳转 Zotero
零依赖（仅 Python 标准库），需 Zotero 桌面端处于打开状态

v2 更新：
- 修复键盘劫持：输入框聚焦时方向键/编辑键全部回归输入框，↓ 进入列表模式
- 新增搜索按钮
- 分类树可折叠（任意层级，记忆折叠状态），显示条目数
- 新增 Zotero 风格标签选择器（彩色圆点、筛选框、点选过滤当前列表）

运行: python3 prototype_picker.py
然后浏览器打开 http://localhost:8765
"""
import json
import subprocess
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = 8765
ZOTERO = "http://localhost:23119"

HTML = r"""<!doctype html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Zotero 文献选择器 · 原型 v2</title>
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
  .item { padding:10px 16px; border-bottom:1px solid #f0f0f2; cursor:pointer; }
  .item.active { background:#fdf1f2; box-shadow:inset 3px 0 0 var(--accent); }
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
  .picked { position:absolute; left:50%; bottom:54px; transform:translateX(-50%);
            background:#232329; color:#fff; border-radius:9px; padding:10px 16px; font-size:13px;
            max-width:700px; box-shadow:0 10px 28px rgba(0,0,0,.35); display:none;
            align-items:center; gap:10px; z-index:5; }
  .picked .pt { max-width:340px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .picked .btn { background:#3a3a42; border-color:#4a4a52; color:#eee; }
  .picked .btn:hover { border-color:#fff; color:#fff; }
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
  <div class="offline" id="offline">⚠ 无法连接 Zotero 本地接口 (localhost:23119) —— 请确认 Zotero 桌面端已打开</div>
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
      <div class="empty" id="empty">← 从左侧选择分类浏览<br>或在上方输入关键词，边打字边出结果</div>
      <div id="items"></div>
    </section>
  </div>
  <footer>
    <span class="hint">输入即搜索 · <kbd>↓</kbd> 进列表 · <kbd>↑</kbd><kbd>↓</kbd> 选择 · <kbd>⏎</kbd> 选定 · <kbd>esc</kbd> 清空</span>
    <span id="status"></span>
  </footer>
  <div class="picked" id="picked">
    <span>✓</span><span class="pt" id="ptitle"></span>
    <button class="btn" onclick="openZotero()">在 Zotero 中打开</button>
    <button class="btn" onclick="openPdf()">打开 PDF 阅读器</button>
    <button class="btn" onclick="closePicked()">收起</button>
  </div>
</div>
<script>
const $ = s => document.querySelector(s);
let raw = [], results = [], sel = -1, listMode = false;
let ctrl = null, tmr = null, curKey = null, curCol = null;
let allTags = [], activeTags = new Set(), tagColors = {}, colorOrder = [];
const q = $('#q');

const esc = s => (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
const year = s => { const m=(s||'').match(/\d{4}/); return m?m[0]:''; };
const creators = cs => { if(!cs||!cs.length) return '';
  const f = cs.slice(0,2).map(c=>c.name||((c.firstName||'')+' '+(c.lastName||'')).trim()).join(', ');
  return cs.length>2 ? f+' 等 '+cs.length+' 人' : f; };
const fmt = it => ({ key:it.key,
  title:it.data.title||'(无标题)',
  meta:[creators(it.data.creators), year(it.data.date), it.data.itemType].filter(Boolean).join(' · '),
  tags:(it.data.tags||[]).map(t=>t.tag).filter(Boolean) });

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
    raw = (data||[]).filter(it=>it.data && !['attachment','note'].includes(it.data.itemType)).map(fmt);
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
      <div class="t">${esc(it.title)}${it.tags.map(t=>`<span class="tag ${t.includes('🔥')?'hot':''} ${activeTags.has(t)?'on':''}">${esc(t)}</span>`).join('')}</div>
      <div class="m">${esc(it.meta)}</div>
    </div>`).join('');
  el.querySelectorAll('.item').forEach(n=>{
    n.onclick = ()=>{ sel=+n.dataset.i; paint(); pick(); };
    n.onmousemove = ()=>{ if(sel!==+n.dataset.i){ sel=+n.dataset.i; paint(); } };
  });
  scrollSel();
}
function paint(){
  $('#list').querySelectorAll('.item').forEach(n=>n.classList.toggle('active', +n.dataset.i===sel));
  scrollSel();
}
function scrollSel(){
  const n = $('#list').querySelector('.item.active');
  if(n) n.scrollIntoView({block:'nearest'});
}

/* ================= 键盘（焦点感知，修复劫持） ================= */
q.addEventListener('keydown', e=>{
  if(e.isComposing || e.keyCode===229) return;   // 中文输入法组合期间不拦截
  if(e.key==='Escape'){ e.preventDefault(); q.value=''; doSearch(); return; }
  if(e.key==='Enter'){ e.preventDefault(); doSearch(); return; }
  if(e.key==='ArrowDown' && results.length){ e.preventDefault(); listMode=true; if(sel<0) sel=0; paint(); }
  /* 其余按键（←→↑、Home/End、退格、IME）全部交给输入框原生行为 */
});
document.addEventListener('keydown', e=>{
  if(document.activeElement===q) return;         // 焦点在搜索框：只走上面的逻辑
  if(e.isComposing || e.keyCode===229) return;
  if(e.key==='Escape'){ closePicked(); return; }
  if(!results.length) return;
  if(e.key==='ArrowDown'){ e.preventDefault(); listMode=true; sel=Math.min(sel+1,results.length-1); paint(); }
  else if(e.key==='ArrowUp'){ e.preventDefault(); listMode=true; sel=Math.max(sel-1,0); paint(); }
  else if(e.key==='Enter' && sel>=0){ pick(); }
  else if(e.key.length===1 && !e.metaKey && !e.ctrlKey && !e.altKey){ q.focus(); }
});

/* ================= 选定 ================= */
function pick(){
  if(sel<0||!results[sel]) return;
  const it = results[sel]; curKey = it.key;
  $('#ptitle').textContent = it.title;
  $('#picked').style.display = 'flex';
  navigator.clipboard && navigator.clipboard.writeText(it.key).catch(()=>{});
  $('#status').textContent = '已选定 · item key 已复制: ' + it.key;
}
function closePicked(){ $('#picked').style.display='none'; }
async function openZotero(){ if(curKey) await jget('/api/open?key='+curKey); }
async function openPdf(){
  if(!curKey) return;
  try{ await jget('/api/open_pdf?key='+curKey); }
  catch(e){ alert(e.message); }
}

/* ================= 可折叠分类树 ================= */
let colRoots = [], colIndex = {}, expanded = new Set();
try{ expanded = new Set(JSON.parse(localStorage.getItem('zp_expanded')||'[]')); }catch(e){}
function saveExpanded(){ try{ localStorage.setItem('zp_expanded', JSON.stringify([...expanded])); }catch(e){} }

function buildTree(cols){
  colIndex = {};
  cols.forEach(c=> colIndex[c.key] = { key:c.key, name:c.data.name||'(未命名)',
    parent:(c.data.parentCollection||''), count:(c.meta&&c.meta.numItems)!=null?c.meta.numItems:null, children:[] });
  const roots = [];
  cols.forEach(c=>{ const n = colIndex[c.key];
    const p = n.parent && colIndex[n.parent]; if(p) p.children.push(n); else roots.push(n); });
  const sortRec = list=>{ list.sort((a,b)=>a.name.localeCompare(b.name,'zh')); list.forEach(n=>sortRec(n.children)); };
  sortRec(roots);
  return roots;
}
function renderCols(){
  const out = [];
  const walk = (n, depth)=>{
    const hasKids = n.children.length>0, open = expanded.has(n.key);
    out.push(`<div class="col-row ${curCol===n.key?'on':''}" data-key="${n.key}" style="padding-left:${8+depth*16}px">
      <span class="twist ${hasKids?'':'ghost'}" data-k="${n.key}">${hasKids?(open?'▾':'▸'):''}</span>
      <span class="cname">${esc(n.name)}</span>${n.count!=null?`<span class="ccnt">${n.count}</span>`:''}</div>`);
    if(hasKids && open) n.children.forEach(ch=>walk(ch, depth+1));
  };
  colRoots.forEach(n=>walk(n,0));
  $('#colwrap').innerHTML =
    `<div class="col-row ${curCol==='__all__'?'on':''}" data-key="__all__" style="padding-left:8px">
       <span class="twist ghost"></span><span class="cname">⌂ 我的文库（最近）</span></div>` + out.join('');
  $('#colwrap').querySelectorAll('.twist:not(.ghost)').forEach(t=>{
    t.onclick = e=>{ e.stopPropagation();
      const k = t.dataset.k; expanded.has(k) ? expanded.delete(k) : expanded.add(k);
      saveExpanded(); renderCols(); };
  });
  $('#colwrap').querySelectorAll('.col-row').forEach(n=> n.onclick = ()=>loadCol(n));
}
async function loadCols(){
  try{
    const cols = await jget('/api/collections');
    colRoots = buildTree(cols);
    renderCols();
  }catch(e){ $('#status').textContent='分类加载失败：'+e.message; }
}
async function loadCol(node){
  $('#colwrap').querySelectorAll('.col-row').forEach(n=>n.classList.remove('on'));
  node.classList.add('on'); curCol = node.dataset.key;
  q.value=''; closePicked(); $('#empty').style.display='none';
  const key = node.dataset.key;
  try{
    const data = key==='__all__' ? await jget('/api/recent') : await jget('/api/collection_items?key='+key);
    raw = (data||[]).filter(it=>it.data && !['attachment','note'].includes(it.data.itemType)).map(fmt);
    filterView();
    $('#status').textContent = node.textContent.trim() + ' · ' + raw.length + ' 条' + (activeTags.size ? '（标签过滤后 '+results.length+' 条）' : '');
  }catch(e){ $('#status').textContent='加载失败：'+e.message; }
}

/* ================= 标签选择器 ================= */
function hashColor(s){ let h=0; for(let i=0;i<s.length;i++) h=(h*31+s.charCodeAt(i))>>>0;
  return `hsl(${h%360} 62% 50%)`; }
function tagColor(name){ return tagColors[name] || hashColor(name); }
function renderTags(f){
  const fstr = (f||'').toLowerCase();
  const sorted = [...allTags].sort((a,b)=>{
    const ia = colorOrder.indexOf(a.tag), ib = colorOrder.indexOf(b.tag);
    if(ia>=0 && ib>=0) return ia-ib;
    if(ia>=0) return -1; if(ib>=0) return 1;
    return a.tag.localeCompare(b.tag,'zh');
  });
  const list = sorted.filter(t=>!fstr||t.tag.toLowerCase().includes(fstr));
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
    const data = await jget('/api/tags');
    allTags = (data||[]).map(t=>({tag:t.tag, count:(t.meta&&t.meta.numItems)||0}));
    renderTags('');
  }catch(e){ $('#taglist').innerHTML = '<span style="font-size:12px;color:#999;padding:6px">标签加载失败：'+esc(e.message)+'</span>'; }
}
async function loadTagColors(){
  try{
    const s = await jget('/api/settings');
    const arr = (s && s.tagColors && s.tagColors.value) || [];
    arr.forEach(o=>{ if(o.name){ tagColors[o.name]=o.color; colorOrder.push(o.name); } });
  }catch(e){ /* 无自定义颜色则用哈希色 */ }
}

/* ================= 自检与启动 ================= */
(async ()=>{ try{ await jget('/api/ping'); }catch(e){ $('#offline').style.display='block'; } })();
loadCols();
loadTagColors().then(loadTags);
</script>
</body>
</html>"""


def zotero_fetch(path, params=None):
    url = ZOTERO + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_all_items(path, extra=None, max_items=500):
    """分页拉取条目，避免单次 limit=100 截断（大分类会丢条目）"""
    out, start = [], 0
    while start < max_items:
        params = dict(extra or {})
        params.update({"format": "json", "limit": 100, "start": start})
        batch = zotero_fetch(path, params)
        out.extend(batch)
        if len(batch) < 100:
            break
        start += 100
    return out[:max_items]


def find_pdf_attachment(item_key):
    children = zotero_fetch(f"/api/users/0/items/{item_key}/children", {"format": "json"})
    for c in children:
        d = c.get("data", {})
        if d.get("itemType") == "attachment" and d.get("contentType") == "application/pdf":
            return c["key"]
    return None


class Handler(BaseHTTPRequestHandler):
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
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        p = parsed.path
        try:
            if p == "/":
                self._send(200, HTML, "text/html; charset=utf-8")
            elif p == "/api/ping":
                zotero_fetch("/api/users/0/items", {"limit": 1, "format": "json"})
                self._json({"ok": True})
            elif p == "/api/search":
                kw = params.get("q", "").strip()
                if not kw:
                    self._json([])
                    return
                self._json(zotero_fetch("/api/users/0/items", {
                    "q": kw, "format": "json", "limit": 30,
                    "itemType": "-attachment", "sort": "dateModified", "direction": "desc",
                }))
            elif p == "/api/recent":
                self._json(fetch_all_items("/api/users/0/items", {
                    "itemType": "-attachment", "sort": "dateModified", "direction": "desc",
                }, max_items=100))
            elif p == "/api/collections":
                self._json(zotero_fetch("/api/users/0/collections", {"format": "json", "limit": 500}))
            elif p == "/api/collection_items":
                key = params.get("key", "")
                self._json(fetch_all_items(f"/api/users/0/collections/{key}/items", {
                    "itemType": "-attachment",
                }))
            elif p == "/api/tags":
                self._json(zotero_fetch("/api/users/0/tags", {"format": "json", "limit": 500}))
            elif p == "/api/settings":
                self._json(zotero_fetch("/api/users/0/settings", {"format": "json"}))
            elif p == "/api/open":
                key = params.get("key", "")
                subprocess.run(["open", f"zotero://select/library/items/{key}"], check=False)
                self._json({"ok": True})
            elif p == "/api/open_pdf":
                key = params.get("key", "")
                att = find_pdf_attachment(key)
                if att:
                    subprocess.run(["open", f"zotero://open-pdf/library/items/{att}"], check=False)
                    self._json({"ok": True})
                else:
                    self._json({"ok": False, "error": "该条目没有 PDF 附件"}, 404)
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:  # noqa: BLE001
            self._json({"error": f"{type(e).__name__}: {e}"}, 502)


if __name__ == "__main__":
    print(f"Zotero 文献选择器原型 v2 运行中 → http://localhost:{PORT}  (Ctrl+C 退出)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
