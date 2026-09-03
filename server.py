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
Phase 2（规划中）：按 DOI/arXiv/ISBN 新增条目，自动查重、打 #来自Agent、被引>1000 打 #🔥；
不提供任何修改/删除已有条目的工具。

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
        "Zotero 文献库访问工具集（只读阶段）。"
        "用户是社会学研究生，文献库 1000+ 条，装有 Better BibTeX。"
        "常用路径：用户想交互式找文献时调用 pick_item 弹出可视化搜索框；"
        "需要全文时先 get_item 或 pick_item 拿到 key，再 read_pdf 读 PDF；"
        "用户提到 Zotero 分类/folder 路径时用 read_collection（如 '硕士论文/CSS中的…'）。"
        "条目标识支持 item key（8 位）、Better BibTeX citekey、DOI 三种形式。"
        "注意：严禁修改或删除 Zotero 中已有条目；若用户给的是 citekey（形如 simonsLarge2026）直接传给工具即可。"
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


if __name__ == "__main__":
    mcp.run()
