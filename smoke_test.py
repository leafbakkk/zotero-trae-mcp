#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端冒烟测试：以 MCP stdio 客户端身份连接 server.py，逐一调用工具验证"""
import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import os
PY = os.environ.get("PYTHON", sys.executable)
SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")

EXPECTED_TOOLS = {"health_check", "search_library", "get_item", "list_collections",
                  "read_collection", "read_pdf", "pick_item", "pick_item_result",
                  "open_in_zotero", "open_pdf_in_zotero"}


async def call(session, name, args=None, quiet=False):
    r = await session.call_tool(name, args or {})
    text = r.content[0].text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"_raw": text}


async def main():
    params = StdioServerParameters(command=PY, args=[SERVER])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()

            tools = await s.list_tools()
            names = {t.name for t in tools.tools}
            missing = EXPECTED_TOOLS - names
            print(f"[1] 工具注册: {len(names)}/{len(EXPECTED_TOOLS)}", "OK" if not missing else f"缺失 {missing}")

            h = await call(s, "health_check")
            print(f"[2] health_check: {h.get('status', h.get('error'))} | 库: {h.get('library_name')} | "
                  f"BBT: {h.get('better_bibtex')} | storage: {h.get('storage_dir_exists')}")

            sr = await call(s, "search_library", {"query": "道德", "limit": 3})
            print(f"[3] search_library(道德): {sr.get('count')} 条")
            assert sr.get("items"), "搜索无结果"
            item0 = sr["items"][0]
            print(f"    首条: {item0['key']} | {item0['title'][:36]} | {item0['creators'][:30]} | {item0['year']}")

            gi = await call(s, "get_item", {"key_or_citekey": item0["key"]})
            print(f"[4] get_item: {gi.get('title', '')[:36]} | citekey: {gi.get('citekey')} | "
                  f"附件 {len(gi.get('attachments', []))} 个 | DOI: {gi.get('DOI', '')[:20]}")
            pdf_att = next((a for a in gi.get("attachments", []) if a.get("is_pdf")), None)

            ck = await call(s, "get_item", {"key_or_citekey": "simonsLarge2026"})
            print(f"[5] get_item(citekey): {ck.get('key')} | {ck.get('citekey')} | {ck.get('title', '')[:36]}")

            if pdf_att:
                pr = await call(s, "read_pdf", {"key_or_citekey": item0["key"], "pages": "1", "max_chars": 2000})
                txt = pr.get("text", "")
                print(f"[6] read_pdf(第1页): 共 {pr.get('total_pages')} 页 | 提取 {len(txt)} 字符 | 开头: {txt.strip()[:60]!r}")
            else:
                print("[6] read_pdf: 首条无 PDF 附件，跳过")

            lc = await call(s, "list_collections")
            cols = lc.get("collections", [])
            print(f"[7] list_collections: 顶层 {len(cols)} 个 | 首个: {cols[0]['path']} ({cols[0].get('numItems')} 条)")

            rc = await call(s, "read_collection", {"path": cols[0]["path"], "limit": 3})
            print(f"[8] read_collection({rc.get('collection')}): {rc.get('count')} 条")
            assert rc.get("count", 0) > 0, "分类条目为空"

            op = await call(s, "open_in_zotero", {"key_or_citekey": item0["key"]})
            print(f"[9] open_in_zotero: {op.get('ok')} | {op.get('action')}")

            # 错误路径
            bad = await call(s, "get_item", {"key_or_citekey": "ZZZZZZZZ"})
            print(f"[10] 错误处理: {'OK' if bad.get('error') else '未返回错误'} | {str(bad.get('error'))[:60]}")

            print("\n全部冒烟项执行完毕（pick_item 为交互工具，需在 Trae 里实测）")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
