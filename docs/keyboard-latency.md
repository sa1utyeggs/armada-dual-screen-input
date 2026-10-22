English · [简体中文](zh-CN/keyboard-latency.md)

<a id="键盘连续输入延迟检查--2026-10-21"></a>

# Continuous keyboard input latency · 2026-10-21

The user reported unresponsive rapid taps, holds and Chinese input. This round used a dedicated upper-screen GTK field on AYN Thor / Armada Game Mode, without automated input to a game or Steam search.

<a id="已确认及修复"></a>

## Confirmed cause and first fix

The old drawing path rebuilt Pango layouts for about 92 labels each frame. Offscreen profiling and real GLib timing showed key handling usually below 1ms, while synchronous repainting occupied the input event loop.

The first fix cached only text layouts/measurements, not the whole keyboard image. It changed neither pulses, repeat speed/delay, keys, languages nor touch preferences. The per-thread cache holds at most 256 entries and invalidates on font-map, scale or font-render-option changes. Color/position remain draw-time decisions. Public measurement layouts remain separate. Pixel comparisons covered English/Chinese, long candidates, scale, translation, device scale and font hinting.

<a id="实测结果与限制"></a>

## Measurements and limits

Baseline `340a4ff`; the candidate changed only text-layout reuse. Real GLib checks and the receiving window used identical fixed input. These short samples are not a system-wide performance promise.

| Check | Baseline | Candidate |
| --- | --- | --- |
| Median routine repaint during tapping | About 13.6–13.8ms | About 9.6–10.7ms |
| Scheduling p95 at 10 taps/second, one receiving-window run | 12.2ms | 9.2ms |
| Scheduling p95 at 15 taps/second, one receiving-window run | 5.1ms | 0.6ms |
| Final key integrity | No loss/reordering in baseline samples | All 496 keys received in order; none held at end |
| Median hold-repeat interval with 20ms setting | About 21.3ms | Letters 21.2ms, Backspace 21.1ms |
| Chinese content | 18 correct fixed-phrase rounds | 24 correct rounds, including candidate taps and queued Space commit |

Final Chinese-worker median response was about 2.8–3.1ms. Candidate/Space commit to GTK text change had a median about 33–40ms, with some samples around 64ms. This channel did not show consistent before/after improvement.

**Occasional long frames remain unresolved.** First/intermittent repaints still measured about 30–45ms; earlier cold-start samples approached 85–92ms. One candidate run captured about 38ms native reception delay. Reduced routine main-thread work does not prove every reported stall is gone. Physical touch, lower-screen presentation, real apps and long use still need acceptance.

<a id="自动化范围"></a>

## Automation scope

- `tools/keyboard_latency_bench.py`: real GLib clock, real PanelApp touch routing, 5/10/15 taps per second and two-second letter/Backspace holds. Fake devices by default; explicit options create its own window/virtual keyboard. Records scheduling, handling, draw, receive and repeat intervals rather than deriving performance from a fake clock.
- `tools/keyboard_ime_latency_bench.py`: real isolated worker, system libpinyin and Gamescope text channel, fixed phrases and a dedicated field, with separate offscreen keys/candidates. Records startup, response and commit-to-text latency, not physical touch/scanout.
- Interactive tools require an idle Steam home screen and focus in their own window. They stop on focus loss without reclaiming it. Run the two tools sequentially; each closes its windows/devices/worker afterward.
- `passed` checks content, ordering, cleanup and timeouts. Frequency, load and cold starts affect performance; a single maximum is not an absolute pass threshold. Retain baseline/candidate JSON for comparison.

<a id="回归检查"></a>

## Regression checks

Mac: 371 Python checks with 70 Linux checks skipped; 15 JavaScript checks passed. Thor: all 371 Python checks passed, including 4 new real Pango/Cairo pixel/cache checks. Node was absent, so JavaScript was not repeated there.

After the first layout cache, the user reported slight improvement with occasional stutters. This round was not recorded as a complete fix.

<a id="第二轮真实下屏窗口和局部刷新"></a>

## Round two: real lower window and partial repainting

Ordinary key down/up and every Chinese-candidate update still repainted the whole panel. Round two limited ordinary changes to old/new keycaps and candidate changes to the overlay. Cairo skips keycaps outside the clip. Shift/Caps/modifier changes and language/mode switches retain full redraws. Sliding off a key also clears highlights without changing key send/release behavior.

