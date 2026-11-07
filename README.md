# zotero-trae-mcp

Zotero 文献库的 **Model Context Protocol (MCP)** 服务器，为 Trae / 支持 MCP 的 AI 客户端提供对 Zotero 桌面端的读 + 写访问。

附带一个 IDE 面板扩展 [zotero-picker-vscode](https://github.com/leafbakkk/zotero-picker-vscode)，可在编辑器侧边栏以面板形式完成文献搜索与勾选；同时内置 `install_picker_extension` 工具，可由 AI 自动完成该扩展的下载与安装。

## 功能特点

**IDE 原生选择面板**

除纯文本工具外，本项目提供配套编辑器扩展：调用 `pick_item` 时可在编辑器侧边弹出搜索面板，支持实时检索、可折叠分类树、标签筛选、批量勾选，以及一键复制 CiteKey 或文中注（`作者 等, 2023` / `Author et al., 2023`）。未安装扩展时，选择器退化为 MCP 客户端内置网页预览，功能一致。

**扩展自动安装**

`install_picker_extension` 工具会从 GitHub 拉取面板扩展、解压到 IDE 扩展目录并完成注册。安装后重启 IDE 即可使用，无需手动打包或配置。

**读写支持与安全边界**

读链路走 Zotero 本地 API（无需认证），写链路走 Zotero Web API（需 Key）。支持按 DOI / arXiv / ISBN / 标题自动抓取元数据入库，也支持 AI 根据对话内容直接创建条目、挂载 PDF 附件。写入前自动查重，默认打 `#来自Agent` 标签以便溯源，高被引文献自动标记 `#🔥`。已有条目的核心元数据不可修改，不提供删除工具。

## 快速开始

```bash
git clone https://github.com/leafbakkk/zotero-trae-mcp.git
cd zotero-trae-mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

在 MCP 客户端（Trae 等）注册：

```json
{
  "mcpServers": {
    "zotero": {
      "command": "python",
      "args": ["/path/to/zotero-trae-mcp/server.py"],
      "env": {
        "ZOTERO_API_KEY": "your_zotero_web_api_key_here"
      }
    }
  }
}
```

如需安装面板扩展，可让 AI 调用 `install_picker_extension`，随后重启 IDE，通过命令面板执行 `Zotero Picker: 打开文献选择器` 验证。

### 前置要求

- **Python ≥ 3.10**
- **Zotero 桌面端**（Zotero 7 默认开启本地 API）
- **Better BibTeX 插件**（citekey 解析，推荐）
- **Zotero Web API Key**（仅写入需要，在 https://www.zotero.org/settings/keys 创建，勾选个人库权限即可）

## 典型使用流程

```
用户：「找几篇关于数字劳工的文献」
        │
        ▼
AI 调用 pick_item ──→ IDE 原生面板（已装扩展）
        │              或内置网页预览（未装扩展）
        ▼
用户在面板中搜索、按分类/标签筛选、勾选多篇
        │
        ▼
复制 CiteKey / 文中注，或点击「选定并返回」
        │
        ▼
AI 获得完整元数据，可继续 read_pdf 读全文
```

## 工具一览（19 个）

### 读链路（无需 API Key）

| 工具 | 说明 |
|------|------|
| `health_check` | 检查 Zotero 本地 API、Better BibTeX、PDF 存储目录连通性 |
| `search_library` | 全库搜索（标题 / 作者 / 年份 / 标签） |
| `get_item` | 按 item key / citekey / DOI 获取完整元数据 |
| `list_collections` | 列出全部分类（树形结构 + 完整路径） |
| `read_collection` | 按分类路径浏览文献（如 `'硕士论文/理论'`） |
| `read_pdf` | 提取 PDF 全文，支持页码范围，中文优化（PyMuPDF） |

### 可视化选择器（两段式）

| 工具 | 说明 |
|------|------|
| `pick_item` | 打开选择器：优先唤起 IDE 原生面板，否则返回 URL 供内置预览打开 |
| `pick_item_result` | 等待用户选定，返回完整元数据 |

### 跳转

| 工具 | 说明 |
|------|------|
| `open_in_zotero` | `zotero://select` 在桌面端定位条目 |
| `open_pdf_in_zotero` | `zotero://open-pdf` 打开 PDF 阅读器 |

### 写入链路（需 API Key）

| 工具 | 元数据来源 | 说明 |
|------|-----------|------|
| `add_paper_by_doi` | Crossref | 按 DOI 自动抓取，查重后写入 |
| `add_paper_by_arxiv` | arXiv + Crossref 兜底 | 优先 DOI→Crossref |
| `add_book_by_isbn` | Open Library | 按 ISBN 抓取图书元数据 |
| `add_paper_by_title` | Crossref 标题搜索 | 标题越长匹配越准 |
| `add_item` | AI 直接提供 | 对话口述 / PDF 解析 → 直接建条目 |
| `attach_pdf_to_item` | 本地文件 | PDF 上传为条目附件 |
| `update_item_meta` | 已有条目 | 仅改标签/评级/简记/extra |

### 配套

| 工具 | 说明 |
|------|------|
| `install_picker_extension` | 从 GitHub 下载安装 Picker IDE 扩展（Trae / VS Code），自动注册，重启 IDE 生效 |

## 写入特性

- **自动查重**：DOI 精确匹配 + 标题模糊匹配，Web API 兜底；已存在则跳过
- **自动标签**：默认打 `#来自Agent`（`auto_tag=false` 可关）；Crossref 被引 > 1000 自动打 `#🔥`
- **分类路径**：所有 `add_*` 支持 `collection='硕士论文/理论'` 直接归档
- **Prompt 指定元数据**：`extra_tags`（额外标签）、`rating`（0-5，自动转 ⭐ 标签）、`notes`（简记）、`extra`（自定义字段）
- **受限更新**：`update_item_meta` 只改元元数据，标题/作者/DOI 等核心字段不可修改

## 架构

```
 读链路（本地，无认证）                写链路（Web API，需 Key）
 ┌───────────────────────┐           ┌────────────────────────┐
 │ Zotero 本地 API        │           │ Zotero Web API          │
 │ Better BibTeX JSON-RPC │  Crossref │ 查重 + 标签 + 分类归档  │
 │ 本地 PDF 存储          │  arXiv    │ 受限更新（标签/评级）   │
 └───────────┬───────────┘  OpenLib  └───────────┬────────────┘
             │                                   │
        zotero_client.py ◄── server.py (FastMCP, stdio)
             │
   ┌─────────┴──────────┐
   │ picker.py (HTTP)    │──→ IDE 原生面板扩展（zotero-picker-vscode）
   │ 可视化选择器服务     │    或 MCP 客户端内置网页预览
   └────────────────────┘
```

## 安全与隐私

- 读链路全本地：Zotero 本地 API + 本地 PDF，数据不出本机
- 写链路仅走官方 `api.zotero.org`；Key 只从环境变量读取，不落盘、不回显
- 元数据抓取均为公开 API（Crossref / arXiv / Open Library）
- 仅新增 + 受限更新，无删除工具

## 项目结构

```
zotero-trae-mcp/
├── server.py           # FastMCP 工具定义（19 个工具）
├── zotero_client.py    # 本地 API 客户端 + Web API 写入 + 元数据抓取 + 查重
├── picker.py           # 可视化选择器 HTTP 服务
├── smoke_test.py       # 端到端冒烟测试
└── requirements.txt
```

配套扩展仓库：[zotero-picker-vscode](https://github.com/leafbakkk/zotero-picker-vscode)

## License

[MIT](./LICENSE)
