# tools_ops.py — Phase 14 原文件改造版（只改 search_ops_knowledge 内部）
# 数据流转：Agent 调 search_ops_knowledge → HTTP POST rag-service:8100/v1/retrieve → 返回 JSON 字符串

import os
import json
import httpx
from pydantic import BaseModel, Field
from typing import Callable
from functools import wraps
import platform
import subprocess

# 数据流转：RAG 服务地址来自环境变量，容器内解析到 rag-service:8100
RAG_BASE_URL = os.getenv("RAG_BASE_URL", "http://rag-service:8100")
RAG_TIMEOUT = float(os.getenv("RAG_TIMEOUT", "10"))

class ToolRegistry:
    def __init__(self):
        self.tools_schema = []      # 给大模型看的 OpenAI 格式的工具列表
        self.tools_func = {}        # 实际执行的 Python 函数映射
        self.tools_meta = {}        # 存储额外的元数据（比如权限要求）

    def register(self, name: str, description: str, args_schema: type[BaseModel], required_permission: str = None):
        """
        装饰器工厂：负责把函数注册到系统中，并自动生成 OpenAI 的 schema
        """
        def decorator(func: Callable):
            # 1. 生成 OpenAI 需要的 JSON Schema
            schema = {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": args_schema.model_json_schema()
                    #继承 BaseModel 后，它自带了 model_json_schema() 方法。Pydantic 会顺藤摸瓜，读取你在这个类里定义的所有变量名、类型提示（str、int）和 Field(...) 里的描述，一键打包成之前那个完美的 JSON 格式。
                    #{'properties': {'filename': {'description': "要统计行数的文件名，例如 'main.py'", 'title': 'Filename', 'type': 'string'}}, 'required': ['filename'], 'title': 'CountLinesArgs', 'type': 'object'}
                }
            }
            # 数据流转：生成 {"type":"function", "function":{"name":"count_lines", ...}} 存入列表
            self.tools_schema.append(schema)

            print(schema["function"]["parameters"])
            #{'properties': {'query': {'description': "搜索关键字，如 'CPU 100%'", 'title': 'Query', 'type': 'string'}}, 'required': ['query'], 'title': 'RAGArgs', 'type': 'object'}
            
            # 2. 保存函数引用和权限要求
            self.tools_func[name] = func
            self.tools_meta[name] = {"required_permission": required_permission}

            #核心目的是：在把原函数“包装”起来的同时，完美伪装成原函数，不破坏它原有的任何属性。
            #@wraps（来自 functools 库）会强行把原函数 func 的 __name__、__doc__、__module__ 等元数据，全部复制到 wrapper 身上。
            @wraps(func)
            def wrapper(*args, **kwargs):
                return func(*args, **kwargs)
            return wrapper
        return decorator

    def execute(self, tool_name: str, arguments_str: str, agent_permissions: list) -> str:
    #: str 表示这个参数期望接收一个字符串（String）。
    #这个箭头 -> 表示函数的返回值类型。这个 execute 函数在执行完毕后，最终会返回一个字符串（String）。
    #arguments_str=={"query":"CPU 100%"}
        """
        核心分发器 (Dispatcher)：取代了上一课的 TOOL_MAP.get() 和手动 json.loads()
        """
        # 1. 检查工具是否存在
        if tool_name not in self.tools_func:
            return json.dumps({"error": f"工具 {tool_name} 不存在"})
        
        # 2. 运维级拦截：权限校验
        required_perm = self.tools_meta[tool_name].get("required_permission")
        if required_perm and required_perm not in agent_permissions:
            # 假设 agent_permissions = ["read"]，若工具要求 "admin"，直接拦截，保护系统
            return json.dumps({"error": f"权限不足：执行 {tool_name} 需要 '{required_perm}' 权限"})
        
        # 3. 参数解析与校验（Pydantic 兜底）
        try:
            # 数据流转："{\"query\": \"CPU 100%\"}" → Python dict → 校验后的对象
            args_dict = json.loads(arguments_str)
            # 这里用到工具定义的 args_schema 进行强校验
            validated_args = self.tools_func[tool_name].__annotations__['args_schema'](**args_dict)
            
            print(validated_args)
            #.__annotations__无论什么函数，只要它有类型提示，__annotations__ 就会把它们变成字典。
            #{'args_schema': <class '__main__.CountLinesArgs'>}
            #validated_args==query='CPU 100%'
            
        except json.JSONDecodeError:
            return json.dumps({"error": "参数格式不是合法的 JSON"})
        except ValidationError as e:
            # 假设模型传了 {"file_name": "test.py"} (拼写错误)，这里会捕获并返回给模型
            return json.dumps({"error": f"参数校验失败: {e.errors()}"},ensure_ascii=False)

        # 4. 真正执行
        try:
            # 数据流转：validated_args.model_dump() → {"query":"CPU 100%"}
            # 【修改前】：
            # result = self.tools_func[tool_name](**validated_args.model_dump())
            
            # 【修改后】：把校验好的对象作为参数传给工具函数
            result = self.tools_func[tool_name](args_schema=validated_args)
            return result
        except Exception as e:
            # 容错处理：防止真实工具报错导致整个 Agent 进程崩溃
            return json.dumps({"error": f"工具执行异常: {str(e)}"},ensure_ascii=False)
            #ensure_ascii=False成功转义中文

