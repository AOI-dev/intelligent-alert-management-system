#!/usr/bin/env bash
# Пересобирает векторные картинки документа из SVG-мастеров.
#
#   img/src/*.svg  — мастера, их можно править руками (Inkscape, Figma, любой
#                    редактор SVG) или текстом;
#   img/*.pdf      — то, что реально включается в rpz.tex; генерируется отсюда,
#                    руками не правится.
#
# Запуск:  bash context/figures.sh  [имя ...]
# Без аргументов пересобирает все.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/img/src"
OUT="$ROOT/img"
CHROME="${CHROME:-/snap/bin/chromium}"

targets=("$@")
if [ ${#targets[@]} -eq 0 ]; then
    for f in "$SRC"/*.svg; do targets+=("$(basename "$f" .svg)"); done
fi

for name in "${targets[@]}"; do
    svg="$SRC/$name.svg"
    [ -f "$svg" ] || { echo "нет файла $svg" >&2; exit 1; }
    # snap-версия Chromium не пишет в произвольный /tmp, поэтому каталог в $HOME
    tmp="$(mktemp -d "$HOME/.cache/figbuild.XXXXXX")"

    # Chromium печатает на страницу Letter и обрезает всё, что шире. Оборачиваем
    # SVG в HTML, у которого размер страницы равен размеру самой картинки.
    python3 - "$svg" "$tmp/page.html" <<'PY'
import re, sys, pathlib
svg = pathlib.Path(sys.argv[1]).read_text()
head = svg[:svg.index('>')]
def dim(attr):
    m = re.search(attr + r"='([\d.]+)(pt|mm|px|in)?'", head) or \
        re.search(attr + r'="([\d.]+)(pt|mm|px|in)?"', head)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2) or 'px'
    return value * {'pt': 1 / 72, 'mm': 1 / 25.4, 'px': 1 / 96, 'in': 1}[unit]
w, h = dim('width'), dim('height')
size = f"@page {{ size: {w + 0.05:.2f}in {h + 0.05:.2f}in; margin: 0; }}" if w and h else "@page { margin: 0; }"
pathlib.Path(sys.argv[2]).write_text(
    f"<!doctype html><meta charset='utf-8'><style>{size}"
    "html,body{margin:0;padding:0}svg{display:block}</style>" + svg)
PY

    "$CHROME" --headless --no-sandbox --disable-gpu --no-pdf-header-footer \
        --print-to-pdf="$tmp/raw.pdf" "file://$tmp/page.html" >/dev/null 2>&1
    pdfcrop --margins 2 "$tmp/raw.pdf" "$OUT/$name.pdf" >/dev/null
    rm -rf "$tmp"
    echo "$name.pdf"
done
