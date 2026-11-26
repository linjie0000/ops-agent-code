# agent_core.py — Ops Agent 的核心逻辑层
# 数据流转：main.py (入口) → master_ops_agent (循环) → tools_ops (工具) / Ollama (推理)

import os
from tools_ops import registry  # 数据流转：导入底层已注册的工具表（含 RAG 与沙盒执行）

# ==========================================
# 组件 1：状态与记忆管理
# ==========================================
class ContextManager:
    def __init__(self, max_turns=5):
        self.max_turns = max_turns

    def count_tokens_roughly(self, messages):
        # 数据流转：将消息列表转为字符串计算字符数 → 粗略估算 Token（3字符≈1Token）
        total_chars = sum(len(str(msg)) for msg in messages)
        return total_chars // 3

    def compress(self, messages, client, model="qwen2.5"):
        # 数据流转：入参 messages 是包含 system/user/assistant/tool 的历史记录
        system_msg = messages[0]
        user_msg = messages[1]
        middle_messages = messages[2:]
        
        current_tokens = self.count_tokens_roughly(messages)
        is_turn_overflow = len(middle_messages) >= self.max_turns * 2
        is_token_overflow = current_tokens > 2000  # 数据流转：生产环境阈值需按模型上下文调整
        
        if not (is_turn_overflow or is_token_overflow):
            return messages

        print(f"⚠️ [ContextManager] 触发记忆压缩！(当前消息数: {len(messages)}, 估算Token: {current_tokens})")
        
        history_text = ""
        for msg in middle_messages:
            role = msg.role if hasattr(msg, 'role') else msg.get("role")
            
            if role == "assistant":
                content = msg.content if hasattr(msg, 'content') else msg.get("content")
                if content:
                    history_text += f"Agent思考: {content}\n"
                
                tool_calls = msg.tool_calls if hasattr(msg, 'tool_calls') else msg.get("tool_calls")
                if tool_calls:
                    names = []
                    for t in tool_calls:
                        if hasattr(t, 'function'):
                            names.append(t.function.name)
                        else:
                            names.append(t.get("function", {}).get("name", "unknown"))
                    history_text += f"Agent调用工具: {names}\n"
                    
            elif role == "tool":
                content = msg.content if hasattr(msg, 'content') else msg.get("content")
                history_text += f"工具返回: {str(content)[:100]}...\n"

        summary_prompt = f"""请将以下运维 Agent 的执行历史压缩成一段极简的摘要，保留关键的进展和发现的错误：
        {history_text}"""

        # 数据流转：将冗长历史发给 LLM → LLM 返回极简摘要
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": summary_prompt}]
        )
        summary = response.choices[0].message.content

        # 数据流转：重组上下文 = 原始 system + 原始 user + LLM生成的摘要
        new_messages = [
            system_msg,
            user_msg,
            {"role": "system", "content": f"【以下是前期的执行摘要，请基于此继续任务】:\n{summary}"}
        ]
        print(f"✅ 压缩完成！旧历史 {len(messages)} 条 -> 新历史 {len(new_messages)} 条")
        
        return new_messages

# ==========================================
# 组件 2：Master Agent 主循环
# ==========================================



def master_ops_agent(user_query, client, model="qwen2.5"):
    system_prompt = """你是一个 K8s/Linux 运维排障专家。
你有两个工具可用：search_ops_knowledge（查手册）和 exec_diagnostic_cmd（查系统）。
请严格遵循以下排查逻辑：
1. 先调用 search_ops_knowledge 找到对应的处理 SOP。如果找不到SOP则自行判断
2. 根据 SOP 的指导，调用 exec_diagnostic_cmd 获取真实的系统指标。
3. 结合 SOP 和指标，给出最终根因分析和处理建议。"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_query}
    ]
    
    context_mgr = ContextManager(max_turns=5)
    max_iterations = 10
    
    for i in range(max_iterations):
        print(f"\n--- [排障第 {i+1} 步] ---")
        
        # 1. 状态管理防爆仓
        messages = context_mgr.compress(messages, client, model)
        
        # 2. 请求模型
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=registry.tools_schema,
            tool_choice="auto"
        )
        
        msg = response.choices[0].message

        print("#########",msg)
        if msg.content:
            print(f"🧠 专家思考: {msg.content}")
            
        messages.append(msg)
        
        # 3. 终止条件
        if not msg.tool_calls:
            return msg.content
        
        # 4. 执行工具（带权限拦截）
        for tool_call in msg.tool_calls:
            f_name = tool_call.function.name
            f_args = tool_call.function.arguments
            print(f"🛠️ 执行动作: {f_name} | 入参: {f_args}")
            
            result = registry.execute(f_name, f_args, ["read"])
            print(f"📥 观测结果: {result[:120]}...")  # 截断打印
            
            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result
            })
            
    return "Agent 排查超时或陷入死循环。"