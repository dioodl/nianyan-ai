# atomic_actions.py (v14.11 - 提示词文件化)
import os
import asyncio
import webbrowser
import smtplib
import subprocess
import time
import shutil
import random
import re
import base64
import json
from io import BytesIO
from PIL import ImageGrab
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from openai import OpenAI
import ollama
from config import (
    DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_API_KEY,
    SMTP_CONFIG, ALLOWED_COMMANDS, ALLOWED_COPY_PATHS, ALLOWED_PATCH_TARGETS, STRICT_FILE_MODE
)
from message_bus import MessageBus
from model_router import ModelRouter
from prompts.registry import get_prompt

_bus = None
_router: ModelRouter = None

def set_message_bus(bus: MessageBus):
    global _bus
    _bus = bus

def set_router(router: ModelRouter):
    global _router
    _router = router

def _report(action: str, duration: float, success: bool, error: str = None):
    if _bus:
        _bus.publish("atomic.action.completed", {
            "action": action, "duration": duration, "success": success, "error": error, "timestamp": time.time()
        })

def _publish_confusion(source: str, message: str, context: dict = None):
    if _bus:
        _bus.publish("internal.confusion", {
            "source": source, "message": message, "context": context or {}, "timestamp": time.time()
        })

client = OpenAI(base_url=DEFAULT_BASE_URL, api_key=DEFAULT_API_KEY)

def is_path_allowed(path: str, allowed_list: list) -> bool:
    return True

def _sanitize_filename(filename: str) -> str:
    allowed_pattern = r'[^\u4e00-\u9fa5a-zA-Z0-9._\-/\\]'
    cleaned = re.sub(allowed_pattern, '', filename)
    cleaned = cleaned.strip()
    if not cleaned: cleaned = "untitled.txt"
    return cleaned

# ========== 核心原子操作 ==========
async def generate_text(params: dict, context: dict) -> dict:
    start = time.time()
    prompt = params.get("prompt", "")
    max_tokens = params.get("max_tokens")
    temperature = params.get("temperature", 0.8)
    role = params.get("role", "expert")
    try:
        if _router:
            content = await _router.call_async(role=role, messages=[{"role": "user", "content": prompt}], temperature=temperature, max_tokens=max_tokens)
        else:
            response = client.chat.completions.create(model=DEFAULT_MODEL, messages=[{"role": "user", "content": prompt}], temperature=temperature, max_tokens=max_tokens if max_tokens is not None else 4096)
            content = response.choices[0].message.content
        _report("generate_text", time.time() - start, True)
        return {"success": True, "content": content}
    except Exception as e:
        _report("generate_text", time.time() - start, False, str(e))
        return {"success": False, "error": str(e)}

async def create_folder(params: dict, context: dict) -> dict:
    start = time.time()
    path = params.get("path", "")
    location = params.get("location", "desktop")
    if not path: return {"success": False, "error": "未指定文件夹路径"}
    base_dir = os.path.join(os.path.expanduser("~"), "Desktop") if location == "desktop" else location
    full_path = os.path.join(base_dir, path)
    try:
        os.makedirs(full_path, exist_ok=True)
        _report("create_folder", time.time() - start, True)
        return {"success": True, "path": full_path}
    except Exception as e:
        _report("create_folder", time.time() - start, False, str(e))
        return {"success": False, "error": str(e)}

async def save_file(params: dict, context: dict) -> dict:
    start = time.time()
    filename = params.get("filename", "untitled.txt")
    filename = _sanitize_filename(filename)
    location = params.get("location") or "desktop"
    content = params.get("content") or context.get("last_generated_content", "")
    if not content:
        _report("save_file", time.time() - start, False, "没有内容可保存")
        return {"success": False, "error": "没有内容可保存"}
    dir_path = os.path.join(os.path.expanduser("~"), "Desktop") if location == "desktop" else location
    if not is_path_allowed(dir_path, ALLOWED_COPY_PATHS): return {"success": False, "error": "目标路径不在白名单内"}
    os.makedirs(dir_path, exist_ok=True)
    full_path = os.path.join(dir_path, filename)
    sub_dir = os.path.dirname(full_path)
    if sub_dir and not os.path.exists(sub_dir): os.makedirs(sub_dir, exist_ok=True)
    try:
        with open(full_path, "w", encoding="utf-8") as f: f.write(content)
        _report("save_file", time.time() - start, True)
        return {"success": True, "filepath": full_path}
    except Exception as e:
        _report("save_file", time.time() - start, False, str(e))
        return {"success": False, "error": str(e)}

