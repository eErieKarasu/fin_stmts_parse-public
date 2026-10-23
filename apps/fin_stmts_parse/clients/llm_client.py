from fin_stmts_parse.utils.logger import logger
from openai import OpenAI
import os
from fin_stmts_parse.utils.read_yaml import load_env_config
from typing import Dict, List, Optional


class LLMClient:
    def __init__(self, config):
        self.logger = logger
        self.config = config
        self.client = self._init_llm()
        # 提取所有 OpenAI API 参数
        self.default_params = self.config.get('parameters', {})

    def _init_llm(self):
        self.logger.info("[LIFECYCLE] 开始创建LLM对象")
        client = OpenAI(
            api_key="EMPTY",
            base_url=self.config.get("base_url"),
            default_headers={
                "Authorization": f"Bearer {self.config.get("api_key")}"
            }
        )
        self.logger.info("[LIFECYCLE] LLM对象创建成功")
        return client

    def _build_messages(self,
                        user_message: str,
                        system_prompt: Optional[str] = None,
                        history: Optional[List[Dict[str, str]]] = None) -> List[Dict[str, str]]:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        if history:
            for msg in history:
                if msg.get("role") not in ("user", "assistant", "system"):
                    raise ValueError("History 中 role 必须是 'user'、'assistant' 或 'system'")
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def chat(self,
             user_message: str,
             system_prompt: Optional[str] = None,
             history: Optional[List[Dict[str, str]]] = None,
             **override_params
             ) -> str:
        """
        同步调用，返回完整回复
        Args:
            user_message: 当前用户输入
            system_prompt: 系统提示词
            history: 历史对话
            **override_params: 运行时覆盖配置文件中的参数（如临时改 temperature）
        """
        messages = self._build_messages(user_message, system_prompt, history)

        # 合并：配置文件参数 + 运行时覆盖
        params = self.default_params.copy()
        params.update(override_params)
        params['model'] = self.config.get('model', "")
        params["messages"] = messages

        # 移除可能为 None 的字段（如 stop: null），避免某些后端报错
        params = {k: v for k, v in params.items() if v is not None}

        response = self.client.chat.completions.create(**params)
        return response.choices[0].message.content.strip()


    def stream_chat(self,
                    user_message: str,
                    system_prompt: Optional[str] = None,
                    history: Optional[List[Dict[str, str]]] = None,
                    **override_params
                    ):
        """流式响应（生成器）"""
        messages = self._build_messages(user_message, system_prompt, history)

        params = self.default_params.copy()
        params.update(override_params)
        params['model'] = self.config.get('model', "")
        params["messages"] = messages
        params["stream"] = True
        params = {k: v for k, v in params.items() if v is not None}

        stream = self.client.chat.completions.create(**params)
        for chunk in stream:
            content = chunk.choices[0].delta.content
            if content:
                yield content

if __name__ == "__main__":
    config = load_env_config(os.getenv("RUNNING_ENV", "local"))
    llm = LLMClient(config.get("llm", {}))
    system_prompt = """
请根据给定的现金流量表表头列表，生成【表头映射字典】。
你的任务是：  
将原始表头映射为如下标准字段（仅限以下字段）：
- 项目
- 本年累计金额
- 本期金额（如存在）

请严格遵循以下业务规则进行判断：
【规则 1】
表头中，“项目”和“本年累计金额”一定需要被识别并映射。
【规则 2】
若表头中同时存在“本期金额”和“上期金额”，  
则：
- “本期金额” → 映射为【本年累计金额】
- “上期金额” → 映射为【上年同期金额】
【规则 3】
若表头中同时存在“本期金额”和“本年累计金额”，  
则：
- “本年累计金额” → 映射为【本年累计金额】
- “本期金额” → 不作为本年累计金额使用
【规则 4】
若表头本身为【日期】或【数值型表头】（如“2023-12-31”“2024年”“金额1”“金额2”等），
且无法通过名称直接判断含义，则：
- 将【日期最新】或【数值最大】的列 → 映射为【本年累计金额】
- 次新的日期或次大的数值列 → 映射为【上年同期金额（如需要）】
【补充说明】
- 表头可能包含“金额”“发生额”“累计数”“合计”等语义相近表达，请结合语义理解。
- 不允许臆造不存在的字段。
- 若某标准字段无法识别，请不要输出该字段。
【输出约束】
请仅以JSON格式输出映射结果，格式如下：
｛"项目":"<原始表头名>","本年累计金额":"<原始表头名>"｝
    """
    user_message = """["项    目 ","行次","本期金额 ","上期金额 ",]"""
    msg = llm.chat(user_message=user_message,system_prompt=system_prompt)
    print(msg)
