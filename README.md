# zotero-trae-mcp

让 AI 直接操作你的 Zotero 文献库：搜索、阅读、引用、写入，全程不离开编辑器。

这是一个 **Model Context Protocol (MCP)** 服务器，配合专属的 IDE 原生面板扩展 [zotero-picker-vscode](https://github.com/leafbakkk/zotero-picker-vscode)，把 Zotero 变成 AI 的一等公民工具。

## 为什么选它

**🖥️ 不是网页，是 IDE 原生面板**

大多数 Zotero MCP 只提供纯文本工具。本项目附带一个 VS Code / Trae 扩展：AI 说「帮我找文献」，编辑器侧边直接弹出搜索面板——实时检索、可折叠分类树、标签筛选、批量勾选，选完一键复制 CiteKey 或文中注（`作者 等, 2023` / `Author et al., 2023`），粘贴回对话框继续聊。

**⚡ 一键装齐整套环境**

内置 `install_picker_extension` 工具：AI 自动从 GitHub 拉取面板扩展、安装到 IDE、完成注册。用户对 AI 说一句「装好 picker」，重启编辑器就能用——不需要手动下载、不需要 vsce 打包、不需要碰任何配置文件。

**📥 读写双全，安全有边界**

读走本地 API（无需认证），写走 Web API（需 Key）。支持按 DOI / arXiv / ISBN / 标题自动联网抓取元数据入库，也支持 AI 根据对话内容直接创建条目、挂载 PDF 附件。自动查重防重复，自动打标签可溯源（`#来自Agent`），高被引文献自动标记 `#🔥`。核心元数据只增不改，已有条目绝不删。

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

然后让 AI 帮你装面板：

> 「调用 install_picker_extension 帮我安装 Zotero Picker 扩展」

重启 IDE，`Cmd+Shift+P` → `Zotero Picker: 打开文献选择器`，Done。

### 前置要求

- **Python ≥ 3.10**
- **Zotero 桌面端**（Zotero 7 默认开启本地 API）
- **Better BibTeX 插件**（citekey 解析，推荐）
- **Zotero Web API Key**（仅写入需要：[获取方式](https://www.zotero.org/settings/keys)，勾选个人库权限即可）

## 工作方式

```
你说：「找几篇关于数字劳工的文献」
        │
        ▼
AI 调用 pick_item ──→ IDE 弹出原生面板（已装扩展）
        │              或内置网页预览（未装扩展）
        ▼
你在面板里搜索、按分类/标签筛选、勾选多篇
        │
        ▼
一键复制 CiteKey / 文中注，或直接「选定并返回」
        │
        ▼
AI 拿到完整元数据，可继续 read_pdf 读全文、写综述
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
| `install_picker_extension` | 一键从 GitHub 下载安装 Picker IDE 扩展（Trae / VS Code），自动注册，重启生效 |

## 写入特性

- **自动查重**：DOI 精确匹配 + 标题模糊匹配，Web API 兜底，已存在则跳过
- **自动标签**：默认打 `#来自Agent`（`auto_tag=false` 可关）；Crossref 被引 > 1000 自动打 `#🔥`
- **分类路径**：所有 `add_*` 支持 `collection='硕士论文/理论'` 直接归档
- **Prompt 指定元数据**：`extra_tags`（额外标签）、`rating`（0-5，自动转 ⭐ 标签）、`notes`（简记）、`extra`（自定义字段）
- **受限更新**：`update_item_meta` 只改元元数据，标题/作者/DOI 等核心字段永不可改

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
- 写链路仅走官方 `api.zotero.org`，Key 只从环境变量读取，不落盘、不回显
- 元数据抓取均为公开 API（Crossref / arXiv / Open Library），零第三方追踪
- 仅新增 + 受限更新，无删除工具，你的文献库永远安全

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
