# tools/browser_tools.py
"""
浏览器工具插件 - 提供搜索、截图、文本提取等能力
==============================================
作为外部插件，不修改核心架构即可启用/禁用。
"""

import os
import time
import asyncio
import random
import urllib.parse
import re
import base64
from typing import Dict, Any

# 全局路由器引用（由 main.py 注入）
_router = None
_bus = None


def set_router(router):
    global _router
    _router = router


def set_bus(bus):
    global _bus
    _bus = bus


def _publish_confusion(source: str, message: str, context: dict = None):
    if _bus:
        _bus.publish("internal.confusion", {
            "source": source,
            "message": message,
            "context": context or {},
            "timestamp": time.time()
        })


# ========== 辅助函数 ==========
async def _extract_summary(container) -> str:
    summary_selectors = [
        '.c-abstract', '.c-span-last', '.c-color-text', '[class*="abstract"]',
        '[class*="desc"]', '[class*="summary"]', '.content-right_2X1X4',
        '.c-gap-top-small', '.c-row', 'div[class*="text"]',
    ]
    for sel in summary_selectors:
        try:
            el = await container.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                if len(text) > 10:
                    return text
        except:
            continue
    try:
        full_text = (await container.inner_text()).strip()
        if full_text:
            return full_text[:200] + ("..." if len(full_text) > 200 else "")
    except:
        pass
    return ""


async def _try_expand_ai_card(page) -> bool:
    expand_selectors = [
        'span:has-text("展开")', 'span:has-text("全文")', 'a:has-text("展开")',
        'a:has-text("全文")', 'span:has-text("阅读更多")', '.op_exactqa_main span[class*="expand"]',
        '.cu-container span[class*="more"]', '[class*="expand-btn"]', '[class*="read-more"]',
        'div[class*="expand"]',
    ]
    for sel in expand_selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1.5)
                return True
        except:
            continue
    return False


async def _extract_ai_card(page, timeout: float = 8.0) -> str:
    ai_selectors = [
        '.op_exactqa_s_answer', '.c-result[data-log*="wise"]', 'div[class*="ai"] div[class*="answer"]',
        'div[class*="ling"]', '.cu-container .cu-answer', '[data-component="wise"] .c-gap-top-small',
        '.op_exactqa_main .op_exactqa_detail', '.c-gap-top-zero[class*="op_"]', '.op_exactqa_main',
        '.xdp-op-content', '.op_exactqa_answer', '.answer-content', '.ai-answer'
    ]
    for sel in ai_selectors:
        try:
            await page.wait_for_selector(sel, timeout=timeout * 1000)
            break
        except:
            continue
    await _try_expand_ai_card(page)
    for sel in ai_selectors:
        try:
            el = await page.query_selector(sel)
            if el:
                text = (await el.inner_text()).strip()
                if len(text) > 30 and not text.startswith("广告"):
                    return text
        except:
            continue
    return ""


def _generate_curiosity_response(query: str, reason: str = "no_results") -> str:
    templates = [
        f"我尝试搜索了「{query}」，但没能找到满意的答案。你能告诉我更多细节吗？我想更了解这个话题。",
        f"关于「{query}」，我找了一圈，似乎没有直接的信息。也许你可以换个关键词，或者直接给我讲讲？",
        f"我搜了一下「{query}」，结果不太理想。我有点好奇，你为什么会想到这个问题呢？",
        f"「{query}」……我没搜到什么有用的内容。如果你知道的话，愿意跟我分享一下吗？",
    ]
    return random.choice(templates)


async def _extract_content_by_vlm(page, query: str) -> str:
    try:
        import ollama
        screenshot_bytes = await page.screenshot()
        img_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')

        vlm_prompt = f"""请提取这张百度搜索结果页面中，关于「{query}」的文心AI或百度AI直接回答区域的核心内容。
该区域通常位于搜索结果的最顶部，有一个明显的卡片样式，可能包含“文心AI”、“百度AI”、“AI+”等标识。
如果页面中没有明显的AI回答区域，请提取搜索结果摘要中与查询最相关的一条信息。
只输出提取到的文本内容，不要任何解释。"""

        if _router:
            content = await _router.call_async(
                role="vision",
                messages=[{"role": "user", "content": vlm_prompt}],
                images=[img_base64],
                temperature=0.3
            )
        else:
            response = ollama.chat(
                model="qwen3.5:4b",
                messages=[{
                    "role": "user",
                    "content": vlm_prompt,
                    "images": [img_base64]
                }],
                options={"temperature": 0.3}
            )
            content = response['message']['content']
        return content.strip() if content and len(content) > 10 else ""
    except Exception as e:
        print(f"VLM 截图理解失败: {e}")
    return ""


