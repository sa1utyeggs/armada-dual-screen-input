"""Optional system libpinyin adapter, loaded only in the isolated IME worker.

No dictionaries/libraries are bundled. libpinyin is GPL-3.0-or-later; see
THIRD_PARTY.md. The main panel exchanges plain data with the worker over pipes.
No personal vocabulary is trained or saved in this initial implementation.
"""
from __future__ import annotations

import ctypes as c
import ctypes.util
from pathlib import Path
import tempfile


class PinyinUnavailable(RuntimeError):
    pass


class PinyinEngine:
    def __init__(self, *, data_dir=None):
        library = ctypes.util.find_library("pinyin")
        if not library:
            raise PinyinUnavailable("System libpinyin is unavailable")
        choices = ([Path(data_dir)] if data_dir else
                   [Path(prefix) / "libpinyin/data" for prefix in
                    ("/usr/lib64", "/usr/lib", "/usr/share", "/usr/lib/aarch64-linux-gnu",
                     "/usr/lib/x86_64-linux-gnu")])
        directory = next((p for p in choices if (p / "table.conf").is_file()), None)
        if directory is None:
            raise PinyinUnavailable("System libpinyin dictionary is unavailable")
        self.lib = c.CDLL(library)
        self.context = self.instance = None
        self.scratch = tempfile.TemporaryDirectory(prefix="ads-pinyin-")
        self.text = ""
        self.candidates = []
        signatures = {
            "pinyin_init": ([c.c_char_p, c.c_char_p], c.c_void_p),
            "pinyin_fini": ([c.c_void_p], None),
            "pinyin_alloc_instance": ([c.c_void_p], c.c_void_p),
            "pinyin_free_instance": ([c.c_void_p], None),
            "pinyin_set_options": ([c.c_void_p, c.c_uint], c.c_bool),
            "pinyin_reset": ([c.c_void_p], c.c_bool),
            "pinyin_parse_more_full_pinyins": ([c.c_void_p, c.c_char_p], c.c_size_t),
            "pinyin_guess_sentence": ([c.c_void_p], c.c_bool),
            "pinyin_guess_candidates": ([c.c_void_p, c.c_size_t, c.c_uint], c.c_bool),
            "pinyin_get_n_candidate": ([c.c_void_p, c.POINTER(c.c_uint)], c.c_bool),
            "pinyin_get_candidate": ([c.c_void_p, c.c_uint, c.POINTER(c.c_void_p)], c.c_bool),
            "pinyin_get_candidate_string": ([c.c_void_p, c.c_void_p, c.POINTER(c.c_char_p)], c.c_bool),
            "pinyin_choose_candidate": ([c.c_void_p, c.c_size_t, c.c_void_p], c.c_int),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.lib, name)
            function.argtypes, function.restype = args, result
        try:
            self.context = self.lib.pinyin_init(bytes(directory), self.scratch.name.encode())
            if not self.context:
                raise PinyinUnavailable("Could not open the system pinyin dictionary")
            # Enable incomplete syllables, e.g. "n". No fuzzy matching/cloud.
            self.lib.pinyin_set_options(self.context, 1 << 3)
            self.instance = self.lib.pinyin_alloc_instance(self.context)
            if not self.instance:
                raise PinyinUnavailable("Could not allocate the pinyin engine")
        except Exception:
            self.close()
            raise

    def lookup(self, text):
        if not isinstance(text, str) or len(text) > 64 or any(ch not in "abcdefghijklmnopqrstuvwxyz'" for ch in text):
            raise ValueError("Only bounded full-pinyin input is accepted")
        self.text, self.candidates = text, []
        self.lib.pinyin_reset(self.instance)
        if not text:
            return []
        parsed = self.lib.pinyin_parse_more_full_pinyins(self.instance, text.encode("ascii"))
        # Never silently discard an invalid/unparsed suffix on commit.
        if parsed != len(text) or not self.lib.pinyin_guess_sentence(self.instance):
            return []
        if not self.lib.pinyin_guess_candidates(self.instance, 0, 22):
            return []
        count = c.c_uint()
        self.lib.pinyin_get_n_candidate(self.instance, c.byref(count))
        for index in range(min(count.value, 60)):
            candidate, value = c.c_void_p(), c.c_char_p()
            if (self.lib.pinyin_get_candidate(self.instance, index, c.byref(candidate))
                    and self.lib.pinyin_get_candidate_string(self.instance, candidate, c.byref(value))
                    and value.value):
                self.candidates.append((index, value.value.decode("utf-8")))
        return [text for _, text in self.candidates]

    def choose(self, index):
        if type(index) is not int or not 0 <= index < len(self.candidates):
            raise ValueError("Candidate is no longer available")
        original, text = self.candidates[index]
        candidate = c.c_void_p()
        if not self.lib.pinyin_get_candidate(self.instance, original, c.byref(candidate)):
            raise PinyinUnavailable("Candidate is no longer available")
        consumed = self.lib.pinyin_choose_candidate(self.instance, 0, candidate)
        if not 0 < consumed <= len(self.text):
            raise PinyinUnavailable("Invalid pinyin consumption offset")
        return text, self.text[consumed:].lstrip("'")

    def close(self):
        if self.instance:
            self.lib.pinyin_free_instance(self.instance)
            self.instance = None
        if self.context:
            self.lib.pinyin_fini(self.context)
            self.context = None
        if getattr(self, "scratch", None):
            self.scratch.cleanup()
            self.scratch = None
