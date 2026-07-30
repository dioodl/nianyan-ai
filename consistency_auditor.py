# consistency_auditor.py
"""
一致性审计模块 - 长篇创作的设定守护者
======================================
定期扫描小说项目的所有章节，检测设定矛盾、性格漂移、时间线错乱。
P1 实现：基于轻量模型逐章对比核心设定与人物性格。
v14.10 - 集成模型路由器，移除 num_predict 硬编码。
"""

import os
import json
import re
import asyncio
import time
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import ollama
from model_router import ModelRouter


class ConsistencyAuditor:
    """
    一致性审计器。
    对指定的小说项目进行全文章节扫描，生成审计报告。
    """

    def __init__(self, model: str = "qwen3.5:4b", router: ModelRouter = None):
        self.model = model
        self.router = router or ModelRouter(max_concurrent_requests=1)
        self.report_dir = "consistency_reports"
        os.makedirs(self.report_dir, exist_ok=True)

    async def audit_project(self, project_path: str) -> Dict:
        """
        对单个项目执行完整审计。
        返回审计报告字典，并保存为 JSON 文件。
        """
        novel_name = os.path.basename(project_path)
        print(f"🔍 [一致性审计] 开始扫描《{novel_name}》...")

        # 1. 收集审计素材
        world_setting = self._load_world_setting(project_path)
        characters = self._load_characters(project_path)
        chapter_summaries = self._load_chapter_summaries(project_path)

        if len(chapter_summaries) < 3:
            print(f"⏭️ [一致性审计] 《{novel_name}》章节数不足3章，跳过")
            return {"status": "skipped", "reason": "insufficient_chapters"}

        # 2. 执行分项审计
        issues = []
        issues.extend(await self._audit_character_consistency(project_path, characters, chapter_summaries))
        issues.extend(await self._audit_setting_consistency(project_path, world_setting, chapter_summaries))
        issues.extend(await self._audit_timeline_consistency(project_path, chapter_summaries))

        # 3. 生成报告
        report = {
            "novel_name": novel_name,
            "project_path": project_path,
            "audit_time": time.time(),
            "audit_time_str": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_chapters": len(chapter_summaries),
            "issues_count": len(issues),
            "issues": issues
        }

        # 4. 保存报告
        report_file = os.path.join(
            self.report_dir,
            f"{novel_name}_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"✅ [一致性审计] 《{novel_name}》完成，发现 {len(issues)} 个问题。报告：{report_file}")
        return report

    # ---------- 素材加载 ----------
    def _load_world_setting(self, project_path: str) -> str:
        path = os.path.join(project_path, "00_世界设定", "世界设定.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return ""

    def _load_characters(self, project_path: str) -> Dict:
        path = os.path.join(project_path, "01_人物设定", "人物设定.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_chapter_summaries(self, project_path: str) -> List[Dict]:
        path = os.path.join(project_path, "02_章节索引", "章节索引.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("chapters", [])
        return []

    def _load_chapter_content(self, project_path: str, chapter_num: int) -> str:
        chapter_path = os.path.join(project_path, "03_正文章节", f"第{chapter_num}章.txt")
        if os.path.exists(chapter_path):
            with open(chapter_path, "r", encoding="utf-8") as f:
                return f.read()[:2000]
        return ""

    # ---------- 审计子模块 ----------
    async def _audit_character_consistency(self, project_path: str, characters: Dict, 
                                           chapter_summaries: List[Dict]) -> List[Dict]:
        """审计人物性格与关系的一致性"""
        issues = []
        protagonist = characters.get("protagonist", {})
        proto_name = protagonist.get("name", "")
        proto_traits = protagonist.get("traits", [])

        if not proto_name or not proto_traits:
            return issues

        sample_indices = [0, len(chapter_summaries) // 2, -1]
        samples = []
        for idx in sample_indices:
            if 0 <= idx < len(chapter_summaries) or (idx == -1 and chapter_summaries):
                ch = chapter_summaries[idx]
                content = self._load_chapter_content(project_path, ch["num"])
                if content:
                    samples.append({"num": ch["num"], "content": content[:1500]})

        if len(samples) < 2:
            return issues

        proto_desc = f"{proto_name}，性格特点：{', '.join(proto_traits)}"
        samples_text = ""
        for s in samples:
            samples_text += f"\n【第{s['num']}章片段】\n{s['content']}\n"

        prompt = f"""你是一位严格的小说编辑。请对比以下人物设定与不同章节中的实际表现，判断是否存在**性格漂移**或**行为矛盾**。

人物设定：{proto_desc}

章节片段：{samples_text}

请检查：
1. 主角的行为是否与其设定性格一致？
2. 不同章节中，主角的性格表现是否有明显矛盾？（例如前期善良，后期突然残忍）
3. 配角关系是否前后矛盾？

如果有问题，请以 JSON 格式输出：
{{"issues": [{{"type": "character_drift", "chapter_range": "第X章-第Y章", "description": "问题描述"}}]}}
如果没有问题，输出：{{"issues": []}}

只输出 JSON，不要其他内容。"""

        try:
            if self.router:
                result_text = await self.router.call_async(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
            else:
                response = await asyncio.to_thread(
                    ollama.chat,
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2}
                )
                result_text = response['message']['content']

            result_text = result_text.strip()
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                for issue in result.get("issues", []):
                    issue["category"] = "character"
                    issues.append(issue)
        except Exception as e:
            print(f"性格审计失败: {e}")

        return issues

    async def _audit_setting_consistency(self, project_path: str, world_setting: str,
                                         chapter_summaries: List[Dict]) -> List[Dict]:
        """审计世界观设定的一致性"""
        issues = []
        if not world_setting or len(chapter_summaries) < 5:
            return issues

        latest = chapter_summaries[-1]
        content = self._load_chapter_content(project_path, latest["num"])
        if not content:
            return issues

        prompt = f"""你是一位严格的小说编辑。请对比以下世界观设定与最新章节的内容，判断是否存在**设定矛盾**。

【世界观设定】
{world_setting[:1000]}

【最新章节（第{latest['num']}章）内容】
核心事件：{latest.get('core_event', '')}
正文片段：{content[:1500]}

请检查：
1. 最新章节是否出现了与世界观设定矛盾的元素？（例如设定中魔法已消失，但章节中却出现魔法）
2. 修炼体系、势力分布、核心规则是否被违反？

如果有问题，请以 JSON 格式输出：
{{"issues": [{{"type": "setting_contradiction", "chapter": {latest['num']}, "description": "问题描述"}}]}}
如果没有问题，输出：{{"issues": []}}

只输出 JSON，不要其他内容。"""

        try:
            if self.router:
                result_text = await self.router.call_async(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
            else:
                response = await asyncio.to_thread(
                    ollama.chat,
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2}
                )
                result_text = response['message']['content']

            result_text = result_text.strip()
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                for issue in result.get("issues", []):
                    issue["category"] = "setting"
                    issues.append(issue)
        except Exception as e:
            print(f"设定审计失败: {e}")

        return issues

    async def _audit_timeline_consistency(self, project_path: str, 
                                          chapter_summaries: List[Dict]) -> List[Dict]:
        """审计时间线的一致性"""
        issues = []
        if len(chapter_summaries) < 5:
            return issues

        timeline = ""
        for ch in chapter_summaries[-10:]:
            timeline += f"第{ch['num']}章：{ch.get('core_event', '')}\n"

        prompt = f"""你是一位严格的小说编辑。请检查以下章节的时间线是否存在**明显错乱**。

章节事件序列：
{timeline}

请判断：
1. 事件的发生顺序是否符合逻辑？（例如角色死亡后又出现）
2. 时间跨度描述是否矛盾？（例如前文说过了三年，后文说只过了一个月）

如果有问题，请以 JSON 格式输出：
{{"issues": [{{"type": "timeline_error", "chapter_range": "第X章-第Y章", "description": "问题描述"}}]}}
如果没有问题，输出：{{"issues": []}}

只输出 JSON，不要其他内容。"""

        try:
            if self.router:
                result_text = await self.router.call_async(
                    role="light_task",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.2
                )
            else:
                response = await asyncio.to_thread(
                    ollama.chat,
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.2}
                )
                result_text = response['message']['content']

            result_text = result_text.strip()
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result = json.loads(json_match.group())
                for issue in result.get("issues", []):
                    issue["category"] = "timeline"
                    issues.append(issue)
        except Exception as e:
            print(f"时间线审计失败: {e}")

        return issues

    # ---------- 批量审计入口 ----------
    async def audit_all_projects(self, novel_root: str = None) -> List[Dict]:
        """审计所有小说项目"""
        if novel_root is None:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            novel_root = os.path.join(desktop, "创作", "小说类")

        if not os.path.exists(novel_root):
            print(f"⚠️ 小说目录不存在: {novel_root}")
            return []

        reports = []
        for novel_name in os.listdir(novel_root):
            project_path = os.path.join(novel_root, novel_name)
            if os.path.isdir(project_path):
                report = await self.audit_project(project_path)
                if report.get("status") != "skipped":
                    reports.append(report)

        return reports


# 供 internal_monitor 调用的同步入口
def run_consistency_audit():
    """同步入口，供 internal_monitor 每日调用"""
    auditor = ConsistencyAuditor()
    try:
        reports = asyncio.run(auditor.audit_all_projects())
        if reports:
            total_issues = sum(r.get("issues_count", 0) for r in reports)
            print(f"📋 [一致性审计] 全部完成，共扫描 {len(reports)} 个项目，发现 {total_issues} 个问题。")
        return reports
    except Exception as e:
        print(f"❌ [一致性审计] 执行失败: {e}")
        return []