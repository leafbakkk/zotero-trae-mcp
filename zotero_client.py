#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zotero 本地 API 客户端
- 读链路全部走 Zotero 桌面端本地接口 (http://localhost:23119)，只读
- PDF 文本从本地存储 (~/Zotero/storage) 提取，支持页码范围
- Better BibTeX JSON-RPC 用于 citekey ↔ item key 解析
- 写链路（Phase 2）将走 Zotero Web API，本模块暂不涉及
"""
import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from urllib.parse import unquote, urlparse

ZOTERO_LOCAL = os.environ.get("ZOTERO_LOCAL_API", "http://localhost:23119").rstrip("/")
STORAGE_DIR = os.environ.get("ZOTERO_STORAGE_DIR", os.path.expanduser("~/Zotero/storage"))

# Zotero item key：8 位、不含 I/O/0/1 的字母数字
KEY_RE = re.compile(r"^[23456789ABCDEFGHJKLMNPQRSTUVWXYZ]{8}$")


class ZoteroError(Exception):
    """带用户可读信息的 Zotero 访问异常"""


# ---------------------------------------------------------------- 基础请求

def _get(path, params=None, timeout=30):
    url = ZOTERO_LOCAL + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise ZoteroError(f"Zotero API HTTP {e.code}: {path}") from e
    except urllib.error.URLError as e:
        raise ZoteroError(
            f"无法连接 Zotero 本地接口 ({ZOTERO_LOCAL})：{e.reason}。请确认 Zotero 桌面端已打开。"
        ) from e
    except json.JSONDecodeError as e:
        raise ZoteroError(f"Zotero API 返回了非 JSON 响应: {path}") from e


def _bbt_rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode("utf-8")
    req = urllib.request.Request(
        ZOTERO_LOCAL + "/better-bibtex/json-rpc",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise ZoteroError(f"无法连接 Better BibTeX JSON-RPC：{e.reason}") from e
    if "error" in resp:
        raise ZoteroError(f"Better BibTeX RPC 错误: {resp['error'].get('message')}")
    return resp.get("result")


def ping():
    """连通性自检，返回库基本信息"""
    probe = _get("/api/users/0/items", {"limit": 1, "format": "json"})
    lib = (probe[0] or {}).get("library", {}) if isinstance(probe, list) and probe else {}
    bbt = True
    try:
        _bbt_rpc("item.search", ["zotero-trae-mcp-healthcheck-nonexistent"])
    except ZoteroError:
        bbt = False
    return {
        "local_api": "ok",
        "library_name": lib.get("name", ""),
        "library_id": lib.get("id"),
        "better_bibtex": "ok" if bbt else "不可用（citekey 解析将受限）",
        "storage_dir": STORAGE_DIR,
        "storage_dir_exists": os.path.isdir(STORAGE_DIR),
    }


# ---------------------------------------------------------------- 通用抓取

def fetch_all(path, extra=None, max_items=1000):
    """分页抓取，避免单次 limit=100 截断"""
    out, start = [], 0
    while start < max_items:
        params = dict(extra or {})
        params.update({"format": "json", "limit": 100, "start": start})
        batch = _get(path, params)
        if not batch:
            break
        out.extend(batch)
        if len(batch) < 100:
            break
        start += 100
    return out[:max_items]


# ---------------------------------------------------------------- 格式化

def _year(datestr):
    m = re.search(r"\d{4}", datestr or "")
    return m.group(0) if m else ""


def _creators(creators, cap=3):
    names = []
    for c in creators or []:
        names.append(c.get("name") or f"{c.get('firstName', '')} {c.get('lastName', '')}".strip())
    names = [n for n in names if n]
    if len(names) > cap:
        return ", ".join(names[:cap]) + f" 等 {len(names)} 人"
    return ", ".join(names)


def _is_regular(it):
    return it.get("data", {}).get("itemType") not in ("attachment", "note")


def format_item(it, brief=True):
    d = it.get("data", {})
    out = {
        "key": it.get("key"),
        "title": d.get("title") or d.get("shortTitle") or "(无标题)",
        "creators": _creators(d.get("creators")),
        "year": _year(d.get("date")),
        "itemType": d.get("itemType"),
        "tags": [t.get("tag") for t in d.get("tags", []) if t.get("tag")],
    }
    if not brief:
        out.update({
            "abstract": (d.get("abstractNote") or "")[:1000],
            "DOI": d.get("DOI") or "",
            "url": d.get("url") or "",
            "date": d.get("date") or "",
            "publicationTitle": d.get("publicationTitle") or d.get("proceedingsTitle") or d.get("bookTitle") or "",
            "citekey": "",
            "attachments": [],
            "numChildren": it.get("meta", {}).get("numChildren"),
        })
        pdf = find_pdf_attachment(out["key"])
        atts = []
        for c in get_children(out["key"]):
            cd = c.get("data", {})
            if cd.get("itemType") != "attachment":
                continue
            atts.append({
                "key": c["key"],
                "contentType": cd.get("contentType"),
                "title": cd.get("title"),
                "is_pdf": cd.get("contentType") == "application/pdf",
            })
        out["attachments"] = atts
        out["citekey"] = citekey_of(out["key"], d)
    return out


# ---------------------------------------------------------------- 条目检索

def search_library(query, limit=20):
    items = _get("/api/users/0/items", {
        "q": query, "format": "json", "limit": min(max(limit, 1), 100),
        "itemType": "-attachment", "sort": "dateModified", "direction": "desc",
    }) or []
    return [format_item(it) for it in items if _is_regular(it)][:limit]


def recent_items(limit=100):
    items = fetch_all("/api/users/0/items", extra={
        "itemType": "-attachment", "sort": "dateModified", "direction": "desc",
    }, max_items=limit)
    return [format_item(it) for it in items if _is_regular(it)]


def get_item_raw(key):
    return _get(f"/api/users/0/items/{key}", {"format": "json"})


def get_children(key):
    return fetch_all(f"/api/users/0/items/{key}/children", max_items=200)


def citekey_of(item_key, data=None):
    """key → citekey。BBT 无直接反向方法，用标题/DOI 搜索后按 URI 匹配，尽力而为"""
    if data is None:
        raw = get_item_raw(item_key)
        if not raw:
            return ""
        data = raw.get("data", {})
    needle = " ".join((data.get("title") or "").split()[:5]) or (data.get("DOI") or "")
    if not needle:
        return ""
    try:
        for it in _bbt_rpc("item.search", [needle]) or []:
            uri = str(it.get("id", ""))
            if uri.rstrip("/").endswith(item_key):
                return it.get("citation-key") or it.get("citekey") or ""
    except ZoteroError:
        pass
    return ""


def _has_cjk(s):
    return any("\u4e00" <= ch <= "\u9fff" for ch in s or "")


def in_text_citation(data):
    """生成文中注（作者-年份制）：中文文献 →（王弘睿 等，2023）；英文 → (Simons et al., 2026)"""
    creators = data.get("creators") or []
    year = _year(data.get("date")) or "n.d."

    def family(c):
        if c.get("name"):
            return c["name"]
        return (c.get("lastName") or c.get("firstName") or "").strip()

    if not creators or not family(creators[0]):
        name = "佚名"
    else:
        name = family(creators[0])
    cjk = _has_cjk(name)
    if len(creators) <= 1:
        return f"（{name}，{year}）" if cjk else f"({name}, {year})"
    if cjk:
        return f"（{name} 等，{year}）"
    if len(creators) == 2:
        return f"({name} & {family(creators[1])}, {year})"
    return f"({name} et al., {year})"


def resolve_key(key_or_citekey):
    """统一入口：item key / citekey / DOI → 原始条目 JSON"""
    s = (key_or_citekey or "").strip()
    if not s:
        raise ZoteroError("条目标识不能为空")
    if KEY_RE.match(s):
        raw = get_item_raw(s)
        if raw:
            return raw
    # citekey 精确匹配（BBT）
    try:
        for it in _bbt_rpc("item.search", [s]) or []:
            ck = it.get("citation-key") or it.get("citekey")
            if ck and ck == s:
                key = str(it.get("id", "")).rstrip("/").rsplit("/", 1)[-1]
                raw = get_item_raw(key)
                if raw:
                    return raw
    except ZoteroError:
        pass
    # DOI 兜底
    items = _get("/api/users/0/items", {"q": s, "format": "json", "limit": 10}) or []
    for it in items:
        if s.upper() == (it.get("data", {}).get("DOI") or "").upper():
            return it
    raise ZoteroError(
        f"找不到条目「{key_or_citekey}」。已尝试 item key、Better BibTeX citekey、DOI 三种解析。"
    )


# ---------------------------------------------------------------- 分类

def _collection_nodes():
    cols = fetch_all("/api/users/0/collections", max_items=2000)
    nodes = {}
    for c in cols:
        nodes[c["key"]] = {
            "key": c["key"],
            "name": c.get("data", {}).get("name") or "(未命名)",
            "numItems": (c.get("meta") or {}).get("numItems"),
            "parent": c.get("data", {}).get("parentCollection") or "",
        }
    return nodes


def _full_path(nodes, key):
    parts = []
    k = key
    while k and k in nodes:
        parts.append(nodes[k]["name"])
        k = nodes[k]["parent"]
    return "/".join(reversed(parts))


def list_collections():
    """嵌套树，每层带完整路径（可直接传给 read_collection）"""
    nodes = _collection_nodes()
    children = {k: [] for k in nodes}
    roots = []
    for k, n in nodes.items():
        p = n["parent"]
        if p and p in nodes:
            children[p].append(k)
        else:
            roots.append(k)
    for v in children.values():
        v.sort(key=lambda k: nodes[k]["name"])
    roots.sort(key=lambda k: nodes[k]["name"])

    def build(key, parent_path):
        n = nodes[key]
        full = f"{parent_path}/{n['name']}" if parent_path else n["name"]
        out = {"name": n["name"], "path": full, "numItems": n["numItems"]}
        if children[key]:
            out["children"] = [build(k, full) for k in children[key]]
        return out

    return [build(k, "") for k in roots]


def resolve_collection(path):
    """按完整路径（'A/B'）、唯一名称或路径后缀匹配分类，返回 (key, full_path)"""
    nodes = _collection_nodes()
    target = (path or "").strip().strip("/")
    if not target:
        raise ZoteroError("分类路径不能为空")
    paths = {k: _full_path(nodes, k) for k in nodes}
    # 1) 完整路径
    for k, fp in paths.items():
        if fp == target:
            return k, fp
    # 2) 唯一同名分类
    by_name = [k for k, n in nodes.items() if n["name"] == target]
    if len(by_name) == 1:
        return by_name[0], paths[by_name[0]]
    if len(by_name) > 1:
        samples = "; ".join(sorted(paths[k] for k in by_name)[:3])
        raise ZoteroError(f"分类名「{target}」有 {len(by_name)} 个同名分类，请用完整路径。例如：{samples}")
    # 3) 路径后缀匹配
    suffix = [k for k, fp in paths.items() if fp.endswith("/" + target)]
    if len(suffix) == 1:
        return suffix[0], paths[suffix[0]]
    if len(suffix) > 1:
        samples = "; ".join(sorted(paths[k] for k in suffix)[:3])
        raise ZoteroError(f"分类路径「{target}」匹配到 {len(suffix)} 个分类，请写完整。例如：{samples}")
    raise ZoteroError(f"找不到分类「{target}」。可先调用 list_collections 查看全部分类路径。")


def collection_items(path, max_items=300):
    key, full = resolve_collection(path)
    items = fetch_all(f"/api/users/0/collections/{key}/items", extra={"itemType": "-attachment"}, max_items=max_items)
    return {"collection": full, "numItems": len(items),
            "items": [format_item(it) for it in items if _is_regular(it)]}


# ---------------------------------------------------------------- 标签

def all_tags(limit=2000):
    tags, start = [], 0
    while start < limit:
        batch = _get("/api/users/0/tags", {"format": "json", "limit": 100, "start": start}) or []
        tags.extend(batch)
        if len(batch) < 100:
            break
        start += 100
    return [{"tag": t.get("tag", ""), "count": (t.get("meta") or {}).get("numItems") or 0}
            for t in tags if t.get("tag")]


def tag_colors():
    """Zotero 标签选择器里配过颜色的标签 → 颜色；本地接口可能不提供，返回空则前端兜底"""
    try:
        s = _get("/api/users/0/settings") or {}
        arr = (s.get("tagColors") or {}).get("value") or []
        return {o.get("name"): o.get("color") for o in arr if o.get("name") and o.get("color")}
    except ZoteroError:
        return {}


# ---------------------------------------------------------------- PDF

def find_pdf_attachment(item_key):
    """返回 (attachment_key, path_spec, file_href) 或 None。优先第一个 PDF 附件

    注意：本地 API 的 data.path 经常为空，但 links.enclosure.href 带 file:// 绝对路径，
    后者是定位 PDF 文件最可靠的方式。
    """
    for c in get_children(item_key):
        d = c.get("data", {})
        if d.get("itemType") == "attachment" and d.get("contentType") == "application/pdf":
            href = (c.get("links", {}).get("enclosure") or {}).get("href") or ""
            return c["key"], d.get("path") or "", href
    return None


def _pdf_file_path(att_key, spec, href):
    """file:// 链接 → 绝对路径；storage:xxx.pdf → STORAGE_DIR/<attKey>/xxx.pdf；链接附件支持绝对路径"""
    if href and href.startswith("file://"):
        return unquote(urlparse(href).path)
    if spec.startswith("storage:"):
        return os.path.join(STORAGE_DIR, att_key, spec[len("storage:"):])
    if spec.startswith("/"):
        return spec
    return None


def read_pdf(key_or_citekey, pages="", max_chars=60000):
    """定位条目的 PDF 附件并提取文本。pages 支持 '3'、'1-5'、'1-3,7'"""
    item = resolve_key(key_or_citekey)
    key = item["key"]
    att = find_pdf_attachment(key)
    if not att:
        raise ZoteroError(f"条目 {key}「{(item.get('data') or {}).get('title', '')}」没有 PDF 附件。"
                          f"可用 get_item 查看全部附件。")
    att_key, spec, href = att
    fpath = _pdf_file_path(att_key, spec, href)
    if not fpath or not os.path.exists(fpath):
        raise ZoteroError(
            f"PDF 文件不存在：{fpath or spec}。如 Zotero 数据目录非默认位置，"
            f"请设置环境变量 ZOTERO_STORAGE_DIR 指向 storage 目录。"
        )
    import pymupdf  # 中文文献文本提取质量显著优于 pypdf
    doc = pymupdf.open(fpath)
    total = doc.page_count
    idx = list(range(total))
    if pages:
        idx = []
        for part in pages.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-", 1)
                idx.extend(i for i in range(int(a) - 1, min(int(b), total)) if i >= 0)
            elif int(part) - 1 < total:
                idx.append(int(part) - 1)
    texts, chars, pages_read = [], 0, []
    for i in idx:
        t = (doc[i].get_text() or "").strip()
        texts.append(f"\n\n=== 第 {i + 1} 页 ===\n{t}")
        chars += len(t)
        pages_read.append(i + 1)
        if chars >= max_chars:
            break
    doc.close()
    text = "".join(texts)
    truncated = len(text) > max_chars
    return {
        "key": key,
        "title": (item.get("data") or {}).get("title", ""),
        "citekey": citekey_of(key),
        "pdf": os.path.basename(fpath),
        "total_pages": total,
        "pages_read": pages_read,
        "truncated": truncated,
        "text": text[:max_chars],
    }


# ---------------------------------------------------------------- 跳转

def open_in_zotero(key_or_citekey):
    key = resolve_key(key_or_citekey)["key"]
    subprocess.run(["open", f"zotero://select/library/items/{key}"], check=False)
    return {"ok": True, "key": key, "action": "已在 Zotero 界面中定位并选中该条目"}


def open_pdf_in_zotero(key_or_citekey):
    item = resolve_key(key_or_citekey)
    att = find_pdf_attachment(item["key"])
    if not att:
        raise ZoteroError(f"条目 {item['key']} 没有 PDF 附件，无法在阅读器中打开。")
    subprocess.run(["open", f"zotero://open-pdf/library/items/{att[0]}"], check=False)
    return {"ok": True, "key": item["key"], "attachment_key": att[0],
            "action": "已在 Zotero 内置阅读器中打开该 PDF"}
