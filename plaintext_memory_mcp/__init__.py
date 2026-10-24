"""plaintext-memory-mcp —— 本地纯文本长期记忆 MCP 服务器。

记忆是你磁盘上的几个文本文件（FACT.md / JOURNAL.jsonl / SOUL.md / USER.md），
本包只负责通过 MCP 读写它们；不联网、不建库、不上云。
"""

from .server import main

__version__ = "0.6.0"

__all__ = ["main", "__version__"]
