#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zotero × Trae MCP Server
Phase 1：读链路 + 可视化选择器 + Zotero 跳转（11 个工具）
- 读：search_library / get_item / list_collections / read_collection / read_pdf
- 选：pick_item（两段式·第一段）+ pick_item_result（第二段）——
  选择器在 Trae 内置网页预览组件中打开，不调用系统浏览器；支持勾选批量复制 citekey/文中注
- 跳：open_in_zotero / open_pdf_in_zotero（zotero:// URL Scheme）
- 检：health_check
Phase 2：写入链路（6 个工具）
- add_paper_by_doi / add_paper_by_arxiv / add_book_by_isbn / add_paper_by_title
- add_item（AI 直接给元数据）+ attach_pdf_to_item（PDF 附件导入）
- 自动查重（本地库已有则跳过）、自动打 #来自Agent（可关）、被引>1000 打 #🔥
- 写入走 Zotero Web API，需要 ZOTERO_API_KEY 环境变量
- 严禁修改或删除已有条目；仅新增

运行方式（stdio）：python server.py
"""
import json
import subprocess
import urllib.parse

from mcp.server.fastmcp import FastMCP

import picker as picker_mod
import zotero_client as zc
from zotero_client import ZoteroError

mcp = FastMCP(
    "zotero",
    instructions=(
        "Zotero 文献库访问工具集（读+写）。"
        "用户是社会学研究生，文献库 1000+ 条，装有 Better BibTeX。"
        "常用路径：用户想交互式找文献时调用 pick_item 弹出可视化搜索框；"
        "需要全文时先 get_item 或 pick_item 拿到 key，再 read_pdf 读 PDF；"
        "用户提到 Zotero 分类/folder 路径时用 read_collection（如 '硕士论文/CSS中的…'）。"
        "条目标识支持 item key（8 位）、Better BibTeX citekey、DOI 三种形式。"
        "写入链路：add_paper_by_doi / add_paper_by_arxiv / add_book_by_isbn / add_paper_by_title 自动联网抓取元数据；"
        "add_item 接收 AI 直接生成的 Zotero itemTemplate 元数据（用户在对话里口述/给 PDF 等）；"
        "attach_pdf_to_item 将本地 PDF 作为附件导入已有条目。"
        "所有 add_* 工具支持 collection 参数指定分类路径（如 '硕士论文'），"
        "自动查重（本地库已有则跳过）、默认打 #来自Agent 标签（auto_tag=false 可关）、被引>1000 自动打 #🔥。"
        "写入需要 ZOTERO_API_KEY 环境变量（Zotero Web API），未配置时工具会返回明确的配置指引。"
        "严禁修改或删除 Zotero 中已有条目；仅新增。"
    ),
)


def _out(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)


def _err(e: Exception):
    return _out({"error": str(e)})


@mcp.tool()
def health_check() -> str:
    """检查 Zotero 连接状态：本地 API、Better BibTeX、PDF 存储目录。开始文献相关工作前建议先调用。"""
    try:
        info = zc.ping()
        return _out({"status": "ok", **info})
    except ZoteroError as e:
        return _err(e)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
def search_library(query: str, limit: int = 20) -> str:
    """全库搜索文献（标题/作者/年份/标签等）。返回条目列表：key、标题、作者、年份、类型、标签。

    找到目标后可用返回的 key 调用 get_item / read_pdf / open_pdf_in_zotero。
    """
    try:
        items = zc.search_library(query, limit=limit)
        return _out({"query": query, "count": len(items), "items": items})
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def get_item(key_or_citekey: str) -> str:
    """获取单篇文献的完整元数据：摘要、DOI、URL、出版物、Better BibTeX citekey、附件清单（是否有 PDF）等。

    key_or_citekey 支持 item key（8 位，如 HU85EYTC）、citekey（如 simonsLarge2026）、DOI。
    """
    try:
        raw = zc.resolve_key(key_or_citekey)
        return _out(zc.format_item(raw, brief=False))
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def list_collections() -> str:
    """列出 Zotero 全部分类（collection）的嵌套树，每个分类带完整路径和条目数。

    返回的 path 可直接传给 read_collection。
    """
    try:
        return _out({"collections": zc.list_collections()})
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def read_collection(path: str, limit: int = 50) -> str:
    """按路径浏览某个 Zotero 分类下的文献。

    path 支持完整路径（如 '硕士论文/CSS中的…'）或唯一分类名；也可以只写路径后缀（如 '理论'）。
    返回该分类下的条目列表（同 search_library 的格式）。
    """
    try:
        data = zc.collection_items(path, max_items=max(limit, 1) * 2)
        items = data["items"][: max(limit, 1)]
        return _out({"collection": data["collection"], "count": len(items), "items": items})
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def read_pdf(key_or_citekey: str, pages: str = "", max_chars: int = 60000) -> str:
    """提取文献 PDF 的全文文本（从本地 Zotero 存储读取）。

    pages 可选，格式如 '3'、'1-5'、'1-3,7'；不传则读全文。
    返回 total_pages、pages_read、text。长文献超过 max_chars 会截断（truncated=true），可用 pages 续读。
    """
    try:
        data = zc.read_pdf(key_or_citekey, pages=pages, max_chars=max(max_chars, 2000))
        return _out(data)
    except ZoteroError as e:
        return _err(e)


def _try_trigger_ext(query: str) -> bool:
    """best-effort 唤起 Zotero Picker 扩展面板（127.0.0.1:8766/open），扩展未运行时静默失败"""
    try:
        import urllib.request
        url = "http://127.0.0.1:8766/open" + (f"?q={urllib.parse.quote(query)}" if query else "")
        req = urllib.request.Request(url, method="POST")
        urllib.request.urlopen(req, timeout=1)
        return True
    except Exception:  # noqa: BLE001
        return False


@mcp.tool()
def pick_item(query: str = "", open_in_browser: bool = False) -> str:
    """打开可视化文献选择器（两段式·第一段）：立即返回 picker_url，不阻塞、不自动打开系统浏览器。

    优先尝试唤起 Zotero Picker 扩展的原生面板（若已安装并运行）；
    否则请用网页预览组件（OpenPreview）打开 picker_url 展示给用户，
    然后调用 pick_item_result(since_seq=返回值中的 since_seq) 等待用户选定。
    用户可在选择器中实时搜索、按分类/标签筛选、勾选多条批量复制 citekey/文中注。
    """
    try:
        port = picker_mod.picker.ensure_started()
        since_seq = picker_mod.picker.current_seq()
        url = f"http://localhost:{port}/" + (f"?q={urllib.parse.quote(query)}" if query else "")
        if open_in_browser:
            subprocess.run(["open", url], check=False)
        ext_ok = _try_trigger_ext(query)
        if ext_ok:
            instruction = (
                "已通过 Zotero Picker 扩展在 Trae 内自动打开选择器面板，"
                "直接调用 pick_item_result(since_seq=%d) 等待用户在面板上点「选定并返回 Trae」；"
                "若用户说没看到面板，再用网页预览组件（OpenPreview）打开 picker_url。" % since_seq
            )
        else:
            instruction = (
                "请立即用网页预览组件（OpenPreview）打开 picker_url 展示给用户，"
                "然后调用 pick_item_result(since_seq=%d) 等待用户在页面上点「选定并返回 Trae」。" % since_seq
            )
        return _out({
            "status": "waiting",
            "picker_url": url,
            "since_seq": since_seq,
            "ext_panel": "opened" if ext_ok else "not_running",
            "instruction": instruction,
        })
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
def pick_item_result(since_seq: int = -1, timeout_seconds: int = 300) -> str:
    """获取可视化选择器的选定结果（两段式·第二段），与 pick_item 配对使用。

    since_seq 传 pick_item 返回的 since_seq（默认自动取当前最新值）。
    阻塞等待用户在页面上点「选定并返回 Trae」；超时返回 selected=false。
    注意：本工具会阻塞至多 timeout_seconds 秒（上限 600）。
    """
    try:
        picker_mod.picker.ensure_started()
        if since_seq < 0:
            since_seq = picker_mod.picker.current_seq()
        data = picker_mod.picker.wait_for_selection(since_seq, timeout_seconds)
        if not data:
            return _out({"selected": False,
                         "message": f"用户未在 {timeout_seconds} 秒内点「选定并返回 Trae」。"
                                    "可重新调用 pick_item 并再次打开预览，或直接询问用户。"})
        full = None
        if data.get("key"):
            raw = zc.get_item_raw(data["key"])
            if raw:
                full = zc.format_item(raw, brief=False)
        return _out({"selected": True, "picked": data, "item": full})
    except ZoteroError as e:
        return _err(e)
    except Exception as e:  # noqa: BLE001
        return _err(e)


@mcp.tool()
def open_in_zotero(key_or_citekey: str) -> str:
    """在 Zotero 桌面端界面中定位并选中该文献（唤起/切换到 Zotero 主窗口）。"""
    try:
        return _out(zc.open_in_zotero(key_or_citekey))
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def open_pdf_in_zotero(key_or_citekey: str) -> str:
    """在 Zotero 内置 PDF 阅读器中直接打开该文献的 PDF（zotero://open-pdf 跳转）。"""
    try:
        return _out(zc.open_pdf_in_zotero(key_or_citekey))
    except ZoteroError as e:
        return _err(e)


