#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
memory-mcp —— 从零写的一个"长期记忆"MCP 服务器

作用：把一组纯文本记忆文件（FACT / JOURNAL / SOUL / USER）暴露成 MCP 工具，
      任何支持 MCP 的客户端（Cherry Studio、DeepSeek Harness、Claude Desktop 等）接上就能读写。

记忆位置：默认 E:\\memory，可用环境变量 MEMORY_DIR 覆盖。
传输方式：stdio（客户端启动本进程，通过标准输入输出收发 JSON-RPC）。
依赖：mcp >= 2.3.0（用的是 McpServer 新接口，mcp 1.x 的 FastMCP 不兼容）。

⚠️ 数据永远不离开本机 —— 本文件可以公开，记忆文件绝不上传。
"""

import difflib
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# ─────────────────────────── 配置 ───────────────────────────
MEMORY_DIR = Path(os.environ.get("MEMORY_DIR", r"E:\memory"))

FACT_FILE = MEMORY_DIR / "FACT.md"          # 长期记忆（整篇覆盖）
JOURNAL_FILE = MEMORY_DIR / "JOURNAL.jsonl"  # 事件日志（逐行追加）

# 允许通过 memory_read 读的文件白名单（防越权读别的文件）；归档文件也可读
READABLE = {"FACT.md", "FACT.archive.md", "JOURNAL.jsonl", "SOUL.md", "USER.md"}

# 缩水闸门：新 FACT 小于 1KB 且旧的大于它 3 倍时，拒绝覆盖（防写坏/截断）
MIN_FACT_BYTES = 1024
SHRINK_RATIO = 3

# 巩固阈值：新事件与"今天的某条"内容相似度达到这个比例，就并进那条，不再新增
MERGE_SIMILARITY = 0.90

mcp = MCPServer("memory")


def _now() -> str:
    """当前时间，UTC ISO 格式（与 JOURNAL 既有的 ts 一致，便于合并排序/去重）。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _backup(path: Path) -> str | None:
    """写入前先备份（文件名带日期）。返回备份路径，没写成功返回 None。"""
    if not path.exists():
        return None
    bak = path.with_suffix(path.suffix + f".bak-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, bak)
    return str(bak)


def _fmt_size(n: int) -> str:
    """字节数转人读格式。"""
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / 1024 / 1024:.2f} MB"


def _norm(s: str) -> str:
    """归一化：小写 + 去掉空白与标点，只留比对用的“字”。"""
    return re.sub(r"[\s\W_]+", "", s.lower())


def _day_of(ts: str) -> date | None:
    """JOURNAL 里的 UTC 时间戳 → 本地日期。解析失败返回 None。"""
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().date()
    except (ValueError, TypeError):
        return None


