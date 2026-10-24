# plaintext-memory-mcp

> 让 AI 记住你，但记忆存在**你自己磁盘上的文本文件**里。
> Local-first, plain-text long-term memory for any MCP client.

<p>
  <img alt="Python" src="https://img.shields.io/badge/python-%E2%89%A53.10-blue">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
  <img alt="MCP" src="https://img.shields.io/badge/MCP-2.x-purple">
</p>

---

## English quick start

A **local-first, plain-text long-term memory server** for any MCP client (Cherry Studio, Claude Desktop, DeepSeek Harness, …). Memory lives in four human-readable files under `MEMORY_DIR` — `FACT.md`, `JOURNAL.jsonl`, `SOUL.md`, `USER.md` — so you can open, edit, back up and `git diff` it.

- No database, no vector store, no network calls.
- Five tools: `memory_read`, `memory_update`, `memory_append`, `memory_search`, `memory_stats`.
- Safety: shrink protection on `FACT.md` (refuses writes that shrink it below 1 KB or to less than 1/3 of its size), automatic `*.bak-<timestamp>` backup before every overwrite, read whitelist.
- Requires Python ≥ 3.10 and `mcp >= 2.3.0`.

```bash
git clone https://github.com/WANGJINSHAN-11/memory_mcp.git
cd memory_mcp
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # macOS/Linux: .venv/bin/python
```

Client config for any MCP client — command = venv python, args = [`server.py`], env = `MEMORY_DIR`:

```json
{
  "mcpServers": {
    "memory": {
      "command": "C:\\path\\to\\memory_mcp\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\memory_mcp\\server.py"],
      "env": { "MEMORY_DIR": "E:\\memory" }
    }
  }
}
```

Ready-made configs for Cherry Studio / Claude Desktop / DeepSeek Harness are in [`examples/`](examples/).

---

## 30 秒看懂

- **记忆 = 4 个纯文本文件**（+ 可选的 `FACT.archive.md` 归档）：`FACT.md`（长期事实）、`JOURNAL.jsonl`（事件流水）、`SOUL.md`（人格）、`USER.md`（用户档案）
- **工具 = 一个 MCP 服务器**：只负责读写上面这几个文件，不联网、不建库、不上云
- **结果**：Cherry Studio、Claude Desktop、DeepSeek Harness……接上**同一个目录**，就共享同一份记忆

记忆长这样（`JOURNAL.jsonl` 的一行，人眼可读，`git diff` 可看）：

```json
{"ts":"2026-10-19T06:59:54.413Z","tags":["项目","进度"],"text":"一句话结论，不抄原文。"}
```

**代码公开，数据私有。** 仓库里只有代码；记忆文件永远留在你本机，`.gitignore` 已经把它们挡死了。

---

## 它解决什么问题

每个 AI 客户端（Cherry Studio、Claude Desktop、Cursor、各种 Agent 框架）都有自己的"记忆"，但数据往往锁在平台里：
换个客户端，记忆就断了；导出是一堆看不懂的 JSON；同步全靠平台。

这个项目只做一件事：**把记忆从平台里拿出来，变成你能打开、能改、能备份、能进 git 的文本文件**，
再用 MCP 把这几个文件开放给任何客户端。

---

## 安装

### 克隆源码

```bash
git clone https://github.com/WANGJINSHAN-11/memory_mcp.git
cd memory_mcp

python -m venv .venv

# Windows
.venv\Scripts\pip install -r requirements.txt
# macOS / Linux
# .venv/bin/pip install -r requirements.txt

# 自检：在临时目录里跑，不碰你的真实记忆
.venv\Scripts\python.exe _test.py
```

要求：**Python ≥ 3.10**（实测 3.13.3）、**mcp ≥ 2.3.0**。
⚠️ 本版用 mcp 2.x 的 `MCPServer` 接口，**1.x 的 `FastMCP` 写法不兼容**。

---

## 接到客户端

三要素就三个字段：

| 字段 | 值 |
|---|---|
| 命令 | 仓库 venv 里的 Python：`<仓库路径>\.venv\Scripts\python.exe`（macOS/Linux 用 `.venv/bin/python`） |
| 参数 | `<仓库路径>/server.py` 的绝对路径 |
| 环境变量 | `MEMORY_DIR=<你的记忆目录>`（建议显式填，默认是 `E:\memory`） |