Partial draws reuse the most recent full frame's OLED orbital offset; full draws advance the original orbit, avoiding seams against retained pixels. New pixel tests cover press/change/release, Shift, scaling, subpixel offsets, candidate appearance/update/removal and touchpad restoration.

`keyboard_window_latency_bench.py` compares full/partial drawing in its own real lower-screen Wayland window with identical state sequences. It creates no input device or upper input. Two 24-second samples per round gave:

| Check | Full redraw | Partial redraw |
| --- | --- | --- |
| English median frame draw | 7.46–10.97ms | Partial frames 1.69–1.75ms |
| English event-loop delay p95 | 8.71–10.40ms | 1.58–1.70ms |
| Chinese-candidate median frame draw | 12.21–12.28ms | Partial frames 2.46–2.50ms |
| Chinese-candidate event-loop delay p95 | 11.96–12.31ms | 2.70–4.69ms |

Per-second status/full redraws remained, with occasional full draws around 35ms and loop delay around 43ms. Routine drawing blocked much less, but intermittent stalls were not eliminated. Physical-touch feel still required acceptance.

Round two: Mac 379 Python checks, 74 Linux skips, 15 JavaScript passes; Thor all 379 Python passes. A new short native test received all 374 keys in order with correct content/Backspace and no held key at end. Partial repainting did not change the key channel.

The user reported a clearly smoother experience, then noted continued tapping could still stutter. This is experiential improvement, not complete resolution.

<a id="第三轮输入期间避开周期完整刷新"></a>

## Round three: avoid periodic full redraws while typing

Round two still redrew the full status/orbit each second, bringing non-key/candidate drawing into the input loop. If keyboard activity occurred within 250ms or a key remained held, round three redrew only the top status row. The next periodic update after typing pauses restores full repaint/orbit. Sampling rate, repeat/delay, language, pointer and touch preferences remain unchanged.

One matched real-window short test reduced full English-phase draws from 7 to 2 and maximum loop delay from 40.84ms to 16.38ms. Chinese-candidate maximum delay fell from 40.11ms to 21.78ms. Full phase-entry draws and other variation remain. One reduced maximum does not establish resolution of all physical latency. The next user test needed to distinguish delayed keycap feedback from delayed upper-screen text.

Round three: Mac 382 Python checks, 77 Linux skips, 15 JavaScript passes; Thor all 382 Python passes. New checks cover status-value partial pixels, draw bounds during tapping/holds and restoration of full drawing after a pause.

<a id="第四轮用户澄清为高亮反馈偶发缺失"></a>

## Round four: the user identifies missing visual highlights

The user clarified that some lower keycaps failed to highlight during rapid taps, while upper text was not late. The remaining focus became visual feedback, not lost keys or text-submission delay.

Old color selection used logical `active_key_press`. A short down/up completed before drawing left only the up state. New independent visual state still sends/release real keys immediately on the existing schedule, but first draws the highlight and retains it for about 60ms afterward. Adjacent quick keys may each briefly highlight through partial redraws. A hold longer than that period clears normally on release. Page exit, cancellation, collapse and close clear visual state/timers.

In 70 simulated taps on a real dedicated lower window, the old logic selected pressed color 57 times; the candidate achieved 70/70:

| Simulated condition | Old highlight draws | Visual-feedback fix |
| --- | --- | --- |
| Down/up in one callback, simulating batched delivery | 0/10 | 10/10 |
| 2ms, 5ms, 8ms taps | Each 9/10 | Each 10/10 |
| 12ms, 20ms, 40ms taps | Each 10/10 | Each 10/10 |

This counts Cairo callbacks choosing pressed color, not confirmed physical presentation, and does not prove the touch driver was the sole cause. Timers send no key events. Real PanelApp integration confirmed a logical key released at 3ms still releases at 3ms; visual duration does not prolong the real press or repeat.

Mac: 388 Python checks, 78 Linux skips, 15 JavaScript passes. Thor: all 388 Python checks passed, covering batched short taps, delayed first draw, repeated same key, multiple highlights, stale callbacks, cancel cleanup and unchanged native timing.

On 2026-10-21 after installing `439fbb8`, the user confirmed every rapid tap now had visible feedback. Highlight feedback passed this round's device acceptance. Configuration bytes and disabled autostart were preserved; Steam and official lower-session processes were not restarted. This conclusion concerns that visual-feedback defect.