# ========== 核心工具函数 ==========
async def web_browser_search(params: dict, context: dict) -> dict:
    """
    统一的浏览器搜索入口。
    参数：
        - query: 搜索关键词
        - direct: 是否直接拼接搜索URL（默认 False）
        - ai_wait_time: 等待AI卡片出现的时间（秒）
    """
    query = params.get("query")
    print(f"🌐 [浏览器搜索] 开始搜索: {query}")
    if not query:
        return {"success": False, "error": "未提供搜索关键词"}

    ai_wait_time = params.get("ai_wait_time", 8)
    max_retries = 2
    direct_mode = params.get("direct", False)

    try:
        from playwright.async_api import async_playwright
        print("🌐 [浏览器搜索] Playwright 导入成功")
    except ImportError as e:
        print(f"❌ [浏览器搜索] Playwright 导入失败: {e}")
        _publish_confusion("web_browser_search", f"无法导入 Playwright，无法搜索「{query}」", {"error": str(e)})
        return {"success": False, "error": "Playwright未安装", "results": "", "raw": []}

    for attempt in range(max_retries):
        try:
            print(f"🌐 [浏览器搜索] 第 {attempt+1} 次尝试...")
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=False)
                page = await browser.new_page()
                await page.set_viewport_size({"width": 1280, "height": 800})

                if direct_mode:
                    encoded_query = urllib.parse.quote(query)
                    search_url = f"https://www.baidu.com/s?wd={encoded_query}"
                    await page.goto(search_url, timeout=60000)
                else:
                    await page.goto("https://www.baidu.com", timeout=60000)
                    await asyncio.sleep(random.uniform(2, 3))

                    await page.evaluate("""
                        () => {
                            const closeSelectors = [
                                'span[class*="close"]', 'a[class*="close"]', 'div[class*="close"]',
                                '[aria-label="关闭"]', '[title="关闭"]', 'button[class*="close"]',
                                '.tang-pass-footerBar span', '.desktop-login-close',
                                '#TANGRAM__PSP_4__closeBtn', '.hot-close', '.s-bottom-close'
                            ];
                            closeSelectors.forEach(sel => {
                                document.querySelectorAll(sel).forEach(el => {
                                    if (el.offsetParent !== null) el.click();
                                });
                            });
                            ["以后再说", "我知道了", "暂不", "关闭"].forEach(text => {
                                document.querySelectorAll('*').forEach(el => {
                                    if (el.innerText && el.innerText.trim() === text && el.offsetParent !== null) {
                                        el.click();
                                    }
                                });
                            });
                        }
                    """)
                    await asyncio.sleep(0.5)

                    input_exists = await page.evaluate("""
                        () => {
                            let input = document.querySelector('input[name="wd"]') || 
                                        document.querySelector('#kw') || 
                                        document.querySelector('input[type="text"][name="wd"]') ||
                                        document.querySelector('input[class*="s_ipt"]');
                            if (!input) {
                                input = document.evaluate(
                                    "//input[contains(@id, 'kw') or contains(@name, 'wd')]",
                                    document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null
                                ).singleNodeValue;
                            }
                            if (input) {
                                input.style.zIndex = '99999';
                                input.style.position = 'relative';
                                input.style.opacity = '1';
                                input.style.display = 'block';
                                input.disabled = false;
                                input.readOnly = false;
                                input.focus();
                                return true;
                            }
                            return false;
                        }
                    """)
                    if not input_exists:
                        raise Exception("无法定位百度搜索框")
                    await asyncio.sleep(0.3)

                    await page.evaluate(f"""
                        (query) => {{
                            let input = document.querySelector('input[name="wd"]') || 
                                        document.querySelector('#kw') || 
                                        document.querySelector('input[type="text"][name="wd"]') ||
                                        document.querySelector('input[class*="s_ipt"]');
                            if (input) {{
                                input.value = query;
                                input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                                input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            }}
                        }}
                    """, query)
                    await asyncio.sleep(0.5)

                    submitted = await page.evaluate("""
                        () => {
                            let submitBtn = document.querySelector('#su') || 
                                            document.querySelector('input[type="submit"]');
                            if (submitBtn && submitBtn.offsetParent !== null) {
                                submitBtn.click();
                                return true;
                            }
                            let input = document.querySelector('input[name="wd"]') || document.querySelector('#kw');
                            if (input) {
                                let form = input.closest('form');
                                if (form) {
                                    form.submit();
                                    return true;
                                }
                            }
                            return false;
                        }
                    """)
                    if not submitted:
                        await page.keyboard.press("Enter")

                try:
                    await page.wait_for_selector('.result, .c-container', timeout=10000)
                except:
                    await page.wait_for_selector('h3 a', timeout=8000)

                results = []
                ai_answer = await _extract_ai_card(page, timeout=ai_wait_time)

                if not ai_answer:
                    print("🌐 [浏览器搜索] DOM提取失败，尝试VLM截图理解...")
                    ai_answer = await _extract_content_by_vlm(page, query)
                    if ai_answer:
                        results.append({"title": "【文心AI-截图识别】", "url": "", "summary": ai_answer})
                        print(f"🌐 [浏览器搜索] VLM截图理解成功，提取到 {len(ai_answer)} 字符")
                else:
                    results.append({"title": "【文心AI直接回答】", "url": "", "summary": ai_answer})

                if not ai_answer:
                    await asyncio.sleep(2)
                    ai_answer = await _extract_ai_card(page, timeout=3)
                    if ai_answer:
                        results.append({"title": "【文心AI直接回答】", "url": "", "summary": ai_answer})

                containers = await page.query_selector_all('.result, .c-container, #content_left > div')
                seen = set()
                for c in containers[:15]:
                    try:
                        link = await c.query_selector('h3 a, .t a, a[href*="http"]')
                        if not link:
                            continue
                        title = (await link.inner_text()).strip()
                        if len(title) < 5:
                            continue
                        url = await link.get_attribute('href')
                        if not url or url in seen:
                            continue
                        seen.add(url)
                        summary = await _extract_summary(c)
                        results.append({"title": title, "url": url, "summary": summary})
                        if len(results) >= 6:
                            break
                    except:
                        continue

                await browser.close()
                print(f"🌐 [浏览器搜索] 浏览器已关闭，获取到 {len(results)} 条结果")

                if results:
                    formatted = "\n\n".join([f"标题：{r['title']}\n摘要：{r['summary']}\n链接：{r['url']}" for r in results[:6]])
                    return {"success": True, "results": formatted, "raw": results}
                else:
                    _publish_confusion("web_browser_search", f"搜索「{query}」无结果", {"query": query})
                    curiosity_resp = _generate_curiosity_response(query, "no_results")
                    return {"success": False, "error": "无搜索结果", "results": curiosity_resp, "raw": []}
        except Exception as e:
            print(f"❌ [浏览器搜索] 第 {attempt+1} 次尝试异常: {e}")
            if attempt == max_retries - 1:
                _publish_confusion("web_browser_search", f"搜索「{query}」时发生异常", {"error": str(e)})
                curiosity_resp = _generate_curiosity_response(query, "error")
                return {"success": False, "error": str(e), "results": curiosity_resp, "raw": []}
            await asyncio.sleep(2)

    curiosity_resp = _generate_curiosity_response(query, "unknown")
    return {"success": False, "error": "搜索失败：未知错误", "results": curiosity_resp, "raw": []}