### Cherry Studio / Claude Desktop / 任何 `mcpServers` 格式的客户端

```json
{
  "mcpServers": {
    "memory": {
      "command": "E:\\memory-mcp\\.venv\\Scripts\\python.exe",
      "args": ["E:\\memory-mcp\\server.py"],
      "env": { "MEMORY_DIR": "E:\\memory" }
    }
  }
}
```

### DeepSeek Harness（`cordis.patch.yml`）

```yaml
- insert:
    - id: mcp-memory
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        transport: stdio
        serverName: memory
        command: 'E:\memory-mcp\.venv\Scripts\python.exe'
        args: ['E:\memory-mcp\server.py']
        env:
          MEMORY_DIR: 'E:\memory'
```

### macOS / Linux 路径对照

把上面的 Python 换成 `<仓库路径>/.venv/bin/python`、`server.py` 换成 `<仓库路径>/server.py` 即可。
`examples/` 里有三个现成文件：`cherry-studio.json`、`claude-desktop.json`、`deepseek-harness.patch.yml`。

> ⚠️ **多个客户端同时开着时**：`memory_update` 是整篇覆盖 `FACT.md`，两个客户端同时写会互相覆盖。
> 约定同一时间只让一个客户端写长期记忆；`memory_append`（追加）可以随便并发。

---

## 五个工具

| 工具 | 作用 |
|---|---|
| `memory_read(filename="FACT.md", tail=0, offset=0, limit=0)` | 读记忆文件；`tail=N` 读末尾 N 行；`offset`/`limit` 按行号读一段（读归档时最省 token） |
| `memory_update(content)` | 整篇覆盖 `FACT.md`；**写入前自动备份** + **缩水保护** |
| `memory_append(text, tags=[], merge=True)` | 往 `JOURNAL.jsonl` 追加一条事件；**默认「巩固」**：与今天某条相似度 ≥90% 就并进那条，不新增 |
| `memory_search(query="", limit=20, tag="", after="", before="", include_archive=True)` | 检索：JOURNAL 关键词 + tag/日期过滤（`YYYY-MM-DD`，本地日期）；**默认连归档文件一起搜**（`include_archive=False` 关掉） |
| `memory_stats()` | **记忆体检（只读）**：各文件体积/行数/条数、最后修改时间与距今天数、JOURNAL 首末时间与今日新增、备份占用；超阈值给整理提示 |

给模型用的习惯：

| 想做的事 | 调用 |
|---|---|
| 读长期记忆 | `memory_read()` |
| 只读 FACT 末尾几节（省 token） | `memory_read(tail=50)` |
| 按行号读归档的一段（配合 search 给的行号） | `memory_read(filename="FACT.archive.md", offset=88, limit=12)` |
| 记一条事件（只写结论，不抄原文） | `memory_append(text="...", tags=["项目"])` |
| 手动补一条重复内容（不想合并） | `memory_append(text="...", merge=False)` |
| 找以前记过的事 | `memory_search(query="关键词")`（默认连归档一起搜） |
| 找已经搬进归档的旧事 | 同上，不用额外参数；需要看原文就 `memory_read(filename="FACT.archive.md")` |
| 看某个方向最近都发生了什么 | `memory_search(tag="项目")` 或 `memory_search(after="2026-10-01", before="2026-10-31")` |
| 先看记忆整体状态、该不该整理 | `memory_stats()` |
| 重写整篇 FACT（谨慎） | `memory_update(content="...")` |

---

## 记忆文件格式

目录结构（默认 `E:\memory`，用环境变量 `MEMORY_DIR` 可改到任意位置）：

```
<MEMORY_DIR>\
├── FACT.md           长期记忆：身份、项目、环境、约定……（整篇覆盖）
├── FACT.archive.md   归档（可选）：从 FACT 搬出的旧段落，不进固定注入，靠 memory_search 找回
├── JOURNAL.jsonl     事件日志：每行一条 JSON（只追加）
├── SOUL.md           人格定义（只读）
└── USER.md           用户档案（只读）
```

`JOURNAL.jsonl` 每行格式（时间戳统一 **UTC、`Z` 结尾、毫秒**，方便跨机器合并排序）：

