English · [简体中文](zh-CN/multilingual-keyboard.md)

<a id="多语言键盘原型"></a>

# Multilingual keyboard prototype

<a id="使用"></a>

## Usage

On Keys+Pad, tap **中/EN** at the former Win-key position to switch input language. Alternatively choose Settings → Keyboard → Input language and save. The `keyboard_language` field in the existing `~/.config/thor-panel/config.json` stores the choice; other preferences remain unchanged.

No permanent language strip reduces the idle touchpad or key sizes. Composition/backend messages temporarily show a candidate overlay, hidden after commit/cancel. The former Win touch key no longer sends Super. The original split layout remains; keyboard enlargement is not provided.

Simplified Chinese currently supports full pinyin:

- Type pinyin and view candidates below; tap, use 1–6, or Space to select.
- Previous/Next pages candidates. Unconsumed pinyin remains after selecting a prefix.
- Backspace deletes composition first, and upper-screen text only when composition is empty.
- Enter commits raw pinyin while composing; otherwise it sends Enter.
- Esc / Cancel clears unfinished input; common punctuation uses Chinese forms.
- Ctrl/Alt/Super shortcuts retain the original physical-key channel. Switch to English for complex shortcuts.

The Chinese backend starts only when selected and the keyboard is visible. Leaving the keyboard, collapsing, closing or switching to English stops it. Autostart remains disabled by default.

<a id="系统接口与兼容边界"></a>

## System interfaces and compatibility boundaries

1. `keyboard_xkb.py` creates private layout state through system libxkbcommon without changing physical/system layouts. The panel currently exposes English US and Chinese pinyin.
2. `pinyin_engine.py` uses system libpinyin/dictionaries in a separate worker. It loads no existing user dictionary and trains/saves no personal frequency data. Work files live in a temporary directory deleted on normal exit. Libraries/dictionaries are not redistributed by this project.
3. `keyboard_composition.py` serializes input, selection and commit. Candidates carry revisions so rapid typing cannot select stale candidates. An upper input-target change cancels composition.
4. `gamescope_text.py` is an isolated **private-protocol adapter**. It connects only to an upper Gamescope socket/process verified as the same user, binds the version-1 text subset and accepts only known manager versions 1–3. It sends no mouse events and takes over no Steam input service. This private interface is not an officially guaranteed stable API for ordinary Wayland apps.

This test device had no Fcitx5/IBus service, only system libpinyin, so no new global input-method service was installed/enabled. Future independent Fcitx5/IBus adapters could reuse the language/candidate UI on systems already running them.

Game Mode Chinese is the prototype target. Desktop Mode Chinese is not enabled; the panel explains the limit and allows English. Steam, Chrome, native-game and Proton fields need individual acceptance. A successful test window does not establish Unicode input in every game.

<a id="性能与输入生命周期"></a>

## Performance and input lifecycle

- GTK callbacks neither load dictionaries, wait for children nor start a command per key.
- A persistent worker starts on demand and blocks awaiting messages when idle; it captures no upper-screen imagery.
- Queues are bounded, commands expire and replies time out. Failures clear composition and report unavailability.
- Failed text submissions are not automatically replayed. Page switches close the old worker and invalidate late replies.
- Pinyin, candidates and committed text travel only in memory/anonymous pipes, never app logs.

<a id="验证记录"></a>

## Validation record

2026-10-20, AYN Thor / Armada 20261010:

- **Automated device checks:** system XKB Shift/Caps/symbols and private German, French and Russian keymap character generation passed. Those language panels are not exposed.
- **Automated device checks:** libpinyin `nihao → 你好`, `zhongwen → 中文`, `shijie → 世界`, incomplete syllables and partial selection passed.
- **Dedicated window:** `tools/keyboard_text_probe.py --run-own-window-test` sent synthetic text only to its own upper-screen GTK field. Unicode commit, separate worker, Space selection after fast typing, no raw-pinyin leak and cancellation on hide passed.
- **User acceptance:** candidates and English/Chinese input worked. Restored key sizes were suitable, but the touchpad became smaller. Win was changed to the language switch, the permanent strip removed, the full touchpad restored and candidates made transient; enlargement was removed. Retesting confirmed switching, input and sizing. Tests never automatically typed into a real game or Steam field.

Mac skips Linux GTK/system-library checks; skipped checks are not device passes.

<a id="回退"></a>

## Rollback

Switching to `English · US` stops the Chinese worker and continues the existing key channel. To remove the entire prototype, use the installer to roll back the app version. It changes neither official Armada/Steam/Gamescope services, drivers nor autostart preferences.
