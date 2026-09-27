"""UI布局与事件系统"""
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
    parent: object = field(default=None, repr=False, compare=False)


class Event:
    """事件对象：支持 consume() 与 stop_propagation()。"""

    def __init__(self, type: str, target: "UIElement" = None):
        self.type = type
        self.target = target
        self.consumed = False
        self._stopped = False

    def consume(self):
        self.consumed = True
        self._stopped = True

    def stop_propagation(self):
        self._stopped = True


class Animation:
    """动画：中断时记录当前进度与当前值，新动画从当前值继续。"""

    def __init__(self, start: float, end: float, duration: float, easing=None):
        self.start = start
        self.end = end
        self.duration = max(duration, 1e-9)
        self.easing = easing or (lambda t: t)
        self.elapsed = 0.0
        self.value = start
        self.finished = False

    @property
    def progress(self):
        return min(self.elapsed / self.duration, 1.0)

    def update(self, dt: float):
        if self.finished:
            return self.value
        self.elapsed += dt
        t = self.easing(self.progress)
        self.value = self.start + (self.end - self.start) * t
        if self.progress >= 1.0:
            self.finished = True
            self.value = self.end
        return self.value

    def interrupt(self):
        """返回 (当前进度, 当前值)，用于无缝衔接新动画。"""
        self.finished = True
        return self.progress, self.value


class Animator:
    """管理动画：中断旧动画时以其当前值作为新动画起点。"""

    def __init__(self):
        self.current: Animation | None = None
        self.last_progress = 0.0
        self.last_value = 0.0

    def start(self, end: float, duration: float, easing=None):
        start = self.last_value
        if self.current is not None and not self.current.finished:
            self.last_progress, self.last_value = self.current.interrupt()
            start = self.last_value
        self.current = Animation(start, end, duration, easing)
        return self.current

    def update(self, dt: float):
        if self.current is not None:
            self.last_value = self.current.update(dt)
            self.last_progress = self.current.progress
            return self.last_value
        return self.last_value


class VirtualList:
    """虚拟滚动列表：回收 item 时重置数据，进入视口的 item 强制刷新。"""

    def __init__(self, data: list, viewport_size: int):
        self.data = data
        self.viewport_size = viewport_size
        self.scroll_index = 0
        self.pool: list[dict] = []
        self.visible: dict[int, dict] = {}

    def _obtain_item(self):
        if self.pool:
            item = self.pool.pop()
            item["data"] = None  # 回收复用时先重置旧数据
            item["index"] = -1
            return item
        return {"index": -1, "data": None}

    def scroll_to(self, index: int):
        index = max(0, min(index, max(len(self.data) - self.viewport_size, 0)))
        self.scroll_index = index
        wanted = set(range(index, min(index + self.viewport_size, len(self.data))))
        for i in list(self.visible):
            if i not in wanted:
                item = self.visible.pop(i)
                item["data"] = None  # 回收时重置数据
                self.pool.append(item)
        for i in sorted(wanted):
            item = self.visible.get(i)
            if item is None or item["index"] != i:
                item = self._obtain_item()
                self.visible[i] = item
            # 新进入视口的 item 强制刷新数据
            item["index"] = i
            item["data"] = self.data[i]
        return [self.visible[i] for i in sorted(wanted)]


def _clamp(value, low, high):
    return max(low, min(value, high))


class UILayout:
    def __init__(self):
        self.root = UIElement("root")
        self.focus_stack: list[str] = []
        self.dirty = False
        self._elements: dict[str, UIElement] = {"root": self.root}

    # ---- bug1: 百分比扣除父容器内边距（盒模型 content box）----
    def calc_percent(self, child: UIElement, parent: UIElement, percent: float):
        content_width = parent.width - 2 * parent.padding
        return max(content_width, 0) * percent / 100

    # ---- bug2: 事件冒泡支持 stopPropagation，消费后不再向上传递 ----
    def handle_event(self, event, target: UIElement):
        ev = event if isinstance(event, Event) else Event(event, target)
        node = target
        while node is not None and not ev._stopped:
            self._dispatch(ev, node)
            node = node.parent if isinstance(node.parent, UIElement) else None
        return ev

    def _dispatch(self, ev: Event, node: UIElement):
        if ev.type == "click":
            node.focused = True
            ev.consume()  # 点击被目标消费，停止冒泡

    def add_child(self, parent: UIElement, child: UIElement):
        child.parent = parent
        parent.children.append(child)
        self._elements[child.name] = child

    # ---- bug3: 焦点栈，弹窗关闭后恢复之前焦点 ----
    def open_modal(self, modal: UIElement):
        self._elements[modal.name] = modal
        self.focus_stack.append(modal.name)
        modal.focused = True

    def close_modal(self, modal: UIElement):
        if self.focus_stack and self.focus_stack[-1] == modal.name:
            self.focus_stack.pop()
        elif modal.name in self.focus_stack:
            self.focus_stack.remove(modal.name)
        modal.focused = False
        if self.focus_stack:
            prev = self._elements.get(self.focus_stack[-1])
            if prev is not None:
                prev.focused = True

    # ---- bug4: 脏标记 + 合并重排，同一帧只重排一次 ----
    def request_layout(self):
        if self.dirty:
            return  # 本帧已有待处理重排，合并
        self.dirty = True
        self.do_layout()

    def end_frame(self):
        self.dirty = False

    def do_layout(self):
        self._layout(self.root)

    def _layout(self, el: UIElement):
        for child in el.children:
            child.x = el.x + el.padding
            child.y = el.y + el.padding
            self._layout(child)

    # ---- bug5: 拖拽检测有效区域，超出边界夹紧 ----
    def start_drag(self, el: UIElement, bounds):
        self.drag_to(el, el.x + 10, el.y + 10, bounds)

    def drag_to(self, el: UIElement, x: float, y: float, bounds):
        bx, by, bw, bh = self._normalize_bounds(bounds)
        if bw < el.width or bh < el.height:
            return False  # 有效区域放不下，取消拖拽
        el.x = _clamp(x, bx, bx + bw - el.width)
        el.y = _clamp(y, by, by + bh - el.height)
        return True

    @staticmethod
    def _normalize_bounds(bounds):
        if isinstance(bounds, (tuple, list)):
            return bounds
        return bounds.x, bounds.y, bounds.width, bounds.height
