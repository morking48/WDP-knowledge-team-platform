"""WDP 定制层公共类型别名。

统一 API handler 的返回类型契约，让 pyright/AI agent 能准确理解：
- 成功 → 返回 dict（响应体）
- 失败 → 返回 (dict, status_code) 元组（错误体 + HTTP 状态码）

用法：
    from api._wdp_types import ApiResult
    def handle_xxx(...) -> ApiResult:
        if bad: return {'error': '...'}, 400
        return {'ok': True}
"""
from __future__ import annotations

from typing import Any, Union

# API handler 统一返回契约：成功 dict，失败 (dict, http_status)
ApiResult = Union[dict[str, Any], tuple[dict[str, Any], int]]
