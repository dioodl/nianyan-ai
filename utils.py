# utils.py
import random
import functools
import logging
import traceback

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("AIDebug")

def log_call(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logger.info(f"Calling {func.__name__} with args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logger.info(f"{func.__name__} returned {result}")
            return result
        except Exception as e:
            logger.error(f"{func.__name__} failed: {e}\n{traceback.format_exc()}")
            raise
    return wrapper

def polish_text(text: str) -> str:
    """简单的文本润色：避免重复词、同义词替换"""
    words = text.split()
    if len(words) < 2:
        return text
    new_words = []
    prev = words[0]
    new_words.append(prev)
    synonyms = {
        "好": ["棒", "优秀", "出色"],
        "很": ["非常", "十分", "特别"],
        "大": ["巨大", "庞大", "宏大"],
        "小": ["细小", "微小", "精致"],
        "是": ["就是", "正是", "便是"],
    }
    for w in words[1:]:
        if w == prev:
            if w in synonyms:
                new_words.append(random.choice(synonyms[w]))
            else:
                new_words.append(w)
        else:
            new_words.append(w)
        prev = w
    return " ".join(new_words)