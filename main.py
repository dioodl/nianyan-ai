# main.py (v14.11 - 集成工具目录 + 动态权限管理器 + 深度阅读器)
import os
import sys
import subprocess
import threading
import asyncio
import logging
import io

# --- 屏蔽 SentenceTransformer 加载时的进度条和报告 ---
os.environ["TRANSFORMERS_VERBOSITY"] = "error"
os.environ["TOKENIZERS_VERBOSITY"] = "error"
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
logging.getLogger("transformers").setLevel(logging.WARNING)

class _FilteredStderr(io.StringIO):
    def __init__(self, original_stderr):
        super().__init__()
        self.original_stderr = original_stderr
    def write(self, s):
        if "Loading weights" not in s and "BertModel LOAD REPORT" not in s and "UNEXPECTED" not in s:
            return self.original_stderr.write(s)
        return len(s)
    def flush(self):
        self.original_stderr.flush()

sys.stderr = _FilteredStderr(sys.stderr)
# -------------------------------------------------------

from message_bus import MessageBus
from frontend import ChatFrontend
from intent_classifier import IntentClassifierModule
from chat_handler import ChatHandlerModule
from task_executor import TaskExecutorModule
from priority_arbiter import PriorityArbiter
from task_planner_agent import TaskPlannerAgent
from control_handlers import ControlHandler
from auto_learner import AutoLearner
from supervisor import Supervisor
from version_manager import VersionManager
from code_generator import CodeGenerator
from b_brain import BBrain
from intent_router import IntentRouter
from emotion_manager import EmotionManager
from strategy_optimizer import StrategyOptimizer
from internal_monitor import InternalMonitor
from optimizer import Optimizer
from conversation_archiver import ConversationArchiver
from autopilot import AutoPilot
from smart_learner import SmartLearner
from info_store import InfoStore
from palace_memory_v3 import PalaceMemoryV3
from dimension_tracker import DimensionTracker, set_tracker_logging
from inner_world import InnerWorld
from cognitive_engine import CognitiveEngine
from deep_dream import DeepDream
from internal_parliament import InternalParliament
from self_narrator import SelfNarrator
from autonomous_executor import AutonomousExecutor
from task_queue import TaskQueue
from permission_manager import PermissionManager
import atomic_actions

from meta_cognition_retriever import get_meta_retriever
# from web_dashboard import WebDashboard
from model_router import ModelRouter

# 工具插件相关导入
# from tools.tool_dispatcher import register_tool
# from tools.browser_tools import register_browser_tools, set_router as browser_set_router, set_bus as browser_set_bus
from tools.deep_reader import register_deep_reader  # 深度阅读器
from tools.tools_catalog import init_catalog  # 工具目录


def cleanup_browsers():
    try:
        subprocess.run(['taskkill', '/f', '/im', 'chromium.exe'],
                       capture_output=True, shell=True)
        print("🧹 已清理残留 Chromium 进程")
    except:
        pass


def start_global_event_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


