from __future__ import annotations

import io
import re
import webbrowser
from typing import Callable

import customtkinter as ctk

from gui import theme

# Lazy imports for optional deps
_pygments_available = False
_matplotlib_available = False

try:
    from pygments import lex
    from pygments.lexers import get_lexer_by_name, TextLexer
    from pygments.token import Token
    _pygments_available = True
except ImportError:
    pass

try:
    import matplotlib
    matplotlib.use("Agg")
    matplotlib.rcParams["font.family"] = "sans-serif"
    matplotlib.rcParams["font.sans-serif"] = [
        "Microsoft YaHei",
        "SimHei",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "DejaVu Sans",
    ]
    matplotlib.rcParams["axes.unicode_minus"] = False
    matplotlib.rcParams["mathtext.fontset"] = "custom"
    matplotlib.rcParams["mathtext.rm"] = "Microsoft YaHei"
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from PIL import Image, ImageTk
    _matplotlib_available = True
except ImportError:
    pass

_URL_RE = re.compile(r"https?://[^\s\)\]>\"']+")

# Block math: $$ or \[
_BLOCK_MATH_OPEN = re.compile(r"^(\$\$|\\\[)\s*$")
_BLOCK_MATH_CLOSE_DD = re.compile(r"^\$\$\s*$")
_BLOCK_MATH_CLOSE_BR = re.compile(r"^\\\]\s*$")
_CJK_RE = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")

# Unicode fallback for common LaTeX symbols
_LATEX_UNICODE = {
    r"\alpha": "\u03b1", r"\beta": "\u03b2", r"\gamma": "\u03b3",
    r"\delta": "\u03b4", r"\epsilon": "\u03b5", r"\theta": "\u03b8",
    r"\lambda": "\u03bb", r"\mu": "\u03bc", r"\pi": "\u03c0",
    r"\sigma": "\u03c3", r"\omega": "\u03c9", r"\phi": "\u03c6",
    r"\psi": "\u03c8", r"\rho": "\u03c1", r"\tau": "\u03c4",
    r"\sum": "\u2211", r"\prod": "\u220f", r"\int": "\u222b",
    r"\infty": "\u221e", r"\partial": "\u2202", r"\nabla": "\u2207",
    r"\pm": "\u00b1", r"\times": "\u00d7", r"\div": "\u00f7",
    r"\leq": "\u2264", r"\geq": "\u2265", r"\neq": "\u2260",
    r"\approx": "\u2248", r"\equiv": "\u2261",
    r"\rightarrow": "\u2192", r"\leftarrow": "\u2190",
    r"\Rightarrow": "\u21d2", r"\Leftarrow": "\u21d0",
    r"\forall": "\u2200", r"\exists": "\u2203",
    r"\in": "\u2208", r"\notin": "\u2209",
    r"\subset": "\u2282", r"\supset": "\u2283",
    r"\cup": "\u222a", r"\cap": "\u2229",
    r"\sqrt": "\u221a", r"\cdot": "\u00b7", r"\ldots": "\u2026",
    r"\Delta": "\u0394", r"\Sigma": "\u03a3", r"\Omega": "\u03a9",
}

# Pygments token -> tag mapping
_TOKEN_TAG_MAP = {
    Token.Keyword: "syn_kw",
    Token.Keyword.Type: "syn_kw",
    Token.Name.Builtin: "syn_builtin",
    Token.Name.Function: "syn_func",
    Token.Name.Class: "syn_cls",
    Token.Name.Decorator: "syn_func",
    Token.Literal.String: "syn_str",
    Token.Literal.String.Doc: "syn_str",
    Token.Literal.String.Single: "syn_str",
    Token.Literal.String.Double: "syn_str",
    Token.Literal.Number: "syn_num",
    Token.Literal.Number.Integer: "syn_num",
    Token.Literal.Number.Float: "syn_num",
    Token.Comment: "syn_comment",
    Token.Comment.Single: "syn_comment",
    Token.Comment.Multiline: "syn_comment",
    Token.Operator: "syn_op",
}

