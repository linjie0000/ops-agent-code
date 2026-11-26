# rag_client.py — Agent 侧 RAG 客户端
# 数据流转：Agent 决策"需要历史经验" → 调 retrieve() → HTTP 打到内部 RAG → 文档注入 ContextManager

import os
import httpx
from rag_contract import RagQuery, RagResult, RagDocument

class InternalRagClient:
    def __init__(self, base_url: str | None = None, timeout: float = 10.0):
        #类型提示：str | None 表示 base_url 可以传字符串，也可以不传（默认 None）。timeout 是浮点数，默认 10 秒。
        # 数据流转：base_url 来自环境变量，容器内解析到 rag-service 服务名
        self.base_url = base_url or os.getenv("RAG_BASE_URL", "http://rag-service:8100")
        #如果在实例化时手动传了 base_url，就用传进来的。
        #如果没传，就去读操作系统的环境变量 RAG_BASE_URL。
        #如果环境变量也没有，就用默认的 "http://rag-service:8100"。
        #在 Docker Compose 或 K8s 环境中，容器之间通信不能写 localhost，而是直接用服务名（rag-service）作为域名，Docker 的内置 DNS 会自动把它解析到对应的容器 IP。
        self.timeout = timeout

    def retrieve(self, query: str, top_k: int = 5, namespace: str | None = None,
                 min_score: float = 0.0) -> list[RagDocument]:
        # 数据流转：构造契约对象 → POST → 解析 RagResult → 返回文档列表
        payload = RagQuery(query=query, top_k=top_k, namespace=namespace, min_score=min_score)
        try:
            #发送请求 httpx支持异步请求
            resp = httpx.post(f"{self.base_url}/v1/retrieve", # 拼接出完整的 API 地址
                              json=payload.model_dump(),  # 把请求参数转成 JSON 发给对方
                              timeout=self.timeout) # 如果对方 10 秒没响应，主动断开，防止卡死

            #{
            #  "documents": [
            #    {
            #      "doc_id": "kb-001",
            #      "content": "Pod CrashLoopBackOff 常见原因：镜像拉取失败、启动命令退出码非0、探针配置错误。排查：kubectl describe pod 看 Events，kubectl logs --previous 看上次日志。",
            #      "score": 0.85,
            #      "source": "runbook/crashloop.md",
            #      "metadata": {
            #        "namespace": "default",
            #        "tags": ["pod", "crashloop"]
            #      }
            #    }
            #  ]
            #}
            
            resp.raise_for_status()
            #如果服务返回的是 200 OK，这行代码什么都不做，继续往下走。
            #如果服务返回了 400（参数错）、401（没权限）、404（找不到接口）或 500（内部报错），这行代码会立刻抛出异常（httpx.HTTPStatusError），中断当前函数。

            result = RagResult.model_validate(resp.json()) #.json将字符串解析成字典
            #RagResult.model_validate(...)它拿着你刚解析出来的字典，对照 RagResult 类的定义进行严格校验。
            #如果远端传回来的数据格式不对（比如少了个字段、类型写错了），这里会立刻抛出异常（ValidationError）。如果校验通过，它就会把字典实例化成一个类型安全的 Python 对象（result）。
            return result.documents
        except httpx.HTTPError as e:
            # 数据流转：RAG 失败不阻塞主流程，返回空列表让 Agent 继续（生产必须优雅降级）
            # 记录结构化异常，供可观测性采集
            print(f"[RAG] retrieve failed: {e}, degrade to empty context")
            return []

    def health(self) -> bool:
        # 数据流转：启动自检 / K8s readinessProbe 调用
        try:
            return httpx.get(f"{self.base_url}/health", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False