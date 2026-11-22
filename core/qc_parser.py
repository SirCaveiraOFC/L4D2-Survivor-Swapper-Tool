from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class QcStatement:
    """Represents a single top-level directive or block in a Source Engine QC file."""

    directive: str
    raw_text: str

    @staticmethod
    def _first_unquoted_brace(text: str) -> int:
        in_quotes = False
        for idx, ch in enumerate(text):
            if ch == '"':
                in_quotes = not in_quotes
            elif not in_quotes and ch == "{":
                return idx
        return -1

    @property
    def has_block(self) -> bool:
        brace_idx = self._first_unquoted_brace(self.raw_text)
        return brace_idx != -1 and "}" in self.raw_text[brace_idx + 1 :]

    def quoted_args(self) -> list[str]:
        """Return quoted strings from the directive header (before any unquoted '{')."""
        brace_idx = self._first_unquoted_brace(self.raw_text)
        header = self.raw_text[:brace_idx] if brace_idx != -1 else self.raw_text
        return re.findall(r'"([^"]*)"', header)

    def first_quoted_arg(self) -> Optional[str]:
        args = self.quoted_args()
        return args[0] if args else None

    def body_text(self) -> str:
        start = self._first_unquoted_brace(self.raw_text)
        if start == -1:
            return ""
        end = self.raw_text.rfind("}")
        return self.raw_text[start + 1 : end] if end > start else ""


class QcDocument:
    """Structured representation of a parsed Source Engine QC file."""

    def __init__(self, statements: list[QcStatement]) -> None:
        self.statements = statements

    def find_all(self, directive: str) -> list[QcStatement]:
        target = directive.lower()
        if not target.startswith("$"):
            target = "$" + target
        return [st for st in self.statements if st.directive == target]

    def find_first(self, directive: str) -> Optional[QcStatement]:
        matches = self.find_all(directive)
        return matches[0] if matches else None

    def to_text(self) -> str:
        return "\n\n".join(st.raw_text.strip() for st in self.statements if st.raw_text.strip()) + "\n"


class QcParser:
    """Quote-aware, comment-aware, balanced-brace parser for Source Engine .qc files."""

    @classmethod
    def parse(cls, content: str) -> QcDocument:
        statements: list[QcStatement] = []
        n = len(content)
        i = 0

        while i < n:
            i = cls._skip_ws_and_comments(content, i)
            if i >= n:
                break

            if content[i] != "$":
                newline = content.find("\n", i)
                i = n if newline == -1 else newline + 1
                continue

            stmt_start = i
            directive_end = i + 1
            while directive_end < n and (content[directive_end].isalnum() or content[directive_end] == "_"):
                directive_end += 1
            directive = content[stmt_start:directive_end].lower()

            pos = directive_end
            in_quotes = False
            brace_found = False

            while pos < n:
                ch = content[pos]
                if in_quotes:
                    if ch == '"':
                        in_quotes = False
                    pos += 1
                    continue

                if ch == '"':
                    in_quotes = True
                    pos += 1
                    continue

                if ch == "/" and pos + 1 < n and content[pos + 1] == "/":
                    nl = content.find("\n", pos)
                    pos = n if nl == -1 else nl
                    continue

                if ch == "/" and pos + 1 < n and content[pos + 1] == "*":
                    end_c = content.find("*/", pos + 2)
                    pos = n if end_c == -1 else end_c + 2
                    continue

                if ch == "{":
                    brace_found = True
                    break

                if ch in "\r\n":
                    peek = cls._skip_ws_and_comments(content, pos)
                    if peek < n and content[peek] == "{":
                        pos = peek
                        brace_found = True
                    break

                pos += 1

            if brace_found:
                end_pos = cls._consume_balanced_braces(content, pos)
                raw = content[stmt_start:end_pos].strip()
                statements.append(QcStatement(directive=directive, raw_text=raw))
                i = end_pos
            else:
                raw = content[stmt_start:pos].strip()
                statements.append(QcStatement(directive=directive, raw_text=raw))
                i = pos

        return QcDocument(statements)

    @staticmethod
    def _skip_ws_and_comments(text: str, pos: int) -> int:
        n = len(text)
        while pos < n:
            if text[pos].isspace():
                pos += 1
            elif text.startswith("//", pos):
                nl = text.find("\n", pos)
                pos = n if nl == -1 else nl + 1
            elif text.startswith("/*", pos):
                end_c = text.find("*/", pos + 2)
                pos = n if end_c == -1 else end_c + 2
            else:
                break
        return pos

    @staticmethod
    def _consume_balanced_braces(text: str, open_brace_pos: int) -> int:
        n = len(text)
        depth = 0
        pos = open_brace_pos
        in_quotes = False

        while pos < n:
            ch = text[pos]
            if in_quotes:
                if ch == '"':
                    in_quotes = False
                pos += 1
                continue

            if ch == '"':
                in_quotes = True
                pos += 1
            elif text.startswith("//", pos):
                nl = text.find("\n", pos)
                pos = n if nl == -1 else nl + 1
            elif text.startswith("/*", pos):
                end_c = text.find("*/", pos + 2)
                pos = n if end_c == -1 else end_c + 2
            elif ch == "{":
                depth += 1
                pos += 1
            elif ch == "}":
                depth -= 1
                pos += 1
                if depth == 0:
                    return pos
            else:
                pos += 1

        return n
