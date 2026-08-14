# Шаблон «Единый документ требований» (ЕДТ)

> Оформление воспроизводит корпоративный Word-шаблон ЕДТ (`example.pdf`):
> синий баннер на титуле, верхний колонтитул с названием проекта, нижний — «стр. N из M»,
> заголовки «1. Раздел» (чёрный Arial bold) и «1.1 Подраздел» (синий Arial),
> шапки таблиц с синей заливкой, подписи «Таблица 1. Название» над таблицей.
> Технически основан на классе `G7-32` (ГОСТ 7.32), но весь внешний вид переопределён в `edtstyle.sty`.

> **Никогда не используй `_` в именах.** Ни в ключах BibTeX, ни в `\label`, ни в именах файлов, ни где-либо ещё.
> LaTeX трактует `_` как спецсимвол (нижний индекс), и без экранирования `\_` компиляция сломается.
> Об экранировании всегда забывают — проще не использовать. Пиши `camelCase` или через дефис: `fig:my-figure`, `tab:comparisonTable`, `ivanov2023`.

## Структура проекта
```
rpz.tex                 — главный файл документа
config.inc.tex          — НАСТРОЙКИ: поля, шрифты, реквизиты документа, нумерация, названия
edtstyle.sty            — оформление ЕДТ: колонтитулы, титул, заголовки, таблицы (не трогать)
preamble.inc.tex        — пакеты и стиль (не трогать)
macros.inc.tex          — пользовательские команды
local-minted.sty        — настройки подсветки кода (minted)
81-biblio.tex           — подключение библиографии
rpz.bib                 — файл источников (BibTeX)
example.pdf             — эталон оформления (экспорт Word-шаблона ЕДТ)
titul.pdf               — старый титул ГОСТ (не используется: титул генерируется \EDTTitlePage)
code/                   — исходные коды для листингов
data/                   — CSV-файлы для таблиц
img/                    — изображения
out/                    — результат компиляции
INSTALL.md              — инструкция по установке окружения
```

## Структура документа (rpz.tex)
```latex
\begin{document}
\EDTTitlePage                        % титул ЕДТ (реквизиты — в config.inc.tex)

\EDTChangeLog{%                      % страница «История изменений»
  1.0 & 08.08.2026 & Первоначальная версия ЕДТ & \\ \hline
}

\tableofcontents                     % оглавление
\clearpage
\frontmatter                         % ненумерованная часть
\Introduction                        % введение (автоматический заголовок)
  ... текст введения ...

\mainmatter                          % нумерованная часть
\chapter{Название главы}
\section{Название раздела}

\frontmatter                         % снова ненумерованная
\backmatter
\Conclusion                          % заключение (автоматический заголовок)
  ... текст заключения ...

\nocite{*}                           % включить все источники
\include{81-biblio}                  % список литературы

\appendix                            % приложения
\chapter{Название приложения}
  ... содержимое ...
\end{document}
```

---

## Компиляция

> Порядок аргументов `-pdf -xelatex` важен. Соблюдай его как в сниппетах.

### Основная сборка
```bash
latexmk -pdf -xelatex -g -bibtex -outdir=out -interaction=nonstopmode -shell-escape rpz.tex
```

### Непрерывная компиляция (авто-обновление при сохранении)
```bash
latexmk -pdf -xelatex -pvc -g -bibtex -outdir=out -interaction=nonstopmode -shell-escape rpz.tex &
```

### Чистый билд (удалить все артефакты)
```bash
latexmk -C -outdir=out
```

### Принудительная сборка
```bash
latexmk -f
```

### Важные флаги
- `-shell-escape` — разрешает исполнять сторонние программы (нужно для `minted`/`pygmentize`)
- `-bibtex` — подключает обработку библиографии
- `-outdir=out` — результат компиляции в папку `out/` (нужны английские имена файлов!)
- `-g` — принудительно пересобирать

### Библиография: первый запуск
При первом добавлении/изменении источников нужно вручную запустить bibtex:
```bash
bibtex out/rpz.aux
```
Иначе источники не обновятся. После этого достаточно обычной сборки через `latexmk`.

### Стили библиографии
- `ugost2008.bst` — основной стиль (ГОСТ 2008)
- `gost780u.bst` — альтернативный
- Источник: https://github.com/AndreyAkinshin/Russian-Phd-LaTeX-Dissertation-Template/tree/master/BibTeX-Styles

---

## Настройки (config.inc.tex)

### Нумерация
```latex
% Для сквозной нумерации закомментировать \...InChapter в config.inc.tex
% \EqInChapter      — формулы:  1.1, 1.2, 2.1 ...
% \TableInChapter   — таблицы:  1.1, 1.2, 2.1 ...
% \PicInChapter     — рисунки:  1.1, 1.2, 2.1 ...
% \ListingInChapter — листинги: 1.1, 1.2, 2.1 ...
```

