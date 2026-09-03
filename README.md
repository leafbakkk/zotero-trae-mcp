# zotero-trae-mcp

Zotero 文献库的 **Model Context Protocol (MCP)** 服务器，为 Trae / 支持 MCP 的 AI 客户端提供对 Zotero 桌面端的只读访问。

配合 [zotero-picker-vscode](https://github.com/leafbakkk/zotero-picker-vscode) 扩展，可在编辑器原生面板内完成文献搜索、批量复制、回流选定等交互。

## 功能

### 读链路

| 工具 | 说明 |
|------|------|
| `health_check` | 检查 Zotero 本地 API、Better BibTeX、PDF 存储目录的连通性 |
| `search_library` | 全文搜索（标题 / 作者 / 年份 / 标签） |
| `get_item` | 按 item key / citekey / DOI 获取单条元数据 |
| `list_collections` | 列出全部分类（返回树形结构） |
| `read_collection` | 读取指定分类路径下的文献 |
| `read_pdf` | 提取 PDF 文本，支持页码范围，中文兼容 |

### 选择器（两段式）

| 工具 | 说明 |
|------|------|
| `pick_item` | 第一段：打开可视化选择器，返回选择器 URL 和 `since_seq` |
| `pick_item_result` | 第二段：等待用户选定，返回完整元数据 |

选择器特性：实时搜索、可折叠分类树、标签过滤、批量勾选 → 一键复制 CiteKey / 文中注。

### 跳转

| 工具 | 说明 |
|------|------|
| `open_in_zotero` | 用 `zotero://select` 在桌面端定位条目 |
| `open_pdf_in_zotero` | 用 `zotero://open-pdf` 打开 PDF 阅读器 |

## 前置要求

- **Python ≥ 3.10**
- **Zotero 桌面端**（Zotero 7 默认开启本地 API `http://localhost:23119`）
- **Better BibTeX 插件**（用于 citekey ↔ item key 双向解析，可选但推荐）

## 安装

```bash
git clone https://github.com/leafbakkk/zotero-trae-mcp.git
cd zotero-trae-mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## 配置到 Trae / MCP 客户端

在 MCP 客户端的配置中注册此服务器（stdio 模式）：

```json
{
  "mcpServers": {
    "zotero": {
      "command": "python",
      "args": ["/path/to/zotero-trae-mcp/server.py"],
      "env": {
        "ZOTERO_STORAGE_DIR": "~/Zotero/storage"
      }
    }
  }
}
```

环境变量（均可选）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZOTERO_LOCAL_API` | `http://localhost:23119` | Zotero 本地 API 地址 |
| `ZOTERO_STORAGE_DIR` | `~/Zotero/storage` | PDF 附件存储目录 |

## 与 zotero-picker-vscode 联动

扩展安装后在本地监听触发端口，MCP 的 `pick_item` 会 best-effort 向该端口发送请求，扩展自动弹出选择器面板。未安装扩展时，`pick_item` 返回 URL 供 MCP 客户端用内置预览组件打开。

## 安全边界

- **只读**：仅通过 Zotero 本地 API 读取，不做任何写操作
- **不管理密钥**：Zotero 本地 API 无需认证，Better BibTeX RPC 同样无鉴权
- **PDF 路径来源**：从 `links.enclosure.href` 提取，避免依赖 Zotero `data.path` 字段

## 项目结构

```
zotero-trae-mcp/
├── server.py           # FastMCP 工具定义（11 个工具）
├── zotero_client.py    # Zotero 本地 API + Better BibTeX JSON-RPC 客户端
├── picker.py           # 可视化选择器 HTTP 服务（供 web 预览 / VS Code 扩展使用）
├── smoke_test.py       # 端到端冒烟测试
└── prototype_picker.py # 选择器原型（开发参考）
```

## License

[MIT](./LICENSE)
