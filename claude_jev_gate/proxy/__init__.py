"""本机 Anthropic Messages 兼容代理：路由 + 先裁再压 + 转发上游。"""

from .server import serve_forever

__all__ = ["serve_forever"]