### Текстовые константы
Все названия разделов и подписей настраиваются в одном месте:
```latex
% Названия разделов
\addto\captionsrussian{\renewcommand\contentsname{Содержание}}
\renewcommand\Introduction{\chapter{\uppercase{Введение}}}
\renewcommand\Conclusion{\chapter{\uppercase{Заключение}}}
\addto\captionsrussian{\renewcommand\bibname{СПИСОК ИСПОЛЬЗОВАННЫХ ИСТОЧНИКОВ}}
\addto\captionsrussian{\renewcommand\appendixname{Приложение}}

% Подписи к объектам
\addto\captionsrussian{\renewcommand\tablename{Таблица}}
\addto\captionsrussian{\renewcommand\figurename{Рисунок}}
\SetupFloatingEnvironment{listing}{name=Листинг}
```
> Для `\contentsname`, `\bibname`, `\tablename`, `\figurename`, `\appendixname`
> обязательно оборачивать в `\addto\captionsrussian{...}` — иначе babel/polyglossia
> перезапишет значение при смене языка.

---

## Сниппеты

### Пропуск номера титула
```latex
\setcounter{page}{2}
\includepdf[pages=-]{tit.pdf}
```

### Списки
```latex
% Маркированный (-)
\begin{itemize}
    \item Первый пункт.
    \item Второй пункт.
\end{itemize}

% Нумерованный: 1. 2. 3.
\begin{enumerate}[1.]
    \item Первый шаг.
    \item Второй шаг.
\end{enumerate}

% Буквенный: а) б) в)
\begin{enumerate}[а)]
    \item первый критерий;
    \item второй критерий;
    \item третий критерий.
\end{enumerate}

% Другие варианты enumerate:
% [I.]   — римские:  I. II. III.
% [a)]   — латинские: a) b) c)
% [(1)]  — в скобках: (1) (2) (3)
```

### Оформление ЕДТ: реквизиты и шапки таблиц
Реквизиты титула и колонтитула задаются в `config.inc.tex`:
```latex
\renewcommand{\edtProjectName}{Интеллектуальная система управления оповещениями}
\renewcommand{\edtBannerTitle}{Единый документ требований}
\renewcommand{\edtDocTitle}{Единый документ требований к ИТ-решению}
\renewcommand{\edtDocVersion}{1.1}
\renewcommand{\edtDocDate}{08.08.2026}
\renewcommand{\edtDocPurpose}{Определяет контекст ...}
\renewcommand{\edtRunningHead}{\edtProjectName{} - ЕДТ - версия \edtDocVersion}
```
Шапка любой таблицы: строка начинается с `\rowcolor{edtdark}`, каждая ячейка — `\hcell{...}`
(белый полужирный Arial на синей заливке). Цвета: `edtdark` (шапки, подзаголовки),
`edtblue` (баннер титула).

### Таблица
```latex
\begin{table}[H]
\centering
\caption{Сравнение IDE}
\label{tab:my-table}
\resizebox{\textwidth}{!}{%
\begin{tabular}{|l|l|l|l|}
\hline
\rowcolor{edtdark} \hcell{Критерий} & \hcell{PyCharm} & \hcell{VS Code} & \hcell{Atom} \\ \hline
Функциональность     & 9                & 8                & 7             \\ \hline
Производительность   & 7                & 8                & 8             \\ \hline
\end{tabular}%
}
\end{table}
```

### Таблица из CSV
```latex
\begin{table}[H]
    \centering
    \caption{Условия содержания}
    \resizebox{\textwidth}{!}{%
        \csvreader[
            separator=comma, respect percent,
            tabular=lllc p{5cm},
            table head=\toprule \textbf{Вид} & \textbf{Темп.} & \textbf{Влажн.} & \textbf{Свет} & \textbf{Особ.} \\ \midrule,
            table foot=\bottomrule, late after line=\\
        ]{data/file.csv}{}{%
            \csvlinetotablerow
        }
    }\label{tab:csv}
\end{table}
```
> `\csvlinetotablerow` работает, только если количество колонок в CSV **точно совпадает** с `tabular=...`.

### Листинг кода
```latex
\begin{code}
    \captionof{listing}{Описание кода}
    \label{code:example}
    \inputminted[fontsize=\footnotesize, linenos, baselinestretch=1, breaklines]{python}{code/main.py}
\end{code}
```

### Картинка (label после caption!)
```latex
\begin{figure}[H]
    \centering
    \includegraphics[width=0.8\textwidth]{img/scheme.png}
    \captionof{figure}{Описание рисунка}
    \label{fig:scheme}
\end{figure}
```