def main():
    if "--dimension-log" in sys.argv:
        set_tracker_logging(True)
        print("📐 维度追踪日志已开启")

    cleanup_browsers()

    # 全局事件循环
    global_loop = asyncio.new_event_loop()
    loop_thread = threading.Thread(target=start_global_event_loop, args=(global_loop,), daemon=True)
    loop_thread.start()
    print("🔄 全局异步事件循环已启动")

    bus = MessageBus()
    bus.global_loop = global_loop
    bus.active_behavior_lock = threading.Lock()

    # ✅ 初始化工具能力目录（念言的自我认知）
    tools_catalog = init_catalog()
    bus.tools_catalog = tools_catalog
    print("🔧 [工具目录] 已初始化，念言已获知自身能力")

    # ✅ 初始化模型路由器
    model_router = ModelRouter(max_concurrent_requests=2)
    bus.model_router = model_router
    print("🚀 模型路由器已初始化，配置已加载")

    # ✅ 注入原子操作模块
    atomic_actions.set_router(model_router)

    # ✅ 浏览器工具插件已注释（关闭浏览器功能）
    # print("🔧 正在加载外部工具插件...")
    # browser_set_router(model_router)
    # browser_set_bus(bus)
    # try:
    #     register_browser_tools()
    #     print("   ✅ 浏览器工具插件已加载")
    # except Exception as e:
    #     print(f"   ⚠️ 浏览器工具插件加载失败: {e}，搜索功能将不可用")

    arbiter = PriorityArbiter(bus)
    vm = VersionManager()

    atomic_actions.set_message_bus(bus)

    archiver = ConversationArchiver()
    palace_memory = PalaceMemoryV3(robot_id="default")
    info_store = InfoStore()

    emotion_mgr = EmotionManager()
    emotion_mgr.bus = bus
    strategy_opt = StrategyOptimizer()

    frontend = ChatFrontend(bus, arbiter, archiver=archiver)

    IntentClassifierModule(bus)
    chat_handler = ChatHandlerModule(bus, window_id="main", palace_memory=palace_memory,
                                     emotion_mgr=emotion_mgr, strategy_opt=strategy_opt,
                                     archiver=archiver, info_store=info_store)
    bus.chat_handler = chat_handler

    TaskExecutorModule(bus)
    task_executor = bus.task_executor

    TaskPlannerAgent(bus, arbiter)

    # ❌ 旧的 AutoLearner 已禁用，SmartLearner 完全替代
    # auto_learner = AutoLearner(bus, memory=palace_memory)
    auto_learner = None

    ControlHandler(bus)
    supervisor = Supervisor(bus, palace_memory=palace_memory)

    IntentRouter(bus)

    code_gen = CodeGenerator(bus, vm, memory=palace_memory)
    b_brain = BBrain(bus, vm, code_gen)

    monitor = InternalMonitor(bus, code_generator=code_gen, memory=palace_memory)
    optimizer = Optimizer(bus, code_generator=code_gen)

    inner_world = InnerWorld(bus)

    cognitive_engine = CognitiveEngine(
        bus=bus,
        intent_classifier=None,
        chat_handler=chat_handler,
        palace_memory=palace_memory,
        auto_learner=None,   # 已禁用
        internal_monitor=monitor,
        smart_learner=None,
        inner_world=inner_world
    )

    smart_learner = SmartLearner(bus, palace_memory, None, cognitive_engine=cognitive_engine)
    cognitive_engine.smart_learner = smart_learner

    deep_dream = DeepDream(palace_memory, bus=bus, cognitive_engine=cognitive_engine)

    internal_parliament = InternalParliament(
        bus=bus,
        chat_handler=chat_handler,
        palace_memory=palace_memory,
        auto_learner=None,   # 已禁用
        smart_learner=smart_learner,
        cognitive_engine=cognitive_engine
    )

    monitor.cognitive_engine = cognitive_engine

    # 初始化自我叙事编织器
    self_narrator = SelfNarrator(
        palace_memory=palace_memory,
        model="qwen2.5:7b",
        cognitive_engine=cognitive_engine
    )
    bus.self_narrator = self_narrator

    # 初始化自主执行器
    autonomous_executor = AutonomousExecutor(
        bus=bus,
        task_executor=task_executor,
        palace_memory=palace_memory
    )
    bus.autonomous_executor = autonomous_executor

    # 初始化任务队列
    task_queue = TaskQueue(bus)
    task_queue.start()
    bus.task_queue = task_queue
    print("✅ 任务队列已初始化并启动")

    # ✅ 初始化动态权限管理器
    permission_manager = PermissionManager(bus)
    bus.permission_manager = permission_manager
    print("🔐 动态权限管理器已激活")

    # 订阅自主执行目标
    def on_autonomous_goal(data):
        goal = data.get("goal", "")
        user_id = data.get("user_id", "user")
        if goal:
            asyncio.run_coroutine_threadsafe(
                autonomous_executor.execute_goal(goal, user_id),
                global_loop
            )

    bus.subscribe("user.goal.autonomous", on_autonomous_goal)

    autopilot = AutoPilot(bus, smart_learner, global_loop)

    tracker = DimensionTracker()
    bus.tracker = tracker

    bus.inner_world = inner_world
    bus.cognitive_engine = cognitive_engine
    bus.deep_dream = deep_dream
    bus.internal_parliament = internal_parliament
    bus.emotion_mgr = emotion_mgr
    bus.palace_memory = palace_memory

    chaos_dir = os.path.join(palace_memory.base_dir, "chaos")
    os.makedirs(chaos_dir, exist_ok=True)

    print("📚 加载元认知知识库...")
    meta_retriever = get_meta_retriever()
    bus.meta_retriever = meta_retriever
    print("  元认知知识库已就绪。")

    # ✅ 注册深度阅读器工具
    print("📖 正在注册深度阅读器...")
    try:
        register_deep_reader(model_router, palace_memory)
        print("   ✅ 深度阅读器已就绪")
    except Exception as e:
        print(f"   ⚠️ 深度阅读器注册失败: {e}")

    cognitive_engine.start()
    monitor.start_monitoring(interval_seconds=604800)  # 每周检查一次

    # dashboard = WebDashboard(bus)
    # dashboard.start()

    print("念言AI 启动完成。")
    print("欲望向量、自我叙事编织器、自主执行器、任务队列、模型路由器已激活。")
    print("跨学科议会、深度研讨模式、深度阅读器、动态权限管理器已就绪。")
    # print(f"🌐 灵魂面板已开启：http://{dashboard.host}:{dashboard.port}")
    print("🌐 Web 仪表盘已关闭（按需可恢复）")
    frontend.run()


if __name__ == "__main__":
    main()