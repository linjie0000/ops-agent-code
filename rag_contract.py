# rag_contract.py — 内部 RAG 检索接口契约（生产环境替换为真实内部平台 API）
# 数据流转：Agent 构造 RagQuery → HTTP POST /v1/retrieve → 返回 RagResult 列表 → 注入 ContextManager

from pydantic import BaseModel, Field
from typing import List, Optional

class RagQuery(BaseModel):
    # 数据流转：query 文本来自 ReAct 循环中“需要历史排障经验”的决策点
    query: str = Field(..., description="检索语句，如 'Pod CrashLoopBackOff 排查步骤'")
    top_k: int = Field(5, ge=1, le=20)          # 数据流转：返回条数上限
    namespace: Optional[str] = None             # 数据流转：按 K8s 命名空间过滤知识库
    min_score: float = Field(0.0, ge=0.0, le=1.0)  # 数据流转：相似度阈值，低于此值丢弃
    #类型必须是浮点数（小数）
    #0.0（第一个位置参数）：这是默认值。如果客户端（比如调用你接口的大模型）没有传这个参数，系统就会自动让它等于 0.0。
    #ge=0.0：ge 是 Greater than or Equal 的缩写，意思是“大于等于 0”。
    #le=1.0：le 是 Less than or Equal 的缩写，意思是“小于等于 1”。

class RagDocument(BaseModel):
    doc_id: str
    content: str                                # 数据流转：排障知识片段，最终拼进 prompt
    score: float                                # 数据流转：检索得分，供 Agent 决定是否采信
    source: str                                 # 数据流转：溯源，如 "runbook/crashloop.md"
    metadata: dict = Field(default_factory=dict)

class RagResult(BaseModel):
    documents: List[RagDocument]
    backend: str = "mock-internal-rag"          # 数据流转：标识后端，便于灰度切换时排查