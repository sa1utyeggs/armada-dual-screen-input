"""Language switch, composition and candidates within the keyboard's own area."""
HEIGHT = 112


def hit(x, y, top):
    y -= top
    if not 0 <= y < HEIGHT:
        return None, None
    if 6 <= y <= 48:
        if 16 <= x <= 240:
            return "language", None
        if 888 <= x <= 1032:
            return "cancel", None
        if 1048 <= x <= 1224:
            return "size", None
    if 56 <= y <= 104:
        for index in range(6):
            left = 16 + index * 164
            if left <= x <= left + 156:
                return "candidate", index
        if 1012 <= x <= 1108:
            return "page", -1
        if 1120 <= x <= 1224:
            return "page", 1
    return "bar", None


def draw(cr, state, top, *, expanded=False):
    from . import steam_style as s
    s.rounded(cr, 0, top, 1240, HEIGHT, 0, s.BG)
    s.button(cr, 16, top + 6, 224, 42, state.label,
             state.language == "zh_CN", tab=True)
    cr.set_source_rgb(*s.FG)
    s.label(cr, state.preedit or ("点击左侧切换英文／中文" if state.language == "en_US"
                                else "简体中文全拼 · 离线系统词库"),
            258, top + 18, 25, max_width=610)
    if state.preedit:
        s.button(cr, 888, top + 6, 144, 42, "取消")
    s.button(cr, 1048, top + 6, 176, 42, "返回键鼠" if expanded else "放大键盘")
    if not state.candidates:
        cr.set_source_rgb(*s.MUTED)
        s.label(cr, state.message, 24, top + 72, 22, max_width=1192)
        return
    for index, candidate in enumerate(state.candidates[state.page * 6:state.page * 6 + 6]):
        s.button(cr, 16 + index * 164, top + 56, 156, 48,
                 str(index + 1) + " " + candidate, index == 0)
    s.button(cr, 1012, top + 56, 96, 48, "上页")
    s.button(cr, 1120, top + 56, 104, 48, "下页")