<a id="第五轮组件裁剪触屏静态层和遗漏的按键结束刷新"></a>

## Round five: component clipping, static touch layer and missed key-end redraw

On 2026-10-21, same-device CPU/GPU tests drove further draw optimization. Components first check actual GTK damage and skip unrelated header/status/pad/candidates. Disjoint keycap regions stay separate rather than using one rectangle covering untouched middle keys. If Cairo cannot provide rectangular clips, drawing conservatively falls back to the original bounds.

Direct touch invalidates only old/new ring boundaries. Static text/background reuse one bounded Cairo layer. Status text, scaling, device scale, font map and rendering-option changes rebuild it; unsupported transforms or cache limits fall back to vectors. An opaque background avoids repeated text-edge blending. GTK damage is rounded outward to widget pixels. The cache costs some memory and stores no upper-screen imagery.

The first real-window check found parent `_end_key_press()` still called full `queue_draw()`, bypassing keycap invalidation on each release/slide-off. The follow-up routes only that draw request through existing `_queue_keyboard_draw()`. The parent's default still repaints fully; key send/release/repeat/modifier semantics remain unchanged. Vendor notes were updated in `vendor/ratatoskr/UPSTREAM`.

Checks cover disjoint damage, unchanged/moved/removed rings, static-cache reuse and invalidation by text/scale/fonts, full/partial pixel equality at normal/double device scale, and real PanelApp release without a hidden whole-page redraw while the key is already released. Offscreen checks create no window/input device.

Device CPU/GPU comparisons replayed synthetic input only into a dedicated upper window while Steam home was idle and personal settings were copied. The separate input driver and sampler were excluded from app CPU. Each scene warmed for at least 4 seconds, then sampled for 10 seconds, for two rounds with reversed second-round order. Baseline was installed v0.1.2. The first candidate covered mouse, keyboard and multi-touch. Only keyboard scenes were repeated after fixing key-end redraw; non-keyboard code was identical. Temporary windows/devices were closed and the real installation, configuration and autostart remained unchanged.

Focus/route checks, physical driver, sensitivity, scrolling, repeat settings, Steam, official lower session and CPU/GPU policy were unchanged. CPU 100% means one logical core. GPU covers the sampled display/composition scene, normalized to a 680 MHz full-frequency equivalent. These short tests measure neither physical end-to-end latency, game FPS nor battery-life gains.

Same-device newly sampled results follow, before / after. Drawing means the lower Cairo callback, not end-to-end input latency:

| Scene | Mean app CPU, one-core % | Draw p95, ms | Display-scene GPU full-frequency equivalent, % |
| --- | --- | --- | --- |
| Single-finger mouse, control | 3.66 / 3.83 | 11.55 / 12.92 | 19.90 / 19.88 |
| Continuous English tapping | 31.01 / 28.31 | 12.78 / 2.01 | 2.87 / 2.79 |
| Chinese pinyin | 42.61 / 28.55 | 13.55 / 1.98 | 3.69 / 3.60 |
| Direct touch: two fingers | 58.02 / 58.15 | 3.62 / 0.66 | 5.62 / 5.23 |
| Direct touch: five fingers | 67.57 / 61.88 | 3.73 / 1.14 | 5.90 / 5.47 |

Chinese mean CPU fell about 33%; English about 9%, with variation between rounds. Both keyboard draw p95 values fell to about 2ms. Direct-touch drawing shortened substantially, but two-finger total app CPU did not materially fall. Five-finger mean CPU fell about 8%; both multi-finger GPU equivalents fell about 7%. Mouse control stayed near baseline, so its high composition GPU load was not resolved.

Touch-process-tree PSS rose from about 113–114 MiB to 125 MiB, including layer/related rendering resources. Cache capacity is one layer, at most 8 million pixels. The total measured memory difference is not the single-layer size. Long-term memory/battery tests were not performed.

Final Mac checks: 436 Python, 86 Linux skips; 15 JavaScript passed. Thor: all 436 Python passed; Node was absent, so JavaScript was not repeated. Synthetic input, real receiving window and offscreen pixels passed. Physical-touch acceptance of this optimized revision remained pending. The real install stayed v0.1.2; files and autostart were not replaced.
