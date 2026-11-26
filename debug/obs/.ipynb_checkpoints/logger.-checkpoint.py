# obs/logger.py — 结构化日志模块
# 数据流转：请求进入 → 生成 trace_id 并绑定到 contextvars → 所有日志自动带上 trace_id

import structlog
import uuid
import contextvars

# 数据流转：使用 contextvars 保证并发请求时 trace_id 不串号
trace_id_var = contextvars.ContextVar("trace_id", default="unknown")

def set_trace_id():
    # 数据流转：生成唯一 ID 并存入上下文
    tid = str(uuid.uuid4())[:8]
    trace_id_var.set(tid)
    return tid

def add_trace_id(logger, method_name, event_dict):
    # 数据流转：每次打日志时，从上下文中取出 trace_id 注入日志字典
    event_dict["trace_id"] = trace_id_var.get()
    return event_dict

# 数据流转：配置 structlog，输出 JSON 格式日志
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        add_trace_id,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()  # 数据流转：输出为 JSON 字符串
    ],
    logger_factory=structlog.PrintLoggerFactory(),
)

log = structlog.get_logger()