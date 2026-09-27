"""UI布局 - 带7个bug"""
from dataclasses import dataclass, field

@dataclass
class UIElement:
    name: str
    x: float = 0
    y: float = 0
    width: float = 100
    height: float = 100
    padding: float = 0
    children: list = field(default_factory=list)
    visible: bool = True
    focused: bool = False

class UILayout:
    def __init__(self):
        self.root = UIElement("root")
        self.focus_stack: list[str] = []
        self.dirty = False

    def calc_percent(self, child: UIElement, parent: UIElement, percent: float):
        # bug1: 不扣除内边距
        return parent.width * percent / 100

    def handle_event(self, event: str, target: UIElement):
        # bug2: 事件消费后不停止冒泡
        if event == "click":
            target.focused = True
        for child in target.children:
            self.handle_event(event, child)

    def open_modal(self, modal: UIElement):
        self.focus_stack.append(modal.name)
        modal.focused = True

    def close_modal(self, modal: UIElement):
        if modal.name in self.focus_stack:
            self.focus_stack.remove(modal.name)
        # bug3: 不恢复之前的焦点
        modal.focused = False

    def request_layout(self):
        # bug4: 不合并重排
        self.do_layout()

    def do_layout(self):
        self._layout(self.root)
        self.dirty = False

    def _layout(self, el: UIElement):
        for child in el.children:
            child.x = el.x + child.padding
            child.y = el.y + child.padding

    def start_drag(self, el: UIElement, bounds):
        # bug5: 不检测有效区域
        el.x += 10
        el.y += 10
