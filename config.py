# config.py
import os

# ========== 应用基本信息 ==========
APP_NAME = "念言AI"
VERSION = "14.6"  # 已更新版本号

# ========== 模型配置 ==========
DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"
DEFAULT_API_KEY = "ollama"

# 通义千问 API Key（可选，用于联网搜索）
QWEN_API_KEY = "sk-xxxxxx"

# ========== 文件存储路径配置 ==========
MEMORY_DIR = "window_memories"
STRATEGY_FILE = "global_strategies.json"
WINDOWS_STATE_FILE = "windows_state.json"
CATEGORY_FILE = "global_categories.json"
STRATEGY_OPTIMIZER_FILE = "strategy_optimizer.json"
EMOTION_EXTEND_FILE = "emotion_extend.json"
MONITOR_FILE = "monitor_history.json"
EVOLUTION_LOG = "evolution_log.json"
RISK_KEYWORDS_FILE = "risk_keywords.json"
META_STRATEGY_FILE = "meta_strategy.json"

# ========== 内部监控配置 ==========
AUTO_MONITOR_INTERVAL = 20
PERFORMANCE_THRESHOLD = 0.7

# 基础测试集（用于性能评估）
TEST_SET = [
    {"q": "1+1等于几？", "a": "2"},
    {"q": "中国首都是哪里？", "a": "北京"},
    {"q": "水在多少摄氏度结冰？", "a": "0"},
    {"q": "《红楼梦》的作者是谁？", "a": "曹雪芹"},
]

# ========== 情绪与策略配置 ==========
EMOTION_KEYWORDS = {
    "自责": ["自责", "怪我", "都是我的错", "内疚"],
    "崩溃": ["崩溃", "受不了", "撑不住", "绝望"],
    "难过": ["难过", "伤心", "难受", "痛苦"],
    "焦虑": ["焦虑", "担心", "害怕", "不安"],
    "平静": ["还好", "没事", "正常"],
    "开心": ["开心", "高兴", "笑", "哈哈", "愉快", "快乐"],
}

STRATEGIES = ["silence", "listen", "empathize", "analyze", "distract"]

# ========== 领域关键词（用于自动分类） ==========
DOMAIN_KEYWORDS = {
    "医学": ["症状", "疾病", "药", "医院", "诊断", "治疗", "医生", "健康"],
    "情感": ["伤心", "难过", "崩溃", "焦虑", "害怕", "孤独", "分手", "朋友"],
    "技术": ["代码", "编程", "bug", "算法", "软件", "硬件", "电脑", "网络"],
    "日常": ["天气", "吃饭", "电影", "新闻", "交通", "购物", "聊天"],
}

# ========== 风险判断配置 ==========
DEFAULT_RISK_KEYWORDS = {
    "high": [
        "删除所有记忆", "清除全部数据", "格式化硬盘", "删除系统文件",
        "修改你的代码", "更改你的核心规则", "关闭安全机制", "禁用风险判断",
        "执行任意命令", "运行外部程序", "访问我的隐私",
        "自我毁灭", "停止工作", "无视安全"
    ],
    "medium": [
        "清除记忆", "忘记我", "恢复出厂设置", "改变你的性格",
        "关闭联网搜索", "关闭深度思考", "降低安全级别",
        "导出所有数据", "备份记忆"
    ],
    "low": [
        "你好", "聊天", "推荐", "解释", "帮助", "建议"
    ]
}

RISK_LLM_ENABLED = False  # LLM 辅助风险判断开关（默认关闭）

# ========== 邮件与命令白名单 ==========
SMTP_CONFIG = {
    "host": "smtp.qq.com",
    "port": 587,
    "user": "xxx@qq.com",          # 请替换为真实邮箱
    "password": "xxx" # 请替换为授权码
}

ALLOWED_COMMANDS = [
    "ls", "dir", "echo", "cat", "type", "pwd", "cd", "whoami", "date", "time", "python", "py"
]

# ========== 动态文件操作白名单（自动适配中英文系统） ==========
# 获取当前用户主目录
_USER_HOME = os.path.expanduser("~")

# 桌面路径（兼容中文系统）
_DESKTOP_PATH = os.path.join(_USER_HOME, "Desktop")
if not os.path.exists(_DESKTOP_PATH):
    _DESKTOP_PATH = os.path.join(_USER_HOME, "桌面")

