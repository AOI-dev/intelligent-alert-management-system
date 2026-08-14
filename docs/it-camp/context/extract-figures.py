#!/usr/bin/env python3
"""Одноразовая утилита: вынимает tikzpicture из rpz.tex в отдельные .tex файлы.

Запускается один раз при переходе на SVG-мастера. Дальше редактируются
img/src/*.svg, а сборка идёт скриптом context/figures.sh.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "img" / "src"
NAMES = [
    "context",
    "connector-asis",
    "connector-tobe",
    "components",
    "flow",
    "automaton",
    "zones",
    "kpi-tree",
]

PREAMBLE = r"""\documentclass[border=6pt]{standalone}
\usepackage{fontspec}
\setmainfont{Times New Roman}
\usepackage{tikz}
\usetikzlibrary{arrows, positioning, shadows, automata, arrows.meta, fit}
\begin{document}
"""

def main() -> int:
    tex = (ROOT / "rpz.tex").read_text()
    blocks = re.findall(r"\\begin\{tikzpicture\}.*?\\end\{tikzpicture\}", tex, re.S)
    if len(blocks) != len(NAMES):
        print(f"найдено {len(blocks)} картинок, ожидалось {len(NAMES)}", file=sys.stderr)
        return 1
    SRC.mkdir(parents=True, exist_ok=True)
    for name, block in zip(NAMES, blocks):
        (SRC / f"fig-{name}.tex").write_text(PREAMBLE + block + "\n\\end{document}\n")
        print(f"fig-{name}.tex")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
