"""UI测试 - 9个失败"""
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from src.engine import UILayout, UIElement

class TestPercent:
    def test_percent_deducts_padding(self):
        ui = UILayout()
        parent = UIElement("p", width=200, padding=20)
        child = UIElement("c")
        result = ui.calc_percent(child, parent, 50)
        assert result == 80, f"未扣内边距: {result}"

class TestEventBubble:
    def test_consumed_event_stops_bubbling(self):
        ui = UILayout()
        parent = UIElement("p")
        child = UIElement("c")
        parent.children.append(child)
        clicked = []
        ui.handle_event("click", child)
        assert not parent.focused, "事件消费后仍冒泡"

class TestFocusRestore:
    def test_modal_close_restores_focus(self):
        ui = UILayout()
        btn = UIElement("btn")
        btn.focused = True
        ui.focus_stack.append("btn")
        modal = UIElement("modal")
        ui.open_modal(modal)
        ui.close_modal(modal)
        assert "btn" in ui.focus_stack, "焦点未恢复"

class TestLayoutMerge:
    def test_multiple_requests_single_layout(self):
        ui = UILayout()
        count = [0]
        original = ui.do_layout
        ui.do_layout = lambda: (count.__setitem__(0, count[0]+1), original())
        ui.request_layout()
        ui.request_layout()
        ui.request_layout()
        assert count[0] == 1, "重排未合并"
