"use strict";

// Isolated renderer tests: fake Steam, fake monotonic clock, no browser or input.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(path.join(__dirname, "../src/armada_dual_screen_input/steam_keyboard_guard.js"), "utf8");
const invoke = new vm.Script(`(${source})(globalThis.__request)`);
const guardKey = "__thorPanelKeyboardGuardV1";

function makeWindow(kind = "main") {
  const calls = [];
  const manager = {};
  for (const name of ["ShowVirtualKeyboard", "SetVirtualKeyboardVisible",
    "SetVirtualKeyboardShownInternal", "SetVirtualKeyboardHidden"]) {
    manager[name] = function (...args) {
      calls.push({name, receiver: this, args});
      return {name, args};
    };
  }
  manager.IsShowingVirtualKeyboard = {Value: false};
  const win = {
    VirtualKeyboardManager: manager,
    LocationPathName: "/library",
    IsMainGamepadUIWindow() { return kind === "main"; },
    IsGamepadUIOverlayWindow() { return kind === "overlay"; },
    NavigateWithoutChangingFocus(...args) {
      calls.push({name: "NavigateWithoutChangingFocus", receiver: this, args});
      return {route: args[0], args};
    },
    NavigateBack(...args) {
      calls.push({name: "NavigateBack", receiver: this, args});
      return "back";
    },
  };
  return {win, manager, calls};
}

function harness(first = makeWindow()) {
  let now = 0;
  let timerID = 0;
  const timers = new Map();
  const microtasks = [];
  const nativeCalls = [];
  const settings = Object.freeze({keyboardEnabled: true, language: "zh-CN"});
  const store = {
    WindowStore: {SteamUIWindows: [first.win]},
    ActiveWindowInstance: first.win,
    settings,
  };
  const context = vm.createContext({
    SteamUIStore: store,
    SteamClient: {
      Input: {
        SetGamepadKeyboardText(...args) { nativeCalls.push({name: "game", args}); },
        ModalKeyboardDismissed(...args) { nativeCalls.push({name: "floating", args}); },
      },
      Settings: new Proxy({}, {get() { throw new Error("Steam preferences must not be accessed"); }}),
    },
    performance: {now: () => now},
    setInterval(callback, period) {
      const id = ++timerID;
      timers.set(id, {callback, period, due: now + period});
      return id;
    },
    clearInterval(id) { timers.delete(id); },
    queueMicrotask(callback) { microtasks.push(callback); },
  });
  function command(action = "renew", owner = "owner-a", ttlMs = 4000) {
    context.__request = {action, owner, ttlMs};
    return invoke.runInContext(context, {timeout: 1000});
  }
  function advance(ms) {
    const end = now + ms;
    while (true) {
      const due = [...timers].filter(([, item]) => item.due <= end)
        .sort((a, b) => a[1].due - b[1].due)[0];
      if (!due) break;
      now = due[1].due;
      due[1].due += due[1].period;
      due[1].callback();
    }
    now = end;
  }
  function flushMicrotasks() {
    while (microtasks.length) microtasks.shift()();
  }
  return {...first, context, store, settings, nativeCalls, timers,
    command, advance, flushMicrotasks,
    jump(ms) { now += ms; },
  };
}

test("show, visible and shown(true) are blocked while hide and shown(false) retain calls", () => {
  const h = harness();
  assert.equal(h.command().active, true);
  const marker = {opaque: true};
  assert.equal(h.manager.ShowVirtualKeyboard("text", marker), undefined);
  assert.equal(h.manager.SetVirtualKeyboardVisible(marker), undefined);
  assert.equal(h.manager.SetVirtualKeyboardShownInternal(true, marker), undefined);
  assert.equal(h.calls.length, 0);
  assert.equal(h.nativeCalls.length, 0, "native cancellation must be deferred");
  h.flushMicrotasks();
  assert.deepEqual(h.nativeCalls, [{name: "floating", args: []}]);
  const hidden = h.manager.SetVirtualKeyboardHidden(marker);
  const shownFalse = h.manager.SetVirtualKeyboardShownInternal(false, marker);
  assert.equal(hidden.name, "SetVirtualKeyboardHidden");
  assert.equal(shownFalse.name, "SetVirtualKeyboardShownInternal");
  assert.equal(h.calls[0].receiver, h.manager);
  assert.deepEqual(h.calls[1].args, [false, marker]);
  assert.equal(h.command("status").blocked, 3);
});

