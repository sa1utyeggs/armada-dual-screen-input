"""Transient composition overlay; no permanent space is taken from the pad."""
HEIGHT = 88


def visible(state):
    return ((state.language == "zh_CN" and (bool(state.preedit) or not state.ready))
            or state.message.startswith("语言保存失败"))


def hit(x, y, top):
    y -= top
    if not 0 <= y < HEIGHT:
        return None, None
    if 4 <= y <= 38:
        if 1048 <= x <= 1224:
            return "cancel", None
    if 44 <= y <= 84:
        for index in range(6):
            left = 16 + index * 164
            if left <= x <= left + 156:
                return "candidate", index
        if 1012 <= x <= 1108:
            return "page", -1
        if 1120 <= x <= 1224:
            return "page", 1
    return "bar", None


def draw(cr, state, top):
    from . import steam_style as s
    s.rounded(cr, 0, top, 1240, HEIGHT, 0, s.BG)
    cr.set_source_rgb(*s.FG)
    s.label(cr, state.preedit or "中文全拼 · 离线系统词库",
            20, top + 10, 25, max_width=1000)
    if state.preedit:
        s.button(cr, 1048, top + 4, 176, 34, "取消")
    if not state.candidates:
        cr.set_source_rgb(*s.MUTED)
        s.label(cr, state.message, 24, top + 60, 22, max_width=1192)
        return
    for index, candidate in enumerate(state.candidates[state.page * 6:state.page * 6 + 6]):
        s.button(cr, 16 + index * 164, top + 44, 156, 40,
                 str(index + 1) + " " + candidate, index == 0)
    s.button(cr, 1012, top + 44, 96, 40, "上页")
    s.button(cr, 1120, top + 44, 104, 40, "下页")
