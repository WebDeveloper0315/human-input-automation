# Overdue case report — legal_cases

A line-by-line translation of `refer/AutoScript/1.md` into AutoScript
(`docs/AUTOSCRIPT.md`), written to show what the same guide looks like once the
program can read it. The prose, the expectations and the order are the
original's; only the steps have been given a grammar.

Runs on: macOS
App: Terminal

## Sub-task 1 — Check the database and make folders

- run `brew services list | grep postgres`
- run `psql -l`
- expect output contains "legal_cases"
- run `mkdir -p ~/Documents/legal_data/{raw,exports,summaries,backups}`
- run `cd ~/Documents/legal_data`
- run `ls -la`

> If `legal_cases` is not in the list, run `createdb legal_cases`. In v1 the
> expectation above stops the run instead; see §7 of the spec.

## Sub-task 2 — Create the CSV (30 rows)

Block: cases_csv

```
case_id,case_name,attorney,court,filing_date,due_date,status
1,Harborline Logistics v. Meridian Corp,Priya Shah,Superior Court of California,2024-01-08,2024-09-15,Open
2,Bayview Dental Group v. Crestpoint Supply,Priya Shah,Superior Court of California,2024-02-12,2024-11-20,Open
3,Redwood Trail Farms v. Cobalt Insurance,Priya Shah,U.S. District Court N.D. Cal,2024-01-22,2024-08-30,Open
```

> Truncated here to three rows; the real document carries all thirty, exactly
> as the guide does.

- run `cat > raw/cases_raw.csv <<'EOF'`
- type block "cases_csv"
- run `EOF`

## Sub-task 3 — Validate the CSV

- run `head -5 raw/cases_raw.csv`
- run `wc -l raw/cases_raw.csv`
- expect output contains "31"
- run `cut -d, -f3 raw/cases_raw.csv | tail -n +2 | sort | uniq -c`
- expect output contains "10 Priya Shah"

## Sub-task 4 — Create the table and import

`psql` is a prompt inside the same Terminal window, so the application does not
change and `run` keeps meaning "type this line and press Enter".

- run `psql legal_cases`
- wait for "legal_cases=#"
- run `CREATE TABLE cases (case_id INTEGER PRIMARY KEY, case_name TEXT NOT NULL, attorney TEXT NOT NULL, court TEXT NOT NULL, filing_date DATE, due_date DATE, status TEXT);`
- run `\copy cases FROM 'raw/cases_raw.csv' WITH (FORMAT csv, HEADER true)`
- expect output contains "COPY 30"
- run `SELECT COUNT(*) FROM cases;`
- expect output contains "30"
- run `SELECT attorney, status, COUNT(*) FROM cases GROUP BY attorney, status ORDER BY 1, 2;`
- run `\d cases`

## Sub-task 5 — Priority column

- run `ALTER TABLE cases ADD COLUMN priority TEXT DEFAULT 'Normal';`
- run `UPDATE cases SET priority = 'High' WHERE status = 'Open' AND due_date < '2024-10-01';`
- expect output contains "UPDATE 8"
- run `SELECT case_id, attorney, due_date, priority FROM cases WHERE priority = 'High' ORDER BY case_id;`

## Sub-task 6 — Audit table and closing cases 5 and 12

- run `CREATE TABLE case_audit (audit_id SERIAL PRIMARY KEY, case_id INTEGER REFERENCES cases(case_id), old_status TEXT, new_status TEXT, changed_at TIMESTAMP DEFAULT now());`
- run `INSERT INTO case_audit (case_id, old_status, new_status) SELECT case_id, status, 'Closed' FROM cases WHERE case_id IN (5, 12);`
- expect output contains "INSERT 0 2"
- run `UPDATE cases SET status = 'Closed' WHERE case_id IN (5, 12);`
- run `SELECT * FROM case_audit;`
- run `SELECT case_id, status FROM cases WHERE case_id IN (5, 12);`

## Sub-task 7 — Overdue query and export

- run `SELECT case_id, case_name, attorney, due_date, DATE '2024-12-01' - due_date AS days_overdue FROM cases WHERE court = 'Superior Court of California' AND status = 'Open' AND due_date < '2024-12-01' ORDER BY attorney, due_date;`
- expect output contains "(10 rows)"
- run `\copy (SELECT case_id, case_name, attorney, due_date, DATE '2024-12-01' - due_date AS days_overdue FROM cases WHERE court = 'Superior Court of California' AND status = 'Open' AND due_date < '2024-12-01' ORDER BY attorney, due_date) TO 'exports/overdue_cases.csv' WITH (FORMAT csv, HEADER true)`
- expect output contains "COPY 10"
- run `\q`