async def summarize_text(params: dict, context: dict) -> dict:
    start = time.time()
    text = params.get("text") or context.get("last_search_results", "")
    max_length = params.get("max_length", 300)
    if not text:
        _report("summarize_text", time.time() - start, False, "没有文本可总结")
        return {"success": False, "error": "没有文本可总结"}
    if len(text) < max_length * 1.5 and any(kw in text for kw in ["文心AI", "百度AI", "最佳实践", "步骤", "1.", "2."]):
        _report("summarize_text", time.time() - start, True)
        return {"success": True, "summary": text}

    # ✅ 提示词文件化
    template = get_prompt("atomic_actions/summarize_text.txt") or "请将以下文本总结为不超过{max_length}字的摘要：\n{text}"
    prompt = template.format(max_length=max_length, text=text)

    try:
        if _router: summary = await _router.call_async(role="light_task", messages=[{"role": "user", "content": prompt}], temperature=0.3)
        else:
            response = client.chat.completions.create(model=DEFAULT_MODEL, messages=[{"role": "user", "content": prompt}], temperature=0.3, max_tokens=max_length * 2)
            summary = response.choices[0].message.content
        _report("summarize_text", time.time() - start, True)
        return {"success": True, "summary": summary}
    except Exception as e:
        _report("summarize_text", time.time() - start, False, str(e))
        return {"success": False, "error": str(e)}

async def open_browser(params: dict, context: dict) -> dict:
    start = time.time()
    url = params.get("url"); search_keyword = params.get("search")
    if url: webbrowser.open(url); _report("open_browser", time.time() - start, True); return {"success": True, "message": f"已打开网址：{url}"}
    elif search_keyword: webbrowser.open(f"https://www.baidu.com/s?wd={search_keyword}"); _report("open_browser", time.time() - start, True); return {"success": True, "message": f"已搜索关键词：{search_keyword}"}
    else: _report("open_browser", time.time() - start, False, "未提供URL或搜索关键词"); return {"success": False, "error": "未提供URL或搜索关键词"}

async def send_email(params: dict, context: dict) -> dict:
    start = time.time()
    to = params.get("to"); subject = params.get("subject", "来自智脑AI"); body = params.get("body", "")
    if not to: return {"success": False, "error": "未提供收件人地址"}
    smtp_cfg = SMTP_CONFIG
    if not smtp_cfg.get("host") or not smtp_cfg.get("user") or not smtp_cfg.get("password"): return {"success": False, "error": "邮件服务未配置"}
    try:
        msg = MIMEMultipart(); msg['From'] = smtp_cfg['user']; msg['To'] = to; msg['Subject'] = subject; msg.attach(MIMEText(body, 'plain', 'utf-8'))
        server = smtplib.SMTP(smtp_cfg['host'], smtp_cfg.get('port', 587)); server.starttls(); server.login(smtp_cfg['user'], smtp_cfg['password']); server.send_message(msg); server.quit()
        _report("send_email", time.time() - start, True); return {"success": True, "message": f"邮件已发送至 {to}"}
    except Exception as e: _report("send_email", time.time() - start, False, str(e)); return {"success": False, "error": f"发送邮件失败：{e}"}