# ---------------------------------------------------------------- 写入链路

@mcp.tool()
def add_paper_by_doi(
    doi: str,
    collection: str = "",
    auto_tag: bool = True,
    extra_tags: str = "",
    rating: int = -1,
    notes: str = "",
    extra: str = "",
) -> str:
    """按 DOI 从 Crossref 自动抓取元数据，查重后写入 Zotero。

    collection 指定分类路径（如 '硕士论文/CSS中的…'），不填则写入根目录。
    auto_tag=True 时自动打 #来自Agent 和（被引>1000 时）#🔥。
    extra_tags 逗号分隔，额外添加的标签。
    rating 0-5 评级（-1 表示不设置）。
    notes 简记/备注文本，会写入条目的 abstractNote 字段。
    extra Zotero extra 字段（键值对 JSON 或纯文本）。
    """
    try:
        return _out(zc.add_paper_by_doi(
            doi, collection=collection or None, auto_tag=auto_tag,
            extra_tags=_parse_tags(extra_tags), rating=rating, notes=notes, extra=extra,
        ))
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def add_paper_by_arxiv(
    arxiv_id: str,
    collection: str = "",
    auto_tag: bool = True,
    extra_tags: str = "",
    rating: int = -1,
    notes: str = "",
    extra: str = "",
) -> str:
    """按 arXiv ID 抓取元数据（优先 DOI→Crossref，兜底 arXiv 自身），查重后写入 Zotero。

    arxiv_id 可写 '2301.12345' 或 'arXiv:2301.12345'。
    其他参数同 add_paper_by_doi。
    """
    try:
        return _out(zc.add_paper_by_arxiv(
            arxiv_id, collection=collection or None, auto_tag=auto_tag,
            extra_tags=_parse_tags(extra_tags), rating=rating, notes=notes, extra=extra,
        ))
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def add_book_by_isbn(
    isbn: str,
    collection: str = "",
    auto_tag: bool = True,
    extra_tags: str = "",
    rating: int = -1,
    notes: str = "",
    extra: str = "",
) -> str:
    """按 ISBN 从 Open Library 自动抓取元数据，查重后写入 Zotero。

    isbn 可带空格/短横线（如 '978-7-100-12345-6'），会自动归一化。
    其他参数同 add_paper_by_doi。
    """
    try:
        return _out(zc.add_book_by_isbn(
            isbn, collection=collection or None, auto_tag=auto_tag,
            extra_tags=_parse_tags(extra_tags), rating=rating, notes=notes, extra=extra,
        ))
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def add_paper_by_title(
    title: str,
    collection: str = "",
    auto_tag: bool = True,
    extra_tags: str = "",
    rating: int = -1,
    notes: str = "",
    extra: str = "",
) -> str:
    """按论文标题在 Crossref 自动搜索匹配最相关条目，查重后写入 Zotero。

    标题越长匹配越准；返回结果带 citations 字段显示被引数。
    其他参数同 add_paper_by_doi。
    """
    try:
        return _out(zc.add_paper_by_title(
            title, collection=collection or None, auto_tag=auto_tag,
            extra_tags=_parse_tags(extra_tags), rating=rating, notes=notes, extra=extra,
        ))
    except ZoteroError as e:
        return _err(e)


