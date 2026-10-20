"""Ordered composition state, independent of GTK, native libraries and pipes."""
from __future__ import annotations


class Composition:
    def __init__(self, engine, transport):
        self.engine, self.transport = engine, transport
        self.preedit = ""
        self.candidates = []
        self.target = None
        self.revision = 0

    def reset(self):
        self.preedit, self.candidates, self.target = "", [], None
        self.revision += 1

    def state(self, status="ready", **extra):
        return {"status": status, "preedit": self.preedit,
                "candidates": self.candidates, "revision": self.revision, **extra}

    def _refresh(self):
        self.candidates = self.engine.lookup(self.preedit)

    def _commit(self, text):
        self.transport.commit(text, self.target)

    def _choose(self, index):
        if not self.candidates:
            return
        text, remaining = self.engine.choose(index)
        self._commit(text)
        self.preedit = remaining
        self._refresh()
        if not remaining:
            self.target = None

    def handle(self, request):
        kind = request.get("kind")
        if kind == "reset":
            self.reset()
            return self.state()
        if kind not in ("key", "choose"):
            raise ValueError("Unknown keyboard request")
        if self.target is not None and not self.transport.matches(self.target):
            self.reset()
            return self.state("focus_changed")
        if self.target is None:
            self.target = self.transport.focus()
        if kind == "choose":
            # A stale candidate tap must never select a newly generated word.
            if request.get("revision") != self.revision:
                return self.state("stale_candidate")
            index = request.get("index")
            if type(index) is not int or not 0 <= index < len(self.candidates):
                return self.state("stale_candidate")
            self._choose(index)
        else:
            code, text = request.get("code"), request.get("text", "")
            if type(code) is not int or not 0 <= code <= 767 or not isinstance(text, str) or len(text) > 1:
                raise ValueError("Invalid keyboard input")
            if code == 14:  # Backspace edits composition before the target.
                if self.preedit:
                    self.preedit = self.preedit[:-1]
                    self._refresh()
                else:
                    self.transport.action(2, self.target)
            elif code == 1 and self.preedit:
                self.reset()
            elif code == 28:
                if self.preedit:
                    self._commit(self.preedit)  # Enter confirms literal pinyin.
                    self.reset()
                else:
                    self.transport.action(1, self.target)
            elif code == 57:
                if self.candidates:
                    self._choose(0)
                elif self.preedit:
                    self._commit(self.preedit)
                    self.reset()
                else:
                    self._commit(" ")
            elif text in "123456" and text and self.preedit and self.candidates:
                page = request.get("page", 0)
                if type(page) is not int or page < 0:
                    page = 0
                index = page * 6 + int(text) - 1
                if index < len(self.candidates):
                    self._choose(index)
            elif text and ("a" <= text <= "z" or text == "'" and self.preedit):
                if len(self.preedit) < 64:
                    self.preedit += text
                    self._refresh()
            elif text and text.isprintable():
                target = self.target
                if self.preedit:
                    if self.candidates:
                        # Punctuation completes the whole best sentence.
                        self._choose(0)
                    else:
                        self._commit(self.preedit)
                    self.reset()
                    self.target = target
                punctuation = {",": "，", ".": "。", "?": "？", "!": "！", ":": "：", ";": "；"}
                self._commit(punctuation.get(text, text))
            elif code in (105, 106):
                target = self.target
                self.reset()
                self.target = target
                self.transport.action(4 if code == 105 else 5, self.target)
            else:
                # Raw Tab/Esc/vertical arrows retain the existing key route.
                # The main panel sends them only while this request is fresh.
                self.reset()
                return self.state(forward_key=code)
        if not self.preedit:
            self.target = None
        self.revision += 1
        return self.state()