```json
{"ts":"2026-10-19T06:59:54.413Z","tags":["项目","进度"],"text":"一句话结论，不抄原文。"}
```

`templates/` 里有一份空的 FACT 骨架和 JOURNAL 示例，可以先照着抄。

**FACT 太大怎么办（归档）**：新会话往往得把 `FACT.md` 整篇读进来，所以它越短越好。用 `memory_stats()` 看体积，超过约 60 KB 就把「日期流水」这类旧段落**整节**剪到 `FACT.archive.md`（原文不动，FACT 原位留一行指针），并且**先备份**。归档文件不参与固定注入，但 `memory_read` 能读、`memory_search` 默认会搜——**归档 = 搬家，不是丢弃**。

---

## 安全设计

1. 🔒 **缩水保护**：`memory_update` 若发现新内容不足 1KB、且旧内容是它的 **3 倍以上**，直接拒绝——防一次误写/截断毁掉全部记忆。真要整篇覆盖，请直接编辑文件（记得先备份）。
2. 💾 **自动备份**：每次覆盖写入前，旧文件先备份成 `FACT.md.bak-<时间戳>`。
3. 📖 **读取白名单**：`memory_read` 只能读 FACT / FACT.archive / JOURNAL / SOUL / USER，`../../secret.txt` 这类越权路径会被拒。
4. 🏠 **数据不出本机**：服务器只读写本地文件，没有任何网络请求。
5. 🔧 **路径不写死**：`MEMORY_DIR` 环境变量，换机器只改一处。

---

## 项目结构

```
memory-mcp/
├── plaintext_memory_mcp/
│   ├── __init__.py            包入口（导出 main、__version__）
│   ├── __main__.py            支持 python -m plaintext_memory_mcp
│   └── server.py              MCP 服务器主体（约 370 行，中文注释，可当源码读）
├── server.py                  兼容层：老配置里写 server.py 路径照样能跑
├── pyproject.toml             打包配置（预留，暂未发布到 PyPI）
├── requirements.txt           源码方式的依赖（只有 mcp）
├── _test.py                   本地自检：临时目录 + 完整握手 + 五个工具 + 越权断言
├── README.md / CHANGELOG.md / LICENSE
├── examples/                  三个客户端的接入配置示例
└── templates/                 记忆文件骨架
```

---

## 设计取舍：为什么不用数据库 / 向量库

- **可读**：出问题打开文件就能看，不用工具、不用查询语句
- **可迁移**：换机器拷一个目录就完事，没有导出/导入格式
- **可版本化**：`git diff` 能看见记忆是怎么长出来的
- **便宜**：一个进程、零 embedding、零索引，不额外烧 token
- **缺点**：`memory_search` 只是关键词子串匹配，没有语义检索；`FACT.md` 变大后要配合 `tail` 分页读，或先用 `memory_stats()` 看体积再决定是否整理

这些缺点是有意接受的——记忆量在"几千条事件、几十 KB 正文"这个量级时，纯文本完全够用，
而可读、可改、可迁移的价值远大于语义检索。

---

## 常见问题

- **装了没反应？** 先确认 `MEMORY_DIR` 存在且可写；客户端里手动调用 `memory_read` 看返回。
- **Windows 路径怎么写？** JSON 里反斜杠要转义：`"E:\\memory"`；YAML 里用单引号：`'E:\memory'`。
- **换机器怎么办？** 拷整个记忆目录过去，只改 `MEMORY_DIR`，其他不动。
- **能和官方 memory MCP 一起用吗？** 能，它们各管各的目录；本项目的记忆是纯文本，随时能肉眼检查。
- **mcp 1.x 报错？** 升级：`pip install -U "mcp>=2.3.0"`。

---

## 版本

见 [CHANGELOG.md](CHANGELOG.md)。当前 **v0.6.0**（2026-10-24）。

## 许可

MIT，见 [LICENSE](LICENSE)。

## 致谢

基于 MCP 官方 Python SDK（[modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)）实现；
接口设计参考了社区里常见的 `memory_read / memory_update / memory_append / memory_search` 四工具约定；`memory_stats` 是本项目额外加的只读"体检"口，不参与读写。
