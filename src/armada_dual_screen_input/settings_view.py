"""Focus-free settings surface using the same logical hit rectangles as input."""
from . import steam_style as s
from .input_settings import BOOLEANS, CHOICES, NUMBERS, SECTIONS

TITLES = {"mouse": "鼠标", "position": "定位触摸", "keyboard": "键盘"}
TOGGLES = {
    "tap_to_click": ("轻点点击", "单指轻点触控板，模拟鼠标左键"),
    "glide": ("惯性滑行", "手指松开后，鼠标继续短暂滑动"),
    "keyboard_repeat_enabled": ("长按重复输入", "按住字母、退格或方向键连续输入"),
}


def draw(cr, draft):
    cr.set_source_rgb(*s.FG)
    s.label(cr, "输入设置", 28, 150, 34, bold=True)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, "仅影响虚拟键鼠 · 保存后生效 · 重启后保留", 28, 194, 22)
    for index, section in enumerate(SECTIONS):
        s.button(cr, 24 + index * 204, 220, 192, 60,
                 TITLES[section], draft.section == section, tab=True)
    for key, top in draft.rows():
        s.rounded(cr, 24, top, 1192, 88, 8, s.SURFACE)
        if key in CHOICES:
            cr.set_source_rgb(*s.FG)
            s.label(cr, "键盘语言", 44, top + 12, 26)
            cr.set_source_rgb(*s.MUTED)
            s.label(cr, "点击切换 · 中文拼音目前用于 Game Mode", 44, top + 55, 21, max_width=700)
            s.button(cr, 790, top + 12, 402, 64,
                     CHOICES[key][draft.values[key]], True)
            continue
        spec = NUMBERS.get(key)
        title, note = (spec.label, spec.note) if spec else TOGGLES[key]
        cr.set_source_rgb(*s.FG)
        s.label(cr, title, 44, top + 12, 26, max_width=490)
        cr.set_source_rgb(*s.MUTED)
        s.label(cr, note, 44, top + 55, 21, max_width=490)
        value = draft.values[key]
        if key in BOOLEANS:
            s.button(cr, 900, top + 12, 292, 64, "开启" if value else "关闭", value)
            continue
        s.button(cr, 552, top + 20, 60, 60, "−")
        s.button(cr, 1000, top + 20, 60, 60, "+")
        ratio = max(0., min(1., (value - spec.low) / (spec.high - spec.low)))
        s.line(cr, 644, top + 50, 968, top + 50, s.BORDER, 8)
        s.line(cr, 644, top + 50, 644 + 324 * ratio, top + 50, s.ACCENT, 8)
        s.rounded(cr, 634 + 324 * ratio, top + 35, 20, 30, 9, s.FG)
        cr.set_source_rgb(*s.ACCENT)
        s.label(cr, spec.display(value), 1134, top + 49, 25, centered=True, max_width=126)
    if draft.section == "position":
        cr.set_source_rgb(*s.MUTED)
        for text, y in (("默认 2.00×；调高后，下屏小幅滑动可让上屏圆环移动更远。", 460),
                        ("第一指滑动定位，第二指按住触摸；抬起第二指释放。", 515),
                        ("仅改变相对移动倍率，不改变触点判定、驱动或游戏设置。", 570)):
            s.label(cr, text, 44, y, 25, max_width=1140)
    cr.set_source_rgb(*(s.DANGER if draft.error else s.ACCENT if draft.dirty else s.MUTED))
    s.label(cr, draft.message, 28, 934, 24, max_width=1180)
    s.button(cr, 24, 996, 270, 64, "恢复本页默认")
    s.button(cr, 662, 996, 250, 64, "放弃修改")
    s.button(cr, 936, 996, 280, 64, "保存设置", True)
