# Установка окружения для сборки шаблона ГОСТ 7-32

## Ubuntu / WSL (Ubuntu 22.04+)

### 1. LaTeX (полная установка)
```bash
sudo apt update
sudo apt install texlive-full
```
> ~5 ГБ. Включает XeLaTeX, все пакеты, шрифты, языки.
> Если нужна минимальная установка — см. раздел ниже.

### 2. Шрифты Microsoft (Times New Roman и др.)
```bash
sudo apt install ttf-mscorefonts-installer
```
> Примет лицензию EULA автоматически. Если не появилось окно — запустить:
> `sudo dpkg-reconfigure ttf-mscorefonts-installer`

После установки обновить кэш шрифтов:
```bash
sudo fc-cache -fv
```

Проверить наличие:
```bash
fc-list | grep "Times New Roman"
```

### 3. Сборщик (latexmk)
```bash
sudo apt install latexmk
```

### 4. Подсветка кода (Pygments для minted)
```bash
python3 -m pip install pygments
```

Проверить:
```bash
pygmentize -V
```

## Сборка проекта

```bash
cd /home/aleks/latexProjects/Курсовая_Template_Claude
latexmk -pdf -xelatex -g -bibtex -outdir=out -interaction=nonstopmode -shell-escape rpz.tex
```

Результат: `out/rpz.pdf`

### Первый запуск библиографии
При первом добавлении источников нужно один раз вручную:
```bash
bibtex out/rpz.aux
```
Далее `latexmk` подхватит автоматически.

### Непрерывная сборка (авто-обновление при сохранении)
```bash
latexmk -pdf -xelatex -pvc -g -bibtex -outdir=out -interaction=nonstopmode -shell-escape rpz.tex &
```

### Очистка артефактов
```bash
latexmk -C -outdir=out
```

## Минимальная установка (вместо texlive-full)

Если не хочется ставить 5 ГБ:
```bash
sudo apt install \
  texlive-xetex \
  texlive-lang-cyrillic \
  texlive-fonts-extra \
  texlive-science \
  texlive-latex-extra \
  texlive-bibtex-extra \
  texlive-extra-utils
```
> Если при сборке будут ошибки о недостающих пакетах — проще поставить `texlive-full`.

## Проверка установки

```bash
xelatex --version    # XeLaTeX
latexmk --version    # сборщик
pygmentize -V        # подсветка кода
fc-list | grep Times # шрифт Times New Roman
kpsewhich booktabs.sty  # пакет booktabs (проверка texlive)
```

Все пять команд должны вернуть версии без ошибок.