def _parse_tags(s: str):
    """逗号分隔标签字符串 → list[str]"""
    if not s:
        return []
    return [t.strip() for t in s.split(",") if t.strip()]


@mcp.tool()
def add_item(
    title: str,
    item_type: str = "journalArticle",
    creators: str = "",
    doi: str = "",
    date: str = "",
    collection: str = "",
    auto_tag: bool = True,
    extra_tags: str = "",
    rating: int = -1,
    notes: str = "",
    extra: str = "",
    **kwargs,
) -> str:
    """通用写入：AI 直接提供条目元数据，查重后写入 Zotero。

    适用于用户在对话里口述文献信息（如"把这个 PDF 作为论文条目加入…"）、
    或 add_* 抓取失败后 AI 自行组装条目的场景。

    creators 格式："姓 名, 姓 名" 或 "Last, First & Last, First"（英文）。
    item_type 可选值：journalArticle / book / bookSection / conferencePaper / preprint /
    thesis / report / dataset / letter / note / artwork 等。
    extra_tags 逗号分隔，额外添加的标签。
    rating 0-5 评级（-1 表示不设置）。
    notes 简记/备注文本，会写入条目的 abstractNote 字段。
    extra Zotero extra 字段（键值对 JSON 或纯文本）。
    kwargs 支持 publicationTitle / volume / issue / pages / publisher / url / language / ISBN 等。
    """
    import re as _re
    # 解析 creators 字符串 → Zotero 格式
    creator_list = []
    if creators:
        for seg in _re.split(r"\s*&\s*|\s*;\s*", creators):
            seg = seg.strip()
            if not seg:
                continue
            parts = seg.split()
            if "," in seg:
                last, first = seg.split(",", 1)
                creator_list.append({"creatorType": "author", "firstName": first.strip(), "lastName": last.strip()})
            elif len(parts) >= 2:
                creator_list.append({"creatorType": "author", "firstName": " ".join(parts[:-1]), "lastName": parts[-1]})
            else:
                creator_list.append({"creatorType": "author", "lastName": seg})

    payload = {
        "itemType": item_type,
        "title": title,
        "creators": creator_list,
    }
    if doi:
        payload["DOI"] = doi
    if date:
        payload["date"] = date
    # kwargs 兜底
    for k, v in kwargs.items():
        if v is not None and v != "" and k in {
            "publicationTitle", "url", "publisher", "ISBN",
            "edition", "volume", "issue", "pages", "series",
            "seriesNumber", "place", "numPages", "language",
        }:
            payload[k] = v

    try:
        return _out(zc.add_item(
            payload, collection=collection or None, auto_tag=auto_tag,
            extra_tags=_parse_tags(extra_tags), rating=rating, notes=notes, extra=extra,
        ))
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def attach_pdf_to_item(pdf_path: str, item_key: str) -> str:
    """将本地 PDF 文件上传为已有条目的子附件（imported_file 模式）。

    item_key 传 8 位 item key（可先 get_item 拿到）。
    """
    try:
        return _out(zc.attach_pdf_to_item(pdf_path, item_key))
    except ZoteroError as e:
        return _err(e)


@mcp.tool()
def update_item_meta(
    item_key: str,
    add_tags: str = "",
    remove_tags: str = "",
    rating: int = -1,
    notes: str = "",
    extra: str = "",
    notes_mode: str = "append",
) -> str:
    """更新已有条目的元数据（标签/评级/简记/extra），核心元数据不可改。

    item_key 传 8 位 item key（可先 get_item 拿到）。
    add_tags 逗号分隔，要追加的标签（已存在的会跳过）。
    remove_tags 逗号分隔，要移除的标签。
    rating 0-5 新评级（-1 表示不改）。
    notes 简记/备注文本。
    notes_mode: 'append' 追加到现有备注末尾 / 'replace' 替换整个备注。
    extra Zotero extra 字段新值（传入则整体替换）。

    安全边界：仅改标签、评级、简记、extra、收藏状态；不可改核心元数据（标题/作者/DOI 等）。
    """
    try:
        return _out(zc.update_item_meta(
            item_key,
            add_tags=_parse_tags(add_tags),
            remove_tags=_parse_tags(remove_tags),
            rating=rating,
            notes=notes,
            extra=extra,
            notes_mode=notes_mode,
        ))
    except ZoteroError as e:
        return _err(e)


if __name__ == "__main__":
    mcp.run()