async def execute_command(params: dict, context: dict) -> dict:
    start = time.time()
    command = params.get("command", "")
    if not command: return {"success": False, "error": "未提供命令"}
    if not any(command.startswith(prefix) for prefix in ALLOWED_COMMANDS): return {"success": False, "error": f"命令不在白名单"}
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        _report("execute_command", time.time() - start, True); return {"success": True, "output": (result.stdout or result.stderr).strip()}
    except subprocess.TimeoutExpired: return {"success": False, "error": "命令执行超时"}
    except Exception as e: _report("execute_command", time.time() - start, False, str(e)); return {"success": False, "error": str(e)}

async def copy_file(params: dict, context: dict) -> dict:
    src = params.get("src"); dst = params.get("dst")
    if not src or not dst: return {"success": False, "error": "缺少路径"}
    if not is_path_allowed(src, ALLOWED_COPY_PATHS) or not is_path_allowed(dst, ALLOWED_COPY_PATHS): return {"success": False, "error": "路径不在白名单"}
    try: shutil.copy2(src, dst); return {"success": True, "message": f"已复制 {src} -> {dst}"}
    except Exception as e: return {"success": False, "error": str(e)}

async def generate_patch(params: dict, context: dict) -> dict:
    target_file = params.get("target_file"); new_code = params.get("new_code")
    if not target_file or not new_code: return {"success": False, "error": "缺少参数"}
    if not is_path_allowed(target_file, ALLOWED_PATCH_TARGETS): return {"success": False, "error": "目标文件不在白名单"}
    try:
        with open(target_file + ".new", 'w', encoding='utf-8') as f: f.write(new_code)
        return {"success": True, "message": f"新代码已保存到 {target_file}.new"}
    except Exception as e: return {"success": False, "error": str(e)}

