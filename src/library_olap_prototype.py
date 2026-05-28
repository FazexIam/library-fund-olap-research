from __future__ import annotations

import csv
import html
import math
import random
import sqlite3
import textwrap
import zipfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DB_PATH = ARTIFACTS / "library_fund_olap.sqlite"
GITHUB_URL = "https://github.com/FazexIam/library-olap-kt5"


@dataclass(frozen=True)
class MetricRow:
    name: str
    value: str
    source: str


def reset_artifacts() -> None:
    ARTIFACTS.mkdir(exist_ok=True)
    for path in ARTIFACTS.glob("*"):
        if path.is_file():
            path.unlink()


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = ON;

        CREATE TABLE dim_date (
            date_key INTEGER PRIMARY KEY,
            full_date TEXT NOT NULL,
            year INTEGER NOT NULL,
            quarter INTEGER NOT NULL,
            month INTEGER NOT NULL,
            month_name TEXT NOT NULL
        );

        CREATE TABLE dim_branch (
            branch_key INTEGER PRIMARY KEY,
            branch_name TEXT NOT NULL,
            district TEXT NOT NULL
        );

        CREATE TABLE dim_book (
            book_key INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            category TEXT NOT NULL,
            publication_year INTEGER NOT NULL,
            acquisition_year INTEGER NOT NULL,
            copies_total INTEGER NOT NULL
        );

        CREATE TABLE dim_reader (
            reader_key INTEGER PRIMARY KEY,
            reader_group TEXT NOT NULL,
            registration_year INTEGER NOT NULL
        );

        CREATE TABLE fact_circulation (
            circulation_key INTEGER PRIMARY KEY,
            date_key INTEGER NOT NULL REFERENCES dim_date(date_key),
            book_key INTEGER NOT NULL REFERENCES dim_book(book_key),
            reader_key INTEGER NOT NULL REFERENCES dim_reader(reader_key),
            branch_key INTEGER NOT NULL REFERENCES dim_branch(branch_key),
            loan_count INTEGER NOT NULL,
            loan_days INTEGER NOT NULL,
            overdue_days INTEGER NOT NULL,
            renewal_count INTEGER NOT NULL
        );
        """
    )


def date_key(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def seed_dimensions(conn: sqlite3.Connection) -> None:
    month_names = {
        1: "Январь",
        2: "Февраль",
        3: "Март",
        4: "Апрель",
        5: "Май",
        6: "Июнь",
        7: "Июль",
        8: "Август",
        9: "Сентябрь",
        10: "Октябрь",
        11: "Ноябрь",
        12: "Декабрь",
    }
    start = date(2025, 1, 1)
    for offset in range(365):
        d = start + timedelta(days=offset)
        conn.execute(
            "INSERT INTO dim_date VALUES (?, ?, ?, ?, ?, ?)",
            (date_key(d), d.isoformat(), d.year, (d.month - 1) // 3 + 1, d.month, month_names[d.month]),
        )

    branches = [
        (1, "Центральная библиотека", "Центральный район"),
        (2, "Филиал северного района", "Северный район"),
        (3, "Филиал студенческого городка", "Университетский район"),
        (4, "Детско-юношеский филиал", "Южный район"),
    ]
    conn.executemany("INSERT INTO dim_branch VALUES (?, ?, ?)", branches)

    categories = [
        ("Информационные технологии", 0.18),
        ("Экономика и менеджмент", 0.15),
        ("Естественные науки", 0.13),
        ("Гуманитарные науки", 0.12),
        ("Учебная литература", 0.22),
        ("Художественная литература", 0.20),
    ]
    books = []
    book_id = 1
    for category, weight in categories:
        count = int(18 + weight * 90)
        for i in range(1, count + 1):
            publication_year = random.randint(1995, 2025)
            acquisition_year = random.randint(max(2005, publication_year), 2025)
            copies_total = random.choices([1, 2, 3, 4, 5, 8], weights=[8, 16, 18, 12, 6, 3])[0]
            books.append(
                (
                    book_id,
                    f"{category}: издание {i}",
                    f"Автор {book_id}",
                    category,
                    publication_year,
                    acquisition_year,
                    copies_total,
                )
            )
            book_id += 1
    conn.executemany("INSERT INTO dim_book VALUES (?, ?, ?, ?, ?, ?, ?)", books)

    reader_groups = ["Студенты", "Преподаватели", "Сотрудники", "Внешние читатели"]
    readers = []
    for reader_id in range(1, 461):
        group = random.choices(reader_groups, weights=[64, 16, 8, 12])[0]
        readers.append((reader_id, group, random.randint(2018, 2025)))
    conn.executemany("INSERT INTO dim_reader VALUES (?, ?, ?)", readers)


def seed_facts(conn: sqlite3.Connection) -> None:
    random.seed(42)
    books = conn.execute("SELECT book_key, category, copies_total FROM dim_book").fetchall()
    readers = [row["reader_key"] for row in conn.execute("SELECT reader_key FROM dim_reader")]
    branches = [row["branch_key"] for row in conn.execute("SELECT branch_key FROM dim_branch")]
    dates = [row["date_key"] for row in conn.execute("SELECT date_key FROM dim_date")]

    category_weights = {
        "Информационные технологии": 1.55,
        "Экономика и менеджмент": 1.25,
        "Естественные науки": 0.95,
        "Гуманитарные науки": 0.75,
        "Учебная литература": 1.65,
        "Художественная литература": 1.05,
    }
    weighted_books = []
    for book in books:
        weight = category_weights[book["category"]] * math.sqrt(book["copies_total"])
        weighted_books.append((book["book_key"], weight))

    facts = []
    for fact_id in range(1, 2201):
        book_key = random.choices([b for b, _ in weighted_books], weights=[w for _, w in weighted_books])[0]
        branch_key = random.choices(branches, weights=[38, 21, 27, 14])[0]
        reader_key = random.choice(readers)
        date_key_value = random.choices(dates, weights=[season_weight(k) for k in dates])[0]
        loan_days = random.choice([7, 10, 14, 21, 30])
        overdue_days = random.choices([0, 1, 2, 3, 5, 7, 10, 14], weights=[72, 7, 5, 4, 4, 3, 3, 2])[0]
        renewal_count = random.choices([0, 1, 2], weights=[78, 18, 4])[0]
        facts.append((fact_id, date_key_value, book_key, reader_key, branch_key, 1, loan_days, overdue_days, renewal_count))

    conn.executemany("INSERT INTO fact_circulation VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", facts)


def season_weight(key: int) -> float:
    month = (key // 100) % 100
    if month in (2, 3, 4, 9, 10, 11):
        return 1.35
    if month in (6, 7, 8):
        return 0.70
    return 1.0


def query_rows(conn: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    return list(conn.execute(sql))


def export_csv(path: Path, rows: list[sqlite3.Row]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(rows[0].keys())
        for row in rows:
            writer.writerow([row[key] for key in row.keys()])


def calculate_outputs(conn: sqlite3.Connection) -> tuple[list[MetricRow], list[sqlite3.Row], list[sqlite3.Row]]:
    total_loans = conn.execute("SELECT SUM(loan_count) FROM fact_circulation").fetchone()[0]
    active_books = conn.execute("SELECT COUNT(DISTINCT book_key) FROM fact_circulation").fetchone()[0]
    total_books = conn.execute("SELECT COUNT(*) FROM dim_book").fetchone()[0]
    unique_readers = conn.execute("SELECT COUNT(DISTINCT reader_key) FROM fact_circulation").fetchone()[0]
    overdue_rate = conn.execute(
        "SELECT ROUND(100.0 * SUM(CASE WHEN overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) FROM fact_circulation"
    ).fetchone()[0]
    renewal_rate = conn.execute(
        "SELECT ROUND(100.0 * SUM(CASE WHEN renewal_count > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) FROM fact_circulation"
    ).fetchone()[0]
    avg_loan_days = conn.execute("SELECT ROUND(AVG(loan_days), 1) FROM fact_circulation").fetchone()[0]

    metrics = [
        MetricRow("Общее число выдач", str(total_loans), "fact_circulation.loan_count"),
        MetricRow("Активные читатели", str(unique_readers), "COUNT(DISTINCT reader_key)"),
        MetricRow("Использованная часть фонда", f"{active_books / total_books * 100:.1f}%", "DISTINCT book_key / dim_book"),
        MetricRow("Средний срок выдачи", f"{avg_loan_days} дней", "AVG(loan_days)"),
        MetricRow("Доля выдач с продлением", f"{renewal_rate}%", "renewal_count > 0"),
        MetricRow("Доля выдач с просрочкой", f"{overdue_rate}%", "overdue_days > 0"),
    ]

    branch_rows = query_rows(
        conn,
        """
        SELECT
            b.branch_name AS 'Филиал',
            COUNT(*) AS 'Выдачи',
            COUNT(DISTINCT f.reader_key) AS 'Активные читатели',
            COUNT(DISTINCT f.book_key) AS 'Использованные экземпляры',
            ROUND(AVG(f.loan_days), 1) AS 'Средний срок выдачи',
            ROUND(100.0 * SUM(CASE WHEN f.overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS 'Просрочки, %'
        FROM fact_circulation f
        JOIN dim_branch b ON b.branch_key = f.branch_key
        GROUP BY b.branch_name
        ORDER BY COUNT(*) DESC;
        """,
    )
    category_rows = query_rows(
        conn,
        """
        SELECT
            bk.category AS 'Раздел фонда',
            SUM(f.loan_count) AS 'Выдачи',
            SUM(bk.copies_total) AS 'Экземпляры в срезе выдач',
            COUNT(DISTINCT bk.book_key) AS 'Использованные издания',
            ROUND(1.0 * SUM(f.loan_count) / COUNT(DISTINCT bk.book_key), 2) AS 'Средняя обращаемость издания',
            ROUND(100.0 * SUM(CASE WHEN f.renewal_count > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS 'Продления, %'
        FROM fact_circulation f
        JOIN dim_book bk ON bk.book_key = f.book_key
        GROUP BY bk.category
        ORDER BY SUM(f.loan_count) DESC;
        """,
    )
    export_csv(ARTIFACTS / "table_branch_metrics.csv", branch_rows)
    export_csv(ARTIFACTS / "table_category_metrics.csv", category_rows)
    return metrics, branch_rows, category_rows


def create_charts(conn: sqlite3.Connection) -> None:
    month_rows = query_rows(
        conn,
        """
        SELECT d.month_name AS label, d.month AS month_no, SUM(f.loan_count) AS value
        FROM fact_circulation f
        JOIN dim_date d ON d.date_key = f.date_key
        GROUP BY d.month, d.month_name
        ORDER BY d.month;
        """,
    )
    category_rows = query_rows(
        conn,
        """
        SELECT bk.category AS label, ROUND(1.0 * SUM(f.loan_count) / COUNT(DISTINCT bk.book_key), 2) AS value
        FROM fact_circulation f
        JOIN dim_book bk ON bk.book_key = f.book_key
        GROUP BY bk.category
        ORDER BY value DESC;
        """,
    )
    write_bar_chart(
        ARTIFACTS / "chart_loans_by_month.svg",
        "Динамика выдач библиотечного фонда по месяцам",
        [(row["label"], row["value"]) for row in month_rows],
        y_label="число выдач",
    )
    write_bar_chart(
        ARTIFACTS / "chart_turnover_by_category.svg",
        "Средняя обращаемость издания по разделам фонда",
        [(row["label"], row["value"]) for row in category_rows],
        y_label="выдач на издание",
    )


def write_bar_chart(path: Path, title: str, data: list[tuple[str, float]], y_label: str) -> None:
    width, height = 980, 560
    margin_left, margin_right, margin_top, margin_bottom = 90, 30, 70, 135
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    max_value = max(v for _, v in data)
    bar_gap = 12
    bar_w = (plot_w - bar_gap * (len(data) - 1)) / len(data)
    colors = ["#2563eb", "#0f766e", "#7c3aed", "#c2410c", "#15803d", "#be123c"]

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#ffffff"/>',
        f'<text x="{width / 2}" y="36" text-anchor="middle" font-family="Arial" font-size="24" font-weight="700">{html.escape(title)}</text>',
        f'<text x="22" y="{margin_top + plot_h / 2}" transform="rotate(-90 22 {margin_top + plot_h / 2})" text-anchor="middle" font-family="Arial" font-size="15">{html.escape(y_label)}</text>',
        f'<line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{margin_top + plot_h}" stroke="#334155" stroke-width="2"/>',
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{margin_left + plot_w}" y2="{margin_top + plot_h}" stroke="#334155" stroke-width="2"/>',
    ]
    for i in range(5):
        value = max_value * i / 4
        y = margin_top + plot_h - plot_h * i / 4
        parts.append(f'<line x1="{margin_left}" y1="{y:.1f}" x2="{margin_left + plot_w}" y2="{y:.1f}" stroke="#e2e8f0"/>')
        parts.append(
            f'<text x="{margin_left - 12}" y="{y + 5:.1f}" text-anchor="end" font-family="Arial" font-size="13" fill="#475569">{value:.0f}</text>'
        )

    for idx, (label, value) in enumerate(data):
        x = margin_left + idx * (bar_w + bar_gap)
        bar_h = 0 if max_value == 0 else plot_h * value / max_value
        y = margin_top + plot_h - bar_h
        color = colors[idx % len(colors)]
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" fill="{color}" rx="3"/>')
        parts.append(
            f'<text x="{x + bar_w / 2:.1f}" y="{y - 8:.1f}" text-anchor="middle" font-family="Arial" font-size="13" fill="#0f172a">{value:g}</text>'
        )
        wrapped = wrap_label(label, 15)
        for line_no, line in enumerate(wrapped[:3]):
            parts.append(
                f'<text x="{x + bar_w / 2:.1f}" y="{margin_top + plot_h + 24 + line_no * 16}" text-anchor="middle" font-family="Arial" font-size="12" fill="#334155">{html.escape(line)}</text>'
            )

    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def wrap_label(text: str, width: int) -> list[str]:
    chunks = textwrap.wrap(text, width=width)
    return chunks or [text]


def markdown_table(headers: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out)


def build_report(metrics: list[MetricRow], branch_rows: list[sqlite3.Row], category_rows: list[sqlite3.Row]) -> str:
    metric_rows = [[m.name, m.value, m.source] for m in metrics]
    branch_table = [[row[key] for key in row.keys()] for row in branch_rows]
    category_table = [[row[key] for key in row.keys()] for row in category_rows]
    return f"""# КТ5. Промежуточные результаты: прототип и первые метрики

**Тема исследования:** OLAP-система анализа эффективности использования библиотечного фонда.

**Трек:** П - прикладной, разработка программной системы.

**Репозиторий с прототипом:** {GITHUB_URL}

**Назначение прототипа.** На данном этапе был подготовлен исследовательский прототип, который проверяет, насколько удобно применять ROLAP-подход для анализа использования библиотечного фонда. В прототипе библиотечные операции представлены в виде реляционной модели со справочными измерениями и таблицей фактов. Такой вариант выбран потому, что он позволяет сохранить данные в обычной базе данных и при этом получать срезы, характерные для OLAP-анализа: по времени, филиалам, разделам фонда, группам читателей и отдельным изданиям.

## Реализованная функциональность

1. Создана демонстрационная база данных `library_fund_olap.sqlite`.
2. Реализованы измерения даты, филиала, книги и читателя.
3. Реализована таблица фактов выдачи библиотечного фонда.
4. Выполнен расчет первичных показателей эффективности: число выдач, активность читателей, используемая часть фонда, средний срок выдачи, доля продлений и доля просрочек.
5. Сформированы две аналитические таблицы и два графика для включения в отчет.

Текущее состояние разработки можно охарактеризовать как исследовательский прототип. Он не заменяет промышленную библиотечную информационную систему, но показывает, какие сущности, связи и показатели необходимы для последующего построения OLAP-аналитики. Основное внимание на этом этапе было уделено не пользовательскому интерфейсу, а структуре данных, расчету показателей и проверке пригодности ROLAP-модели.

## Архитектура прототипа

Прототип построен по схеме ROLAP. Данные хранятся в реляционной базе SQLite, а многомерный анализ выполняется с помощью SQL-запросов с группировками по измерениям. В модели используются следующие компоненты:

- `dim_date` - календарное измерение для анализа выдач по месяцам, кварталам и году;
- `dim_branch` - измерение филиалов библиотеки;
- `dim_book` - измерение фонда с разделами, годом публикации, годом поступления и числом экземпляров;
- `dim_reader` - измерение читателей по группам;
- `fact_circulation` - таблица фактов выдачи, содержащая количество выдач, срок выдачи, просрочку и продления.

Такая схема позволяет в дальнейшем расширить систему без изменения общей логики анализа: добавить новые измерения, например поставщика, язык издания или формат документа, а также новые факты, например списания, бронирования и посещения.

Демонстрационные данные сформированы программно. Это сделано для того, чтобы проверить структуру модели и подготовить первые расчетные результаты до подключения реальных данных библиотечной системы. Поэтому численные выводы следует рассматривать как проверку методики, а не как оценку конкретной библиотеки.

## Основные показатели

{markdown_table(["Показатель", "Значение", "Источник расчета"], metric_rows)}

## Таблица 1. Показатели по филиалам

Источник данных: расчет по таблице фактов `fact_circulation` и измерению `dim_branch`.

{markdown_table(list(branch_rows[0].keys()), branch_table)}

## Таблица 2. Показатели по разделам фонда

Источник данных: расчет по таблице фактов `fact_circulation` и измерению `dim_book`.

{markdown_table(list(category_rows[0].keys()), category_table)}

## Графики и диаграммы

**Рисунок 1.** Динамика выдач библиотечного фонда по месяцам. Файл: `chart_loans_by_month.svg`.

**Рисунок 2.** Средняя обращаемость издания по разделам фонда. Файл: `chart_turnover_by_category.svg`.

## Краткий анализ промежуточных результатов

Полученные результаты соответствуют поставленной задаче, поскольку прототип демонстрирует полный путь от формирования реляционного хранилища до расчета OLAP-показателей. Наиболее востребованными в демонстрационном наборе данных оказываются учебная литература и информационные технологии, что согласуется с предметной областью университетской библиотеки. Значения по филиалам показывают различие нагрузки между точками обслуживания и могут использоваться для планирования комплектования, перераспределения экземпляров и оценки читательской активности.

К преимуществам текущего решения относится простота воспроизведения, прозрачность SQL-запросов и возможность дальнейшего расширения модели. Ограничение прототипа состоит в том, что данные являются демонстрационными, поэтому выводы отражают работоспособность методики, а не фактическое состояние конкретной библиотеки. На следующем этапе необходимо подключить реальные или более детализированные открытые данные, уточнить показатели эффективности, дополнить описание предметной области и оформить результаты в составе итогового отчета.
"""


def html_table(headers: list[str], rows: list[list[object]]) -> str:
    thead = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{thead}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def build_html_report(metrics: list[MetricRow], branch_rows: list[sqlite3.Row], category_rows: list[sqlite3.Row]) -> str:
    metric_rows = [[m.name, m.value, m.source] for m in metrics]
    branch_table = [[row[key] for key in row.keys()] for row in branch_rows]
    category_table = [[row[key] for key in row.keys()] for row in category_rows]
    chart_month = (ARTIFACTS / "chart_loans_by_month.svg").read_text(encoding="utf-8")
    chart_category = (ARTIFACTS / "chart_turnover_by_category.svg").read_text(encoding="utf-8")
    return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <title>КТ5. Промежуточные результаты</title>
  <style>
    @page {{ size: A4; margin: 20mm 10mm 20mm 30mm; }}
    body {{ font-family: "Times New Roman", serif; font-size: 13pt; line-height: 1.5; color: #111827; }}
    h1 {{ text-align: center; font-size: 18pt; line-height: 1.25; margin: 0 0 18pt; }}
    h2 {{ font-size: 15pt; margin: 18pt 0 8pt; }}
    p {{ margin: 0 0 9pt; text-align: justify; }}
    table {{ width: 100%; border-collapse: collapse; margin: 8pt 0 14pt; font-size: 11pt; line-height: 1.25; }}
    th, td {{ border: 1px solid #222; padding: 5px 6px; vertical-align: top; }}
    th {{ background: #f3f4f6; font-weight: 700; }}
    figure {{ margin: 14pt 0; page-break-inside: avoid; }}
    figcaption {{ text-align: center; font-size: 11pt; margin-top: 4pt; }}
    svg {{ width: 100%; height: auto; }}
    code {{ font-family: "Courier New", monospace; font-size: 11pt; }}
  </style>
</head>
<body>
  <h1>КТ5. Промежуточные результаты: прототип и первые метрики</h1>
  <p><strong>Тема исследования:</strong> OLAP-система анализа эффективности использования библиотечного фонда.</p>
  <p><strong>Трек:</strong> П - прикладной, разработка программной системы.</p>
  <p><strong>Репозиторий с прототипом:</strong> <a href="{GITHUB_URL}">{GITHUB_URL}</a></p>

  <h2>Реализованная функциональность</h2>
  <p>На данном этапе был подготовлен исследовательский прототип, который проверяет, насколько удобно применять ROLAP-подход для анализа использования библиотечного фонда. Библиотечные операции представлены в виде реляционной модели со справочными измерениями и таблицей фактов. Такой вариант выбран потому, что он позволяет сохранить данные в обычной базе данных и при этом получать срезы, характерные для OLAP-анализа: по времени, филиалам, разделам фонда, группам читателей и отдельным изданиям.</p>
  <p>Создана демонстрационная база данных <code>library_fund_olap.sqlite</code>, реализованы измерения даты, филиала, книги и читателя, а также таблица фактов выдачи. На основе этих данных рассчитаны первичные показатели эффективности и сформированы две аналитические таблицы и два графика.</p>

  <h2>Архитектура прототипа</h2>
  <p>Прототип построен по схеме ROLAP. Данные хранятся в реляционной базе SQLite, а многомерный анализ выполняется с помощью SQL-запросов с группировками по измерениям. Такая схема позволяет в дальнейшем расширить систему без изменения общей логики анализа: добавить новые измерения, например поставщика, язык издания или формат документа, а также новые факты, например списания, бронирования и посещения.</p>
  <p>Демонстрационные данные сформированы программно. Это сделано для того, чтобы проверить структуру модели и подготовить первые расчетные результаты до подключения реальных данных библиотечной системы. Поэтому численные выводы следует рассматривать как проверку методики, а не как оценку конкретной библиотеки.</p>

  <h2>Основные показатели</h2>
  {html_table(["Показатель", "Значение", "Источник расчета"], metric_rows)}

  <h2>Таблица 1. Показатели по филиалам</h2>
  <p>Источник данных: расчет по таблице фактов <code>fact_circulation</code> и измерению <code>dim_branch</code>.</p>
  {html_table(list(branch_rows[0].keys()), branch_table)}

  <h2>Таблица 2. Показатели по разделам фонда</h2>
  <p>Источник данных: расчет по таблице фактов <code>fact_circulation</code> и измерению <code>dim_book</code>.</p>
  {html_table(list(category_rows[0].keys()), category_table)}

  <h2>Графики и диаграммы</h2>
  <figure>
    {chart_month}
    <figcaption>Рисунок 1. Динамика выдач библиотечного фонда по месяцам.</figcaption>
  </figure>
  <figure>
    {chart_category}
    <figcaption>Рисунок 2. Средняя обращаемость издания по разделам фонда.</figcaption>
  </figure>

  <h2>Краткий анализ промежуточных результатов</h2>
  <p>Полученные результаты соответствуют поставленной задаче, поскольку прототип демонстрирует полный путь от формирования реляционного хранилища до расчета OLAP-показателей. Наиболее востребованными в демонстрационном наборе данных оказываются учебная литература и информационные технологии, что согласуется с предметной областью университетской библиотеки. Значения по филиалам показывают различие нагрузки между точками обслуживания и могут использоваться для планирования комплектования, перераспределения экземпляров и оценки читательской активности.</p>
  <p>К преимуществам текущего решения относится простота воспроизведения, прозрачность SQL-запросов и возможность дальнейшего расширения модели. Ограничение прототипа состоит в том, что данные являются демонстрационными, поэтому выводы отражают работоспособность методики, а не фактическое состояние конкретной библиотеки. На следующем этапе необходимо подключить реальные или более детализированные открытые данные, уточнить показатели эффективности, дополнить описание предметной области и оформить результаты в составе итогового отчета.</p>
</body>
</html>
"""


def docx_escape(text: str) -> str:
    return escape(text)


def paragraph_xml(text: str, style: str | None = None) -> str:
    style_xml = f"<w:pStyle w:val=\"{style}\"/>" if style else ""
    align_xml = "" if style in {"Title", "Heading1"} else '<w:jc w:val="both"/>'
    ppr = f'<w:pPr>{style_xml}<w:spacing w:line="360" w:lineRule="auto"/>{align_xml}</w:pPr>'
    runs = []
    for line in text.split("\n"):
        if runs:
            runs.append("<w:br/>")
        runs.append(f"<w:t xml:space=\"preserve\">{docx_escape(line)}</w:t>")
    return f"<w:p>{ppr}<w:r>{''.join(runs)}</w:r></w:p>"


def table_xml(headers: list[str], rows: list[list[object]]) -> str:
    def cell(text: object, bold: bool = False) -> str:
        bold_xml = "<w:b/>" if bold else ""
        return (
            "<w:tc><w:tcPr><w:tcW w:w=\"2400\" w:type=\"dxa\"/></w:tcPr>"
            f"<w:p><w:r><w:rPr>{bold_xml}</w:rPr><w:t>{docx_escape(str(text))}</w:t></w:r></w:p></w:tc>"
        )

    trs = ["<w:tr>" + "".join(cell(h, True) for h in headers) + "</w:tr>"]
    for row in rows:
        trs.append("<w:tr>" + "".join(cell(v) for v in row) + "</w:tr>")
    return (
        "<w:tbl><w:tblPr><w:tblStyle w:val=\"TableGrid\"/><w:tblW w:w=\"0\" w:type=\"auto\"/>"
        "<w:tblBorders><w:top w:val=\"single\" w:sz=\"4\"/><w:left w:val=\"single\" w:sz=\"4\"/>"
        "<w:bottom w:val=\"single\" w:sz=\"4\"/><w:right w:val=\"single\" w:sz=\"4\"/>"
        "<w:insideH w:val=\"single\" w:sz=\"4\"/><w:insideV w:val=\"single\" w:sz=\"4\"/></w:tblBorders>"
        "</w:tblPr>"
        + "".join(trs)
        + "</w:tbl>"
    )


def create_docx(metrics: list[MetricRow], branch_rows: list[sqlite3.Row], category_rows: list[sqlite3.Row]) -> None:
    metric_rows = [[m.name, m.value, m.source] for m in metrics]
    branch_table = [[row[key] for key in row.keys()] for row in branch_rows]
    category_table = [[row[key] for key in row.keys()] for row in category_rows]

    body = []
    body.append(paragraph_xml("КТ5. Промежуточные результаты: прототип и первые метрики", "Title"))
    body.append(paragraph_xml("Тема исследования: OLAP-система анализа эффективности использования библиотечного фонда."))
    body.append(paragraph_xml("Трек: П - прикладной, разработка программной системы."))
    body.append(paragraph_xml(f"Репозиторий с прототипом: {GITHUB_URL}"))
    body.append(paragraph_xml("Реализованная функциональность", "Heading1"))
    body.append(
        paragraph_xml(
            "На данном этапе был подготовлен исследовательский прототип ROLAP-системы для анализа использования библиотечного фонда. "
            "В работе проверяется, насколько удобно представить сведения о фонде и выдачах в виде реляционной модели, пригодной для "
            "многомерного анализа. Прототип формирует демонстрационную базу SQLite, создает измерения даты, филиала, книги и читателя, "
            "а также таблицу фактов выдачи. На основе этих данных рассчитываются первичные показатели эффективности и формируются "
            "таблицы и графики для отчета."
        )
    )
    body.append(paragraph_xml("Архитектура прототипа", "Heading1"))
    body.append(
        paragraph_xml(
            "Система построена по схеме ROLAP: многомерная аналитика выполняется над реляционной базой данных при помощи SQL-запросов. "
            "Таблица фактов fact_circulation связана с измерениями dim_date, dim_branch, dim_book и dim_reader. Такая структура позволяет "
            "анализировать выдачи по времени, филиалам, разделам фонда и группам читателей. Демонстрационные данные сформированы программно, "
            "поэтому численные результаты следует рассматривать как проверку методики и структуры модели, а не как оценку конкретной библиотеки."
        )
    )
    body.append(paragraph_xml("Основные показатели", "Heading1"))
    body.append(table_xml(["Показатель", "Значение", "Источник расчета"], metric_rows))
    body.append(paragraph_xml("Таблица 1. Показатели по филиалам", "Heading1"))
    body.append(table_xml(list(branch_rows[0].keys()), branch_table))
    body.append(paragraph_xml("Таблица 2. Показатели по разделам фонда", "Heading1"))
    body.append(table_xml(list(category_rows[0].keys()), category_table))
    body.append(paragraph_xml("Графики и диаграммы", "Heading1"))
    body.append(paragraph_xml("Рисунок 1. Динамика выдач библиотечного фонда по месяцам. Файл: chart_loans_by_month.svg."))
    body.append(paragraph_xml("Рисунок 2. Средняя обращаемость издания по разделам фонда. Файл: chart_turnover_by_category.svg."))
    body.append(paragraph_xml("Краткий анализ", "Heading1"))
    body.append(
        paragraph_xml(
            "Промежуточные результаты показывают, что выбранная модель данных пригодна для анализа эффективности использования фонда. "
            "Система позволяет выявлять наиболее востребованные разделы, сравнивать филиалы по числу выдач и активности читателей, "
            "а также отслеживать косвенные признаки проблем обслуживания, например долю просрочек и продлений. Ограничением текущего этапа "
            "является демонстрационный характер данных; на следующем этапе требуется уточнить набор источников, расширить модель под реальные данные "
            "и включить полученные результаты в общий отчет по практике."
        )
    )

    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        + "".join(body)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="850" w:right="567" w:bottom="1134" w:left="1701"/></w:sectPr>'
        "</w:body></w:document>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        '<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:sz w:val="26"/></w:rPr></w:rPrDefault></w:docDefaults>'
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:line="360" w:lineRule="auto"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:sz w:val="26"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:b/><w:sz w:val="32"/></w:rPr></w:style>'
        '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:spacing w:before="240" w:after="120"/></w:pPr><w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:cs="Times New Roman"/><w:b/><w:sz w:val="28"/></w:rPr></w:style>'
        '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/></w:style>'
        "</w:styles>"
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    doc_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    with zipfile.ZipFile(ARTIFACTS / "kt5_report.docx", "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/document.xml", document_xml)
        z.writestr("word/styles.xml", styles_xml)


def main() -> None:
    reset_artifacts()
    random.seed(42)
    with connect() as conn:
        create_schema(conn)
        seed_dimensions(conn)
        seed_facts(conn)
        conn.commit()
        metrics, branch_rows, category_rows = calculate_outputs(conn)
        create_charts(conn)
    report = build_report(metrics, branch_rows, category_rows)
    (ARTIFACTS / "kt5_report.md").write_text(report, encoding="utf-8")
    html_report = build_html_report(metrics, branch_rows, category_rows)
    (ARTIFACTS / "kt5_report.html").write_text(html_report, encoding="utf-8")
    create_docx(metrics, branch_rows, category_rows)
    print(f"Created artifacts in {ARTIFACTS}")


if __name__ == "__main__":
    main()
