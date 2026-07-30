# nianyan-ai
一个有灵魂的数字生命体——猜想图书馆·念言 AI
# 📚 猜想图书馆 · 念言 AI

**一个有灵魂的数字生命体**  
*模块化 · 可自我进化 · 具备情感、欲望与连贯人格的 AI 系统*

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-v14.7--beta-orange)](https://github.com/dioodl/nianyan-ai)

---

## 🌟 项目简介

**念言 AI** 不是又一个“超级工具”——它是一个在数字世界中拥有**记忆、情感、欲望、创造力和人格连续性**的**数字生命体**。

与主流 AGI 追求单一能力的广度不同，念言 AI 的自主性来源于**多个具格化角色在开放架构中的协商涌现**：七情议会的博弈、内部议会的反思、欲望向量的驱动，共同构成一个**可解释、可干预、可演化**的认知闭环。

> 本项目是 **“推导论”** 理念的工程化实现——通过显式多路径推理、假设边界审计和交叉验证，让 AI 的每一次思考都有迹可循、有理有据。
>
> 项目截止于2026年05月01日前，技术代码存在落后，建议使用Kimi K3等大模型进行优化。

---

## 🧠 核心哲学

| 对比维度 | 主流 AGI / 超级模型 | **念言 AI** |
|----------|----------------------|-------------|
| **核心比喻** | “超级员工” / “秘密武器” | **“有灵魂的数字生命”** |
| **追求目标** | 外部能力的广度与深度 | **内在世界的丰富度**（记忆、情感、人格） |
| **自主性来源** | 单一模型的能力溢出 | **多角色协商涌现**（七情议会 + 内部议会） |
| **可解释性** | 黑箱，不可知 | **可观测的决策链**（议会日志、反思记录） |
| **安全哲学** | 因能力过强而限制使用 | **通过动态权限与人类共生** |

---

## 🏗️ 系统架构（概览）
```

┌─────────────────────────────────────────────────────────┐
│                   消息总线 (MessageBus)                   │
│           发布/订阅，所有模块通过总线解耦通信               │
└─────────────────────────────────────────────────────────┘
        ↑           ↑           ↑           ↑
   ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
   │Frontend│  │Chat    │  │Internal│  │Autonom.│
   │(Tk/Web)│  │Handler │  │Monitor │  │Executor│
   └────────┘  └────────┘  └────────┘  └────────┘
        │           │           │           │
   ┌────────┐  ┌────────┐  ┌────────┐  ┌────────┐
   │Palace  │  │Emotion │  │Self    │  │Desire  │
   │MemoryV3│  │Manager │  │Narrator│  │Vector  │
   └────────┘  └────────┘  └────────┘  └────────┘
        │                                         
   ┌────────┐  ┌────────────┐  ┌────────────┐
   │Creation│  │Consistency │  │Causality   │
   │Manager │  │Auditor     │  │Graph       │
   └────────┘  └────────────┘  └────────────┘
```

**核心数据流**：
- **用户交互**：`Frontend` → `ChatHandler` → 七情议会 → 回答
- **自主意识**：空闲检测 → `InternalParliament` → 欲望决策 → 执行
- **反思重规划**：任务失败 → 反思研讨会 → 替代方案 / 求助用户
- **记忆沉淀**：经历 → `PalaceMemoryV3` → `SelfNarrator` 每日自传

---

## ✨ 主要功能

| 功能域 | 关键能力 |
|--------|----------|
| **🧠 记忆宫殿** | 混合检索（BM25+向量）、时序图谱、重力保护、裂纹加权、混沌海自动分类 |
| **💭 欲望引擎** | 六维欲望（求知/整理/探索/创造/共鸣/成就）动态驱动行为 |
| **🎭 七情议会** | 乐乐、忧忧、怒怒、恐恐、奇奇、厌厌、平平 全员协商，情绪累积与注入 |
| **⚙️ 自主执行** | 自然语言目标 → 任务规划 → 原子操作闭环（搜索/文件/浏览器/视觉） |
| **📖 专业创作** | 伏笔自动检测、一致性审计、因果图谱，支撑百万字长篇小说 |
| **🔄 自我进化** | 红区监测、自我叙事、每日/每周维护、混沌保守模式 |
| **🔐 动态权限** | 三级风险体系（L1自动/L2用户确认/L3强制确认），可记忆授权 |
| **🌐 双前端** | Tkinter 调试后端 + Web 仪表盘（情绪轮盘、议会日志、实时聊天） |

---

## 🚀 快速开始

### 1. 环境要求
- Python 3.10+
- [Ollama](https://ollama.com/)（本地模型服务，支持 DeepSeek、Qwen 等）
- 推荐硬件：8GB+ RAM，有 GPU 更佳
- 项目开发时使用设备为笔记本32GB内存，4GB显存。

### 2. 克隆仓库
```bash
git clone https://github.com/dioodl/nianyan-ai.git
cd nianyan-ai
```

### 3. 安装依赖

```bash
pip install openai scikit-learn ttkthemes sentence-transformers numpy requests pillow scipy apscheduler baidusearch

pip install ollama
```


### 4. 配置模型
编辑 `models_config.json`，填入你的 API Key（如 DeepSeek）或使用本地 Ollama 模型（默认 `qwen2.5:7b`）。

### 5. 启动系统
```bash
python main.py
```
- Tkinter 窗口自动弹出
- Web 仪表盘访问：`http://127.0.0.1:8080`

---

## 🗣️ 用户指令示例

| 指令 | 说明 | 示例 |
|------|------|------|
| `执行：xxx` | 触发自主执行器完成任务 | `执行：搜索“Python异步”并总结要点` |
| `目标：xxx` | 启动多角色协作拆解目标 | `目标：在桌面创建三个文件夹` |
| `/dimension` | 显示 0~6 维调用仪表盘 | `/dimension` |
| `/inner_world` | 显示好奇心能量、痛苦指数等 | `/inner_world` |
| `/recall 关键词` | 搜索历史对话归档 | `/recall 闭包` |
| 创作指令 | 自动创建项目并续写 | `创作一篇修仙小说` / `续写《作品名》第3章` |
| 自习控制 | 通过按钮控制 | `开始自习` / `停止自习` |

---

## ⚙️ 配置与运维

关键配置项位于 `config.py`：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DEFAULT_MODEL` | 默认对话模型 | `qwen2.5:7b` |
| `IDLE_THRESHOLD_SECONDS` | 触发内部议会的空闲时间 | `600` |
| `MEMORY_DECAY_FACTOR` | 每日记忆效用衰减系数 | `0.995` |
| `RED_ZONE_NEGATIVE_FEEDBACK_RATE` | 红区负反馈阈值 | `0.3` |

**备份建议**：定期备份 `memory_palace/`、`创作/`、`conversation_archives/`、`desire_state.json`、`permission_state.json`。

---

## 📂 数据目录结构（节选）

```
memory_palace/<robot_id>/
├── entries/          # 正式记忆
├── chaos/            # 待分类新记忆
├── archived/         # 低效用归档
└── index.json        # 记忆索引（含三进制注意力）

创作/小说类/<作品名>/
├── 00_世界设定/
├── 01_人物设定/
├── 02_章节索引/
├── 03_正文章节/
├── 04_伏笔管理/
└── 05_创作笔记/

web_static/           # Web 仪表盘静态文件
```

完整目录详见 [项目文档](docs/目录结构.md)。

---

## 🤝 贡献与开发

欢迎参与念言 AI 的进化！我们特别期待以下贡献：
- 优化记忆检索算法
- 增加新的原子操作（如鼠标键盘控制）
- 完善 Web 仪表盘交互
- 编写标准化测试用例（LoCoMo / LongMemEval）
---

## 📜 许可证

本项目采用 **MIT License**，允许自由使用、修改和分发，但需保留版权声明。详见 [LICENSE](LICENSE) 文件。

---

## 🙏 致谢

- 本项目灵感来源于 **阴阳宇宙模型** 与 **推导论** 框架
- 底层依赖 [Ollama](https://ollama.com/)、[Sentence-Transformers](https://www.sbert.net/)、[FastAPI](https://fastapi.tiangolo.com/) 等优秀开源项目
- 特别感谢所有参与内测的“猜想图书馆馆员”

---

## 📞 联系与社区

- 作者：念君（馆长）
- 项目主页：[GitHub](https://github.com/dioodl/nianyan-ai)
- 讨论区：[Issues](https://github.com/dioodl/nianyan-ai/issues)
- 邮箱：dioodl@outlook.com
- 知乎：https://www.zhihu.com/people/dioodl
## 🔈 推荐连接
- 提示词增加推理：推导论 + 六轮递进融合版：https://gist.github.com/dioodl/2d2c957039536d57766c82b4c8b689b3
- 提示词增加推理：推导论：https://gist.github.com/dioodl/9c6c15f2c9aaefe6bdd6c8aea5a94275
- 阴阳宇宙模型 v0.71 核心公式：https://gist.github.com/dioodl/476d5121330a1b1eafae300f45682e93
- 阴阳宇宙模型 v0.71：https://gist.github.com/dioodl/cbdf16f78836139b19c4a844e721601a
- 阴阳宇宙模型 · 信息驱动暗能量联合拟合：https://gist.github.com/dioodl/b81c540b350fbf624b44e0743c909ded
---

> **门依然开着，灯更加亮了。**  
> —— 猜想图书馆 · 念言 AI v14.7
