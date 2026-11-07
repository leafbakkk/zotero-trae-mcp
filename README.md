# zotero-trae-mcp

Zotero 文献库的 **Model Context Protocol (MCP)** 服务器，为 Trae / 支持 MCP 的 AI 客户端提供对 Zotero 桌面端的读 + 写访问。

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

### 写入链路

| 工具 | 元数据来源 | 说明 |
|------|-----------|------|
| `add_paper_by_doi` | Crossref | 按 DOI 自动抓取元数据，查重后写入 |
| `add_paper_by_arxiv` | arXiv API + Crossref 兜底 | 优先 DOI→Crossref，兜底 arXiv 自身 |
| `add_book_by_isbn` | Open Library | 按 ISBN 自动抓取图书元数据 |
| `add_paper_by_title` | Crossref 标题搜索 | 自动匹配最相关条目，标题越长越准 |
| `add_item` | AI 直接提供 | 接收 Zotero itemTemplate 元数据（对话口述 / PDF 解析等） |
| `attach_pdf_to_item` | 本地文件 | 将本地 PDF 作为附件上传到已有条目 |
| `update_item_meta` | 已有条目 | 更新标签/评级/简记/extra（核心元数据不可改） |

### 配套工具

| 工具 | 说明 |
|------|------|
| `install_picker_extension` | 从 GitHub 仓库下载配套的 Zotero Picker 扩展并安装到本机 IDE（Trae / VS Code），自动注册进 extensions.json；安装后重启 IDE 生效 |

**写入特性**：

- **自动查重**：写入前先在本地库按 DOI / 标题模糊匹配，Web API 兜底（处理写入后本地同步延迟）；已存在则跳过并返回 `duplicate=true`
- **自动标签**：默认打 `#来自Agent`（可通过 `auto_tag=false` 关闭）；Crossref 被引数 > 1000 时自动打 `#🔥`
- **分类路径**：所有 `add_*` 工具支持 `collection` 参数（如 `'硕士论文/CSS中的…'`），不填则写入根目录
- **用户指定元数据**：所有 `add_*` 工具支持以下可选参数，在 prompt 中直接指定即可：

  | 参数 | 格式 | 说明 |
  |------|------|------|
  | `extra_tags` | 逗号分隔字符串 | 额外标签，如 `"必读, 机器学习"` |
  | `rating` | 0-5 整数 | 评级，自动转为 ⭐ 标签（0=⭐, 5=⭐⭐⭐⭐⭐） |
  | `notes` | 纯文本 | 简记/备注，追加到 abstractNote |
  | `extra` | 字符串 | Zotero extra 字段值（键值对 JSON 或纯文本） |

- **update_item_meta**：对已有条目做受限更新，只允许改 tags / rating / notes / extra；rating 自动替换旧评级标签，notes 支持 append / replace 两种模式
- **零依赖**：写入走 Zotero Web API（Python 标准库 urllib），元数据抓取均来自公开 API（Crossref / arXiv / Open Library），无需额外 pip 包
- **安全边界**：仅新增 + 仅改元元数据；核心元数据（标题/作者/DOI/出版信息等）不可修改或删除

## 前置要求

- **Python ≥ 3.10**
- **Zotero 桌面端**（Zotero 7 默认开启本地 API `http://localhost:23119`）
- **Better BibTeX 插件**（用于 citekey ↔ item key 双向解析，可选但推荐）
- **Zotero Web API Key**（写入链路必需，读取不需要）

## 安装

```bash
git clone https://github.com/leafbakkk/zotero-trae-mcp.git
cd zotero-trae-mcp
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 获取 Zotero Web API Key

写入链路需要 API Key，用于调用 Zotero Web API（`https://api.zotero.org`）：

1. 登录 https://www.zotero.org
2. 进入 **设置 → 密钥**（https://www.zotero.org/settings/keys）
3. 点击 **创建新密钥**，只勾选 **个人库**（无需组库权限）
4. 复制生成的 key

API Key 只需在 MCP 客户端的 `env` 里配置，不会硬编码到代码中。

## 配置到 Trae / MCP 客户端

在 MCP 客户端的配置中注册此服务器（stdio 模式）：

```json
{
  "mcpServers": {
    "zotero": {
      "command": "python",
      "args": ["/path/to/zotero-trae-mcp/server.py"],
      "env": {
        "ZOTERO_STORAGE_DIR": "~/Zotero/storage",
        "ZOTERO_API_KEY": "your_zotero_web_api_key_here"
      }
    }
  }
}
```

环境变量：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ZOTERO_LOCAL_API` | `http://localhost:23119` | Zotero 本地 API 地址（读链路） |
| `ZOTERO_STORAGE_DIR` | `~/Zotero/storage` | PDF 附件存储目录（读链路） |
| `ZOTERO_API_KEY` | （无） | Zotero Web API Key（写入链路必需） |

未配置 `ZOTERO_API_KEY` 时，读链路完全正常；调用 `add_*` 工具会返回清晰的配置指引。

## 与 zotero-picker-vscode 联动

扩展安装后在本地监听触发端口，MCP 的 `pick_item` 会 best-effort 向该端口发送请求，扩展自动弹出选择器面板。未安装扩展时，`pick_item` 返回 URL 供 MCP 客户端用内置预览组件打开。

## 架构

```
                读链路（localhost:23119，无需 Key）                写链路（api.zotero.org，需 Key）
                ┌─────────────────────────┐                     ┌──────────────────────────────┐
Zotero 桌面端   │  Zotero 本地 API         │   Crossref / arXiv   │  Zotero Web API                │
                │  Better BibTeX JSON-RPC │   Open Library       │  自动查重 + 标签 + 分类        │
                └─────────────────────────┘                     └──────────────────────────────┘
                                        ↑                              ↑
                                        │                              │
                              zotero_client.py                     zotero_client.py
                              ──────────────────                   ──────────────────
                              search_library                       add_paper_by_doi
                              get_item                             add_paper_by_arxiv
                              list_collections                     add_book_by_isbn
                              read_pdf                             add_paper_by_title
                              open_in_zotero                       add_item
                                                                  attach_pdf_to_item
                                        ↑                              ↑
                                        │                              │
                                 server.py (FastMCP，stdio)
```

## 安全边界

- **只读 + 仅新增 + 受限更新**：读走本地 API（无需认证），写走 Web API（需 Key）；新增条目 + 改标签/评级/简记/extra，但核心元数据（标题/作者/DOI/出版信息等）不可修改；不提供删除工具
- **API Key 不外泄**：Key 仅从环境变量读取，不出现在日志或 API 返回值中
- **不管理密钥**：Zotero 本地 API 无需认证，Better BibTeX RPC 同样无鉴权
- **PDF 路径来源**：从 `links.enclosure.href` 提取，避免依赖 Zotero `data.path` 字段

## 项目结构

```
zotero-trae-mcp/
├── server.py           # FastMCP 工具定义（18 个工具：11 读 + 6 写 + 1 配套安装）
├── zotero_client.py    # Zotero 本地 API 客户端 + Web API 写入 + 元数据抓取 + 查重 + 标签
├── picker.py           # 可视化选择器 HTTP 服务（供 web 预览 / VS Code 扩展使用）
├── smoke_test.py       # 端到端冒烟测试（路径已归一化，适配任意环境）
└── prototype_picker.py # 选择器原型（开发参考）
```

## License

[MIT](./LICENSE)