async def extract_full_page_text(params: dict, context: dict) -> dict:
    """提取网页全文内容"""
    url = params.get("url")
    wait_until = params.get("wait_until", "networkidle")
    max_length = params.get("max_length", 10000)

    if not url:
        return {"success": False, "error": "未提供 URL"}

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"success": False, "error": "Playwright 未安装"}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until=wait_until, timeout=30000)

            title = await page.title()
            body_text = await page.evaluate("() => document.body.innerText")

            await browser.close()

            full_text = f"【页面标题】{title}\n\n【正文内容】\n{body_text}"
            if len(full_text) > max_length:
                full_text = full_text[:max_length] + f"\n\n... (内容过长，已截断至 {max_length} 字符)"

            print(f"📄 [全页文本] 提取完成，共 {len(full_text)} 字符")
            return {
                "success": True,
                "text": full_text,
                "url": page.url
            }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def capture_full_page_screenshot(params: dict, context: dict) -> dict:
    """全页长截图"""
    url = params.get("url")
    output_path = params.get("output_path")
    filename = params.get("filename")

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return {"success": False, "error": "Playwright 未安装"}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.set_viewport_size({"width": 1280, "height": 800})

            if url:
                await page.goto(url, wait_until="networkidle")

            screenshot_bytes = await page.screenshot(full_page=True)
            await browser.close()

            img_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
            img_data_url = f"data:image/png;base64,{img_base64}"

            result = {
                "success": True,
                "image_base64": img_data_url,
            }

            if output_path or filename:
                if not filename:
                    filename = f"fullpage_{time.strftime('%Y%m%d_%H%M%S')}.png"
                if not output_path:
                    output_path = os.path.join(os.path.expanduser("~"), "Desktop")
                full_path = os.path.join(output_path, filename)
                with open(full_path, "wb") as f:
                    f.write(screenshot_bytes)
                result["filepath"] = full_path
                print(f"📸 [全页截图] 已保存: {full_path}")

            return result
    except Exception as e:
        return {"success": False, "error": str(e)}


# ========== 工具注册函数 ==========
def register_browser_tools():
    """注册所有浏览器相关工具到调度器"""
    from tools.tool_dispatcher import register_tool
    register_tool("web_browser_search", web_browser_search)
    register_tool("extract_full_page_text", extract_full_page_text)
    register_tool("capture_full_page_screenshot", capture_full_page_screenshot)