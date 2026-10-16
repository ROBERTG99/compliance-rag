"""Incremental parser that yields each ``claims[i]`` object as soon as its JSON closes."""

from __future__ import annotations

import contextlib
import json
from typing import Any


class ClaimStreamParser:
    def __init__(self) -> None:
        self._buf = ""
        self._pos = 0
        self._array_start: int | None = None
        self._depth = 0
        self._in_string = False
        self._escape = False
        self._obj_start: int | None = None
        self._done = False

    def feed(self, chunk: str) -> list[dict[str, Any]]:
        self._buf += chunk
        out: list[dict[str, Any]] = []
        if self._done:
            return out
        if self._array_start is None:
            key = self._buf.find('"claims"')
            if key < 0:
                return out
            bracket = self._buf.find("[", key)
            if bracket < 0:
                return out
            self._array_start = bracket
            self._pos = bracket + 1
        while self._pos < len(self._buf):
            ch = self._buf[self._pos]
            if self._in_string:
                if self._escape:
                    self._escape = False
                elif ch == "\\":
                    self._escape = True
                elif ch == '"':
                    self._in_string = False
            elif ch == '"':
                self._in_string = True
            elif ch == "{":
                if self._depth == 0:
                    self._obj_start = self._pos
                self._depth += 1
            elif ch == "}":
                self._depth -= 1
                if self._depth == 0 and self._obj_start is not None:
                    with contextlib.suppress(json.JSONDecodeError):
                        out.append(json.loads(self._buf[self._obj_start : self._pos + 1]))
                    self._obj_start = None
            elif ch == "]" and self._depth == 0:
                self._done = True
                self._pos += 1
                break
            self._pos += 1
        return out
