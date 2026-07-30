# self_reviewer.py (v14.11 - 提示词文件化 + 修复语法错误)
"""
编辑型自审模块 - 数字生命体的质量守卫
======================================
在AI生成回答后，快速评估其相关性、一致性、完整性，
并决定是否需要修正。
v13.5 - 新增自我元认知积累，从错误中学习“我是谁”。
v14.8 - 集成 ModelRouter 统一模型调用。
v14.11- 提示词文件化，从 prompts/ 目录加载。
"""

import json
import re
import asyncio
from typing import Dict, Optional
import ollama
from model_router import ModelRouter
from prompts.registry import get_prompt


class SelfReviewer:
    """
    自审模块。使用轻量级本地模型对回答进行快速质量评估。
    支持将评估中发现的问题模式积累为自我认知（元记忆）。
    """

    def __init__(self, model: str = "qwen2.5:7b", palace_memory=None, router: Optional[ModelRouter] = None):
        self.model = model
        self.palace = palace_memory
        self.router = router or ModelRouter(max_concurrent_requests=1)

    async def review(self, 
                     user_request: str, 
                     ai_response: str, 
                     memory_context: str = "",
                     recent_history: str = "",
                     expected_style: Optional[str] = None) -> Dict:
        """
        对AI回答进行质量评估。
        返回包含各维度得分、问题列表、是否需要修正的字典。
        """
        style_constraint = ""
        if expected_style:
            style_constraint = f"\n用户指定的风格要求：{expected_style}"

        prompt = f"""你是一位严格的编辑。请审视以下AI对用户请求的回答，并从以下维度给出评估：

用户请求：{user_request}
{style_constraint}

对话历史中的关键信息：{recent_history[:500] if recent_history else "无"}

记忆库中的参考资料：{memory_context[:500] if memory_context else "无"}

AI回答：
{ai_response[:1500]}

请从以下维度评分（0-1）：
1. 相关性(relevance)：回答是否紧密围绕用户请求？是否引入了无关的外部人物、情节、广告或信息？
2. 一致性(consistency)：回答是否与对话历史和参考资料中已确立的信息保持一致？是否出现矛盾？
3. 完整性(completeness)：是否满足用户明确提出的字数、格式、风格要求？
4. 预测质量(predicted_feedback)：你估计用户给出正面反馈的概率是多少？

同时，列出发现的具体问题（如有），并判断是否需要修正。

请以JSON格式输出：
{{"relevance_score": 0.8, "consistency_score": 0.9, "completeness_score": 0.7, "predicted_feedback": 0.75, "issues": ["问题描述1", "问题描述2"], "needs_revision": false}}

只输出JSON，不要其他内容。"""

        try:
            if self.router:
                content = await self.router.call_async(
                    role="self_reviewer",
                    messages=[{"role": "user", "content": prompt}],
                )
            else:
                response = await ollama.AsyncClient().chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"num_predict": 300}
                )
                content = response['message']['content']
            
            content = content.strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = json.loads(content)
        except Exception as e:
            print(f"自审模块评估失败: {e}")
            result = {
                "relevance_score": 0.8,
                "consistency_score": 0.8,
                "completeness_score": 0.8,
                "predicted_feedback": 0.7,
                "issues": [],
                "needs_revision": False
            }

        if self.palace and (result.get("needs_revision", False) or 
                            result.get("relevance_score", 1.0) < 0.6 or
                            result.get("consistency_score", 1.0) < 0.6 or
                            result.get("completeness_score", 1.0) < 0.6):
            asyncio.create_task(self._store_meta_cognition(user_request, ai_response, result))

        return result

    async def _store_meta_cognition(self, user_request: str, ai_response: str, review_result: Dict):
        issues = review_result.get("issues", [])
        relevance = review_result.get("relevance_score", 0.8)
        consistency = review_result.get("consistency_score", 0.8)
        completeness = review_result.get("completeness_score", 0.8)

        issue_summary = "；".join(issues) if issues else "无明显具体问题"
        weak_areas = []
        if relevance < 0.6:
            weak_areas.append("相关性较弱，容易偏离主题或引入无关信息")
        if consistency < 0.6:
            weak_areas.append("与历史信息或参考资料不一致")
        if completeness < 0.6:
            weak_areas.append("回答不完整，未满足字数或格式要求")
        weak_desc = "；".join(weak_areas) if weak_areas else "整体表现尚可，但仍有改进空间"

        # ✅ 提示词文件化（降级字符串使用三引号避免引号冲突）
        prompt_template = get_prompt("self_reviewer/meta_cognition.txt") or '''
你是一个正在自我反思的AI系统。根据以下信息，提炼出一句关于"我"的自我认知（不超过30字），用第一人称表达我从这次回答中认识到的自己的不足或特点。

用户请求：{user_request}
AI回答：{ai_response}
发现的问题：{issue_summary}
低分维度：{weak_desc}

请只输出一句中文自我认知，不要前缀。'''
        prompt = prompt_template.format(
            user_request=user_request[:100],
            ai_response=ai_response[:200],
            issue_summary=issue_summary,
            weak_desc=weak_desc
        )

        try:
            if self.router:
                cognition = await self.router.call_async(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                )
            else:
                response = await ollama.AsyncClient().chat(
                    model="qwen3.5:4b",
                    messages=[{"role": "user", "content": prompt}],
                    options={"num_predict": 60}
                )
                cognition = response['message']['content']
            
            cognition = cognition.strip()
            if cognition:
                self.palace.add_to_chaos(
                    question="自我认知反思",
                    answer=cognition,
                    utility=0.6,
                    source="self_reviewer",
                    mem_type="self_meta"
                )
                print(f"🧠 [自我认知] 已记录：{cognition}")
        except Exception as e:
            print(f"存储自我认知失败: {e}")

    def determine_revision_strategy(self, review_result: Dict) -> str:
        if not review_result.get("needs_revision", False):
            return "none"

        relevance = review_result.get("relevance_score", 0.8)
        consistency = review_result.get("consistency_score", 0.8)
        completeness = review_result.get("completeness_score", 0.8)

        if relevance < 0.5:
            return "regenerate_no_search"
        elif consistency < 0.5:
            return "regenerate_with_memory"
        elif completeness < 0.5:
            return "regenerate_with_constraints"
        elif any("无关" in issue or "外部" in issue or "广告" in issue for issue in review_result.get("issues", [])):
            return "simplify"
        elif any("矛盾" in issue or "不一致" in issue for issue in review_result.get("issues", [])):
            return "regenerate_with_memory"
        else:
            return "regenerate"