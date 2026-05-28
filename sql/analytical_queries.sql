-- SQL-запросы для промежуточных результатов КТ5.
-- База данных: artifacts/library_fund_olap.sqlite
-- Тема: OLAP-система анализа эффективности использования библиотечного фонда.

-- 1. Основные таблицы прототипа:
-- dim_date          - календарное измерение;
-- dim_branch        - измерение филиалов библиотеки;
-- dim_book          - измерение фонда;
-- dim_reader        - измерение читателей;
-- fact_circulation  - таблица фактов выдачи.

-- 2. Общие показатели использования фонда.
SELECT
    SUM(loan_count) AS total_loans,
    COUNT(DISTINCT reader_key) AS active_readers,
    COUNT(DISTINCT book_key) AS active_books,
    ROUND(AVG(loan_days), 1) AS avg_loan_days,
    ROUND(100.0 * SUM(CASE WHEN renewal_count > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS renewal_rate_percent,
    ROUND(100.0 * SUM(CASE WHEN overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS overdue_rate_percent
FROM fact_circulation;

-- 3. Таблица показателей по филиалам.
SELECT
    b.branch_name AS branch_name,
    COUNT(*) AS loans,
    COUNT(DISTINCT f.reader_key) AS active_readers,
    COUNT(DISTINCT f.book_key) AS used_books,
    ROUND(AVG(f.loan_days), 1) AS avg_loan_days,
    ROUND(100.0 * SUM(CASE WHEN f.overdue_days > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS overdue_rate_percent
FROM fact_circulation f
JOIN dim_branch b ON b.branch_key = f.branch_key
GROUP BY b.branch_name
ORDER BY COUNT(*) DESC;

-- 4. Таблица показателей по разделам фонда.
SELECT
    bk.category AS category,
    SUM(f.loan_count) AS loans,
    SUM(bk.copies_total) AS copies_in_loan_slice,
    COUNT(DISTINCT bk.book_key) AS used_titles,
    ROUND(1.0 * SUM(f.loan_count) / COUNT(DISTINCT bk.book_key), 2) AS avg_title_turnover,
    ROUND(100.0 * SUM(CASE WHEN f.renewal_count > 0 THEN 1 ELSE 0 END) / COUNT(*), 1) AS renewal_rate_percent
FROM fact_circulation f
JOIN dim_book bk ON bk.book_key = f.book_key
GROUP BY bk.category
ORDER BY SUM(f.loan_count) DESC;

-- 5. Данные для графика динамики выдач по месяцам.
SELECT
    d.month_name AS month_name,
    d.month AS month_number,
    SUM(f.loan_count) AS loans
FROM fact_circulation f
JOIN dim_date d ON d.date_key = f.date_key
GROUP BY d.month, d.month_name
ORDER BY d.month;

-- 6. Данные для графика обращаемости по разделам фонда.
SELECT
    bk.category AS category,
    ROUND(1.0 * SUM(f.loan_count) / COUNT(DISTINCT bk.book_key), 2) AS avg_title_turnover
FROM fact_circulation f
JOIN dim_book bk ON bk.book_key = f.book_key
GROUP BY bk.category
ORDER BY avg_title_turnover DESC;
