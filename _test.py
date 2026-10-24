# -*- coding: utf-8 -*-
"""
本地自检脚本：在**临时目录**里起一份记忆，走一遍完整的 MCP 握手 + 五个工具。

为什么用临时目录：测试会写入 FACT / JOURNAL，绝不能在真实记忆目录上跑
（真记忆在 E:\\memory，测试跑完临时目录会被删掉）。

用法：
    .venv\\Scripts\\python.exe _test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# Windows 控制台默认 GBK，记忆里可能有 emoji —— 不换编码会直接 UnicodeEncodeError
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

HERE = Path(__file__).parent
PY = HERE / ".venv" / ("Scripts" if os.name == "nt" else "bin") / ("python.exe" if os.name == "nt" else "python")

tmp = Path(tempfile.mkdtemp(prefix="memory-mcp-test-"))
env = dict(os.environ, PYTHONIOENCODING="utf-8", MEMORY_DIR=str(tmp))
print(f"测试记忆目录：{tmp}")

p = subprocess.Popen(
    [str(PY), str(HERE / "server.py")],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", env=env, bufsize=1,
)


def send(obj):
    p.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
    p.stdin.flush()


def recv():
    line = p.stdout.readline()
    return json.loads(line) if line.strip() else None


def call(i, name, args):
    send({"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}})
    r = recv()
    if r and "result" in r:
        return r["result"]["content"][0]["text"]
    return f"[错误] {str(r)[:300]}"


try:
    send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "memory-mcp-selftest", "version": "1"}}})
    r = recv()
    print("initialize ->", "OK" if r and "result" in r else r)
    send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    r = recv()
    names = [t["name"] for t in r["result"]["tools"]]
    print("tools/list ->", names)
    assert names == ["memory_read", "memory_update", "memory_append", "memory_search", "memory_stats"], names

    # 1) 读一个还不存在的文件
    print("memory_read(空) ->", call(3, "memory_read", {"filename": "FACT.md"}))

    # 2) 写 FACT（旧文件不存在 ⇒ 应成功）。要写到 3KB 以上，缩水闸门才有得比
    print("memory_update ->", call(4, "memory_update", {"content": "第一条长期记忆，用来占位。\n" * 200}))

    # 3) 再写一次小内容（旧内容已 > 3KB ⇒ 应被缩水闸门拒绝）
    print("memory_update(缩水) ->", call(5, "memory_update", {"content": "x"}))

    # 4) 追加事件
    print("memory_append ->", call(6, "memory_append", {"text": "自检事件 🐟", "tags": ["test"]}))

    # 5) 再追加一条几乎一样的（应被「巩固」合并，不新增条目）
    merged = call(7, "memory_append", {"text": "自检事件 🐟", "tags": ["test", "dup"]})
    print("memory_append(重复) ->", merged)
    assert "已合并" in merged, merged

    # 6) 追加一条完全不同的（应正常新增）
    print("memory_append(新) ->", call(8, "memory_append", {"text": "另一条完全不同的事件：今天下雨", "tags": ["weather"]}))

    # 7) 关键词搜索
    print("memory_search(关键词) ->", call(9, "memory_search", {"query": "自检", "limit": 3}))

    # 8) 只按 tag 过滤（query 留空）
    tag_out = call(10, "memory_search", {"tag": "weather"})
    print("memory_search(tag) ->", tag_out)
    assert "今天下雨" in tag_out, tag_out

    # 9) 按日期过滤：今天的应查得到，明天以后的查不到
    from datetime import date, timedelta
    today = date.today().isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    d_out = call(11, "memory_search", {"after": today, "before": today})
    print("memory_search(日期=今天) ->", d_out)
    assert "自检事件" in d_out or "今天下雨" in d_out, d_out
    empty_out = call(12, "memory_search", {"after": tomorrow})
    print("memory_search(日期=明天起) ->", empty_out)
    assert "没找到" in empty_out, empty_out

    # 10) 越权读取应被拒
    print("memory_read(越权) ->", call(13, "memory_read", {"filename": "../../secret.txt"}))

    # 11) 归档文件：可读 + 搜索默认覆盖归档
    (tmp / "FACT.archive.md").write_text(
        "# FACT 归档\n\n## 归档 2026-10-24 · 10-13~10-20 流水\n\n- 旧事件：音游 IIDX33 放弃\n",
        encoding="utf-8",
    )
    arch_read = call(14, "memory_read", {"filename": "FACT.archive.md"})
    print("memory_read(归档) ->", arch_read.strip().splitlines()[-1][:60])
    assert "IIDX33" in arch_read, arch_read
    arch_hit = call(15, "memory_search", {"query": "IIDX33"})
    print("memory_search(归档) ->", arch_hit.strip().splitlines()[-1][:100])
    assert "归档文件命中" in arch_hit, arch_hit

    # 11b) 按行号读一段（v0.6.0）：只读第 4 行起的 2 行，应命中 IIDX33 且带行号头
    seg = call(19, "memory_read", {"filename": "FACT.archive.md", "offset": 4, "limit": 2})
    print("memory_read(行段) ->", seg.strip().splitlines()[:2])
    assert "第 4–5 行" in seg, seg
    assert "IIDX33" in seg, seg
    over = call(20, "memory_read", {"filename": "FACT.archive.md", "offset": 999})
    print("memory_read(越界) ->", over)
    assert "超出范围" in over, over

    # 12) 记忆体检（只读）
    stats_out = call(16, "memory_stats", {})
    print("memory_stats ->\n" + stats_out)
    assert "FACT.md" in stats_out and "JOURNAL.jsonl" in stats_out, stats_out
    assert "FACT.archive.md" in stats_out, stats_out

    print("\n全部断言通过 ✅")
finally:
    try:
        p.stdin.close()
    except Exception:
        pass
    p.terminate()
    err = p.stderr.read()
    if err.strip():
        print("\n[stderr]", err[:800])
    shutil.rmtree(tmp, ignore_errors=True)
    print("临时记忆目录已删除")
