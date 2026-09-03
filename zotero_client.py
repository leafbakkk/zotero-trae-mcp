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


# ================================================================= 写入链路（Phase 2）
# 写入走 Zotero Web API，需要 API Key；读取仍走本地 API（无需 Key）。

ZOTERO_WEB = "https://api.zotero.org"
AGENT_TAG = "#来自Agent"
HOT_TAG = "#🔥"
HOT_CITES = 1000


def _get_web_api_key():
    """从环境变量读取 Zotero Web API Key，未配置则返回 None"""
    return os.environ.get("ZOTERO_API_KEY", "").strip() or None


def _require_web_key():
    key = _get_web_api_key()
    if not key:
        raise ZoteroError(
            "写入需要 Zotero Web API Key，但未配置环境变量 ZOTERO_API_KEY。"
            "请访问 https://www.zotero.org/settings/keys 生成新 API Key，"
            "然后设置环境变量：export ZOTERO_API_KEY='你的key'"
        )
    return key


def _get_user_id():
    """从 Web API Key 反查 user ID（缓存到模块变量）"""
    key = _require_web_key()
    try:
        req = urllib.request.Request(
            f"{ZOTERO_WEB}/keys/current",
            headers={"Zotero-API-Key": key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            info = json.loads(r.read().decode("utf-8"))
        return str(info.get("userID") or info.get("user", {}).get("id") or "")
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError):
        return ""


def _web_post_items(payload, collection_key=None):
    """向 Zotero Web API POST 一个或多个条目，返回创建结果列表"""
    key = _require_web_key()
    user_id = _get_user_id() or "0"
    url = f"{ZOTERO_WEB}/users/{user_id}/items"
    params = {"format": "json"}
    if collection_key:
        params["collectionKey"] = collection_key
    url += "?" + urllib.parse.urlencode(params)

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Zotero-API-Key": key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass
        raise ZoteroError(f"Zotero Web API HTTP {e.code}: {detail or e.reason}") from e
    except urllib.error.URLError as e:
        raise ZoteroError(f"无法连接 Zotero Web API：{e.reason}") from e


def _web_upload_file(parent_key, file_path, content_type="application/pdf"):
    """上传文件作为已有条目的子附件。Zotero 文件上传需要 multipart，
    为保持零依赖，使用简单的 boundary 拼接（仅支持 PDF，够用）。"""
    import mimetypes

    key = _require_web_key()
    user_id = _get_user_id() or "0"
    fname = os.path.basename(file_path)
    ct = content_type or mimetypes.guess_type(fname)[0] or "application/pdf"

    boundary = "----zoterotrae" + str(abs(hash(str(os.times()))))
    file_size = os.path.getsize(file_path)
    file_bytes = open(file_path, "rb").read()

    # 先创建 attachment 条目（linkMode=file）
    att_payload = [{
        "itemType": "attachment",
        "linkMode": "imported_file",
        "title": fname,
        "contentType": ct,
        "filename": fname,
        "parentItem": parent_key,
        "tags": [{"tag": AGENT_TAG}],
    }]
    created = _web_post_items(att_payload)
    att_key = created.get("successful", {}).get("0", {}).get("key")
    if not att_key:
        raise ZoteroError(f"创建附件条目失败: {created}")

    # 再上传文件体
    url = f"{ZOTERO_WEB}/users/{user_id}/items/{att_key}/file"
    parts = [
        (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{fname}\"\r\n"
         f"Content-Type: {ct}\r\nContent-Length: {file_size}\r\n\r\n").encode(),
        file_bytes,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={
            "Zotero-API-Key": key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return {"ok": True, "attachment_key": att_key, "size": file_size}
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            detail = str(e)
        # 文件上传失败时清理刚创建的 attachment 条目
        _web_delete_item(att_key)
        raise ZoteroError(f"文件上传失败 HTTP {e.code}: {detail or e.reason}") from e


def _web_delete_item(key):
    """清理辅助函数：删除刚创建失败的条目"""
    try:
        key = _require_web_key()
        user_id = _get_user_id() or "0"
        req = urllib.request.Request(
            f"{ZOTERO_WEB}/users/{user_id}/items/{key}",
            method="DELETE",
            headers={"Zotero-API-Key": key},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- 查重

def _dup_check_by_doi(doi):
    """本地库查 DOI 是否存在；兜底查 Web API（处理 Web 写入后本地未同步的时序问题）"""
    if not doi:
        return None
    # 本地 API 精确匹配
    items = _get("/api/users/0/items", {"q": doi, "format": "json", "limit": 10}) or []
    for it in items:
        if doi.upper() == (it.get("data", {}).get("DOI") or "").upper():
            return it
    # Web API 兜底
    try:
        key = _get_web_api_key()
        url = f"{ZOTERO_WEB}/users/{_get_user_id() or '0'}/items?filter=doi:{urllib.parse.quote(doi)}&format=json&limit=1"
        req = urllib.request.Request(url, headers={"Zotero-API-Key": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            witems = json.loads(r.read().decode("utf-8"))
        if witems:
            return witems[0]  # Web API 返回的 item 结构略有不同，但有 key 字段
    except Exception:  # noqa: BLE001
        pass
    return None


def _dup_check_by_title(title):
    """本地库查标题是否高度相似；兜底查 Web API"""
    if not title:
        return None
    norm = re.sub(r"[\s\-_:.,!?']+", "", title.lower())[:80]
    items = _get("/api/users/0/items", {"q": title[:30], "format": "json", "limit": 30}) or []
    for it in items:
        t = (it.get("data", {}).get("title") or "")
        tn = re.sub(r"[\s\-_:.,!?']+", "", t.lower())[:80]
        if tn == norm or (norm and (norm in tn or tn in norm)):
            return it
    # Web API 兜底（title 搜索）
    try:
        key = _get_web_api_key()
        url = f"{ZOTERO_WEB}/users/{_get_user_id() or '0'}/items?format=json&q={urllib.parse.quote(title[:30])}&limit=30"
        req = urllib.request.Request(url, headers={"Zotero-API-Key": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            witems = json.loads(r.read().decode("utf-8"))
        for it in witems:
            t = (it.get("data", {}).get("title") or "")
            tn = re.sub(r"[\s\-_:.,!?']+", "", t.lower())[:80]
            if tn == norm or (norm and (norm in tn or tn in norm)):
                return it
    except Exception:  # noqa: BLE001
        pass
    return None


def _dup_check_by_arxiv(arxiv_id):
    """本地库 + Web API 兜底查重 arXiv ID"""
    if not arxiv_id:
        return None
    # 本地
    items = _get("/api/users/0/items", {"q": arxiv_id, "format": "json", "limit": 10}) or []
    for it in items:
        d = it.get("data", {})
        if arxiv_id.upper() in (d.get("url") or "").upper() or arxiv_id.upper() in (d.get("extra") or "").upper():
            return it
    # Web 兜底
    try:
        key = _get_web_api_key()
        url = f"{ZOTERO_WEB}/users/{_get_user_id() or '0'}/items?format=json&q={urllib.parse.quote(arxiv_id)}&limit=10"
        req = urllib.request.Request(url, headers={"Zotero-API-Key": key, "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as r:
            witems = json.loads(r.read().decode("utf-8"))
        for it in witems:
            d = it.get("data", {})
            if arxiv_id.upper() in (d.get("url") or "").upper() or arxiv_id.upper() in (d.get("extra") or "").upper():
                return it
    except Exception:  # noqa: BLE001
        pass
    return None


# ---------------------------------------------------------------- 元数据抓取（公开 API，无需 Key）

def _fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "zotero-trae-mcp/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _fetch_doi(doi):
    """Crossref API → DOI 元数据。优先用 /works/{doi} 端点（精确匹配最快），
    失败时降级到 search + filter=doi"""
    q = urllib.parse.quote(doi, safe="")  # 完整编码，包括斜杠
    url = f"https://api.crossref.org/works/{q}"
    try:
        j = _fetch_json(url)
        msg = j.get("message", {})
        return _crossref_to_zotero(msg), msg.get("is-referenced-by-count", 0) or 0
    except Exception as primary_err:  # noqa: BLE001
        # 降级：search + filter
        url2 = f"https://api.crossref.org/works?filter=doi:{q}&rows=3"
        try:
            j = _fetch_json(url2)
        except Exception as secondary_err:  # noqa: BLE001
            raise ZoteroError(f"Crossref DOI 查询失败 {doi}: {primary_err} / {secondary_err}") from secondary_err
        items = (j.get("message", {}).get("items") or [])
        if not items:
            raise ZoteroError(f"Crossref 未找到 DOI={doi}")
        for it in items:
            if (it.get("DOI") or "").upper() == doi.upper():
                return _crossref_to_zotero(it), it.get("is-referenced-by-count", 0) or 0
        return _crossref_to_zotero(items[0]), items[0].get("is-referenced-by-count", 0) or 0


def _fetch_arxiv(arxiv_id):
    """arXiv API → 元数据 + 自动下载 PDF"""
    url = f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(arxiv_id)}"
    try:
        data = urllib.request.urlopen(url, timeout=15).read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        raise ZoteroError(f"arXiv 查询失败 {arxiv_id}: {e}") from e
    # 只取第一个 <entry> 块（feed 根元素也有 title，会误匹配）
    entry_m = re.search(r"<entry>(.*?)</entry>", data, re.DOTALL)
    entry_block = entry_m.group(1) if entry_m else data

    def _tag(tag, text):
        m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", text, re.DOTALL)
        return m.group(1).strip() if m else ""
    def _author_names(text):
        return [m.group(1).strip() for m in re.finditer(r"<name>(.*?)</name>", text)]

    title = _tag("title", entry_block).replace("\n", " ")
    summary = _tag("summary", entry_block).replace("\n", " ")
    published = _tag("published", entry_block)[:10]
    doi_m = re.search(r"<arxiv:doi[^>]*>(.*?)</arxiv:doi>", entry_block)
    doi = doi_m.group(1).strip() if doi_m else ""
    # PDF 下载链接
    pdf_url = ""
    for m in re.finditer(r'<link[^>]+title="pdf"[^>]*href="([^"]+)"', entry_block):
        pdf_url = m.group(1)
        break
    item_type = "journalArticle" if doi else "preprint"
    creators = []
    for name in _author_names(entry_block):
        parts = name.split()
        if len(parts) >= 2:
            creators.append({"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]})
        else:
            creators.append({"creatorType": "author", "lastName": name})
    out = {
        "itemType": item_type,
        "title": title,
        "creators": creators,
        "date": published,
        "abstractNote": summary,
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "extra": f"arXiv:{arxiv_id}",
    }
    if doi:
        out["DOI"] = doi
        try:
            crossref, _ = _fetch_doi(doi)
            # Crossref 覆盖 arXiv 字段（更完整）
            out.update({k: v for k, v in crossref.items() if v})
            out["extra"] = f"arXiv:{arxiv_id}"
        except ZoteroError:
            pass  # DOI 查不到就用 arXiv 自己的数据
    return out, 0, pdf_url


def _fetch_isbn(isbn):
    """Open Library API → ISBN 元数据"""
    url = f"https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data"
    try:
        j = _fetch_json(url)
    except Exception as e:  # noqa: BLE001
        raise ZoteroError(f"Open Library 查询失败 ISBN:{isbn}: {e}") from e
    book = (j.get(f"ISBN:{isbn}") or {}) if j else {}
    if not book:
        raise ZoteroError(f"Open Library 未找到 ISBN:{isbn}")
    title = book.get("title", "")
    # 可能含副标题
    if book.get("subtitle"):
        title += ": " + book["subtitle"]
    creators = []
    for a in book.get("authors", []):
        name = a.get("name", "")
        parts = name.split()
        if len(parts) >= 2:
            creators.append({"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]})
        elif len(parts) == 1:
            creators.append({"creatorType": "author", "lastName": parts[0]})
    publish_date = book.get("publish_date", "")[:10]
    publishers = book.get("publishers", [])
    pub_name = publishers[0].get("name", "") if publishers else ""
    return {
        "itemType": "book",
        "title": title,
        "creators": creators,
        "date": publish_date,
        "publisher": pub_name,
        "ISBN": isbn,
        "url": book.get("url", ""),
    }, 0


def _fetch_by_title(title):
    """Crossref 标题搜索 → 取最匹配的第一条"""
    q = urllib.parse.quote(title)
    url = f"https://api.crossref.org/works?query.title={q}&rows=5"
    try:
        j = _fetch_json(url)
    except Exception as e:  # noqa: BLE001
        raise ZoteroError(f"Crossref 标题搜索失败: {e}") from e
    items = (j.get("message", {}).get("items") or [])
    if not items:
        raise ZoteroError(f"Crossref 未找到标题匹配：{title}")
    best = items[0]
    if len(items) > 1:
        # 标题归一化精确匹配优先
        norm_q = re.sub(r"[\s\-_:.,!?']+", "", title.lower())[:80]
        for it in items:
            t = (it.get("title") or [""])[0]
            if re.sub(r"[\s\-_:.,!?']+", "", t.lower())[:80] == norm_q:
                best = it
                break
    return _crossref_to_zotero(best), best.get("is-referenced-by-count", 0) or 0


def _crossref_to_zotero(msg):
    """Crossref message → Zotero itemTemplate 字段"""
    out = {"itemType": "journalArticle"}
    title = msg.get("title") or msg.get("subtitle")
    out["title"] = title[0] if isinstance(title, list) else (title or "")
    out["DOI"] = msg.get("DOI", "")
    out["url"] = msg.get("URL", "") or out.get("DOI") and f"https://doi.org/{out['DOI']}"
    # 作者 —— 必须带 creatorType（Zotero Web API 硬性要求）
    creators = []
    for a in msg.get("author", []):
        creators.append({
            "creatorType": "author",
            "firstName": a.get("given", ""),
            "lastName": a.get("family", ""),
        })
    for a in msg.get("editor", []):
        creators.append({
            "creatorType": "editor",
            "firstName": a.get("given", ""),
            "lastName": a.get("family", ""),
        })
    out["creators"] = creators
    # 日期
    published = msg.get("published-print") or msg.get("published-online") or msg.get("created") or {}
    dp = published.get("date-parts", [[None, None, None]])[0]
    parts = [str(x).zfill(2) for x in dp if x is not None]
    out["date"] = "-".join(parts) if parts else ""
    # 出版物
    container = (msg.get("container-title") or [""])[0]
    out["publicationTitle"] = container
    out["publisher"] = msg.get("publisher", "")
    # 摘要（有时在 abstract 字段带 JATS 标签）
    abs_raw = msg.get("abstract", "")
    if abs_raw:
        out["abstractNote"] = re.sub(r"<[^>]+>", "", abs_raw).strip()[:2000]
    # 类型映射
    crossref_type = msg.get("type", "")
    type_map = {
        "journal-article": "journalArticle",
        "book": "book",
        "book-chapter": "bookSection",
        "conference-paper": "conferencePaper",
        "proceedings-article": "conferencePaper",
        "dissertation": "thesis",
        "report": "report",
        "dataset": "dataset",
        "posted-content": "preprint",
    }
    out["itemType"] = type_map.get(crossref_type, "journalArticle")
    return out


# ---------------------------------------------------------------- 组装 + 写入

def _apply_tags(payload, extra_tags=None, auto_tag=True, is_hot=False):
    """给条目加 tags：必加 #来自Agent，可选 #🔥（被引>1000）"""
    all_tags = list(payload.get("tags") or [])
    existing = {t.get("tag") if isinstance(t, dict) else t for t in all_tags}
    if auto_tag and AGENT_TAG not in existing:
        all_tags.append({"tag": AGENT_TAG})
    if auto_tag and is_hot and HOT_TAG not in existing:
        all_tags.append({"tag": HOT_TAG})
    for t in (extra_tags or []):
        if t and (t not in existing and {"tag": t} not in existing):
            all_tags.append({"tag": t})
    payload["tags"] = all_tags
    return payload


def _resolve_collection_key(collection_path):
    """分类路径 → Web API 接受的 collectionKey（本地/远程 key 相同）"""
    if not collection_path:
        return None
    key, _ = resolve_collection(collection_path)
    return key


def _standardize_payload(payload):
    """将外部提供的条目元数据归一化为 Zotero itemTemplate 格式"""
    out = dict(payload)
    # 确保 creators 是 [{creatorType, firstName, lastName}] 或 [{creatorType, name}]
    creators = out.get("creators") or []
    normalized = []
    for c in creators:
        if isinstance(c, str):
            # 纯字符串：尝试拆分
            parts = c.split()
            if len(parts) >= 2:
                normalized.append({"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]})
            else:
                normalized.append({"creatorType": "author", "lastName": c})
        elif isinstance(c, dict):
            if c.get("name"):
                normalized.append({"creatorType": "author", "name": c["name"]})
            else:
                normalized.append({
                    "creatorType": c.get("creatorType") or "author",
                    "firstName": c.get("firstName", ""),
                    "lastName": c.get("lastName", ""),
                })
    out["creators"] = normalized
    # 确保 tags 格式
    raw_tags = out.get("tags") or []
    out["tags"] = [{"tag": t} if isinstance(t, str) else t for t in raw_tags]
    return out


# ---------------------------------------------------------------- 对外入口函数

def add_item(raw_payload, collection=None, auto_tag=True, extra_tags=None):
    """通用写入：AI 直接提供元数据，去重后写入 Zotero。

    raw_payload 支持 Zotero itemTemplate 字段（itemType, title, creators, DOI, date, ...）。
    """
    payload = _standardize_payload(raw_payload)
    if not payload.get("title"):
        raise ZoteroError("条目必须有 title")

    # 查重
    dup = None
    if payload.get("DOI"):
        dup = _dup_check_by_doi(payload["DOI"])
    if not dup and payload.get("title"):
        dup = _dup_check_by_title(payload["title"])
    if dup:
        return {"added": False, "duplicate": True, "existing_key": dup["key"],
                "message": f"本地库已存在该条目（key={dup['key']}），跳过写入"}

    # 从 Crossref 拿被引数（如果有 DOI）
    cites = 0
    if payload.get("DOI"):
        try:
            _, cites = _fetch_doi(payload["DOI"])
        except ZoteroError:
            cites = 0

    payload = _apply_tags(payload, extra_tags=extra_tags, auto_tag=auto_tag, is_hot=cites >= HOT_CITES)
    collection_key = _resolve_collection_key(collection) if collection else None

    result = _web_post_items([payload], collection_key=collection_key)
    created = result.get("successful", {}).get("0", {})
    new_key = created.get("key")
    return {
        "added": True,
        "key": new_key,
        "title": payload.get("title"),
        "citations": cites,
        "is_hot": cites >= HOT_CITES,
        "collection": collection,
        "web_key_configured": bool(_get_web_api_key()),
    }


def add_paper_by_doi(doi, collection=None, auto_tag=True):
    """按 DOI 从 Crossref 抓取元数据，查重后写入"""
    doi = doi.strip().lstrip("doi:")
    dup = _dup_check_by_doi(doi)
    if dup:
        return {"added": False, "duplicate": True, "existing_key": dup["key"],
                "message": f"本地库已存在 DOI={doi} 的条目（key={dup['key']}），跳过写入"}
    payload, cites = _fetch_doi(doi)
    return add_item(payload, collection=collection, auto_tag=auto_tag)


def add_paper_by_arxiv(arxiv_id, collection=None, auto_tag=True):
    """按 arXiv ID 抓取元数据（优先走 DOI→Crossref，兜底 arXiv 自身），查重后写入"""
    arxiv_id = arxiv_id.strip()
    dup = _dup_check_by_arxiv(arxiv_id)
    if dup:
        return {"added": False, "duplicate": True, "existing_key": dup["key"],
                "message": f"本地库已存在 arXiv:{arxiv_id} 的条目，跳过写入"}
    payload, cites, _pdf_url = _fetch_arxiv(arxiv_id)
    return add_item(payload, collection=collection, auto_tag=auto_tag)


def add_book_by_isbn(isbn, collection=None, auto_tag=True):
    """按 ISBN 从 Open Library 抓取元数据，查重后写入"""
    isbn = re.sub(r"[\s-]", "", isbn).strip()
    dup = None
    items = _get("/api/users/0/items", {"q": isbn, "format": "json", "limit": 10}) or []
    for it in items:
        if (it.get("data", {}).get("ISBN") or "").replace(" ", "").replace("-", "") == isbn:
            dup = it
            break
    if dup:
        return {"added": False, "duplicate": True, "existing_key": dup["key"],
                "message": f"本地库已存在 ISBN={isbn} 的条目，跳过写入"}
    payload, _ = _fetch_isbn(isbn)
    return add_item(payload, collection=collection, auto_tag=auto_tag)


def add_paper_by_title(title, collection=None, auto_tag=True):
    """按标题搜索 Crossref 自动匹配最相关条目，查重后写入"""
    title = title.strip()
    if not title:
        raise ZoteroError("标题不能为空")
    dup = _dup_check_by_title(title)
    if dup:
        return {"added": False, "duplicate": True, "existing_key": dup["key"],
                "message": f"本地库已存在标题「{title}」的条目（key={dup['key']}），跳过写入"}
    payload, cites = _fetch_by_title(title)
    return add_item(payload, collection=collection, auto_tag=auto_tag)


def attach_pdf_to_item(pdf_path, item_key):
    """将本地 PDF 文件上传为已有条目的附件"""
    if not os.path.isfile(pdf_path):
        raise ZoteroError(f"PDF 文件不存在：{pdf_path}")
    item = get_item_raw(item_key)
    if not item:
        raise ZoteroError(f"条目 {item_key} 不存在")
    return _web_upload_file(item_key, pdf_path)