test("exact keyboard and gameapiosk routes cancel asynchronously without navigating", () => {
  const h = harness();
  h.command();
  h.win.NavigateWithoutChangingFocus("/keyboard", {origin: "floating"});
  h.win.NavigateWithoutChangingFocus("/gameapiosk", "unused");
  assert.equal(h.calls.length, 0);
  assert.deepEqual(h.nativeCalls, []);
  h.flushMicrotasks();
  assert.deepEqual(h.nativeCalls, [
    {name: "floating", args: []},
    {name: "game", args: [false, ""]},
  ]);
});

test("other routes preserve receiver, argument identity and return value", () => {
  const h = harness();
  h.command();
  const receiver = {custom: true};
  const marker = {opaque: true};
  for (const route of ["/library", "/keyboard/help", "/keyboard?layout=full", "/gameapiosk-extra"]) {
    const result = h.win.NavigateWithoutChangingFocus.call(receiver, route, marker, 42);
    assert.equal(result.route, route);
    assert.equal(result.args[1], marker);
    const last = h.calls.at(-1);
    assert.equal(last.receiver, receiver);
    assert.deepEqual(last.args, [route, marker, 42]);
  }
  assert.equal(h.nativeCalls.length, 0);
});

test("release restores own descriptors, inherited methods and configuration exactly", () => {
  const first = makeWindow();
  const inherited = first.manager.ShowVirtualKeyboard;
  delete first.manager.ShowVirtualKeyboard;
  Object.setPrototypeOf(first.manager, {ShowVirtualKeyboard: inherited});
  Object.defineProperty(first.manager, "SetVirtualKeyboardVisible", {
    value: first.manager.SetVirtualKeyboardVisible, enumerable: false,
    writable: false, configurable: true,
  });
  const descriptor = Object.getOwnPropertyDescriptor(first.manager, "SetVirtualKeyboardVisible");
  const shown = first.manager.SetVirtualKeyboardShownInternal;
  const navigate = first.win.NavigateWithoutChangingFocus;
  const h = harness(first);
  const settingsBefore = JSON.stringify(h.settings);
  h.command();
  assert.equal(Object.hasOwn(h.manager, "ShowVirtualKeyboard"), true);
  h.command("release");
  assert.equal(Object.hasOwn(h.manager, "ShowVirtualKeyboard"), false);
  assert.equal(h.manager.ShowVirtualKeyboard, inherited);
  assert.deepEqual(Object.getOwnPropertyDescriptor(h.manager, "SetVirtualKeyboardVisible"), descriptor);
  assert.equal(h.manager.SetVirtualKeyboardShownInternal, shown);
  assert.equal(h.win.NavigateWithoutChangingFocus, navigate);
  assert.equal(JSON.stringify(h.settings), settingsBefore);
  assert.equal(h.context[guardKey], undefined);
  assert.equal(h.timers.size, 0);
  assert.equal(h.manager.ShowVirtualKeyboard("after").name, "ShowVirtualKeyboard");
});

test("renderer expiry restores behavior when heartbeat or owning process disappears", () => {
  const h = harness();
  const original = h.manager.ShowVirtualKeyboard;
  h.command();
  h.advance(3999);
  h.manager.ShowVirtualKeyboard();
  assert.equal(h.calls.length, 0);
  h.advance(1);
  assert.equal(h.manager.ShowVirtualKeyboard, original);
  assert.equal(h.command("status").active, false);
  assert.equal(h.timers.size, 0);
});

test("expired wrappers fail open even before the timer callback is delivered", () => {
  const h = harness();
  h.command();
  h.jump(4100);
  const result = h.manager.ShowVirtualKeyboard("late");
  assert.equal(result.name, "ShowVirtualKeyboard");
  assert.equal(h.calls.length, 1);
  assert.equal(h.command("status").active, false);
});

test("renewal extends the lease and does not stack wrappers", () => {
  const h = harness();
  h.command();
  const wrapper = h.manager.ShowVirtualKeyboard;
  h.advance(3000);
  assert.equal(h.command().windows, 1);
  assert.equal(h.manager.ShowVirtualKeyboard, wrapper);
  h.advance(1500);
  assert.equal(h.command("status").active, true);
  h.advance(2500);
  assert.equal(h.command("status").active, false);
});