def _parse_day(s: str) -> date | None:
    """把 YYYY-MM-DD / YYYY/MM/DD 解析成本地日期；空串或非法返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s.replace("/", "-"), "%Y-%m-%d").date()
    except ValueError:
        return None


def _merge_into_today(text: str, tags: list[str]) -> str | None:
    """「巩固」：今天已有高度相似的条目就并进去，返回提示文案；没有就返回 None。

    只回看最近 500 行、碰到更早的日期就停 —— 巩固的是“同一天里反复出现的事”。
    """
    today = datetime.now().date()
    lines = JOURNAL_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    new_norm = _norm(text)
    if not new_norm:
        return None

    best_i, best_ratio, best_entry = -1, 0.0, None
    for i in range(len(lines) - 1, max(-1, len(lines) - 500), -1):
        try:
            e = json.loads(lines[i])
        except json.JSONDecodeError:
            continue
        if _day_of(e.get("ts", "")) != today:
            break
        old_norm = _norm(str(e.get("text", "")))
        if not old_norm:
            continue
        if new_norm in old_norm:
            ratio = 1.0
        else:
            ratio = difflib.SequenceMatcher(None, old_norm, new_norm).ratio()
        if ratio > best_ratio:
            best_i, best_ratio, best_entry = i, ratio, e

    if best_entry is None or best_ratio < MERGE_SIMILARITY:
        return None

    old_text = str(best_entry.get("text", ""))
    if new_norm not in _norm(old_text):
        best_entry["text"] = f"{old_text}；{text}"
    best_entry["tags"] = sorted({*(str(t) for t in (best_entry.get("tags") or [])), *tags})
    lines[best_i] = json.dumps(best_entry, ensure_ascii=False)

    bak = _backup(JOURNAL_FILE)
    tmp = JOURNAL_FILE.with_name(JOURNAL_FILE.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, JOURNAL_FILE)
    return (
        f"已合并进今天的第 {best_i + 1} 行（相似度 {best_ratio:.0%}，未新增条目），"
        f"当前共 {len(lines)} 条" + (f"，备份：{bak}" if bak else "")
    )


def _archive_files() -> list[Path]:
    """记忆目录里的归档文件（`*.archive.md`，按名字排序）。

    归档 = 从 FACT.md 搬出去的旧段落：不进每次会话的固定注入，但仍旧可读、可搜。
    """
    if not MEMORY_DIR.exists():
        return []
    return sorted(MEMORY_DIR.glob("*.archive.md"))


# ─────────────────────────── 工具 ───────────────────────────

@mcp.tool(description=(
    "读取记忆文件。filename 默认 FACT.md；可传 SOUL.md / USER.md / JOURNAL.jsonl / FACT.archive.md（归档）。"
    "三种取法（按优先级）：tail>0 只返回最后 tail 行；offset>0 或 limit>0 按行号读一段"
    "（offset 从 1 起，limit 最多几行；配合 memory_search 给的行号读归档最省 token）；"
    "都不给就整份返回。"
))
def memory_read(filename: str = "FACT.md", tail: int = 0, offset: int = 0, limit: int = 0) -> str:
    name = Path(filename).name
    if name not in READABLE:
        return f"拒绝：只能读 {sorted(READABLE)}，收到的是 {filename!r}"
    path = MEMORY_DIR / name
    if not path.exists():
        return f"文件不存在：{path}"
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    total = len(lines)
    if tail > 0:
        start = max(1, total - tail + 1)
        return f"[{name} 第 {start}–{total} 行 / 共 {total} 行]\n" + "\n".join(lines[-tail:])
    if offset > 0 or limit > 0:
        start = max(1, offset or 1)
        if start > total:
            return f"{name} 只有 {total} 行，offset={start} 超出范围"
        end = total if limit <= 0 else min(total, start + limit - 1)
        return f"[{name} 第 {start}–{end} 行 / 共 {total} 行]\n" + "\n".join(lines[start - 1:end])
    return text


@mcp.tool(description=(
    "覆盖写入 FACT.md（长期记忆）。写入前会自动备份，并有缩水保护："
    "若新内容不足 1KB 且旧内容的三倍以上，则拒绝（防写坏）。"
))
def memory_update(content: str) -> str:
    old = FACT_FILE.read_text(encoding="utf-8") if FACT_FILE.exists() else ""
    if len(content.encode("utf-8")) < MIN_FACT_BYTES and len(old.encode("utf-8")) > MIN_FACT_BYTES * SHRINK_RATIO:
        return (f"拒绝写入：新内容太小（{len(content.encode('utf-8'))} 字节），"
                f"旧内容有 {len(old.encode('utf-8'))} 字节，疑似写坏/截断。"
                f"确实要整篇覆盖，请直接编辑文件（写入前记得先备份）。")
    bak = _backup(FACT_FILE)
    FACT_FILE.write_text(content, encoding="utf-8")
    return f"已写入 FACT.md（{len(content.encode('utf-8'))} 字节）" + (f"，备份：{bak}" if bak else "")


@mcp.tool(description=(
    "往 JOURNAL.jsonl 追加一条事件记录。tags 可选，是标签列表。"
    "默认先做「巩固」：如果今天已有条目与新内容相似度 ≥90%（或新内容被旧条目包含），"
    "就不再新增，而是把新信息并进那条（保留原时间戳、tags 取并集）。merge=False 可强制新增。"
))
def memory_append(text: str, tags: list[str] | None = None, merge: bool = True) -> str:
    text = (text or "").strip()
    if not text:
        return "拒绝：text 不能为空"
    tags = [str(t) for t in (tags or [])]
    if merge and JOURNAL_FILE.exists():
        merged = _merge_into_today(text, tags)
        if merged:
            return merged
    entry = {"ts": _now(), "tags": tags, "text": text}
    with JOURNAL_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    with JOURNAL_FILE.open(encoding="utf-8", errors="replace") as f:
        n = sum(1 for _ in f)
    return f"已追加到 JOURNAL（当前共 {n} 条）"


@mcp.tool(description=(
    "在记忆里检索。默认同时搜 JOURNAL 事件和归档文件（FACT.archive.md）——"
    "归档是从 FACT 搬走的旧段落，不占固定注入，靠这里找回。"
    "query 为空时只按 tag / 日期过滤 JOURNAL（= 列出某段时间的事）。"
    "tag 可写多个（逗号分隔），命中任一即可；after / before 用 YYYY-MM-DD（本地日期，含当天）。"
    "返回最近 limit 条事件（带时间戳与 tags）和命中的归档行。大小写不敏感的普通子串匹配，不是语义检索。"
))
def memory_search(
    query: str = "",
    limit: int = 20,
    tag: str = "",
    after: str = "",
    before: str = "",
    include_archive: bool = True,
) -> str:
    q = (query or "").strip().lower()
    want_tags = [t.strip().lower() for t in (tag or "").split(",") if t.strip()]
    d_after, d_before = _parse_day(after), _parse_day(before)

    hits: list[tuple[str, str, list[str]]] = []
    if JOURNAL_FILE.exists():
        for line in JOURNAL_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                if q and q in line.lower():
                    hits.append(("", line, []))
                continue
            body = str(e.get("text", ""))
            etags = [str(t) for t in (e.get("tags") or [])]
            if q and q not in body.lower() and q not in line.lower():
                continue
            if want_tags and not any(t in {x.lower() for x in etags} for t in want_tags):
                continue
            if d_after or d_before:
                d = _day_of(e.get("ts", ""))
                if d is None or (d_after and d < d_after) or (d_before and d > d_before):
                    continue
            hits.append((str(e.get("ts", "")), body, etags))

    hits = hits[-limit:]  # 取最近的

    # 归档文件：按行子串匹配（默认开，避免"图省事只搜 JOURNAL"导致归档变成黑洞）
    arch_hits: list[tuple[str, int, str]] = []
    if q and include_archive:
        for f in _archive_files():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if q in line.lower():
                    s = line.strip()
                    if len(s) > 300:
                        s = s[:300] + "…"
                    arch_hits.append((f.name, i, s))

    if not hits and not arch_hits:
        bits = []
        if q:
            bits.append(f"含 {query!r}")
        if want_tags:
            bits.append("tags=" + ",".join(want_tags))
        if d_after:
            bits.append(f">={d_after}")
        if d_before:
            bits.append(f"<={d_before}")
        return "没找到" + ("（" + " ".join(bits) + "）" if bits else "任何记录")

    out: list[str] = []
    if hits:
        out.append(f"找到 {len(hits)} 条 JOURNAL 事件（最近 {len(hits)} 条）：")
        for ts, body, etags in hits:
            tail = f"　（tags: {', '.join(etags)}）" if etags else ""
            out.append(f"[{ts}] {body}{tail}")
    else:
        out.append(f"JOURNAL 里没找到{'含 ' + repr(query) if q else '匹配记录'}（可能只在归档里，见下）")
    if arch_hits:
        out.append(f"归档文件命中 {len(arch_hits)} 行（不进每次注入，按需 memory_read 读原文）：")
        for name, i, s in arch_hits[:limit]:
            out.append(f"[{name}:{i}] {s}")
    return "\n".join(out)


@mcp.tool(description=(
    "记忆体检（只读）：返回各记忆文件的体积、行数/条数、最后修改时间与距今天数，"
    "JOURNAL 的首末时间与今日新增条数，以及备份文件占用。"
    "适合在整理记忆前、或回答「你记不记得某件事」之前先看整体状态——"
    "它只量尺寸，不判断内容重要性、不动任何文件。"
))
def memory_stats() -> str:
    if not MEMORY_DIR.exists():
        return f"记忆目录不存在：{MEMORY_DIR}"

    now = datetime.now()
    today = now.date()
    out = [f"记忆目录：{MEMORY_DIR}"]
    hints: list[str] = []

    names = ["FACT.md", "USER.md", "SOUL.md", "JOURNAL.jsonl"] + [p.name for p in _archive_files()]
    for name in names:
        path = MEMORY_DIR / name
        if not path.exists():
            out.append(f"{name}：不存在")
            continue
        size = path.stat().st_size
        text = path.read_text(encoding="utf-8", errors="replace")

        if name == "JOURNAL.jsonl":
            lines = text.splitlines()
            first_ts = last_ts = "?"
            today_n = 0
            for ln in lines:
                try:
                    entry = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                ts = str(entry.get("ts", ""))
                if not ts:
                    continue
                if first_ts == "?":
                    first_ts = ts
                last_ts = ts
                try:
                    local_day = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().date()
                except ValueError:
                    continue
                if local_day == today:
                    today_n += 1
            out.append(
                f"{name}：{_fmt_size(size)}，{len(lines)} 条，"
                f"今日新增 {today_n} 条，{first_ts[:10]} → {last_ts[:10]}"
            )
            if size > 400 * 1024:
                hints.append(f"JOURNAL 已到 {_fmt_size(size)}，旧事件可考虑归档")
        else:
            lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
            mtime = datetime.fromtimestamp(path.stat().st_mtime)
            out.append(
                f"{name}：{_fmt_size(size)}，{lines} 行，"
                f"改于 {mtime:%Y-%m-%d %H:%M}（{(now - mtime).days} 天前）"
            )
            if name == "FACT.md" and size > 60 * 1024:
                hints.append(f"FACT 已到 {_fmt_size(size)}（新会话要整份注入），可考虑归档旧段落")

    baks = [p for p in MEMORY_DIR.iterdir() if p.is_file() and ".bak" in p.name]
    if baks:
        total = sum(p.stat().st_size for p in baks)
        out.append(f"备份文件：{len(baks)} 个，共 {_fmt_size(total)}")

    if hints:
        out.append("提示：" + "；".join(hints))
    else:
        out.append("提示：各文件体积正常")
    return "\n".join(out)


def main() -> None:
    if not MEMORY_DIR.exists():
        print(f"警告：记忆目录不存在 {MEMORY_DIR}，已自动创建（空的记忆）。", file=sys.stderr)
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
