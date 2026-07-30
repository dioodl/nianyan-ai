# code_generator.py (v14.11 - 提示词文件化)
import threading
import time
import os
import ast
import re
import textwrap
from openai import OpenAI
from message_bus import MessageBus
from version_manager import VersionManager
from config import DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY
from meta_cognition_retriever import get_meta_retriever
from model_router import ModelRouter
from prompts.registry import get_prompt


class CodeGenerator:
    def __init__(self, bus: MessageBus, vm: VersionManager, target_module="chat_handler.py", memory=None):
        self.bus = bus
        self.vm = vm
        self.target_module = target_module
        self.memory = memory

        self.router = getattr(bus, 'model_router', None) or ModelRouter(max_concurrent_requests=1)
        self.client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)
        self.model = DEFAULT_MODEL

        self.running = True
        self.evolution_interval = 2592000  # 默认30天
        self.thread = threading.Thread(target=self._evolution_loop, daemon=True)
        self.thread.start()
        self.meta_retriever = get_meta_retriever()

    def set_target_module(self, module_name):
        self.target_module = module_name

    def _evolution_loop(self):
        while self.running:
            time.sleep(self.evolution_interval)
            self.attempt_upgrade()

    def _check_syntax(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            print(f"❌ 语法错误: {e}")
            if hasattr(e, 'lineno'):
                lines = code.split('\n')
                if e.lineno <= len(lines):
                    print(f"   错误行 {e.lineno}: {lines[e.lineno-1]}")
            return False

    def _fix_indentation(self, code: str) -> str:
        dedented = textwrap.dedent(code)
        lines = dedented.split('\n')
        fixed_lines = []
        for i, line in enumerate(lines):
            stripped = line.lstrip()
            if stripped.startswith(('def ', 'class ', 'if ', 'elif ', 'else:', 'for ', 'while ', 'try:', 'except', 'finally:', 'with ')):
                if not stripped.rstrip().endswith(':'):
                    if not any(kw in stripped for kw in ['else', 'except', 'finally']):
                        line = line.rstrip() + ':'
            fixed_lines.append(line)
        return '\n'.join(fixed_lines)

    def _extract_code(self, content: str) -> str:
        content = re.sub(r'^(好的|以下|这是|改进后).*?[:：]\s*', '', content.strip(), flags=re.IGNORECASE)
        code_blocks = re.findall(r'```python\s*(.*?)```', content, re.DOTALL | re.IGNORECASE)
        if code_blocks: return code_blocks[0].strip()
        code_blocks = re.findall(r'```\s*(.*?)```', content, re.DOTALL)
        if code_blocks: return code_blocks[0].strip()
        stripped = content.strip()
        if re.match(r'^(import |from |def |class |async def |@)', stripped, re.MULTILINE): return stripped
        lines = content.split('\n')
        code_lines = []
        in_code = False
        for line in lines:
            if re.match(r'^\s*(import |from |def |class |async def |@|if |for |while |try:|except|return |#)', line): in_code = True
            if in_code: code_lines.append(line)
        return '\n'.join(code_lines) if code_lines else stripped

    def _sanitize_non_ascii_in_code(self, code: str) -> str:
        return re.sub(r'[^\x00-\x7F]+', ' ', code)

    def _retrieve_relevant_knowledge(self, query: str) -> str:
        if not self.memory: return ""
        try:
            memories = self.memory.retrieve_by_semantic(query, top_k=3, threshold=0.4, mem_type="fact")
            if memories: return "\n".join([f"- {item['answer']}" for item in memories if item.get('answer')])
        except Exception as e: print(f"检索记忆失败: {e}")
        return ""

    def _emotional_review(self, code: str, module: str) -> bool:
        internal_parliament = getattr(self.bus, 'internal_parliament', None)
        if not internal_parliament or not hasattr(internal_parliament, '_collect_parliament_opinions'):
            print("⚠️ 七情议会不可用，跳过价值对齐审查")
            return True
        import asyncio
        try:
            opener = f"A 智脑为模块 {module} 生成了一个代码补丁，请从你的性格出发，用一句话表达你是否支持这次进化，以及原因（不超过25字）。"
            loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
            opinions = loop.run_until_complete(internal_parliament._collect_parliament_opinions(opener, "进化审查"))
            loop.close()
            if not opinions or len(opinions) < 3: return True
            negative_signals = ["反对", "危险", "担心", "不稳定", "不可", "不行", "拒绝"]
            veto_count = sum(1 for op in opinions if any(kw in op for kw in negative_signals))
            if veto_count >= 3:
                print(f"🚫 [七情审查] 补丁被否决！反对票 {veto_count}/7")
                return False
            print(f"✅ [七情审查] 补丁通过，反对票 {veto_count}/7")
            return True
        except Exception as e:
            print(f"⚠️ 七情审查异常: {e}，默认通过")
            return True

    def attempt_upgrade(self, specific_module=None, failure_context=None):
        module = specific_module or self.target_module
        print(f"🔧 A智脑：尝试升级模块 {module} ...")

        if not os.path.exists(module):
            print(f"模块 {module} 不存在，跳过")
            return

        with open(module, "r", encoding="utf-8") as f:
            current_code = f.read()

        query = failure_context if failure_context else f"改进 {module} 的代码"
        knowledge = self._retrieve_relevant_knowledge(query)
        if knowledge: print(f"📚 检索到相关编程知识：\n{knowledge[:200]}...")

        meta_context = self.meta_retriever.retrieve_as_context(query, top_k=2) or ""
        if meta_context: print(f"🧠 元认知指引：{meta_context[:100]}...")

        # ✅ 提示词文件化
        template = get_prompt("code_generator/upgrade_prompt.txt") or (
            "{meta_context}\n{failure_context_hint}改进以下Python代码，提升性能或稳定性。\n\n"
            "要求：\n1. 不改变原有函数签名和公共接口。\n2. 只优化内部实现。\n"
            "3. **严格遵守 Python 缩进规范，使用4个空格缩进。**\n"
            "4. **只输出纯英文 Python 代码，严禁中文注释或非 ASCII 字符。**\n"
            "5. 只输出完整代码，不要任何解释。\n{knowledge_section}\n\n当前代码：\n{current_code}\n改进后的代码："
        )
        failure_context_hint = f"改进以下Python代码，以解决性能/稳定性问题：{failure_context}\n" if failure_context else ""
        knowledge_section = f"\n参考以下相关知识：\n{knowledge}\n" if knowledge else ""
        prompt = template.format(
            meta_context=meta_context + "\n\n" if meta_context else "",
            failure_context_hint=failure_context_hint,
            knowledge_section=knowledge_section,
            current_code=current_code
        )

        try:
            if self.router:
                content = self.router.call(role="code_generator", messages=[{"role": "user", "content": prompt}], temperature=0.3)
            else:
                response = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], temperature=0.3)
                content = response.choices[0].message.content

            code = self._extract_code(content)
            if not code:
                print("⚠️ 未能提取有效代码，原始响应：")
                print(content[:500])
                return

            code = self._sanitize_non_ascii_in_code(code)
            code = self._fix_indentation(code)

            if not self._check_syntax(code):
                print("❌ 生成的代码有语法错误，放弃")
                with open(f"{module}.failed", "w", encoding="utf-8") as f: f.write(code)
                print(f"   失败代码已保存至 {module}.failed")
                return

            if not self._emotional_review(code, module):
                print("🚫 [A智脑] 补丁被七情议会否决，不应用此版本")
                return

            temp_file = f"{module}.new"
            with open(temp_file, "w", encoding="utf-8") as f: f.write(code)

            self.bus.publish("code.new_version", {
                "temp_file": temp_file, "target_file": module, "test_temp_file": None,
                "version_name": f"auto_{module.replace('.py','')}_{int(time.time())}"
            })
            print(f"✅ 新版本补丁已生成: {temp_file}")
        except Exception as e:
            print(f"❌ A智脑生成代码失败: {e}")

    def improve_from_failures(self, failures):
        if not failures: return
        context = "\n".join([f"问题：{f['question']}\n期望：{f['expected']}\n实际：{f['actual']}" for f in failures])
        self.attempt_upgrade(failure_context=context)

    def receive_upgrade_result(self, success):
        if success: print("✅ 升级成功，新版本已生效")
        else: print("❌ 升级失败，已回滚")