# causality_graph.py
"""
因果图谱模块 - 长篇创作的情节导航仪
====================================
为小说项目构建章节间的因果关联网络，追踪伏笔从埋设到回收的完整链条，
并生成可视化的情节发展图谱。
v14.10 - 集成模型路由器，移除 num_predict 硬编码。
"""

import os
import json
import re
import asyncio
import time
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import ollama
from model_router import ModelRouter


class CausalityGraph:
    """
    因果图谱管理器。
    负责从章节索引和伏笔清单中提取因果关系，构建情节网络。
    """

    def __init__(self, model: str = "qwen3.5:4b", router: ModelRouter = None):
        self.model = model
        self.router = router or ModelRouter(max_concurrent_requests=1)
        self.graph_dir = "causality_graphs"
        os.makedirs(self.graph_dir, exist_ok=True)

    # ---------- 图谱构建 ----------
    async def build_or_update_graph(self, project_path: str) -> Dict:
        """
        为指定项目构建或更新因果图谱。
        每次章节完成后调用，增量更新。
        """
        novel_name = os.path.basename(project_path)
        print(f"🔗 [因果图谱] 开始分析《{novel_name}》的情节因果...")

        # 1. 加载基础数据
        chapters = self._load_chapters(project_path)
        foreshadows = self._load_foreshadows(project_path)
        characters = self._load_characters(project_path)

        if len(chapters) < 2:
            print(f"⏭️ [因果图谱] 《{novel_name}》章节数不足2章，跳过")
            return {"status": "skipped", "reason": "insufficient_chapters"}

        # 2. 加载或初始化图谱
        graph = self._load_existing_graph(project_path) or {
            "novel_name": novel_name,
            "project_path": project_path,
            "created_at": time.time(),
            "updated_at": time.time(),
            "nodes": [],      # 事件节点
            "edges": [],      # 因果关系边
            "foreshadow_chains": []  # 伏笔链条
        }

        # 3. 检测新增章节，提取事件节点
        existing_chapter_nums = {n["chapter"] for n in graph["nodes"] if n["type"] == "chapter_event"}
        new_chapters = [c for c in chapters if c["num"] not in existing_chapter_nums]

        if new_chapters:
            new_nodes = await self._extract_event_nodes(project_path, new_chapters, characters)
            graph["nodes"].extend(new_nodes)

        # 4. 推断新增的因果关系边
        if len(graph["nodes"]) >= 2:
            new_edges = await self._infer_causal_edges(graph["nodes"], chapters, foreshadows)
            existing_edge_keys = {(e["source"], e["target"]) for e in graph["edges"]}
            for edge in new_edges:
                if (edge["source"], edge["target"]) not in existing_edge_keys:
                    graph["edges"].append(edge)
                    existing_edge_keys.add((edge["source"], edge["target"]))

        # 5. 更新伏笔链条
        graph["foreshadow_chains"] = self._build_foreshadow_chains(foreshadows, chapters)

        # 6. 保存图谱
        graph["updated_at"] = time.time()
        self._save_graph(project_path, graph)

        # 7. 生成人类可读的报告
        self._generate_readable_report(project_path, graph)

        print(f"✅ [因果图谱] 《{novel_name}》更新完成，{len(graph['nodes'])}个事件节点，{len(graph['edges'])}条因果边")
        return graph

    # ---------- 数据加载 ----------
    def _load_chapters(self, project_path: str) -> List[Dict]:
        path = os.path.join(project_path, "02_章节索引", "章节索引.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("chapters", [])
        return []

    def _load_foreshadows(self, project_path: str) -> List[Dict]:
        path = os.path.join(project_path, "04_伏笔管理", "伏笔清单.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("foreshadows", [])
        return []

    def _load_characters(self, project_path: str) -> Dict:
        path = os.path.join(project_path, "01_人物设定", "人物设定.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _load_existing_graph(self, project_path: str) -> Optional[Dict]:
        graph_file = os.path.join(self.graph_dir, f"{os.path.basename(project_path)}_graph.json")
        if os.path.exists(graph_file):
            with open(graph_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return None

    def _save_graph(self, project_path: str, graph: Dict):
        graph_file = os.path.join(self.graph_dir, f"{os.path.basename(project_path)}_graph.json")
        with open(graph_file, "w", encoding="utf-8") as f:
            json.dump(graph, f, indent=2, ensure_ascii=False)

    # ---------- 事件节点提取 ----------
    async def _extract_event_nodes(self, project_path: str, chapters: List[Dict], 
                                   characters: Dict) -> List[Dict]:
        """从新增章节中提取核心事件节点"""
        nodes = []
        protagonist = characters.get("protagonist", {}).get("name", "主角")

        for ch in chapters:
            content = self._load_chapter_content(project_path, ch["num"])
            if not content:
                continue

            prompt = f"""你是一位小说分析专家。请从以下章节内容中提取**核心事件**，作为因果图谱的节点。

章节：第{ch['num']}章
核心事件摘要：{ch.get('core_event', '')}
正文片段：{content[:1500]}

请以 JSON 格式输出：
{{
  "events": [
    {{
      "id": "ch{ch['num']}_event1",
      "name": "事件名称（不超过15字）",
      "description": "事件简述（不超过50字）",
      "participants": ["角色1", "角色2"],
      "importance": 0.5  // 0.1-1.0，对主线的重要程度
    }}
  ]
}}

通常一章有1-3个核心事件。只输出 JSON，不要其他内容。"""

            try:
                # 优先使用路由器
                if self.router:
                    result_text = await self.router.call_async(
                        role="light_task",   # 使用轻量任务角色
                        messages=[{"role": "user", "content": prompt}],
                        temperature=0.2
                    )
                else:
                    response = await asyncio.to_thread(
                        ollama.chat,
                        model=self.model,
                        messages=[{"role": "user", "content": prompt}],
                        options={"temperature": 0.2}   # 移除 num_predict
                    )
                    result_text = response['message']['content']

                result_text = result_text.strip()
                json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
                if json_match:
                    result = json.loads(json_match.group())
                    for event in result.get("events", []):
                        event["chapter"] = ch["num"]
                        event["type"] = "chapter_event"
                        event["core_event_summary"] = ch.get("core_event", "")
                        nodes.append(event)
            except Exception as e:
                print(f"提取第{ch['num']}章事件失败: {e}")
                # 降级：使用章节摘要作为单一事件
                nodes.append({
                    "id": f"ch{ch['num']}_event1",
                    "name": ch.get('core_event', f'第{ch["num"]}章核心事件')[:15],
                    "description": ch.get('core_event', '')[:50],
                    "participants": [protagonist],
                    "importance": 0.5,
                    "chapter": ch["num"],
                    "type": "chapter_event",
                    "core_event_summary": ch.get("core_event", "")
                })

        return nodes

    def _load_chapter_content(self, project_path: str, chapter_num: int) -> str:
        chapter_path = os.path.join(project_path, "03_正文章节", f"第{chapter_num}章.txt")
        if os.path.exists(chapter_path):
            with open(chapter_path, "r", encoding="utf-8") as f:
                return f.read()[:2000]
        return ""

    # ---------- 因果关系推断 ----------
    async def _infer_causal_edges(self, nodes: List[Dict], chapters: List[Dict],
                                  foreshadows: List[Dict]) -> List[Dict]:
        """推断新增节点与已有节点之间的因果关系"""
        edges = []

        sorted_nodes = sorted(nodes, key=lambda x: (x.get("chapter", 0), x.get("id", "")))
        chapter_map = {c["num"]: c.get("core_event", "") for c in chapters}
        recent_nodes = sorted_nodes[-10:]

        if len(recent_nodes) < 2:
            return edges

        nodes_text = ""
        for node in recent_nodes:
            nodes_text += f"- [{node['id']}] 第{node.get('chapter', '?')}章：{node.get('name', '')}（{node.get('description', '')}）\n"

        prompt = f"""你是一位小说情节分析师。请分析以下事件节点之间的**因果关系**。

事件节点列表：
{nodes_text}

请判断哪些事件之间存在因果关系（A导致B、A引发B、A是B的铺垫）。
对于每一对有因果关系的事件，输出：
{{
  "edges": [
    {{
      "source": "源节点ID",
      "target": "目标节点ID",
      "relation": "causes | leads_to | foreshadows | enables",
      "description": "因果关系简述（不超过30字）"
    }}
  ]
}}

注意：
- 因果关系应具有方向性（从因到果）
- 通常跨章节的事件更容易形成因果链
- 只输出 JSON，不要其他内容。"""

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
                edges.extend(result.get("edges", []))
        except Exception as e:
            print(f"推断因果关系失败: {e}")

        return edges

    # ---------- 伏笔链条 ----------
    def _build_foreshadow_chains(self, foreshadows: List[Dict], chapters: List[Dict]) -> List[Dict]:
        chains = []
        chapter_map = {c["num"]: c.get("core_event", "") for c in chapters}

        for f in foreshadows:
            chain = {
                "foreshadow_id": f.get("id", ""),
                "description": f.get("description", ""),
                "planted_chapter": f.get("planted_chapter"),
                "planted_event": chapter_map.get(f.get("planted_chapter", 0), ""),
                "resolved": f.get("resolved", False),
                "resolved_chapter": f.get("resolved_chapter"),
                "resolution": f.get("resolution", "")
            }
            chains.append(chain)

        chains.sort(key=lambda x: x.get("planted_chapter", 0) or 0)
        return chains

    # ---------- 可读报告生成 ----------
    def _generate_readable_report(self, project_path: str, graph: Dict):
        report_file = os.path.join(self.graph_dir, f"{graph['novel_name']}_report.md")

        lines = [
            f"# 《{graph['novel_name']}》因果图谱报告",
            f"生成时间：{datetime.fromtimestamp(graph['updated_at']).strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## 📊 统计概览",
            f"- 事件节点：{len(graph['nodes'])} 个",
            f"- 因果关联：{len(graph['edges'])} 条",
            f"- 伏笔链条：{len(graph['foreshadow_chains'])} 条",
            ""
        ]

        if graph["edges"]:
            lines.append("## 🔗 主要因果链")
            edges_by_source = {}
            for edge in graph["edges"]:
                src = edge["source"]
                if src not in edges_by_source:
                    edges_by_source[src] = []
                edges_by_source[src].append(edge)

            for src, edges in list(edges_by_source.items())[:10]:
                for edge in edges[:2]:
                    lines.append(f"- {src} --({edge['relation']})--> {edge['target']}：{edge['description']}")
            lines.append("")

        if graph["foreshadow_chains"]:
            lines.append("## 📌 伏笔追踪")
            unresolved = [c for c in graph["foreshadow_chains"] if not c["resolved"]]
            resolved = [c for c in graph["foreshadow_chains"] if c["resolved"]]

            lines.append(f"**未回收 ({len(unresolved)} 条)**：")
            for c in unresolved[-5:]:
                lines.append(f"- [{c['foreshadow_id']}] {c['description']} （埋于第{c['planted_chapter']}章）")

            lines.append(f"\n**已回收 ({len(resolved)} 条)**：")
            for c in resolved[-5:]:
                lines.append(f"- [{c['foreshadow_id']}] {c['description']} → 第{c['resolved_chapter']}章回收：{c['resolution'][:30]}...")
            lines.append("")

        lines.append("---")
        lines.append("*本报告由智脑AI因果图谱模块自动生成。*")

        with open(report_file, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        print(f"📄 因果图谱报告已生成：{report_file}")

    # ---------- 供续写时参考的图谱摘要 ----------
    def get_context_summary(self, project_path: str, current_chapter: int) -> str:
        graph = self._load_existing_graph(project_path)
        if not graph:
            return ""

        parts = ["【情节因果链参考】"]

        relevant_edges = []
        for edge in graph.get("edges", []):
            src_ch = self._extract_chapter_from_id(edge.get("source", ""))
            tgt_ch = self._extract_chapter_from_id(edge.get("target", ""))
            if src_ch and src_ch < current_chapter:
                relevant_edges.append(edge)

        if relevant_edges:
            seen = set()
            for edge in relevant_edges[-8:]:
                key = f"{edge['source']}->{edge['target']}"
                if key not in seen:
                    parts.append(f"- {edge['source']} --({edge['relation']})--> {edge['target']}：{edge['description']}")
                    seen.add(key)

        unresolved = [c for c in graph.get("foreshadow_chains", []) 
                      if not c["resolved"] and c.get("planted_chapter", 0) < current_chapter]
        if unresolved:
            parts.append("\n【待回收伏笔提醒】")
            for c in unresolved[-3:]:
                parts.append(f"- [{c['foreshadow_id']}] {c['description']} （埋于第{c['planted_chapter']}章）")

        return "\n".join(parts) if len(parts) > 1 else ""

    def _extract_chapter_from_id(self, node_id: str) -> Optional[int]:
        match = re.search(r'ch(\d+)_', node_id)
        if match:
            return int(match.group(1))
        return None


# 供 internal_monitor 调用的同步入口
def run_causality_update(project_path: str = None):
    graph = CausalityGraph()
    try:
        if project_path:
            asyncio.run(graph.build_or_update_graph(project_path))
        else:
            desktop = os.path.join(os.path.expanduser("~"), "Desktop")
            novel_root = os.path.join(desktop, "创作", "小说类")
            if os.path.exists(novel_root):
                for novel_name in os.listdir(novel_root):
                    proj_path = os.path.join(novel_root, novel_name)
                    if os.path.isdir(proj_path):
                        asyncio.run(graph.build_or_update_graph(proj_path))
    except Exception as e:
        print(f"❌ [因果图谱] 更新失败: {e}")