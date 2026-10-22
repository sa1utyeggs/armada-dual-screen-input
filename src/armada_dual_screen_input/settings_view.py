"""Focus-free settings surface using the same logical hit rectangles as input."""
from . import steam_style as s
from .input_settings import BOOLEANS, CHOICES, NUMBERS, SETTINGS_PAGES, choice_caption

TITLES = {"mouse": "鼠标", "position": "触屏", "keyboard": "键盘", "updates": "更新"}
TOGGLES = {
    "tap_to_click": ("轻点点击", "单指轻点触控板，模拟鼠标左键"),
    "glide": ("惯性滑行", "手指松开后，鼠标继续短暂滑动"),
    "keyboard_repeat_enabled": ("长按重复输入", "按住字母、退格或方向键连续输入"),
}
CHOICE_LABELS = {
    'keyboard_language': ('键盘语言', '点击切换 · 中文拼音目前用于 Game Mode'),
    'marker_frame_rate': ('圆环帧率上限', '点击切换 · 静止时不持续刷新'),
}


def draw(cr, draft, updates=None, *, monitor_millihz=0):
    cr.set_source_rgb(*s.FG)
    s.label(cr, "设置", 28, 150, 34, bold=True)
    cr.set_source_rgb(*s.MUTED)
    s.label(cr, "仅更新本应用 · 保留个人配置与自启动选择" if draft.section == 'updates'
            else "仅影响虚拟键鼠 · 保存后生效 · 重启后保留", 28, 194, 22)
    for index, section in enumerate(SETTINGS_PAGES):
        s.button(cr, 24 + index * 204, 220, 192, 60,
                 TITLES[section], draft.section == section, tab=True)
    if draft.section == 'updates':
        draw_updates(cr, draft, updates)
        return
    for key, top in draft.rows():
        s.rounded(cr, 24, top, 1192, 88, 8, s.SURFACE)
        if key in CHOICES:
            title, note = CHOICE_LABELS[key]
            cr.set_source_rgb(*s.FG)
            s.label(cr, title, 44, top + 12, 26)
            cr.set_source_rgb(*s.MUTED)
            s.label(cr, note, 44, top + 55, 21, max_width=700)
            s.button(cr, 790, top + 12, 402, 64,
                     choice_caption(key, draft.values[key], monitor_millihz), True)
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
        for text, y in (("定位速度仅影响定位子模式；直接触屏按绝对位置映射。", 540),
                        ("第一指滑动定位，第二指按住触摸；抬起第二指释放。", 595),
                        ("圆环最高不超过上屏刷新率；实际帧率取决于系统负载。", 650),
                        ("帧率设置适用于两种触屏模式，不改变游戏限帧或输入频率。", 705)):
            s.label(cr, text, 44, y, 25, max_width=1140)
    cr.set_source_rgb(*(s.DANGER if draft.error else s.ACCENT if draft.dirty else s.MUTED))
    s.label(cr, draft.message, 28, 934, 24, max_width=1180)
    s.button(cr, 24, 996, 270, 64, "恢复本页默认")
    s.button(cr, 662, 996, 250, 64, "放弃修改")
    s.button(cr, 936, 996, 280, 64, "保存设置", True)


def draw_updates(cr, draft, updates):
    s.rounded(cr, 24, 310, 1192, 380, 8, s.SURFACE)
    cr.set_source_rgb(*s.FG)
    s.label(cr, '虚拟键鼠', 44, 342, 34, bold=True)
    cr.set_source_rgb(*s.MUTED)
    current = updates.current if updates else '未知'
    latest = updates.latest.tag if updates and updates.latest else '尚未检查'
    for text, y in ((f'当前版本：v{current}', 410), (f'最新正式版：{latest}', 465),
                    ('更新来源：GitHub 官方仓库 · ARM64 正式安装包', 520)):
        s.label(cr, text, 44, y, 26, max_width=1120)
    message = updates.message if updates else '更新功能暂不可用'
    cr.set_source_rgb(*(s.DANGER if updates and updates.phase == 'error' else s.ACCENT))
    s.label(cr, message, 44, 590, 25, max_width=1120)
    cr.set_source_rgb(*s.MUTED)
    if draft.dirty:
        note = '有未保存的输入设置；请先切回原页保存或放弃修改。'
    elif updates and not updates.managed:
        note = '源码运行支持检查；更新需要先通过安装器安装应用。'
    elif updates and updates.confirming:
        note = '确认后开始下载；安装时面板会短暂重新打开。'
    else:
        note = '手动检查，不自动下载；失败后可重试，旧版本保留供回退。'
    s.label(cr, note, 44, 708, 23, max_width=1140)
    can_check = bool(updates and not updates.busy)
    can_install = bool(updates and updates.available and not draft.dirty)
    s.button(cr, 44, 760, 520, 76, '检查更新' if can_check else '正在处理…', can_check)
    caption = ('确认更新并重启' if updates and updates.confirming else '更新至 ' + updates.latest.tag
               if updates and updates.latest and can_install else '更新')
    s.button(cr, 620, 760, 572, 76, caption, can_install)
    if updates and updates.confirming:
        s.button(cr, 620, 850, 572, 64, '取消')