test("new owner takes over and an old owner cannot release the new lease", () => {
  const h = harness();
  const original = h.manager.ShowVirtualKeyboard;
  h.command("renew", "old");
  h.command("renew", "new");
  h.command("release", "old");
  assert.equal(h.command("status").owner, "new");
  assert.equal(h.command("status").active, true);
  h.manager.ShowVirtualKeyboard();
  assert.equal(h.calls.length, 0);
  h.command("release", "new");
  assert.equal(h.manager.ShowVirtualKeyboard, original);
});

test("third-party wrapper installed later survives release and calls through transparently", () => {
  const h = harness();
  h.command();
  const guardWrapper = h.manager.ShowVirtualKeyboard;
  let thirdPartyCalls = 0;
  const thirdParty = function (...args) {
    thirdPartyCalls++;
    return guardWrapper.apply(this, args);
  };
  h.manager.ShowVirtualKeyboard = thirdParty;
  h.manager.ShowVirtualKeyboard("blocked");
  assert.equal(h.calls.length, 0);
  h.advance(4000);
  assert.equal(h.manager.ShowVirtualKeyboard, thirdParty);
  const receiver = {custom: true};
  const result = h.manager.ShowVirtualKeyboard.call(receiver, "allowed");
  assert.equal(thirdPartyCalls, 2);
  assert.equal(result.name, "ShowVirtualKeyboard");
  assert.equal(h.calls[0].receiver, receiver);
  assert.deepEqual(h.calls[0].args, ["allowed"]);
});

test("new Game Mode windows are guarded once and desktop windows are left alone", () => {
  const h = harness();
  h.command();
  const overlay = makeWindow("overlay");
  const desktop = makeWindow("desktop");
  h.store.WindowStore.SteamUIWindows.push(overlay.win, desktop.win, overlay.win);
  h.advance(250);
  overlay.manager.ShowVirtualKeyboard();
  desktop.manager.ShowVirtualKeyboard();
  assert.equal(overlay.calls.length, 0);
  assert.equal(desktop.calls.length, 1);
  assert.equal(h.command("status").windows, 2);
  h.command("release");
  overlay.manager.ShowVirtualKeyboard();
  assert.equal(overlay.calls.length, 1);
});

test("an already-open exact keyboard route is cleaned up only on first adoption", () => {
  const first = makeWindow();
  first.win.LocationPathName = "/keyboard";
  first.manager.IsShowingVirtualKeyboard.Value = true;
  const h = harness(first);
  h.command();
  assert.deepEqual(h.calls.map(row => row.name), ["SetVirtualKeyboardHidden"]);
  h.flushMicrotasks();
  assert.deepEqual(h.calls.map(row => row.name), ["SetVirtualKeyboardHidden", "NavigateBack"]);
  h.advance(1000);
  h.command();
  assert.equal(h.calls.length, 2);
});

test("deferred cleanup does not navigate back after the keyboard route already disappeared", () => {
  const first = makeWindow();
  first.win.LocationPathName = "/gameapiosk";
  const h = harness(first);
  h.command();
  first.win.LocationPathName = "/library";
  h.flushMicrotasks();
  assert.equal(h.calls.length, 0);
});

test("a partially incompatible window fails open and restores methods already patched", () => {
  const first = makeWindow();
  const original = first.manager.ShowVirtualKeyboard;
  Object.defineProperty(first.manager, "SetVirtualKeyboardVisible", {
    value: first.manager.SetVirtualKeyboardVisible, configurable: false, writable: false,
  });
  const h = harness(first);
  const result = h.command();
  assert.equal(result.active, false);
  assert.equal(result.reason, "Incompatible Steam UI");
  assert.equal(h.manager.ShowVirtualKeyboard, original);
  assert.equal(h.context[guardKey], undefined);
  assert.equal(h.timers.size, 0);
});

test("missing Steam UI returns unavailable without creating a guard or timer", () => {
  const h = harness();
  h.store.ActiveWindowInstance = null;
  assert.equal(h.command().active, false);
  assert.equal(h.context[guardKey], undefined);
  assert.equal(h.timers.size, 0);
});

test("requested TTL is bounded between one and six seconds", () => {
  const h = harness();
  h.command("renew", "short", 1);
  h.advance(1000);
  assert.equal(h.command("status").active, false);
  h.command("renew", "long", 600000);
  h.advance(5999);
  assert.equal(h.command("status").active, true);
  h.advance(1);
  assert.equal(h.command("status").active, false);
});
