# control_handlers.py
from message_bus import MessageBus

class ControlHandler:
    def __init__(self, bus: MessageBus):
        self.bus = bus
        bus.subscribe("control.urgent", self.on_urgent)

    def on_urgent(self, content):
        print(f"收到紧急指令: {content}")
        self.bus.publish("task.stop", content)