# creation_manager.py (v14.11 - 提示词文件化)
import os
import re
import json
import time
import asyncio
import shutil
import uuid
import traceback
from typing import Dict, List, Optional
from message_bus import MessageBus
from atomic_actions import generate_text, save_file
from causality_graph import CausalityGraph
import ollama
from model_router import ModelRouter
from prompts.registry import get_prompt


class CreationManager:
    """专业创作管理器 v14.11 - 提示词文件化"""
    def __init__(self, bus: MessageBus, palace_memory=None):
        self.bus = bus
        self.palace = palace_memory
        self.desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        self.creation_root = os.path.join(self.desktop, "创作")
        self.novel_root = os.path.join(self.creation_root, "小说类")
        self.bookshelf_dir = os.path.join(self.desktop, "bookshelf")
        os.makedirs(self.bookshelf_dir, exist_ok=True)
        self.router = getattr(bus, 'model_router', None) or ModelRouter(max_concurrent_requests=1)
        self.ollama_options = {"num_ctx": 32768, "num_predict": 3275}
        self.creative_model = "qwen3.5:9b"
        self.causality_graph = CausalityGraph()

    # ---------- 项目初始化（略，保持不变） ----------
    def ensure_project_structure(self, novel_name: str) -> str:
        project_path = os.path.join(self.novel_root, novel_name)
        folders = ["00_世界设定","01_人物设定","02_章节索引","03_正文章节","04_伏笔管理","05_创作笔记"]
        for folder in folders: os.makedirs(os.path.join(project_path, folder), exist_ok=True)
        self._init_world_setting(project_path, novel_name); self._init_character_setting(project_path)
        self._init_chapter_index(project_path); self._init_foreshadowing(project_path)
        self._init_story_planning(project_path)
        return project_path

    def _init_world_setting(self, project_path: str, novel_name: str):
        path = os.path.join(project_path, "00_世界设定", "世界设定.txt")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f: f.write(f"【作品名称】{novel_name}\n【时代背景】\n【主要地域】\n【修炼体系】\n【势力分布】\n【核心规则】\n")
    def _init_character_setting(self, project_path: str):
        path = os.path.join(project_path, "01_人物设定", "人物设定.json")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f: json.dump({"protagonist":{"name":"","age":0,"traits":[],"background":"","goal":""},"supporting":[],"antagonists":[],"relations":[]}, f, indent=2, ensure_ascii=False)
    def _init_chapter_index(self, project_path: str):
        path = os.path.join(project_path, "02_章节索引", "章节索引.json")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f: json.dump({"chapters":[],"latest_chapter":0,"total_words":0}, f, indent=2, ensure_ascii=False)
    def _init_foreshadowing(self, project_path: str):
        path = os.path.join(project_path, "04_伏笔管理", "伏笔清单.json")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f: json.dump({"foreshadows":[]}, f, indent=2, ensure_ascii=False)
    def _init_story_planning(self, project_path: str):
        path = os.path.join(project_path, "00_世界设定", "剧情规划.json")
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f: json.dump({"story_arcs":[{"chapter":10,"event":"主角获得第一件重要法宝","type":"milestone"},{"chapter":20,"event":"首次正面击败主要反派","type":"climax"},{"chapter":30,"event":"发现身世之谜","type":"revelation"}],"ending_direction":"主角最终成为一方强者，守护了所爱之人与家族"}, f, indent=2, ensure_ascii=False)

    # ---------- 辅助方法 ----------
    def _load_chapter_excerpt(self, project_path: str, chapter_num: int, context_query: str, excerpt_length: int = 400) -> str:
        chapter_path = os.path.join(project_path, "03_正文章节", f"第{chapter_num}章.txt")
        if not os.path.exists(chapter_path): return ""
        with open(chapter_path, "r", encoding="utf-8") as f: full_text = f.read()
        if len(full_text) <= excerpt_length * 2: return full_text[:excerpt_length] + "..."
        best_pos=0
        for kw in context_query[:30].split():
            if len(kw)<2: continue
            pos=full_text.find(kw)
            if pos!=-1: best_pos=max(0,pos-excerpt_length//2); break
        return f"（第{chapter_num}章原文片段）...{full_text[best_pos:best_pos+excerpt_length]}..."

    # ---------- 智能上下文构建 ----------
    def build_context(self, project_path: str, goal: str) -> str:
        parts = []; novel_name = os.path.basename(project_path)
        world_path = os.path.join(project_path, "00_世界设定", "世界设定.txt")
        if os.path.exists(world_path):
            with open(world_path, "r", encoding="utf-8") as f: parts.append("【世界设定】\n" + f.read() + "\n")
        char_path = os.path.join(project_path, "01_人物设定", "人物设定.json")
        if os.path.exists(char_path):
            with open(char_path, "r", encoding="utf-8") as f: parts.append(self._format_characters(json.load(f)))
        index_path = os.path.join(project_path, "02_章节索引", "章节索引.json")
        latest_chapter_num = 0
        if os.path.exists(index_path):
            with open(index_path, "r", encoding="utf-8") as f: index = json.load(f); latest_chapter_num = index.get("latest_chapter",0); parts.append(self._format_chapter_index(index))
        planning_path = os.path.join(project_path, "00_世界设定", "剧情规划.json")
        if os.path.exists(planning_path):
            with open(planning_path, "r", encoding="utf-8") as f: parts.append(self._format_story_planning(json.load(f), latest_chapter_num))
        fore_path = os.path.join(project_path, "04_伏笔管理", "伏笔清单.json")
        if os.path.exists(fore_path):
            with open(fore_path, "r", encoding="utf-8") as f: parts.append(self._format_foreshadows(json.load(f)))
        if self.palace:
            creative_category = f"创作/{novel_name}"
            style_memories = self.palace.retrieve_by_semantic(query=f"小说 {novel_name} 文风 描写", top_k=3, threshold=0.4, mem_type="writing_style", category_prefix=creative_category)
            if style_memories: parts.append("【文风参考】\n" + "\n".join([m['answer'] for m in style_memories]) + "\n")
            plot_memories = self.palace.retrieve_by_semantic(query=goal, top_k=2, threshold=0.4, mem_type="plot_pattern", category_prefix=creative_category)
            if plot_memories: parts.append("【类似情节参考】\n" + "\n".join([m['answer'] for m in plot_memories]) + "\n")
            try:
                history_memories = self.palace.retrieve_by_semantic(query=f"{novel_name} {goal}", top_k=5, threshold=0.4, mem_type="fact", category_prefix=creative_category, include_chaos=False)
                filtered_history = [m for m in history_memories if m.get("footnote",{}).get("source","") in ["writing_style_extractor","plot_extractor","creation_manager","dialogue","foreshadow_detector"] and f"第{latest_chapter_num}章" not in m.get("question","")]
                if filtered_history:
                    parts.append("【伏笔与历史情节回忆】\n")
                    for mem in filtered_history[:3]:
                        parts.append(f"- 相关记忆：{mem.get('question','')[:50]}\n  内容摘要：{mem.get('answer','')[:200]}...\n")
                    parts.append("请在续写时自然地呼应这些历史情节，体现故事的连贯性。\n")
                    high_similarity = [(m.get("retrieval_score",0),) for m in filtered_history if m.get("retrieval_score",0)>0.7]
            except Exception as e: print(f"检索历史情节记忆失败: {e}")
        notes_dir = os.path.join(project_path, "05_创作笔记")
        if os.path.exists(notes_dir):
            notes = [f for f in os.listdir(notes_dir) if f.endswith('.txt')]
            if notes:
                lines = ["【创作指引】"]
                for nf in sorted(notes):
                    with open(os.path.join(notes_dir, nf), "r", encoding="utf-8") as f:
                        lines.append(f"· {nf[:-4]}: {f.read().strip()}")
                lines.append("请在创作时融入上述指引，但应自然流畅，不生硬堆砌。\n")
                parts.append("\n".join(lines))
        latest_chapter = self._get_latest_chapter(project_path)
        if latest_chapter:
            chapter_path = os.path.join(project_path, "03_正文章节", f"第{latest_chapter}章.txt")
            if os.path.exists(chapter_path):
                with open(chapter_path, "r", encoding="utf-8") as f: parts.append(f"【最新章结尾（第{latest_chapter}章）】\n{f.read()[-1500:]}\n")
        causality_summary = self.causality_graph.get_context_summary(project_path, latest_chapter_num)
        if causality_summary: parts.append(causality_summary)
        if self.palace:
            try:
                spark_memories = self.palace.retrieve_by_semantic(query=f"灵感 创意 跨界 {random.choice(['宇宙','历史','艺术','科学','神话'])}", top_k=2, threshold=0.25, mem_type="fact", include_chaos=True)
                if spark_memories:
                    sparks = [f"- ✨ {m.get('answer','')[:100]}" for m in spark_memories]
                    parts.append("【随机创意火花】\n" + "\n".join(sparks) + "\n")
            except: pass
        return "\n".join(parts)

    def _format_characters(self, chars): pass # 保持不变
    def _format_chapter_index(self, index): pass
    def _format_story_planning(self, planning, current): pass
    def _format_foreshadows(self, fores): pass
    def _get_latest_chapter(self, project_path: str) -> int:
        d = os.path.join(project_path, "03_正文章节")
        if not os.path.exists(d): return 0
        return max([int(re.search(r'第(\d+)章', f).group(1)) for f in os.listdir(d) if re.search(r'第(\d+)章', f)] + [0])

    # ---------- 章节生成 ----------
    async def generate_chapter(self, project_path: str, goal: str, chapter_num: int = None):
        novel_name = os.path.basename(project_path)
        if chapter_num is None: chapter_num = self._get_latest_chapter(project_path) + 1
        context = self.build_context(project_path, goal)

        # ✅ 提示词文件化
        chapter_template = get_prompt("creation/generate_chapter.txt") or (
            "你是一位专业的小说作家... (完整降级内容)"
        )
        prompt = chapter_template.format(context=context, goal=goal, chapter_num=chapter_num)

        self.bus.publish("output.display", f"📝 正在创作第{chapter_num}章...")
        try:
            if self.router:
                content = await self.router.call_async(role="creator", messages=[{"role":"user","content":prompt}])
            else:
                result = await generate_text({"prompt":prompt,"max_tokens":3275,"options":self.ollama_options,"model":self.creative_model},{})
                content = result.get("content","") if result.get("success") else ""
        except Exception as e:
            self.bus.publish("output.display", f"❌ 创作调用失败: {e}")
            return None

        if not content: self.bus.publish("output.display", "❌ 生成内容为空"); return None
        chapter_path = os.path.join(project_path, "03_正文章节", f"第{chapter_num}章.txt")
        await save_file({"filename": os.path.relpath(chapter_path, self.desktop), "location":"desktop", "content":content}, {})
        self.bus.publish("output.display", f"✅ 第{chapter_num}章已保存")
        self._copy_to_bookshelf(chapter_path, novel_name, chapter_num)
        await self._update_chapter_index(project_path, chapter_num, content)
        asyncio.create_task(self._extract_writing_style(content, novel_name, chapter_num))
        asyncio.create_task(self._extract_plot_pattern(content, novel_name, chapter_num))
        asyncio.create_task(self._extract_and_update_settings(project_path, chapter_num, content))
        asyncio.create_task(self._update_causality_graph(project_path))
        return content

    def _copy_to_bookshelf(self, src, name, num):
        try: shutil.copy(src, os.path.join(self.bookshelf_dir, f"{name}_第{num}章.txt"))
        except Exception as e: print(f"书架复制失败: {e}")

    async def _update_chapter_index(self, project_path: str, chapter_num: int, content: str):
        idx_path = os.path.join(project_path, "02_章节索引", "章节索引.json")
        with open(idx_path, "r", encoding="utf-8") as f: idx = json.load(f)
        # ✅ 提示词文件化
        summary_template = get_prompt("creation/summarize_chapter.txt") or "请用一句话（不超过30字）概括以下小说章节的核心事件：\n{content}"
        prompt = summary_template.format(content=content[:800])
        core = f"第{chapter_num}章内容"
        try:
            if self.router: core = await self.router.call_async(role="light_task", messages=[{"role":"user","content":prompt}])
            else:
                sr = await generate_text({"prompt":prompt,"max_tokens":60,"options":self.ollama_options,"model":"qwen3.5:4b"},{})
                if sr.get("success"): core = sr["content"]
        except: pass
        idx["chapters"].append({"num":chapter_num,"core_event":core.strip(),"new_characters":[],"foreshadow_planted":[],"word_count":len(content)})
        idx["latest_chapter"]=chapter_num; idx["total_words"]=sum(ch.get("word_count",0) for ch in idx["chapters"])
        with open(idx_path,"w",encoding="utf-8") as f: json.dump(idx,f,indent=2,ensure_ascii=False)

    async def _extract_writing_style(self, chapter_content, novel_name, chapter_num):
        if not self.palace: return
        # ✅ 提示词文件化
        template = get_prompt("creation/extract_writing_style.txt") or "请分析以下小说片段的文风特征，用一句话概括（不超过40字）：\n{content}\n输出格式：文风特征描述。"
        prompt = template.format(content=chapter_content[:1000])
        try:
            style_desc = (await self.router.call_async(role="creator", messages=[{"role":"user","content":prompt}])) if self.router else (await generate_text({"prompt":prompt,"max_tokens":60,"options":self.ollama_options,"model":self.creative_model},{})).get("content","")
            if style_desc and self.palace:
                self.palace.add_to_chaos(question=f"《{novel_name}》第{chapter_num}章文风特征", answer=style_desc, utility=0.7, source="writing_style_extractor", mem_type="writing_style", custom_footnote={"summary":f"文风：{style_desc[:30]}","tags":["文风",novel_name],"category_path":f"创作/{novel_name}/文风"})
        except Exception as e: print(f"文风提取失败: {e}")

    async def _extract_plot_pattern(self, chapter_content, novel_name, chapter_num):
        if not self.palace: return
        # ✅ 提示词文件化
        template = get_prompt("creation/extract_plot_pattern.txt") or "请用一句话概括以下小说片段的情节模式（如「英雄遇险」、「秘境探索」、「师徒授艺」等）：\n{content}\n输出格式：情节模式名称。"
        prompt = template.format(content=chapter_content[:800])
        try:
            pattern = (await self.router.call_async(role="light_task", messages=[{"role":"user","content":prompt}])) if self.router else (await generate_text({"prompt":prompt,"max_tokens":30,"options":self.ollama_options,"model":self.creative_model},{})).get("content","")
            if pattern and self.palace:
                self.palace.add_to_chaos(question=f"《{novel_name}》第{chapter_num}章情节模式", answer=pattern, utility=0.6, source="plot_extractor", mem_type="plot_pattern", custom_footnote={"summary":f"情节：{pattern}","tags":["情节模式",novel_name],"category_path":f"创作/{novel_name}/情节"})
        except Exception as e: print(f"情节模式提取失败: {e}")

    async def _detect_foreshadows(self, project_path, chapter_num, content):
        analysis_text = content[:3000]
        fore_path = os.path.join(project_path, "04_伏笔管理", "伏笔清单.json")
        existing = []
        if os.path.exists(fore_path):
            with open(fore_path, "r", encoding="utf-8") as f: existing = [f for f in json.load(f).get("foreshadows",[]) if not f.get("resolved")]
        existing_desc = "\n".join([f"- ID:{f.get('id','?')} | 描述:{f.get('description','')} | 埋于第{f.get('planted_chapter','?')}章" for f in existing[:5]]) if existing else ""
        # ✅ 提示词文件化
        template = get_prompt("creation/detect_foreshadows.txt") or (
            "你是一位专业的小说编辑，擅长识别叙事中的伏笔。\n请分析以下小说章节内容... (完整降级)"
        )
        prompt = template.format(chapter_num=chapter_num, existing_desc=("当前未回收的伏笔：\n"+existing_desc) if existing_desc else "", analysis_text=analysis_text)
        try:
            response_text = await self.router.call_async(role="light_task", messages=[{"role":"user","content":prompt}], temperature=0.3) if self.router else (await asyncio.to_thread(ollama.chat, model="qwen2.5:3b", messages=[{"role":"user","content":prompt}], options={"temperature":0.3}))["message"]["content"]
            result = json.loads(re.search(r'\{.*\}', response_text, re.DOTALL).group(0) if re.search(r'\{.*\}', response_text, re.DOTALL) else response_text)
            if result.get("new_foreshadows") or result.get("resolved_foreshadows"):
                self._update_foreshadow_file(project_path, chapter_num, result["new_foreshadows"], result["resolved_foreshadows"])
        except Exception as e: print(f"伏笔检测失败: {e}")

    def _update_foreshadow_file(self, project_path, chapter_num, new_foreshadows, resolved_foreshadows):
        fore_path = os.path.join(project_path, "04_伏笔管理", "伏笔清单.json")
        data = json.load(open(fore_path, "r", encoding="utf-8")) if os.path.exists(fore_path) else {"foreshadows":[]}
        for desc in new_foreshadows:
            data["foreshadows"].append({"id":f"F{len(data['foreshadows'])+1:03d}","description":desc,"planted_chapter":chapter_num,"resolved":False,"resolved_chapter":None,"resolution":None})
        for res in resolved_foreshadows:
            for f in data["foreshadows"]:
                if f.get("id")==res.get("id") and not f["resolved"]: f["resolved"]=True; f["resolved_chapter"]=chapter_num; f["resolution"]=res.get("resolution","")
        with open(fore_path,"w",encoding="utf-8") as f: json.dump(data,f,indent=2,ensure_ascii=False)

    async def _update_causality_graph(self, project_path):
        try: await self.causality_graph.build_or_update_graph(project_path)
        except Exception as e: print(f"因果图谱更新失败: {e}")