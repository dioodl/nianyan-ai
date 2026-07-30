# time_expression_parser.py
"""
自然语言时间表达式解析器
========================
将中文时间表达（如“去年”、“三年前的夏天”、“上个月”、“我生日那天”）转换为
精确或模糊的时间戳范围。
v14.10 - 集成模型路由器，移除 num_predict 硬编码。
"""

import re
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import ollama
from model_router import ModelRouter


class TimeExpressionParser:
    """
    时间表达式解析器。
    采用“规则优先 + LLM 兜底”策略，保证常见表达的解析速度和准确率，
    同时覆盖规则无法处理的复杂表达。
    """

    def __init__(self, model: str = "qwen2.5:3b", cache_file: str = "time_parse_cache.json",
                 router: ModelRouter = None):
        self.model = model
        self.router = router or ModelRouter(max_concurrent_requests=1)
        self.cache_file = cache_file
        self.cache: Dict[str, Dict] = {}
        self._load_cache()

        # 用户特定日期记忆（如生日），可通过 info_store 注入
        self.user_special_dates: Dict[str, float] = {}

    # ---------- 缓存 ----------
    def _load_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
            except:
                self.cache = {}

    def _save_cache(self):
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, indent=2, ensure_ascii=False)

    def set_special_date(self, name: str, timestamp: float):
        """设置用户特定日期，如生日、纪念日"""
        self.user_special_dates[name] = timestamp

    # ---------- 公共接口 ----------
    def parse(self, text: str) -> Dict:
        """
        解析自然语言时间表达，返回结构化时间范围。
        返回格式：
        {
            "success": True/False,
            "time_bias": "range" / "before" / "after" / "recent" / None,
            "start_time": float or None,   // Unix 时间戳
            "end_time": float or None,
            "reference_time": float or None,  // 用于 before/after
            "fuzzy": bool,                 // 是否模糊匹配
            "parsed_expression": str,       // 解析出的时间表达原文
            "confidence": float             // 0~1
        }
        """
        if not text or len(text) < 2:
            return self._fail_result()

        # 1. 查缓存
        if text in self.cache:
            return self.cache[text].copy()

        # 2. 规则匹配
        result = self._rule_parse(text)
        if result["success"] and result["confidence"] > 0.8:
            self.cache[text] = result
            self._save_cache()
            return result

        # 3. LLM 兜底
        llm_result = self._llm_parse(text)
        if llm_result["success"]:
            self.cache[text] = llm_result
            self._save_cache()
            return llm_result

        # 4. 完全失败
        return self._fail_result()

    # ---------- 规则解析 ----------
    def _rule_parse(self, text: str) -> Dict:
        now = datetime.now()
        today_start = datetime(now.year, now.month, now.day).timestamp()
        today_end = today_start + 86400

        # 1. 相对时间：最近N天/周/月
        match = re.search(r'最近\s*(\d+)\s*(天|周|月|年)', text)
        if match:
            num = int(match.group(1))
            unit = match.group(2)
            if unit == '天':
                start = (now - timedelta(days=num)).timestamp()
            elif unit == '周':
                start = (now - timedelta(weeks=num)).timestamp()
            elif unit == '月':
                start = (now - timedelta(days=num*30)).timestamp()
            else:  # 年
                start = (now - timedelta(days=num*365)).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=now.timestamp(),
                parsed_expression=match.group(0),
                confidence=0.95
            )

        # 2. 绝对时间：今天/昨天/前天/明天
        if '今天' in text:
            return self._make_result(
                time_bias="range",
                start_time=today_start,
                end_time=today_end,
                parsed_expression="今天",
                confidence=0.99
            )
        if '昨天' in text:
            yesterday = now - timedelta(days=1)
            start = datetime(yesterday.year, yesterday.month, yesterday.day).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=start + 86400,
                parsed_expression="昨天",
                confidence=0.99
            )
        if '前天' in text:
            day_before = now - timedelta(days=2)
            start = datetime(day_before.year, day_before.month, day_before.day).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=start + 86400,
                parsed_expression="前天",
                confidence=0.99
            )

        # 3. 本周/上周/下周
        if '本周' in text or '这周' in text:
            weekday = now.weekday()
            start = today_start - weekday * 86400
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=start + 7 * 86400,
                parsed_expression="本周",
                confidence=0.95
            )
        if '上周' in text:
            weekday = now.weekday()
            start = today_start - (weekday + 7) * 86400
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=start + 7 * 86400,
                parsed_expression="上周",
                confidence=0.95
            )

        # 4. 本月/上月/今年/去年
        if '本月' in text or '这个月' in text:
            start = datetime(now.year, now.month, 1).timestamp()
            if now.month == 12:
                end = datetime(now.year+1, 1, 1).timestamp()
            else:
                end = datetime(now.year, now.month+1, 1).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=end,
                parsed_expression="本月",
                confidence=0.95
            )
        if '上月' in text or '上个月' in text:
            if now.month == 1:
                start = datetime(now.year-1, 12, 1).timestamp()
                end = datetime(now.year, 1, 1).timestamp()
            else:
                start = datetime(now.year, now.month-1, 1).timestamp()
                end = datetime(now.year, now.month, 1).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=end,
                parsed_expression="上月",
                confidence=0.95
            )
        if '今年' in text:
            start = datetime(now.year, 1, 1).timestamp()
            end = datetime(now.year+1, 1, 1).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=end,
                parsed_expression="今年",
                confidence=0.99
            )
        if '去年' in text:
            start = datetime(now.year-1, 1, 1).timestamp()
            end = datetime(now.year, 1, 1).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=end,
                parsed_expression="去年",
                confidence=0.99
            )
        if '明年' in text:
            start = datetime(now.year+1, 1, 1).timestamp()
            end = datetime(now.year+2, 1, 1).timestamp()
            return self._make_result(
                time_bias="range",
                start_time=start,
                end_time=end,
                parsed_expression="明年",
                confidence=0.99
            )

        # 5. 季节：去年夏天/今年春天等
        season_map = {
            '春': (3, 5), '夏': (6, 8), '秋': (9, 11), '冬': (12, 2)
        }
        for season, (start_month, end_month) in season_map.items():
            # 今年X天
            if f'今年{season}天' in text or f'这个{season}天' in text:
                year = now.year
                start = datetime(year, start_month, 1).timestamp()
                if end_month == 2:
                    end = datetime(year+1, 3, 1).timestamp()
                elif end_month == 12:
                    end = datetime(year+1, 1, 1).timestamp()
                else:
                    end = datetime(year, end_month+1, 1).timestamp()
                return self._make_result(
                    time_bias="range",
                    start_time=start,
                    end_time=end,
                    parsed_expression=f"今年{season}天",
                    confidence=0.9
                )
            # 去年X天
            if f'去年{season}天' in text:
                year = now.year - 1
                start = datetime(year, start_month, 1).timestamp()
                if end_month == 2:
                    end = datetime(year+1, 3, 1).timestamp()
                elif end_month == 12:
                    end = datetime(year+1, 1, 1).timestamp()
                else:
                    end = datetime(year, end_month+1, 1).timestamp()
                return self._make_result(
                    time_bias="range",
                    start_time=start,
                    end_time=end,
                    parsed_expression=f"去年{season}天",
                    confidence=0.9
                )

        # 6. “最近” / “近期” → 偏好近期，无硬范围
        if '最近' in text or '近期' in text:
            return self._make_result(
                time_bias="recent",
                parsed_expression="最近",
                confidence=0.85
            )

        # 7. 特殊日期（生日、纪念日）
        for name, ts in self.user_special_dates.items():
            if name in text:
                dt = datetime.fromtimestamp(ts)
                start = datetime(dt.year, dt.month, dt.day).timestamp()
                return self._make_result(
                    time_bias="range",
                    start_time=start,
                    end_time=start + 86400,
                    parsed_expression=name,
                    confidence=0.95
                )

        # 8. “第一次/上次/之前/之后” 与某个事件关联
        if any(kw in text for kw in ['第一次', '上次', '之前', '之后', '当时', '那时']):
            return self._fail_result(confidence=0.3)

        return self._fail_result()

    # ---------- LLM 兜底 ----------
    def _llm_parse(self, text: str) -> Dict:
        now = datetime.now()
        prompt = f"""你是一个时间表达式解析器。请将用户的口语化时间表达转换为结构化数据。

当前时间：{now.strftime('%Y-%m-%d %H:%M:%S')}，星期{['一','二','三','四','五','六','日'][now.weekday()]}

用户表达："{text}"

请判断用户想要的时间范围类型，并输出 JSON：
{{
    "time_bias": "range" / "before" / "after" / "recent" / null,
    "start_time": "YYYY-MM-DD HH:MM:SS" 或 null,
    "end_time": "YYYY-MM-DD HH:MM:SS" 或 null,
    "reference_time": "YYYY-MM-DD HH:MM:SS" 或 null,
    "fuzzy": true/false,
    "parsed_expression": "规范化后的时间表达"
}}

规则：
- "range": 指定时间范围，需提供 start_time 和 end_time
- "before": 某时间点之前，需提供 reference_time
- "after": 某时间点之后，需提供 reference_time
- "recent": 仅表示偏好近期，无具体范围
- 如果无法解析，time_bias 为 null

只输出 JSON，不要其他内容。"""

        try:
            # 优先使用路由器
            if self.router:
                content = self.router.call(
                    role="time_parser",   # 使用配置中的时间解析角色
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1
                )
            else:
                response = ollama.chat(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    options={"temperature": 0.1}   # 移除 num_predict
                )
                content = response['message']['content']

            content = content.strip()
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
            else:
                data = json.loads(content)

            # 转换时间字符串为时间戳
            result = {
                "success": data.get("time_bias") is not None,
                "time_bias": data.get("time_bias"),
                "start_time": self._str_to_timestamp(data.get("start_time")),
                "end_time": self._str_to_timestamp(data.get("end_time")),
                "reference_time": self._str_to_timestamp(data.get("reference_time")),
                "fuzzy": data.get("fuzzy", True),
                "parsed_expression": data.get("parsed_expression", text),
                "confidence": 0.75
            }
            return result
        except Exception as e:
            print(f"LLM 时间解析失败: {e}")
            return self._fail_result()

    def _str_to_timestamp(self, s: str) -> Optional[float]:
        if not s:
            return None
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
            return dt.timestamp()
        except:
            try:
                dt = datetime.strptime(s, "%Y-%m-%d")
                return dt.timestamp()
            except:
                return None

    # ---------- 辅助方法 ----------
    def _make_result(self, time_bias: str, parsed_expression: str, confidence: float,
                     start_time: float = None, end_time: float = None,
                     reference_time: float = None, fuzzy: bool = False) -> Dict:
        return {
            "success": True,
            "time_bias": time_bias,
            "start_time": start_time,
            "end_time": end_time,
            "reference_time": reference_time,
            "fuzzy": fuzzy,
            "parsed_expression": parsed_expression,
            "confidence": confidence
        }

    def _fail_result(self, confidence: float = 0.0) -> Dict:
        return {
            "success": False,
            "time_bias": None,
            "start_time": None,
            "end_time": None,
            "reference_time": None,
            "fuzzy": False,
            "parsed_expression": "",
            "confidence": confidence
        }