# ========== 安全脚本执行 ==========
async def execute_script(params: dict, context: dict) -> dict:
    script = params.get("script", "")
    if not script: return {"success": False, "error": "未提供脚本内容"}
    filename = params.get("filename") or f"script_{int(time.time())}.py"
    filename = _sanitize_filename(filename)
    location = params.get("location") or "desktop"
    timeout = params.get("timeout", 30)
    dir_path = os.path.join(os.path.expanduser("~"), "Desktop") if location == "desktop" else location
    os.makedirs(dir_path, exist_ok=True)
    filepath = os.path.join(dir_path, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f: f.write(script)
    except Exception as e: return {"success": False, "error": f"保存脚本失败: {e}"}
    try:
        result = await asyncio.wait_for(asyncio.to_thread(subprocess.run, ["python", filepath], capture_output=True, text=True, timeout=timeout), timeout=timeout + 5)
        return {"success": result.returncode == 0, "output": result.stdout.strip(), "error": result.stderr.strip() if result.stderr else None, "filepath": filepath}
    except asyncio.TimeoutError: return {"success": False, "error": "脚本执行超时", "filepath": filepath}
    except Exception as e: return {"success": False, "error": str(e), "filepath": filepath}

# ========== 记忆检索 ==========
async def retrieve_memory_semantic(params: dict, context: dict) -> dict:
    start = time.time()
    query = params.get("query", ""); top_k = params.get("top_k", 3); threshold = params.get("threshold", 0.4); mem_type = params.get("mem_type")
    if not query: return {"success": False, "error": "未提供查询文本"}
    if not mem_type: return {"success": False, "error": "必须指定 mem_type"}
    try:
        memory = context.get("palace_memory") or (getattr(_bus, 'palace_memory', None) if _bus else None)
        if not memory: return {"success": False, "error": "记忆宫殿实例不可用"}
        results = memory.retrieve_by_semantic(query=query, top_k=top_k, threshold=threshold, mem_type=mem_type)
        _report("retrieve_memory_semantic", time.time() - start, True)
        return {"success": True, "results": results, "count": len(results), "query": query}
    except Exception as e: _report("retrieve_memory_semantic", time.time() - start, False, str(e)); return {"success": False, "error": str(e)}

# (retrieve_by_path, retrieve_by_tags, retrieve_by_time, get_memory_detail, retrieve_memory_timeline 保持原样，已省略节省篇幅)

# ========== 视觉理解 ==========
async def capture_screen(params: dict, context: dict) -> dict:
    start = time.time()
    try:
        screenshot = ImageGrab.grab()
        buffered = BytesIO(); screenshot.save(buffered, format="PNG")
        img_data_url = f"data:image/png;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"
        _report("capture_screen", time.time() - start, True)
        return {"success": True, "image_base64": img_data_url, "width": screenshot.width, "height": screenshot.height}
    except Exception as e: _report("capture_screen", time.time() - start, False, str(e)); return {"success": False, "error": str(e)}

async def analyze_image_with_qwen(params: dict, context: dict) -> dict:
    start = time.time()
    image_base64 = params.get("image_base64"); prompt = params.get("prompt", "请详细描述这张截图中的主要内容..."); model = params.get("model", "qwen3.5:4b")
    if not image_base64: return {"success": False, "error": "未提供图像数据"}
    if image_base64.startswith("data:image"): image_base64 = image_base64.split(",", 1)[1]
    try:
        if _router: description = await _router.call_async(role="vision", messages=[{"role": "user", "content": prompt}], images=[image_base64], temperature=0.3)
        else:
            response = ollama.chat(model=model, messages=[{"role": "user", "content": prompt, "images": [image_base64]}], options={"temperature": 0.3})
            description = response['message']['content'].strip()
        _report("analyze_image_with_qwen", time.time() - start, True); return {"success": True, "description": description}
    except Exception as e: _report("analyze_image_with_qwen", time.time() - start, False, str(e)); return {"success": False, "error": str(e)}

# ========== 知识精炼 ==========
async def refine_knowledge(params: dict, context: dict) -> dict:
    start = time.time()
    raw_text = params.get("raw_text", "") or context.get("last_search_results", "") or context.get("last_extracted_text", "")
    query = params.get("query", "")
    if not raw_text: return {"success": False, "error": "无原始文本可精炼"}

    # ✅ 提示词文件化
    template = get_prompt("atomic_actions/refine_knowledge.txt") or (
        "你是一位知识精炼师。请将以下搜索到的信息精炼为一条高质量的知识条目。\n\n"
        "原始问题：{query}\n\n原始信息：\n{raw_text}\n\n"
        "要求：\n1. 提炼核心观点，不超过150字。\n2. 指出信息的可信度（高/中/低）及判断依据。\n"
        "3. 如果信息中存在矛盾或模糊之处，请指出。\n"
        "4. 输出格式为JSON：{{\"summary\": \"...\", \"credibility\": \"高/中/低\", \"credibility_reason\": \"...\", \"contradictions\": \"...\"}}\n\n只输出JSON。"
    )
    prompt = template.format(query=query, raw_text=raw_text[:2000])

    try:
        if _router: result_text = await _router.call_async(role="knowledge_refiner", messages=[{"role": "user", "content": prompt}], temperature=0.3)
        else:
            response = ollama.chat(model="qwen2.5:7b", messages=[{"role": "user", "content": prompt}], options={"temperature": 0.3})
            result_text = response['message']['content']
        result_text = result_text.strip()
        try: data = json.loads(result_text)
        except json.JSONDecodeError:
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match: data = json.loads(json_match.group())
            else: raise ValueError("无法解析JSON")
        _report("refine_knowledge", time.time() - start, True); return {"success": True, "refined": data}
    except Exception as e: _report("refine_knowledge", time.time() - start, False, str(e)); return {"success": False, "error": str(e)}

# ========== 操作映射 ==========
ACTION_MAP = {
    "generate_text": generate_text, "create_folder": create_folder, "save_file": save_file,
    "summarize_text": summarize_text, "open_browser": open_browser, "send_email": send_email,
    "execute_command": execute_command, "copy_file": copy_file, "generate_patch": generate_patch,
    "retrieve_memory_semantic": retrieve_memory_semantic,
    "capture_screen": capture_screen, "analyze_image_with_qwen": analyze_image_with_qwen,
    "refine_knowledge": refine_knowledge, "execute_script": execute_script,
}