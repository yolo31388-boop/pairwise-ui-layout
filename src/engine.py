"""UI布局 - 7个bug已修复

1. 百分比计算扣除父容器内边距（盒模型 content-box）
2. 事件冒泡支持 stopPropagation，消费后停止
3. 焦点栈管理，弹窗关闭恢复之前焦点
4. 重排脏标记 + 帧内合并
5. 拖拽目标区域检测，越界夹紧
6. 虚拟滚动回收重置数据，新 item 强制刷新
7. 动画中断记录进度和当前值，新动画从当前值继续
"""
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
    parent: object = None
    handlers: dict = field(default_factory=dict)


class Event:
    """UI事件，支持 stopPropagation 与消费标记。"""

    def __init__(self, type: str, target: UIElement):
        self.type = type
        self.target = target
        self.consumed = False
        self._stopped = False

    def stopPropagation(self):
        self._stopped = True

    @property
    def propagation_stopped(self) -> bool:
        return self._stopped or self.consumed


class UILayout:
    def __init__(self):
        self.root = UIElement("root")
        self.focus_stack: list[str] = []
        self._focus_registry: dict[str, UIElement] = {}
        self.dirty = False

    # ---- bug1: 百分比扣除父容器内边距（盒模型 content 区域）----
    def calc_percent(self, child: UIElement, parent: UIElement, percent: float):
        content_width = max(0.0, parent.width - 2 * parent.padding)
        return content_width * percent / 100

    # ---- bug2: 事件冒泡，消费或 stopPropagation 后停止 ----
    def add_child(self, parent: UIElement, child: UIElement):
        child.parent = parent
        parent.children.append(child)

    def handle_event(self, event, target: UIElement):
        if isinstance(event, str):
            event = Event(event, target)
        el = target
        while el is not None and not event.propagation_stopped:
            self._dispatch(event, el)
            el = el.parent

    def _dispatch(self, event: Event, el: UIElement):
        handler = el.handlers.get(event.type)
        if handler is not None:
            if handler(event, el):
                event.consumed = True
            return
        # 默认行为：click 聚焦并消费
        if event.type == "click":
            el.focused = True
            event.consumed = True

    # ---- bug3: 焦点栈，弹窗关闭恢复之前焦点 ----
    def set_focus(self, el: UIElement):
        if self.focus_stack and self.focus_stack[-1] in self._focus_registry:
            self._focus_registry[self.focus_stack[-1]].focused = False
        self.focus_stack.append(el.name)
        self._focus_registry[el.name] = el
        el.focused = True

    def open_modal(self, modal: UIElement):
        if self.focus_stack and self.focus_stack[-1] in self._focus_registry:
            self._focus_registry[self.focus_stack[-1]].focused = False
        self.focus_stack.append(modal.name)
        self._focus_registry[modal.name] = modal
        modal.focused = True

    def close_modal(self, modal: UIElement):
        if modal.name in self.focus_stack:
            self.focus_stack.remove(modal.name)
        modal.focused = False
        # 恢复栈顶（之前）元素的焦点
        if self.focus_stack:
            prev = self._focus_registry.get(self.focus_stack[-1])
            if prev is not None:
                prev.focused = True

    # ---- bug4: 脏标记 + 同帧合并重排 ----
    def request_layout(self):
        if self.dirty:
            return  # 本帧已调度，合并掉重复请求
        self.dirty = True
        self.do_layout()

    def end_frame(self):
        """帧结束，清除脏标记，下一帧可再次重排。"""
        self.dirty = False

    def do_layout(self):
        self._layout(self.root)

    def _layout(self, el: UIElement):
        for child in el.children:
            child.parent = el
            child.x = el.x + el.padding
            child.y = el.y + el.padding
            self._layout(child)

    # ---- bug5: 拖拽检测有效区域，越界夹紧到边界 ----
    def start_drag(self, el: UIElement, bounds):
        self.drag(el, 10, 10, bounds)

    def drag(self, el: UIElement, dx: float, dy: float, bounds) -> bool:
        """bounds 为 (min_x, min_y, max_x, max_y)；返回 False 表示拖拽被取消。"""
        min_x, min_y, max_x, max_y = self._normalize_bounds(bounds)
        if max_x < min_x or max_y < min_y:
            return False  # 无效区域，取消拖拽
        nx = min(max(el.x + dx, min_x), max(min_x, max_x - el.width))
        ny = min(max(el.y + dy, min_y), max(min_y, max_y - el.height))
        el.x, el.y = nx, ny
        return True

    @staticmethod
    def _normalize_bounds(bounds):
        if isinstance(bounds, dict):
            return bounds["min_x"], bounds["min_y"], bounds["max_x"], bounds["max_y"]
        return tuple(bounds)


# ---- bug6: 虚拟滚动，回收重置数据，新 item 强制刷新 ----
class ItemView:
    def __init__(self):
        self.index = None
        self.data = None
        self.refreshed = False

    def reset(self):
        self.index = None
        self.data = None
        self.refreshed = False

    def refresh(self, index, data):
        self.index = index
        self.data = data
        self.refreshed = True


class VirtualScroll:
    def __init__(self, items: list, viewport_size: int):
        self.items = items
        self.viewport_size = viewport_size
        self.offset = 0
        self.active: dict[int, ItemView] = {}
        self.pool: list[ItemView] = []
        self.scroll_to(0)

    def scroll_to(self, offset: int):
        self.offset = max(0, min(offset, max(0, len(self.items) - 1)))
        start = self.offset
        end = min(len(self.items), start + self.viewport_size)
        # 回收滚出视口的 item：重置数据后再入池
        for index in list(self.active):
            if not (start <= index < end):
                view = self.active.pop(index)
                view.reset()
                self.pool.append(view)
        # 新进入视口的 item：优先复用回收 view，并强制刷新数据
        for index in range(start, end):
            if index not in self.active:
                view = self.pool.pop() if self.pool else ItemView()
                view.refresh(index, self.items[index])
                self.active[index] = view
        return [self.active[i] for i in range(start, end)]


# ---- bug7: 动画中断记录进度和当前值，新动画从当前值继续 ----
def linear(t: float) -> float:
    return t


def ease_in_out(t: float) -> float:
    return t * t * (3 - 2 * t)


class Animation:
    def __init__(self, start: float, end: float, duration: float, easing=linear):
        self.start = start
        self.end = end
        self.duration = max(duration, 1e-9)
        self.easing = easing
        self.elapsed = 0.0
        self.progress = 0.0
        self.value = start

    @property
    def done(self) -> bool:
        return self.elapsed >= self.duration

    def update(self, dt: float) -> float:
        self.elapsed = min(self.elapsed + dt, self.duration)
        self.progress = self.elapsed / self.duration
        self.value = self.start + (self.end - self.start) * self.easing(self.progress)
        return self.value

    def interrupt(self) -> float:
        """中断动画，返回当前值（progress 已记录在 self.progress）。"""
        return self.value


class Animator:
    """管理单个属性的动画；新动画自动从中断处的当前值继续。"""

    def __init__(self, initial: float = 0.0):
        self.value = initial
        self.current: Animation | None = None

    def start(self, target: float, duration: float, easing=linear) -> Animation:
        begin = self.value
        if self.current is not None and not self.current.done:
            begin = self.current.interrupt()  # 从当前值继续，而不是从0开始
        self.current = Animation(begin, target, duration, easing)
        self.value = begin
        return self.current

    def update(self, dt: float) -> float:
        if self.current is not None:
            self.value = self.current.update(dt)
        return self.value