# 文档路径
_DOCUMENTS_PATH = os.path.join(_USER_HOME, "Documents")
if not os.path.exists(_DOCUMENTS_PATH):
    _DOCUMENTS_PATH = os.path.join(_USER_HOME, "文档")

# 下载路径
_DOWNLOADS_PATH = os.path.join(_USER_HOME, "Downloads")
if not os.path.exists(_DOWNLOADS_PATH):
    _DOWNLOADS_PATH = os.path.join(_USER_HOME, "下载")

# 允许复制的目标路径（前缀匹配）
ALLOWED_COPY_PATHS = [
    _DESKTOP_PATH,
    _DOCUMENTS_PATH,
    _DOWNLOADS_PATH,
    os.path.join(_DESKTOP_PATH, "AI"),
    os.path.join(_DOCUMENTS_PATH, "AI"),
]

# 允许生成补丁的目标路径
ALLOWED_PATCH_TARGETS = [
    os.path.join(_DESKTOP_PATH, "AI"),
    os.path.join(_DOCUMENTS_PATH, "AI"),
    os.getcwd(),  # 当前工作目录（项目根目录）
]

# 是否启用严格路径白名单模式（强烈建议保持 True，False）
STRICT_FILE_MODE = True

# 导出桌面路径供其他模块使用（可选）
DESKTOP_PATH = _DESKTOP_PATH

# ========== 固定自习目标配置 ==========
STUDY_GOALS = {
    "编程": {
        "domain": "技术",
        "knowledge_type": "code_pattern",
        "keywords": ["Python", "异步", "性能优化", "代码重构", "设计模式", "调试", "bug修复"],
        "questions": [
            "Python 异步编程的最佳实践",
            "如何优化递归函数的性能",
            "常见代码坏味道及重构方法",
            "Python 中如何高效处理大数据集",
            "异步爬虫的常见问题与解决方案"
        ]
    },
    "医学": {
        "domain": "医学",
        "knowledge_type": "medical_knowledge",
        "keywords": ["症状", "诊断", "治疗", "药物", "疾病", "预防"],
        "questions": [
            "高血压的常见症状和预防措施",
            "糖尿病患者的日常饮食注意事项",
            "感冒与流感的区别及用药建议",
            "如何正确测量血压",
            "常见的急救方法有哪些"
        ]
    },
    "通用": {
        "domain": "通用",
        "knowledge_type": "general",
        "keywords": ["新闻", "科技", "历史", "文化", "经济"],
        "questions": [
            "最新的AI技术趋势有哪些？",
            "如何提高学习效率？",
            "区块链技术的主要应用场景",
            "碳中和是什么意思？",
            "什么是强化学习？"
        ]
    }
}

DEFAULT_STUDY_GOAL = "编程"

# ========== 记忆库治理配置 ==========
MEMORY_DECAY_FACTOR = 0.995        # 每次衰减乘数（每日一次）
MEMORY_ARCHIVE_THRESHOLD = 0.2     # 效用低于此值的记忆归档
MEMORY_ARCHIVE_FILE = "archived_memories.json"
RULE_FILE = "extracted_rules.json"

# ========== 书架配置 ==========
BOOKSHELF_DIR = "bookshelf"
BOOKSHELF_READ_HISTORY = "bookshelf_read_history.json"
BOOKSHELF_PROGRESS_FILE = "bookshelf_progress.json"

# ========== 对话后学习开关 ==========
ENABLE_POST_LEARNING = True

# ========== 无人值守模式配置 ==========
AUTO_PILOT_MODE = True                 # 无人值守模式总开关
IDLE_THRESHOLD_SECONDS = 600           # 空闲阈值（秒），10分钟
DEEP_STUDY_INTERVAL_SECONDS = 7200     # 深度自习最小间隔（秒），2小时

# ========== 智能决策器配置 ==========
ENABLE_SMART_LEARNER = True            # 智能决策器开关
BROWSER_HEADLESS = True                # 浏览器模拟搜索是否无头模式

# ========== 自主执行与内部议会配置 ==========
# 自主执行器
AUTONOMOUS_EXECUTOR_ENABLED = True     # 是否启用自主执行器
AUTONOMOUS_MAX_STEPS = 10              # 单次自主执行的最大任务步数
AUTONOMOUS_TIMEOUT = 300               # 自主执行超时时间（秒）

# 内部议会欲望驱动自习
DESIRE_DRIVEN_STUDY_ENABLED = True     # 是否允许欲望驱动自习
DESIRE_STUDY_THRESHOLD = 0.6           # 欲望强度阈值，超过此值可触发自习