registry = ToolRegistry()

# 运维白名单：只允许 Agent 执行这些只读诊断命令
ALLOWED_COMMANDS = ["top", "df", "free", "ps", "uptime", "tasklist","kubectl"]

class RAGArgs(BaseModel):
    query: str = Field(..., description="搜索关键字，如 'CPU 100%'")

class ExecArgs(BaseModel):
    command: str = Field(..., description="要执行的只读诊断命令，如 'top' 或 'df'")

@registry.register(
    name="search_ops_knowledge",
    description="搜索内部运维手册和故障处理 SOP",
    args_schema=RAGArgs,
    required_permission="read",
)
def search_ops_knowledge(args_schema: RAGArgs):
    # 数据流转：query → POST /v1/retrieve → RagResult → 取 top1 拼成旧格式 JSON
    # 关键：返回结构保持 {"source":..., "content":...} 不变，主循环和模型无感知
    try:
        resp = httpx.post(
            f"{RAG_BASE_URL}/v1/retrieve",
            json={"query": args_schema.query, "top_k": 1, "min_score": 0.0},
            timeout=RAG_TIMEOUT,
        )
        resp.raise_for_status()
        #如果服务返回的是 200 OK，这行代码什么都不做，继续往下走。
        #如果服务返回了 400（参数错）、401（没权限）、404（找不到接口）或 500（内部报错），这行代码会立刻抛出异常（httpx.HTTPStatusError），中断当前函数。
        data = resp.json()
        docs = data.get("documents", [])
        if not docs:
            return json.dumps({"error": "未找到相关 SOP"}, ensure_ascii=False)
        top = docs[0]
        # 数据流转：保持 Phase 14 的返回契约，模型看到的内容格式不变
        return json.dumps(
            {"source": top.get("source", "VectorDB"),
             "content": top.get("content", ""),
             "score": top.get("score", 0.0)},
            ensure_ascii=False,
        )
    except httpx.HTTPError as e:
        # 数据流转：RAG 不可用时优雅降级——返回 error JSON，模型会看到并继续
        return json.dumps({"error": f"RAG 服务不可用: {e}"}, ensure_ascii=False)


@registry.register(name="exec_diagnostic_cmd", description="执行只读的系统诊断命令（如查进程、查磁盘）", args_schema=ExecArgs, required_permission="read")
def exec_diagnostic_cmd(args_schema: ExecArgs):
    cmd_str = args_schema.command.strip().lower()
    
    # 1. 提取主命令
    base_cmd = cmd_str.split()[0]
    
    
    # 2. 跨平台命令转换（如果是 Windows 系统）
    if platform.system() == "Windows":
        if base_cmd == "top":
            #cmd_str = "tasklist | findstr /I \"java python\"" # 模拟查高占用进程
            cmd_str = "tasklist" 
        elif base_cmd == "df":
            cmd_str = "wmic logicaldisk get size,freespace,caption"
            
    # 3. 重新校验白名单
    final_base_cmd = cmd_str.split()[0]
    if final_base_cmd not in ALLOWED_COMMANDS:
        return json.dumps({"error": f"权限拒绝：命令 '{final_base_cmd}' 不在白名单中"}, ensure_ascii=False)

    # 4. 真实执行：使用 subprocess 捕获输出，设置 10 秒超时熔断
    try:
        # 注意：如果是 Windows 跑这段代码，可能需要把 'top' 换成别的命令，比如 'tasklist'
        result = subprocess.run(
            cmd_str,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10  # 防止死循环
        )
        
        # 3. 格式化返回：将真实的执行结果返回给大模型
        return json.dumps({
            "stdout": result.stdout[:1000], # 截断输出，防止撑爆上下文
            "stderr": result.stderr[:500],
            "exitCode": result.returncode
        }, ensure_ascii=False)
        
    except subprocess.TimeoutExpired:
        return json.dumps({"error": "执行超时，命令已被系统强制终止"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": f"执行引擎异常: {str(e)}"}, ensure_ascii=False)