## Sub-task 8 — Check the export in the shell

- run `cat exports/overdue_cases.csv`
- run `wc -l exports/overdue_cases.csv`
- expect output contains "11"
- run `cut -d, -f3 exports/overdue_cases.csv | tail -n +2 | sort | uniq -c`
- expect output contains "4 Priya Shah"
- expect output contains "3 Marcus Chen"
- expect output contains "3 Elena Rodriguez"

## Routine: attorney summary

Takes `attorney` and `slug`. This is the guide's own observation — "press the
Up arrow and change only the name and the file name" — written down once
instead of three times.

- run `awk -F, -v a="{{attorney}}" 'NR>1 && $3==a {n++; list=list (n>1 ? "; " : "") $2; if ($5+0 > max) {max=$5+0; top=$2}} END {print "Attorney: " a; print "Overdue cases: " n; print "Max days overdue: " max; print "Most overdue case: " top; print "Cases: " list}' exports/overdue_cases.csv > summaries/summary_{{slug}}.txt`
- run `cat summaries/summary_{{slug}}.txt`
- expect output contains "Attorney: {{attorney}}"

## Sub-task 9 — Summary file per attorney

Table: Attorneys

| attorney | slug |
|---|---|
| Priya Shah | shah |
| Marcus Chen | chen |
| Elena Rodriguez | rodriguez |

- for each row in "Attorneys":
  - do "attorney summary" with attorney="{{attorney}}", slug="{{slug}}"
- run `ls summaries`

## Sub-task 10 — Markdown report

- run `{ echo "# Overdue Case Report - Superior Court of California"; echo "Generated: $(date +%Y-%m-%d)"; echo; for f in summaries/summary_*.txt; do echo "## $(head -1 "$f" | cut -d: -f2 | sed 's/^ //')"; tail -n +2 "$f"; echo; done; } > summaries/overdue_report.md`
- run `cat summaries/overdue_report.md`
- expect output contains "Overdue Case Report"

## Sub-task 11 — Pipe-delimited import file

- run `for f in summaries/summary_*.txt; do awk -F': ' '/^Attorney:/{a=$2} /^Overdue cases:/{n=$2} /^Max days overdue:/{m=$2} /^Cases:/{c=$2} END{print a "|" n "|" m "|" c}' "$f"; done > summaries/summary_import.psv`
- run `cat summaries/summary_import.psv`

## Sub-task 12 — Summary table

- run `psql legal_cases`
- wait for "legal_cases=#"
- run `CREATE TABLE attorney_overdue_summary (attorney TEXT PRIMARY KEY, overdue_count INTEGER, max_days_overdue INTEGER, case_list TEXT);`
- run `\copy attorney_overdue_summary FROM 'summaries/summary_import.psv' WITH (FORMAT csv, DELIMITER '|')`
- expect output contains "COPY 3"
- run `SELECT attorney, overdue_count, max_days_overdue FROM attorney_overdue_summary ORDER BY attorney;`

## Sub-task 13 — View and comparison

- run `CREATE VIEW v_overdue_by_attorney AS SELECT attorney, COUNT(*) AS overdue_count, MAX(DATE '2024-12-01' - due_date) AS max_days_overdue FROM cases WHERE court = 'Superior Court of California' AND status = 'Open' AND due_date < '2024-12-01' GROUP BY attorney;`
- run `SELECT * FROM v_overdue_by_attorney ORDER BY attorney;`
- run `SELECT s.attorney, s.overdue_count AS table_count, v.overdue_count AS view_count, CASE WHEN s.overdue_count = v.overdue_count AND s.max_days_overdue = v.max_days_overdue THEN 'MATCH' ELSE 'MISMATCH' END AS check_result FROM attorney_overdue_summary s JOIN v_overdue_by_attorney v USING (attorney) ORDER BY s.attorney;`
- expect output contains "MATCH"
- expect output does not contain "MISMATCH"

## Sub-task 14 — Total check

- run `SELECT SUM(overdue_count) AS total_overdue FROM attorney_overdue_summary;`
- read "total_overdue" as total
- expect {{total}} == 10
- run `\dt`
- run `\dv`
- run `\q`
- run `tail -n +2 exports/overdue_cases.csv | wc -l`
- expect output contains "10"

## Sub-task 15 — Backup and final listing

- run `pg_dump -d legal_cases -t cases -t case_audit -t attorney_overdue_summary -f backups/legal_cases_backup.sql`
- run `grep -c "CREATE TABLE" backups/legal_cases_backup.sql`
- expect output contains "3"
- run `ls -lh backups`
- run `find ~/Documents/legal_data -type f | sort`