### Две subfigure
```latex
\begin{figure}[H]
    \begin{subfigure}[H]{\textwidth}
        \begin{code}
            \captionof{listing}{Matlab код}
            \inputminted[fontsize=\footnotesize, linenos, breaklines]{matlab}{matlab/code.m}
        \end{code}
    \end{subfigure}
    \begin{subfigure}[H]{\textwidth}
        \inputminted[fontsize=\footnotesize, linenos, breaklines]{python}{python/code.py}
    \end{subfigure}
\end{figure}
```

### Verbatim (просто текст)
```latex
\begin{verbatim}
Текст без форматирования, моноширинным шрифтом.
\end{verbatim}
```

```latex
\begin{minted}[fontsize=\small]{text}
code snippet
\end{minted}
```

### Следующая страница
```latex
\clearpage
```

### Приложения
```latex
\appendix   % после этой команды главы нумеруются как А, Б, В...

\chapter{Исходный код модуля}
\label{app:code}
Текст приложения, листинги, таблицы и т.д.

\chapter{Результаты экспериментов}
\label{app:results}
```

### Ссылки
```latex
% На таблицу, рисунок, листинг, формулу, приложение:
таблица~\ref{tab:my-table}
рисунок~\ref{fig:my-figure}
листинг~\ref{code:my-code}
формула~(\ref{eq:my-equation})
приложение~\ref{app:code}

% На источник:
\cite{knuth1997}
\cite{knuth1997, cormen2009}   % несколько сразу
```

### Все источники без явного цитирования
```latex
\nocite{*}
```

---

## Библиография (rpz.bib) — стиль ugost2008

### Все поля ugost2008.bst
```bibtex
@тип{ключ,
  % --- Авторы и редакторы ---
  author       = {},  % автор(ы): {Фамилия, И. О. and Фамилия, И. О.}
  bookauthor   = {},  % автор книги (для @incollection — глава из чужой книги)
  editor       = {},  % редактор(ы)
  compiler     = {},  % составитель(и) сборника

  % --- Название ---
  title        = {},  % название работы
  booktitle    = {},  % название книги/сборника (для @incollection, @inproceedings)
  journal      = {},  % название журнала (для @article)

  % --- Издание ---
  address      = {},  % город: {Москва}, {СПб.}, {New York}
  publisher    = {},  % издательство
  year         = {},  % год
  month        = {},  % месяц (число 1-12)
  edition      = {},  % издание: {3-е}, {2nd}
  series       = {},  % серия: {Классика Computer Science}
  volume       = {},  % том
  number       = {},  % номер журнала/выпуска
  chapter      = {},  % номер главы

  % --- Страницы ---
  pages        = {},  % диапазон страниц: {45--52}, {113--168}
  numpages     = {},  % общее кол-во страниц (для диссертаций)

  % --- Организация ---
  organization = {},  % организация-спонсор (конференции, manual)
  institution  = {},  % учреждение (для @techreport)
  school       = {},  % учебное заведение (для @phdthesis)

  % --- Тип и формат ---
  type         = {},  % тип документа: {ГОСТ}, {Дис. ... канд. техн. наук}
  medium       = {},  % носитель: {Текст}, {Электронный ресурс}
  howpublished = {},  % как опубликовано: {Электронный ресурс}, {Издание официальное}

  % --- Идентификаторы ---
  isbn         = {},  % ISBN
  doi          = {},  % DOI (формирует гиперссылку)
  eprint       = {},  % номер препринта: {1706.03762}
  eprinttype   = {},  % тип архива: {arxiv}
  eprintclass  = {},  % класс: {cs.CL}

  % --- Интернет ---
  url          = {},  % URL электронного ресурса
  urldate      = {},  % дата обращения: {2025-03-13}

  % --- Язык ---
  language     = {},  % язык работы: {russian}, {english}
  booklanguage = {},  % язык книги (если отличается от language)

  % --- Прочее ---
  key          = {},  % ключ сортировки (если нет author)
  note         = {},  % примечание: {Пер. с англ.}
  annote       = {},  % аннотация (выводится после записи)
}
```

### Примеры по типам (см. rpz.bib)
| Тип | Для чего | Обязательные поля |
|-----|----------|-------------------|
| `@book` | Книга | author, title, publisher, year |
| `@article` | Статья в журнале | author, title, journal, year |
| `@inproceedings` | Доклад на конференции | author, title, booktitle, year |
| `@incollection` | Глава из книги | author, title, booktitle, publisher, year |
| `@phdthesis` | Диссертация | author, title, school, year |
| `@techreport` | Стандарт, ГОСТ, техотчёт | title, institution, year |
| `@manual` | Документация | title, year |
| `@misc` | Всё остальное (сайты, препринты) | title, year |
