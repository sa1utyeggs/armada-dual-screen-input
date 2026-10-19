/* Temporary Steam UI keyboard guard. No Steam files or preferences are changed.
 * Input: {action, owner, ttlMs}. The renderer owns the expiry timer so a killed
 * panel, stopped UI heartbeat, or broken connection cannot leave a live block.
 */
(function (request) {
  "use strict";
  const key = "__thorPanelKeyboardGuardV1";
  const root = globalThis;
  let state = root[key];
  if (request.action === "release") {
    if (state && state.owner === request.owner) state.restore();
    return {active: false};
  }
  if (request.action === "status") {
    return state ? state.status() : {active: false};
  }
  if (request.action !== "renew") throw new Error("Unknown guard action");
  if (state && state.owner !== request.owner) state.restore();
  state = root[key];
  if (!state) {
    const store = root.SteamUIStore;
    if (!store?.WindowStore || !store?.ActiveWindowInstance?.VirtualKeyboardManager)
      return {active: false, reason: "Steam keyboard manager unavailable"};
    state = {
      owner: request.owner, active: true, expires: 0, timer: null,
      entries: [], seen: new WeakSet(), blocked: 0, errors: 0,
      live() { return this.active && performance.now() < this.expires; },
      status() {
        return {active: this.live(), owner: this.owner, windows: this.entries.length / 4,
          blocked: this.blocked, errors: this.errors};
      },
      restore() {
        this.active = false;
        clearInterval(this.timer);
        for (const entry of this.entries.reverse()) {
          // Leave later third-party patches intact. Any nested copy of our
          // wrapper becomes transparent because active is now false.
          if (entry.object[entry.name] === entry.wrapper) {
            if (entry.descriptor) Object.defineProperty(entry.object, entry.name, entry.descriptor);
            else delete entry.object[entry.name];
          }
        }
        if (root[key] === this) delete root[key];
      },
      patch(object, name, handler) {
        const original = object[name];
        if (typeof original !== "function") throw new Error("Incompatible keyboard method");
        const descriptor = Object.getOwnPropertyDescriptor(object, name);
        const guard = this;
        const wrapper = function (...args) {
          if (!guard.live()) return original.apply(this, args);
          return handler.call(this, guard, original, args);
        };
        Object.defineProperty(object, name, {value: wrapper, configurable: true, writable: true});
        this.entries.push({object, name, original, descriptor, wrapper});
      },
      cancel(kind) {
        // Wait for the original native message handler's stack to finish.
        // These are Steam's own cancel paths; no text is read or submitted.
        queueMicrotask(() => {
          try {
            const input = root.SteamClient.Input;
            if (kind === "game") input.SetGamepadKeyboardText(false, "");
            else input.ModalKeyboardDismissed();
          } catch (_) { this.errors++; }
        });
      },
      scan() {
        const windows = new Set([
          store.ActiveWindowInstance, ...(store.WindowStore.SteamUIWindows || []),
        ]);
        for (const win of windows) {
          if (!win || this.seen.has(win) ||
              !(win.IsMainGamepadUIWindow?.() || win.IsGamepadUIOverlayWindow?.())) continue;
          const manager = win.VirtualKeyboardManager;
          if (!manager || typeof win.NavigateWithoutChangingFocus !== "function") continue;
          // Validate all methods before patching this window.
          const methods = ["ShowVirtualKeyboard", "SetVirtualKeyboardVisible", "SetVirtualKeyboardShownInternal"];
          if (!methods.every(name => typeof manager[name] === "function") ||
              typeof manager.SetVirtualKeyboardHidden !== "function") continue;
          this.seen.add(win);
          // Hide an already-open keyboard once using its normal cleanup.
          // Do not repeatedly dismiss keyboards or change non-keyboard routes.
          if (manager.IsShowingVirtualKeyboard?.Value) manager.SetVirtualKeyboardHidden();
          const oldRoute = win.LocationPathName;
          if (["/keyboard", "/gameapiosk"].includes(oldRoute)) queueMicrotask(() => {
            // Hidden can already have run the normal keyboard route cleanup.
            // Recheck before backing out, rather than popping another page.
            if (win.LocationPathName === oldRoute && typeof win.NavigateBack === "function")
              win.NavigateBack();
          });
          this.patch(manager, "ShowVirtualKeyboard", function (guard) { guard.blocked++; });
          this.patch(manager, "SetVirtualKeyboardVisible", function (guard) {
            guard.blocked++;
            guard.cancel("floating");
          });
          this.patch(manager, "SetVirtualKeyboardShownInternal", function (guard, original, args) {
            if (args[0]) { guard.blocked++; return; }
            return original.apply(this, args);
          });
          this.patch(win, "NavigateWithoutChangingFocus", function (guard, original, args) {
            if (args[0] === "/keyboard" || args[0] === "/gameapiosk") {
              guard.blocked++;
              guard.cancel(args[0] === "/gameapiosk" ? "game" : "floating");
              return;
            }
            return original.apply(this, args);
          });
        }
      },
    };
    root[key] = state;
    state.timer = setInterval(() => {
      if (!state.live()) state.restore();
      else {
        try { state.scan(); }
        catch (_) { state.errors++; state.restore(); }
      }
    }, 250);
  }
  state.expires = performance.now() + Math.min(6000, Math.max(1000, request.ttlMs || 4000));
  try { state.scan(); }
  catch (_) { state.errors++; state.restore(); return {active: false, reason: "Incompatible Steam UI"}; }
  return state.status();
})
