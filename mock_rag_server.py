# mock_rag_server.py — 模拟内部 RAG 检索服务（FastAPI）
# 数据流转：HTTP 请求 → 关键词匹配内置知识库 → 返回带 score 的文档 → Agent 消费

from fastapi import FastAPI
from rag_contract import RagQuery, RagResult, RagDocument
import re

app = FastAPI(title="Mock Internal RAG")

# 数据流转：内置排障知识库，生产环境这里换成对内部检索平台的 HTTP 调用或 SDK
# mock_rag_server.py — 替换 KB 和 _score，对齐你 Phase 14 的 kb 字典
KB = [
    RagDocument(doc_id="SOP-001", content="【SOP-001】CPU 异常排查：1. 运行 top 查看占用最高的进程；2. 检查是否有死循环；3. 检查流量是否突增。",
                score=0.0, source="SOP-001", metadata={"tags": ["cpu", "top"]}),
    RagDocument(doc_id="SOP-002", content="【SOP-002】磁盘打满：1. 运行 df -h 检查挂载点；2. 清理 /var/log 下的旧日志。",
                score=0.0, source="SOP-002", metadata={"tags": ["disk", "df"]}),
    RagDocument(doc_id="SOP-003", content="【SOP-003】内存泄漏排查：1. 运行 free -m 检查剩余内存；2. 运行 ps aux 查找占用内存最高的进程。",
                score=0.0, source="SOP-003", metadata={"tags": ["memory", "free"]}),
    RagDocument(doc_id="SOP-004", content="【SOP-004】k8s排查：1. 运行 kubectl 等相关命令检查资源；",
                score=0.0, source="SOP-004", metadata={"tags": ["k8s"]}),
]

def _score(query: str, doc: RagDocument) -> float:
    # 数据流转：中英文混合匹配——英文关键词 + 中文子串
    q = query.lower()
    tags = doc.metadata.get("tags", [])
    en_hit = sum(1 for t in tags if t in q)
    zh_hit = 1.0 if any(k in doc.content for k in ["CPU", "磁盘", "内存","k8s"]) and any(
        k in query for k in ["CPU", "磁盘", "内存","k8s"]) else 0.0
    # 简单可解释打分，够 mock 用
    return min(1.0, (en_hit * 0.4) + (zh_hit * 0.4))

@app.post("/v1/retrieve", response_model=RagResult)
#它告诉 FastAPI：“当有客户端向 /v1/retrieve 发送 POST 请求时，就交给下面这个 retrieve 函数来处理。”
#response_model=RagResult告诉 FastAPI，这个函数返回的数据必须符合 RagResult 的格式，并且在返回给客户端之前，自动将其转换为 JSON。
def retrieve(q: RagQuery):
    #q: RagQuery：FastAPI 的魔法。它自动读取 HTTP 请求体中的 JSON，用 Pydantic 的 RagQuery 模型进行校验，然后实例化成对象 q 传进来。如果客户端少传了必填参数， 
    #FastAPI 会直接返回 422 错误，根本不会执行到函数里面。
    # 数据流转：对每条知识打分 → 过滤 min_score → 按分数降序取 top_k
    scored = []
    for doc in KB:
        if q.namespace and doc.metadata.get("namespace") not in (None, q.namespace):
        #如果请求里指定了 q.namespace，且当前文档的 namespace 不是 None 且和请求不一致，就直接跳过（continue）。
            continue
        s = _score(q.query, doc)
        if s >= q.min_score and s > 0:
            #双重校验。分数必须大于等于客户端要求的“最低分数线”，并且必须大于 0（排除完全不相关的垃圾数据）。
            scored.append(doc.model_copy(update={"score": round(s, 4)}))
            #doc.model_copy(update=...)：这是 Pydantic v2 的常用写法。它复制了一份原文档对象，顺便把算出来的得分（保留 4 位小数）更新进去。
    scored.sort(key=lambda d: d.score, reverse=True)
    #sort：使用 lambda 提取每个文档的 score 进行降序排列（reverse=True）
    #按得分（元组的第二个元素）降序排序，最相似的排最前。
    return RagResult(documents=scored[: q.top_k])
    #取排序后的前 top_k 个 

#documents=scored
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

@app.get("/health")
def health():
    # 数据流转：供 Compose healthcheck / K8s readinessProbe 探测
    return {"status": "ok", "backend": "mock-internal-rag", "kb_size": len(KB)}