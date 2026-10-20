"""Choose the Thor lower-panel monitor without guessing by size or position.

The caller supplies connector names in GdkDisplay.get_monitor(index) order:

    screen = display.get_default_screen()
    names = [screen.get_monitor_plug_name(i)
             for i in range(display.get_n_monitors())]
    index = choose_bottom_monitor(names, "desktop")

GTK 3's public, deprecated GdkScreen.get_monitor_plug_name() returns the actual
connector, unlike GdkMonitor.get_model(). Its implementation reads the same
GdkDisplay monitor index. The Wayland backend receives the name from wl_output
or xdg-output. Sources pinned to GTK 3.24.52; the host still needs validation:

https://github.com/GNOME/gtk/blob/3.24.52/gdk/gdkscreen.c#L815-L827
https://github.com/GNOME/gtk/blob/3.24.52/gdk/wayland/gdkscreen-wayland.c
https://docs.gtk.org/gdk3/method.Screen.get_monitor_plug_name.html

Game Mode's one-monitor exception is safe ONLY after the caller has selected
and verified Armada's dedicated `armada-plasma-bottom` Wayland socket. Never
apply that exception to an unverified/default display or Desktop Mode.

This module neither opens displays nor changes keyboard focus. Integration
must use GtkLayerShell.KeyboardMode.NONE and explicitly set the chosen monitor
before mapping the window; a None result means leave the window unmapped.
"""

MODE_DESKTOP = "desktop"
MODE_GAMEMODE = "gamemode"
BOTTOM_CONNECTOR = "DSI-1"


def choose_bottom_monitor(connector_names, mode):
    """Return a verified lower monitor index, or None when unavailable/ambiguous.

    `connector_names` is a list/tuple of strings or None in GDK monitor order.
    `mode` is exactly "desktop" or "gamemode". Names are matched exactly.
    A sole unknown/renamed connector is allowed only on the caller-verified
    dedicated Game Mode bottom compositor. There is no top/primary fallback.
    """
    if mode not in (MODE_DESKTOP, MODE_GAMEMODE):
        return None
    if not isinstance(connector_names, (list, tuple)) or not connector_names:
        return None
    if mode == MODE_GAMEMODE and len(connector_names) == 1:
        return 0
    matches = [index for index, name in enumerate(connector_names)
               if name == BOTTOM_CONNECTOR]
    return matches[0] if len(matches) == 1 else None
