# tools/deep_reader.py (多级瀑布版 - 自适应中间层)
"""
深度阅读器 - 自适应多级摘要流水线
====================================
根据中间材料的总长度，自动插入额外的提炼层级，
确保最终蒸馏阶段不会超出模型上下文窗口。
"""

import asyncio
import time
import gc
from typing import List, Dict, Optional, Any
from model_router import ModelRouter


class DeepReader:
    def __init__(self, router: ModelRouter, memory=None, max_parallel_blocks: int = 1):
        self.router = router
        self.memory = memory
        self.max_parallel_blocks = max_parallel_blocks

    async def deep_read(self, params: dict, context: dict = None) -> dict:
        mode = params.get("mode", "novel")
        source = params.get("source")
        target_length = params.get("target_length", 32000)

        if not source:
            return {"success": False, "error": "未提供 source 参数"}

        try:
            if mode == "novel":
                block_iterator = self._stream_blocks(source, target_tokens=28000)
                blocks = []
                for block in block_iterator:
                    blocks.append(block)
                if not blocks:
                    return {"success": False, "error": "文件为空"}
            elif mode == "memory":
                entries = self._query_memory(source)
                if not entries:
                    return {"success": False, "error": "未检索到任何记忆"}
                blocks = self._group_memory_entries(entries)
            else:
                return {"success": False, "error": f"未知模式: {mode}"}

            if not blocks:
                return {"success": False, "error": "没有可用于处理的文本块"}

            # L1：原子摘要
            atomic_summaries = await self._process_atomic_blocks(blocks)

            # L2：段落合成
            paragraph_summaries = await self._synthesize_paragraphs(atomic_summaries)

            # 动态决定是否需要中间层
            final_input = paragraph_summaries
            # 安全窗口：最终蒸馏模型的 max_tokens 设定约 24K tokens，对应约 48000 字符
            safe_input_chars = 48000

            if self._total_chars(final_input) > safe_input_chars:
                print("📖 [深度阅读] 段落摘要总长超出安全窗口，自动插入中间提炼层...")
                # L2.5：中间提炼（章节合成）
                chapter_summaries = await self._compress_to_target(
                    paragraph_summaries, 
                    target_group_size=5, 
                    max_target_chars=safe_input_chars
                )
                final_input = chapter_summaries

            # L3：最终蒸馏
            final = await self._final_distill(final_input, target_length)

            return {"success": True, "content": final}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _total_chars(self, texts: List[str]) -> int:
        return sum(len(t) for t in texts)

    async def _compress_to_target(self, summaries: List[str], target_group_size: int, max_target_chars: int) -> List[str]:
        """
        将摘要列表再次压缩，直到总字符数低于 max_target_chars
        """
        current = summaries
        while self._total_chars(current) > max_target_chars:
            new_current = []
            for i in range(0, len(current), target_group_size):
                group = current[i:i+target_group_size]
                if len(group) == 1:
                    new_current.append(group[0])
                    continue
                combined = " ".join(group)
                prompt = f"""你是一位资深的编辑。请将以下几段摘要合并成一个连贯的段落（约2000字），保留核心信息、逻辑链条和关键细节。

摘要片段：
{combined}

合并后的段落："""
                try:
                    para = await self.router.call_async(
                        role="creator",
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.5,
                    )
                    new_current.append(para.strip())
                except Exception as e:
                    print(f"中间压缩失败: {e}")
                    new_current.append(combined[:2000])
            current = new_current
            # 释放上一轮变量（可选）
            gc.collect()
        return current

    # ---------- 流式文件读取 ----------
    def _stream_blocks(self, file_path: str, target_tokens: int = 28000, overlap_chars: int = 500):
        chunk_size = target_tokens * 2
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                while True:
                    buffer = f.read(chunk_size)
                    if not buffer:
                        break
                    yield buffer
                    current_pos = f.tell()
                    if current_pos >= chunk_size:
                        f.seek(current_pos - overlap_chars)
        except Exception as e:
            print(f"流式读取文件失败: {e}")

    # ---------- 核心流水线 ----------
    async def _process_atomic_blocks(self, blocks: List[str]) -> List[str]:
        summaries = []
        for i, block in enumerate(blocks):
            summary = await self._summarize_block(block, i)
            if summary:
                summaries.append(summary)
            blocks[i] = None
            gc.collect()
        return summaries

    async def _summarize_block(self, block: str, index: int) -> str:
        if len(block) < 500:
            return block
        prompt = f"""请精炼以下内容的核心要素，用一段话概括（不超过800字）：
- 主要事件、人物、情感变化
- 关键设定、伏笔或悬念
- 任何重要的转折或冲突

内容：
{block[:6000]}

核心摘要："""
        try:
            summary = await self.router.call_async(
                role="researcher",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.4,
            )
            return summary.strip()
        except Exception as e:
            print(f"原子摘要生成失败 (块{index}): {e}")
            return block[:800]

    async def _synthesize_paragraphs(self, atomic_summaries: List[str]) -> List[str]:
        if not atomic_summaries:
            return []
        paragraphs = []
        context = ""
        for i in range(0, len(atomic_summaries), 3):
            group = atomic_summaries[i:i+3]
            combined = " ".join(group)
            prompt = f"""你是一位资深的编辑。请将以下若干章节的摘要合并成一个连贯的段落（约1500字），确保逻辑清晰、情感线索连贯。
{'前情提要：' + context[:1000] if context else '这是开头部分。'}

章节摘要：
{combined}

合并后的段落："""
            try:
                para = await self.router.call_async(
                    role="creator",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.5,
                )
                para = para.strip()
                paragraphs.append(para)
                context = para
            except Exception as e:
                print(f"段落合成失败: {e}")
                paragraphs.append(combined[:1500])
        return paragraphs

    async def _final_distill(self, summaries: List[str], target_length: int) -> str:
        if not summaries:
            return ""
        combined = "\n\n".join(summaries)
        if len(combined) <= target_length * 1.2:
            return combined[:target_length]
        prompt = f"""你是一位博学的文学评论家。请根据以下分段摘要，撰写一篇完整、连贯、去重的精读报告（不超过{target_length}字）。
要求：
- 保留核心故事脉络和人物弧光
- 指出关键转折点和主题思想
- 语言精炼、有洞察力

分段摘要：
{combined}

精读报告："""
        try:
            final = await self.router.call_async(
                role="creator",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            return final.strip()
        except Exception as e:
            print(f"最终蒸馏失败: {e}")
            return combined[:target_length]

    # ---------- 记忆相关 ----------
    def _query_memory(self, query_spec: Any) -> List[Dict]:
        if not self.memory:
            return []
        if isinstance(query_spec, str):
            return self.memory.retrieve_by_semantic(query=query_spec, top_k=200, threshold=0.3, mem_type="fact")
        elif isinstance(query_spec, dict):
            return self.memory.retrieve_by_semantic(
                query=query_spec.get("query", ""),
                top_k=query_spec.get("top_k", 200),
                threshold=query_spec.get("threshold", 0.3),
                mem_type=query_spec.get("mem_type", "fact"),
                time_bias=query_spec.get("time_bias"),
                time_range_start=query_spec.get("time_range_start"),
                time_range_end=query_spec.get("time_range_end")
            )
        return []

    def _group_memory_entries(self, entries: List[Dict], style: str = "time", max_per_group: int = 50) -> List[str]:
        if not entries:
            return []
        entries_sorted = sorted(entries, key=lambda e: e.get("timestamp", 0))
        if style == "count":
            groups = [entries_sorted[i:i+max_per_group] for i in range(0, len(entries_sorted), max_per_group)]
        else:
            groups = {}
            for entry in entries_sorted:
                ts = entry.get("timestamp", 0)
                day = time.strftime("%Y-%m-%d", time.localtime(ts))
                groups.setdefault(day, []).append(entry)
            groups = list(groups.values())
        text_blocks = []
        for group in groups:
            lines = [f"问：{e.get('question', '')[:100]}\n答：{e.get('answer', '')[:200]}" for e in group]
            text_blocks.append("\n".join(lines))
        return text_blocks


def register_deep_reader(router: ModelRouter, memory=None, max_parallel_blocks: int = 1):
    from tools.tool_dispatcher import register_tool
    reader = DeepReader(router=router, memory=memory, max_parallel_blocks=max_parallel_blocks)
    register_tool("deep_read", reader.deep_read)
    print("📖 [深度阅读器] 已注册工具: deep_read (多级瀑布版)")