# Syntax colors per theme
_SYN_COLORS = {
    "dark": {
        "syn_kw": "#C678DD", "syn_str": "#98C379", "syn_num": "#D19A66",
        "syn_comment": "#5C6370", "syn_func": "#61AFEF", "syn_cls": "#E5C07B",
        "syn_op": "#56B6C2", "syn_builtin": "#E06C75",
    },
    "light": {
        "syn_kw": "#A626A4", "syn_str": "#50A14F", "syn_num": "#986801",
        "syn_comment": "#A0A1A7", "syn_func": "#4078F2", "syn_cls": "#C18401",
        "syn_op": "#0184BC", "syn_builtin": "#E45649",
    },
}


class MarkdownRenderer(ctk.CTkTextbox):

    def __init__(self, master, **kwargs):
        kwargs.setdefault("wrap", "word")
        kwargs.setdefault("state", "disabled")
        kwargs.setdefault("fg_color", theme.get("BG_CARD"))
        kwargs.setdefault("text_color", theme.get("TEXT_PRIMARY"))
        kwargs.setdefault("font", theme.font_body())
        kwargs.setdefault("corner_radius", 8)
        super().__init__(master, **kwargs)

        self._urls: list[str] = []
        self._link_map: dict[str, str] = {}
        self._link_counter = 0
        self._in_code_block = False
        self._code_lang = ""
        self._code_lines: list[str] = []
        self._in_table = False
        self._table_rows: list[str] = []
        self._in_math_block = False
        self._math_block_closer: re.Pattern | None = None
        self._math_lines: list[str] = []
        self._stream_buffer = ""
        self._math_images: list = []

        self._setup_tags()
        theme.on_theme_change(self._apply_theme)

    def _setup_tags(self) -> None:
        tw = self._textbox
        tw.tag_configure(
            "heading", font=theme.font_heading(18),
            foreground=theme.get("TEXT_PRIMARY"), spacing1=8, spacing3=4,
        )
        tw.tag_configure(
            "heading2", font=theme.font_heading(15),
            foreground=theme.get("TEXT_PRIMARY"), spacing1=6, spacing3=3,
        )
        tw.tag_configure(
            "heading3", font=theme.font_heading(13),
            foreground=theme.get("TEXT_PRIMARY"), spacing1=4, spacing3=2,
        )
        tw.tag_configure("bold", font=(*theme.font_body()[:1], theme.font_body()[1], "bold"))
        tw.tag_configure(
            "inline_code", font=theme.font_mono(),
            background=theme.get("MD_CODE_BG"), foreground=theme.get("TEXT_PRIMARY"),
        )
        tw.tag_configure(
            "code_block", font=theme.font_mono(),
            background=theme.get("MD_CODE_BG"), foreground=theme.get("TEXT_PRIMARY"),
            lmargin1=16, lmargin2=16, rmargin=16, spacing1=4, spacing3=4,
        )
        tw.tag_configure("link", foreground=theme.get("ACCENT_BLUE"), underline=True)
        tw.tag_configure("list_item", lmargin1=24, lmargin2=36)
        tw.tag_configure(
            "table_header",
            font=(*theme.font_mono()[:1], theme.font_mono()[1], "bold"),
            background=theme.get("MD_CODE_BG"), foreground=theme.get("TEXT_PRIMARY"),
            lmargin1=8, lmargin2=8,
        )
        tw.tag_configure(
            "table_row", font=theme.font_mono(),
            foreground=theme.get("TEXT_PRIMARY"), lmargin1=8, lmargin2=8,
        )
        tw.tag_configure(
            "table_border", font=theme.font_mono(),
            foreground=theme.get("TEXT_MUTED"), lmargin1=8, lmargin2=8,
        )
        tw.tag_configure(
            "math_block", font=theme.font_mono(),
            foreground=theme.get("ACCENT_BLUE"),
            lmargin1=24, lmargin2=24, spacing1=4, spacing3=4,
        )
        tw.tag_configure(
            "math_inline", font=theme.font_mono(),
            foreground=theme.get("ACCENT_BLUE"),
        )
        # Syntax highlighting tags
        mode = theme.current_mode()
        colors = _SYN_COLORS.get(mode, _SYN_COLORS["dark"])
        for tag_name, color in colors.items():
            tw.tag_configure(
                tag_name, font=theme.font_mono(),
                foreground=color, background=theme.get("MD_CODE_BG"),
                lmargin1=16, lmargin2=16, rmargin=16,
            )
        tw.tag_bind("link", "<Enter>", lambda e: tw.configure(cursor="hand2"))
        tw.tag_bind("link", "<Leave>", lambda e: tw.configure(cursor=""))

    def render(self, text: str) -> None:
        self.configure(state="normal")
        self._textbox.delete("1.0", "end")
        self._reset_state()
        self._render_lines(text.split("\n"))
        self._flush_code_block()
        self._flush_table()
        self._flush_math_block()
        self.configure(state="disabled")

    def render_append(self, text: str) -> None:
        self.configure(state="normal")
        self._render_lines(text.split("\n"))
        self._flush_code_block()
        self._flush_table()
        self._flush_math_block()
        self.configure(state="disabled")

    def append_chunk(self, text: str) -> None:
        self._stream_buffer += text
        lines = self._stream_buffer.split("\n")
        if len(lines) > 1:
            complete = lines[:-1]
            self._stream_buffer = lines[-1]
            self.configure(state="normal")
            self._render_lines(complete)
            self.configure(state="disabled")
            self.see("end")

    def flush_stream(self) -> None:
        self.configure(state="normal")
        if self._stream_buffer:
            self._render_lines([self._stream_buffer])
            self._stream_buffer = ""
        self._flush_code_block()
        self._flush_table()
        self._flush_math_block()
        self.configure(state="disabled")
        self.see("end")

    def clear(self) -> None:
        self.configure(state="normal")
        for tag in list(self._link_map):
            try:
                self._textbox.tag_delete(tag)
            except Exception:
                pass
        self._textbox.delete("1.0", "end")
        self._reset_state()
        self.configure(state="disabled")

    def _reset_state(self) -> None:
        self._urls.clear()
        self._link_map.clear()
        self._link_counter = 0
        self._in_code_block = False
        self._code_lang = ""
        self._code_lines.clear()
        self._in_table = False
        self._table_rows.clear()
        self._in_math_block = False
        self._math_block_closer: re.Pattern | None = None
        self._math_lines.clear()
        self._stream_buffer = ""
        self._math_images.clear()

    def get_urls(self) -> list[str]:
        return list(self._urls)

    # ── Line rendering ──

    def _render_lines(self, lines: list[str]) -> None:
        tw = self._textbox
        for line in lines:
            stripped = line.strip()

            # Math block toggle ($$ or \[...\])
            if self._in_math_block:
                if self._math_block_closer and self._math_block_closer.match(stripped):
                    self._flush_math_block()
                else:
                    self._math_lines.append(line)
                continue

            m_open = _BLOCK_MATH_OPEN.match(stripped)
            if m_open:
                if self._in_table:
                    self._flush_table()
                self._in_math_block = True
                opener = m_open.group(1)
                self._math_block_closer = _BLOCK_MATH_CLOSE_BR if opener == "\\[" else _BLOCK_MATH_CLOSE_DD
                continue

            # Code block toggle
            if stripped.startswith("```"):
                if self._in_table:
                    self._flush_table()
                if self._in_code_block:
                    self._flush_code_block()
                else:
                    self._in_code_block = True
                    self._code_lang = stripped[3:].strip().lower()
                    tw.insert("end", "\n")
                continue

            if self._in_code_block:
                self._code_lines.append(line)
                continue

            # Table detection
            if stripped.startswith("|") and stripped.endswith("|"):
                self._in_table = True
                self._table_rows.append(stripped)
                continue
            elif self._in_table:
                self._flush_table()

            # Headings
            if stripped.startswith("# "):
                tw.insert("end", stripped[2:] + "\n", "heading")
                continue
            if stripped.startswith("## "):
                tw.insert("end", stripped[3:] + "\n", "heading2")
                continue
            if stripped.startswith("### "):
                tw.insert("end", stripped[4:] + "\n", "heading3")
                continue

            # List items
            if re.match(r"^[-*]\s", stripped):
                self._render_inline(tw, "  \u2022 " + stripped[2:], extra_tag="list_item")
                tw.insert("end", "\n")
                continue
            if re.match(r"^\d+\.\s", stripped):
                self._render_inline(tw, "  " + stripped, extra_tag="list_item")
                tw.insert("end", "\n")
                continue

            # Normal line
            if stripped:
                self._render_inline(tw, stripped)
                tw.insert("end", "\n")
            else:
                tw.insert("end", "\n")

    # ── Code block with syntax highlighting (F3) ──

    def _flush_code_block(self) -> None:
        if not self._in_code_block:
            return
        self._in_code_block = False
        tw = self._textbox
        code = "\n".join(self._code_lines)
        self._code_lines.clear()

        if _pygments_available and self._code_lang:
            try:
                lexer = get_lexer_by_name(self._code_lang, stripall=True)
            except Exception:
                lexer = None
            if lexer:
                for ttype, value in lex(code, lexer):
                    tag = self._resolve_token_tag(ttype)
                    tw.insert("end", value, tag)
                tw.insert("end", "\n")
                return

        # Fallback: plain code_block
        tw.insert("end", code + "\n", "code_block")

    def _resolve_token_tag(self, ttype) -> str:
        while ttype:
            tag = _TOKEN_TAG_MAP.get(ttype)
            if tag:
                return tag
            ttype = ttype.parent
        return "code_block"

    # ── Table rendering ──

    def _flush_table(self) -> None:
        if not self._table_rows:
            self._in_table = False
            return
        tw = self._textbox
        rows = self._table_rows
        self._table_rows = []
        self._in_table = False

        parsed: list[list[str]] = []
        separator_idx = -1
        for i, row in enumerate(rows):
            cells = [c.strip() for c in row.strip("|").split("|")]
            if all(re.match(r"^[-:]+$", c) for c in cells):
                separator_idx = i
                continue
            parsed.append(cells)

        if not parsed:
            return

        max_cols = max(len(r) for r in parsed)
        col_widths = [0] * max_cols
        for row in parsed:
            for j, cell in enumerate(row):
                if j < max_cols:
                    col_widths[j] = max(col_widths[j], len(cell))
        col_widths = [max(w, 3) for w in col_widths]

        def format_row(cells: list[str]) -> str:
            parts = []
            for j in range(max_cols):
                val = cells[j] if j < len(cells) else ""
                parts.append(val.ljust(col_widths[j]))
            return " | ".join(parts)

        border = "-+-".join("-" * w for w in col_widths)

        for i, row in enumerate(parsed):
            tag = "table_header" if i == 0 and separator_idx >= 0 else "table_row"
            tw.insert("end", format_row(row) + "\n", tag)
            if i == 0 and separator_idx >= 0:
                tw.insert("end", border + "\n", "table_border")

    # ── Math / LaTeX rendering (F12) ──

    def _flush_math_block(self) -> None:
        if not self._in_math_block and not self._math_lines:
            return
        self._in_math_block = False
        formula = "\n".join(self._math_lines).strip()
        self._math_lines.clear()
        if not formula:
            return
        self._render_math(formula, block=True)

    def _render_math(self, formula: str, block: bool = False) -> None:
        tw = self._textbox
        if _matplotlib_available:
            try:
                img = self._latex_to_image(formula)
                if img:
                    self._math_images.append(img)
                    if block:
                        tw.insert("end", "\n")
                    tw.image_create("end", image=img)
                    if block:
                        tw.insert("end", "\n")
                    return
            except Exception:
                pass
        # Fallback: Unicode approximation
        text = self._latex_to_unicode(formula)
        tag = "math_block" if block else "math_inline"
        if block:
            tw.insert("end", text + "\n", tag)
        else:
            tw.insert("end", text, tag)

    @staticmethod
    def _latex_to_unicode(formula: str) -> str:
        text = formula
        # Superscripts
        sup_map = str.maketrans("0123456789+-=()ni", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079\u207a\u207b\u207c\u207d\u207e\u207f\u2071")
        text = re.sub(r"\^{?(\w+)}?", lambda m: m.group(1).translate(sup_map), text)
        # Subscripts
        sub_map = str.maketrans("0123456789+-=()aeiou", "\u2080\u2081\u2082\u2083\u2084\u2085\u2086\u2087\u2088\u2089\u208a\u208b\u208c\u208d\u208e\u2090\u2091\u2092\u2093\u2094")
        text = re.sub(r"_{?(\w+)}?", lambda m: m.group(1).translate(sub_map), text)
        # Fractions
        text = re.sub(r"\\frac\{([^}]+)\}\{([^}]+)\}", r"(\1)/(\2)", text)
        # Known symbols
        for latex, uni in _LATEX_UNICODE.items():
            text = text.replace(latex, uni)
        # Clean remaining braces
        text = text.replace("{", "").replace("}", "")
        return text

    def _latex_to_image(self, formula: str) -> "ImageTk.PhotoImage | None":
        if not _matplotlib_available:
            return None
        mode = theme.current_mode()
        fg = "#E0E0E0" if mode == "dark" else "#1A1A1A"
        bg = theme.get("BG_CARD")
        # Clean formula: strip outer $ or \( \) if present
        clean = formula.strip()
        for prefix, suffix in [("\\(", "\\)"), ("\\[", "\\]"), ("$$", "$$"), ("$", "$")]:
            if clean.startswith(prefix) and clean.endswith(suffix):
                clean = clean[len(prefix):-len(suffix)].strip()
                break
        if not clean:
            return None
        try:
            fig = plt.figure(figsize=(0.01, 0.01))
            fig.patch.set_facecolor(bg)
            if _CJK_RE.search(clean):
                fig.text(
                    0,
                    0.5,
                    clean,
                    fontsize=14,
                    color=fg,
                    ha="left",
                    va="center",
                    fontfamily="Microsoft YaHei",
                )
            else:
                fig.text(
                    0,
                    0.5,
                    f"${clean}$",
                    fontsize=14,
                    color=fg,
                    ha="left",
                    va="center",
                    usetex=False,
                    math_fontfamily="dejavusans",
                )
            canvas = FigureCanvasAgg(fig)
            fig.set_dpi(120)
            canvas.draw()
            bbox = fig.get_tightbbox(canvas.get_renderer())
            if bbox:
                fig.set_size_inches(bbox.width + 0.1, bbox.height + 0.1)
                canvas.draw()
            buf = io.BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight",
                        pad_inches=0.05, facecolor=bg, dpi=120)
            plt.close(fig)
            buf.seek(0)
            pil_img = Image.open(buf)
            return ImageTk.PhotoImage(pil_img)
        except Exception:
            plt.close("all")
            return None

    # ── Inline rendering ──

    def _render_inline(self, tw, text: str, extra_tag: str | None = None) -> None:
        pattern = re.compile(
            r"(\*\*(.+?)\*\*)"
            r"|(`([^`]+)`)"
            r"|(\[([^\]]+)\]\(([^)]+)\))"
            r"|(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)"
            r"|(?:\\\()(.+?)(?:\\\))"
        )
        pos = 0
        tags = (extra_tag,) if extra_tag else ()
        for m in pattern.finditer(text):
            if m.start() > pos:
                segment = text[pos:m.start()]
                self._insert_with_bare_urls(tw, segment, tags)
            if m.group(2):  # bold
                tw.insert("end", m.group(2), ("bold", *tags))
            elif m.group(4):  # inline code
                tw.insert("end", m.group(4), ("inline_code", *tags))
            elif m.group(6):  # link
                url = m.group(7)
                link_tag = self._make_link_tag(url)
                tw.insert("end", m.group(6), ("link", link_tag, *tags))
            elif m.group(8):  # inline math $...$
                self._render_math(m.group(8), block=False)
            elif m.group(9):  # inline math \(...\)
                self._render_math(m.group(9), block=False)
            pos = m.end()
        if pos < len(text):
            self._insert_with_bare_urls(tw, text[pos:], tags)

    def _insert_with_bare_urls(self, tw, text: str, tags: tuple) -> None:
        pos = 0
        for m in _URL_RE.finditer(text):
            if m.start() > pos:
                tw.insert("end", text[pos:m.start()], tags)
            url = m.group(0).rstrip(".,;:!?)")
            link_tag = self._make_link_tag(url)
            tw.insert("end", url, ("link", link_tag, *tags))
            pos = m.start() + len(url)
        if pos < len(text):
            tw.insert("end", text[pos:], tags)

    def _make_link_tag(self, url: str) -> str:
        self._link_counter += 1
        tag = f"link_{self._link_counter}"
        self._link_map[tag] = url
        if url not in self._urls:
            self._urls.append(url)
        self._textbox.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
        return tag

    def _apply_theme(self) -> None:
        self.configure(
            fg_color=theme.get("BG_CARD"),
            text_color=theme.get("TEXT_PRIMARY"),
        )
        self._setup_tags()
        self._math_images.clear()

    def destroy(self):
        theme.remove_listener(self._apply_theme)
        super().destroy()
