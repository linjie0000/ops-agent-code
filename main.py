# main.py — 基于你 master_ops_agent 的 FastAPI 封装
# 数据流转：POST /agent/run → 构造 OpenAI client(指向 ollama 服务名) → master_ops_agent → 返回报告

import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from openai import OpenAI
from agent_core import master_ops_agent   # 你的原主循环，原样 import
from fastapi.staticfiles import StaticFiles


app = FastAPI(title="Ops Agent")

# 数据流转：容器内 base_url 指向 ollama 服务名，不是 localhost
client = OpenAI(
    base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434/v1"),
    api_key="ollama",
)
MODEL = os.getenv("LLM_MODEL", "qwen2.5")

class AgentRequest(BaseModel):
    task: str

#AgentResponse 继承自 BaseModel，在创建这个对象的瞬间，Pydantic 会做一次“安检”：
#它检查 req.task 是不是字符串？
#它检查 report 变量是不是字符串？
class AgentResponse(BaseModel):
    task: str
    report: str

@app.post("/agent/run", response_model=AgentResponse)
##它告诉 FastAPI：“当有客户端向 /agent/run 发送 POST 请求时，就交给下面这个 agent_run 函数来处理。”
##response_model=AgentResponse告诉 FastAPI，这个函数返回的数据必须符合 AgentResponse 的格式，并且在返回给客户端之前，自动将其转换为 JSON。
def agent_run(req: AgentRequest):
    # 数据流转：task → master_ops_agent → ReAct(tool_calls) → RAG/沙盒 → 最终报告
    try:
        report = master_ops_agent(req.task, client, MODEL)
        return AgentResponse(task=req.task, report=report)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"agent failed: {e}")

@app.get("/health")
def health():
    return {"status": "ok"}


app.mount("/debug", StaticFiles(directory="debug", html=True), name="debug")
