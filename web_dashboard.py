# web_dashboard.py (集成动态权限审批)
import asyncio
import threading
import uuid
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
import uvicorn
from message_bus import MessageBus


class WebDashboard:
    def __init__(self, bus: MessageBus, host: str = "127.0.0.1", port: int = 8080):
        self.bus = bus
        self.host = host
        self.port = port
        self.app = FastAPI()
        self.active_connections: list[WebSocket] = []
        self.chat_connections: dict[str, WebSocket] = {}
        self.pending_responses: dict[str, str] = {}
        self.response_lock = threading.Lock()

        # 创建专用后台事件循环
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.loop_thread.start()

        self.app.mount("/static", StaticFiles(directory="web_static"), name="static")

        @self.app.get("/")
        async def get_index():
            try:
                with open("web_static/index.html", "r", encoding="utf-8") as f:
                    return HTMLResponse(f.read())
            except FileNotFoundError:
                with open("web_static/dashboard.html", "r", encoding="utf-8") as f:
                    return HTMLResponse(f.read())

        @self.app.websocket("/ws")
        async def dashboard_websocket(websocket: WebSocket):
            await websocket.accept()
            self.active_connections.append(websocket)
            print(f"🔗 仪表盘连接，总数: {len(self.active_connections)}")
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                self.active_connections.remove(websocket)
                print(f"🔌 仪表盘断开，剩余: {len(self.active_connections)}")

        @self.app.websocket("/ws/chat")
        async def chat_websocket(websocket: WebSocket):
            await websocket.accept()
            session_id = str(uuid.uuid4())
            self.chat_connections[session_id] = websocket
            print(f"💬 聊天连接: {session_id[:8]}...")
            await websocket.send_json({"type": "system", "content": "连接成功"})
            try:
                while True:
                    try:
                        raw_data = await websocket.receive_text()
                        if not raw_data:
                            continue
                        data = json.loads(raw_data)
                    except:
                        continue

                    action = data.get("action")
                    if action == "send_message":
                        message = data.get("message", "").strip()
                        deep_reasoning = data.get("deep_reasoning", False)
                        if message:
                            request_id = str(uuid.uuid4())
                            await websocket.send_json({"type": "request_id", "request_id": request_id})
                            loop = asyncio.get_running_loop()
                            response = await loop.run_in_executor(
                                None,
                                self.bus.chat_handler.process_message_sync,
                                message,
                                session_id,
                                deep_reasoning
                            )
                            with self.response_lock:
                                self.pending_responses[request_id] = response
                            print(f"📤 回答已存储，request_id: {request_id[:8]}...")
                    elif action == "start_study":
                        self.bus.publish("smart_learner.manual", {})
                    elif action == "stop_study":
                        self.bus.publish("smart_learner.stop", {})
                    elif action == "deep_study":
                        self.bus.publish("smart_learner.deep_study", {})
            except WebSocketDisconnect:
                pass
            finally:
                if session_id in self.chat_connections:
                    del self.chat_connections[session_id]

        @self.app.get("/api/response/{request_id}")
        async def get_response(request_id: str):
            with self.response_lock:
                if request_id in self.pending_responses:
                    response = self.pending_responses.pop(request_id)
                    return {"status": "ready", "content": response}
                else:
                    return {"status": "pending"}

        @self.app.get("/api/energy")
        async def get_energy():
            energy = 0.5
            if hasattr(self.bus, 'cognitive_engine') and self.bus.cognitive_engine:
                state = self.bus.cognitive_engine.get_state()
                energy = state.get("curiosity_energy", 0.5)
            return {"energy": energy}

        # ========== 权限审批接口 ==========
        @self.app.post("/api/permission/response")
        async def permission_response(data: dict):
            request_id = data.get("request_id")
            granted = data.get("granted", False)
            remember = data.get("remember", False)
            if request_id:
                self.bus.publish("permission.response", {
                    "request_id": request_id,
                    "granted": granted,
                    "remember": remember,
                    "user_id": "web"
                })
                print(f"🔐 [Web] 权限审批: {request_id} -> {'允许' if granted else '拒绝'}")
            return {"status": "ok"}

        # 订阅仪表盘事件，通过专用循环安全执行
        bus.subscribe("dashboard.state_update", self._sync(self.on_state_update))
        bus.subscribe("emotion.state_changed", self._sync(self.on_emotion_changed))
        bus.subscribe("internal.parliament.log", self._sync(self.on_parliament_log))
        bus.subscribe("multi_agent.log", self._sync(self.on_multi_agent_log))
        bus.subscribe("thinking.log", self._sync(self.on_thinking_log))
        bus.subscribe("permission.request", self._sync(self.on_permission_request))  # 新增：权限申请推送

        print("✅ WebDashboard 事件订阅完成（仪表盘状态推送 + 权限审批已激活）")

        # 挂载自身到 bus
        bus.web_dashboard = self

    def _run_event_loop(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def _sync(self, async_func):
        """返回同步函数，将异步调用安全提交到后台循环"""
        def wrapper(data):
            asyncio.run_coroutine_threadsafe(async_func(data), self.loop)
        return wrapper

    # ---------- 仪表盘广播回调 ----------
    async def on_state_update(self, data):
        await self.broadcast_dashboard({"type": "state_update", "data": data})

    async def on_emotion_changed(self, data):
        valence = data.get('current_vector', {}).get('valence', 0)
        print(f"📡 情绪更新，效价={valence:.2f}")
        await self.broadcast_dashboard({"type": "emotion", "data": data})

    async def on_parliament_log(self, data):
        await self.broadcast_dashboard({"type": "parliament_log", "data": data})

    async def on_multi_agent_log(self, data):
        await self.broadcast_dashboard({"type": "multi_agent_log", "data": data})

    async def on_thinking_log(self, data):
        await self.broadcast_dashboard({"type": "thinking_log", "data": data})

    async def broadcast_dashboard(self, message: dict):
        for conn in self.active_connections:
            try:
                await conn.send_json(message)
            except:
                pass

    # ---------- 权限申请推送 ----------
    async def on_permission_request(self, data):
        """将权限申请推送到所有仪表盘 WebSocket 连接"""
        await self.broadcast_dashboard({"type": "permission_request", "data": data})
        print(f"🔐 [WebDashboard] 推送权限申请: {data.get('request_id')}")

    def start(self):
        def run_server():
            uvicorn.run(self.app, host=self.host, port=self.port, log_level="info")
        self.thread = threading.Thread(target=run_server, daemon=True)
        self.thread.start()
        print(f"🌐 Web 仪表盘已启动：http://{self.host}:{self.port}")