# Legal cases — overdue case report

Platform: macOS

The attorney figures below are used in several stages. They come from the guide's expectations in sub-tasks 3, 8 and 12.

Table: Attorneys
| attorney | file | overdue | max_days |
|---|---|---|---|
| Priya Shah | summary_shah.txt | 4 | 87 |
| Marcus Chen | summary_chen.txt | 3 | 111 |
| Elena Rodriguez | summary_rodriguez.txt | 3 | 132 |

## Sub-task 1 — Check the database and make folders

The guide assumes a shell is already open. These first steps open Terminal from Spotlight.

App: Finder

- key-click cmd+space
- wait 300 ms
- type "terminal"
- key-click enter
- wait for window "Terminal"
> CHECK: "Terminal" - a Terminal window's title is usually "<user> — -zsh — 80×24", not "Terminal"; this only works if the screen map resolves the name to the Terminal window.

App: Terminal

- run `brew services list | grep postgres`
- run `psql -l`

> UNSUPPORTED: "If `legal_cases` is not in the list, run `createdb legal_cases`." — AutoScript v1 has no conditional (§9, §10), so a step that runs only when the database is missing cannot be written.

- run `mkdir -p ~/Documents/legal_data/{raw,exports,summaries,backups}`
- run `cd ~/Documents/legal_data`
- run `ls -la`

## Sub-task 2 — Create the CSV (30 rows)

Block: cases_csv
```
case_id,case_name,attorney,court,filing_date,due_date,status
1,Harborline Logistics v. Meridian Corp,Priya Shah,Superior Court of California,2024-01-08,2024-09-15,Open
2,Bayview Dental Group v. Crestpoint Supply,Priya Shah,Superior Court of California,2024-02-12,2024-11-20,Open
3,Redwood Trail Farms v. Cobalt Insurance,Priya Shah,U.S. District Court N.D. Cal,2024-01-22,2024-08-30,Open
4,Silverline Media v. Orchard Street LLC,Priya Shah,Superior Court of California,2024-03-05,2024-10-10,Open
5,Lumen Architects v. Parkside Holdings,Priya Shah,Superior Court of California,2024-03-18,2024-10-25,Open
6,Northgate Bakery v. Foster Equipment,Priya Shah,Superior Court of California,2024-04-02,2024-12-15,Open
7,Tidewater Marine v. Kessler Freight,Priya Shah,Superior Court of California,2024-04-20,2024-07-31,Closed
8,Granite Peak Builders v. Hollis Steel,Priya Shah,Superior Court of California,2024-05-06,2024-09-05,Open
9,Oakmont Clinic v. Brightway Staffing,Priya Shah,U.S. District Court N.D. Cal,2024-05-21,2024-11-01,Closed
10,Sunridge Solar v. Delta Grid Partners,Priya Shah,Superior Court of California,2024-06-03,2025-01-20,Open
11,Pinecrest Realty v. Albright Title Co,Marcus Chen,Superior Court of California,2024-01-15,2024-08-12,Open
12,Coastal Freight v. Newport Warehousing,Marcus Chen,Superior Court of California,2024-02-01,2024-09-28,Open
13,Maple Grove School v. Summit Buses,Marcus Chen,U.S. District Court N.D. Cal,2024-02-19,2024-10-14,Open
14,Ironwood Tools v. Vega Distribution,Marcus Chen,Superior Court of California,2024-03-11,2024-11-05,Open
15,Bluewater Hotels v. Linden Linens,Marcus Chen,Superior Court of California,2024-03-29,2024-06-30,Closed
16,Cedar Hill Vineyards v. Rowan Bottling,Marcus Chen,Superior Court of California,2024-04-15,2024-10-30,Open
17,Keystone Data v. Arrowhead Networks,Marcus Chen,Superior Court of California,2024-05-02,2024-12-20,Open
18,Westfield Auto v. Parker Parts Inc,Marcus Chen,U.S. District Court N.D. Cal,2024-05-27,2024-09-18,Open
19,Evergreen Pharmacy v. Mercer Labs,Marcus Chen,Superior Court of California,2024-06-10,2024-11-25,Closed
20,Horizon Fitness v. Stanton Gear,Marcus Chen,Superior Court of California,2024-06-24,2025-02-10,Open
21,Riverbend Foods v. Calloway Packaging,Elena Rodriguez,Superior Court of California,2024-01-10,2024-07-22,Open
22,Starlight Theaters v. Monroe Sound,Elena Rodriguez,Superior Court of California,2024-02-05,2024-10-03,Open
23,Glenwood Apartments v. Hartley Roofing,Elena Rodriguez,U.S. District Court N.D. Cal,2024-02-26,2024-09-09,Open
24,Copperfield Mining v. Ridge Transport,Elena Rodriguez,Superior Court of California,2024-03-14,2024-08-19,Closed
25,Willow Creek Spa v. Nolan Plumbing,Elena Rodriguez,Superior Court of California,2024-04-01,2024-11-12,Open
26,Brookside Print v. Atlas Paper Co,Elena Rodriguez,Superior Court of California,2024-04-22,2024-12-30,Open
27,Falcon Security v. Grayson Alarms,Elena Rodriguez,Superior Court of California,2024-05-09,2024-10-21,Closed
28,Lakeshore Rowing v. Keel Boatworks,Elena Rodriguez,U.S. District Court N.D. Cal,2024-05-30,2024-11-28,Open
29,Summit Ridge HOA v. Pacific Paving,Elena Rodriguez,Superior Court of California,2024-06-12,2025-01-08,Open
30,Clearview Optics v. Benton Glassworks,Elena Rodriguez,Superior Court of California,2024-06-28,2024-12-05,Open
```

App: Terminal

- run `cat > raw/cases_raw.csv <<'EOF'`
- type block "cases_csv"
- key-click enter
- run `EOF`

## Sub-task 3 — Validate the CSV

App: Terminal

- run `head -5 raw/cases_raw.csv`
- run `tail -3 raw/cases_raw.csv`
- run `wc -l raw/cases_raw.csv`
- expect output contains "31 raw/cases_raw.csv"
- run `cut -d, -f3 raw/cases_raw.csv | tail -n +2 | sort | uniq -c`
- for each row in "Attorneys":
  - expect output contains "10 {{attorney}}"

Expected: 31 lines (header + 30). 10 cases per attorney.

## Sub-task 4 — Create the table and import

Open psql from inside the folder (so relative paths work). The shell is still in ~/Documents/legal_data from sub-task 1.

App: Terminal

- run `psql legal_cases`
- run `CREATE TABLE cases (case_id INTEGER PRIMARY KEY, case_name TEXT NOT NULL, attorney TEXT NOT NULL, court TEXT NOT NULL, filing_date DATE, due_date DATE, status TEXT);`
- run `\copy cases FROM 'raw/cases_raw.csv' WITH (FORMAT csv, HEADER true)`
- expect output contains "COPY 30"
- run `SELECT COUNT(*) FROM cases;`
- read output as case_count
- expect {{case_count}} matches "(?m)^\\s*30\\s*$"
- run `SELECT attorney, status, COUNT(*) FROM cases GROUP BY attorney, status ORDER BY 1, 2;`
- read output as by_status
- for each row in "Attorneys":
  - expect {{by_status}} matches "{{attorney}}\\s*\\|\\s*Open\\s*\\|\\s*8\\b"
  - expect {{by_status}} matches "{{attorney}}\\s*\\|\\s*Closed\\s*\\|\\s*2\\b"
- run `\d cases`

Expected: `COPY 30`, count 30, 8 Open + 2 Closed per attorney.

## Sub-task 5 — Priority column

Table: High priority cases
| case_id |
|---|
| 1 |
| 3 |
| 8 |
| 11 |
| 12 |
| 18 |
| 21 |
| 23 |

App: Terminal

- run `ALTER TABLE cases ADD COLUMN priority TEXT DEFAULT 'Normal';`
- run `UPDATE cases SET priority = 'High' WHERE status = 'Open' AND due_date < '2024-10-01';`
- expect output contains "UPDATE 8"
- run `SELECT case_id, attorney, due_date, priority FROM cases WHERE priority = 'High' ORDER BY case_id;`
- expect output contains "(8 rows)"
- read output as high_rows
- for each row in "High priority cases":
  - expect {{high_rows}} matches "(?m)^\\s*{{case_id}} \\|[^\\n]*\\|\\s*High"

Expected: `UPDATE 8` (cases 1, 3, 8, 11, 12, 18, 21, 23).

## Sub-task 6 — Audit table and closing cases 5 and 12

App: Terminal

- run `CREATE TABLE case_audit (audit_id SERIAL PRIMARY KEY, case_id INTEGER REFERENCES cases(case_id), old_status TEXT, new_status TEXT, changed_at TIMESTAMP DEFAULT now());`
- run `INSERT INTO case_audit (case_id, old_status, new_status) SELECT case_id, status, 'Closed' FROM cases WHERE case_id IN (5, 12);`
- run `UPDATE cases SET status = 'Closed' WHERE case_id IN (5, 12);`
- run `SELECT * FROM case_audit;`
- run `SELECT case_id, status FROM cases WHERE case_id IN (5, 12);`

## Sub-task 7 — Overdue query and export

App: Terminal

- run `SELECT case_id, case_name, attorney, due_date, DATE '2024-12-01' - due_date AS days_overdue FROM cases WHERE court = 'Superior Court of California' AND status = 'Open' AND due_date < '2024-12-01' ORDER BY attorney, due_date;`
- expect output contains "(10 rows)"
- run `\copy (SELECT case_id, case_name, attorney, due_date, DATE '2024-12-01' - due_date AS days_overdue FROM cases WHERE court = 'Superior Court of California' AND status = 'Open' AND due_date < '2024-12-01' ORDER BY attorney, due_date) TO 'exports/overdue_cases.csv' WITH (FORMAT csv, HEADER true)`
- expect output contains "COPY 10"
- run `\q`

Expected: 10 rows, `COPY 10`. (`\copy` must be on one line.)

## Sub-task 8 — Check the export in the shell

App: Terminal

- run `cat exports/overdue_cases.csv`
- run `wc -l exports/overdue_cases.csv`
- expect output contains "11 exports/overdue_cases.csv"
- run `cut -d, -f3 exports/overdue_cases.csv | tail -n +2 | sort | uniq -c`
- for each row in "Attorneys":
  - expect output contains "{{overdue}} {{attorney}}"

Expected: 11 lines. Shah 4, Chen 3, Rodriguez 3.

## Sub-task 9 — Summary file per attorney

The three awk commands differ only in the attorney name and the file name, so they are one routine ("write attorney summary", at the end of this script) called once per row of the Attorneys table.

App: Terminal

- for each row in "Attorneys":
  - do "write attorney summary" with attorney="{{attorney}}", file="{{file}}"
- App: Terminal
- run `ls summaries`
- for each row in "Attorneys":
  - run `cat summaries/{{file}}`

Tip: after the first awk line, press the Up arrow and change only the name and the file name. (The routine replaces this tip: each command is typed in full.)

## Sub-task 10 — Markdown report

App: Terminal

- run `{ echo "# Overdue Case Report - Superior Court of California"; echo "Generated: $(date +%Y-%m-%d)"; echo; for f in summaries/summary_*.txt; do echo "## $(head -1 "$f" | cut -d: -f2 | sed 's/^ //')"; tail -n +2 "$f"; echo; done; } > summaries/overdue_report.md`
- run `cat summaries/overdue_report.md`

## Sub-task 11 — Pipe-delimited import file

App: Terminal

- run `for f in summaries/summary_*.txt; do awk -F': ' '/^Attorney:/{a=$2} /^Overdue cases:/{n=$2} /^Max days overdue:/{m=$2} /^Cases:/{c=$2} END{print a "|" n "|" m "|" c}' "$f"; done > summaries/summary_import.psv`
- run `cat summaries/summary_import.psv`

## Sub-task 12 — Summary table

App: Terminal

- run `psql legal_cases`
- run `CREATE TABLE attorney_overdue_summary (attorney TEXT PRIMARY KEY, overdue_count INTEGER, max_days_overdue INTEGER, case_list TEXT);`
- run `\copy attorney_overdue_summary FROM 'summaries/summary_import.psv' WITH (FORMAT csv, DELIMITER '|')`
- expect output contains "COPY 3"
- run `SELECT attorney, overdue_count, max_days_overdue FROM attorney_overdue_summary ORDER BY attorney;`
- read output as summary_rows
- for each row in "Attorneys":
  - expect {{summary_rows}} matches "{{attorney}}\\s*\\|\\s*{{overdue}}\\s*\\|\\s*{{max_days}}\\b"
- run `SELECT * FROM attorney_overdue_summary;`

Expected: `COPY 3`. Rodriguez 3 / 132, Chen 3 / 111, Shah 4 / 87.

## Sub-task 13 — View and comparison

App: Terminal

- run `CREATE VIEW v_overdue_by_attorney AS SELECT attorney, COUNT(*) AS overdue_count, MAX(DATE '2024-12-01' - due_date) AS max_days_overdue FROM cases WHERE court = 'Superior Court of California' AND status = 'Open' AND due_date < '2024-12-01' GROUP BY attorney;`
- run `SELECT * FROM v_overdue_by_attorney ORDER BY attorney;`
- run `SELECT s.attorney, s.overdue_count AS table_count, v.overdue_count AS view_count, CASE WHEN s.overdue_count = v.overdue_count AND s.max_days_overdue = v.max_days_overdue THEN 'MATCH' ELSE 'MISMATCH' END AS check_result FROM attorney_overdue_summary s JOIN v_overdue_by_attorney v USING (attorney) ORDER BY s.attorney;`
- expect output contains "(3 rows)"
- expect output does not contain "MISMATCH"
- read output as comparison
- for each row in "Attorneys":
  - expect {{comparison}} matches "{{attorney}}\\s*\\|\\s*{{overdue}}\\s*\\|\\s*{{overdue}}\\s*\\|\\s*MATCH\\b"

Expected: 3 rows, all `MATCH`.

## Sub-task 14 — Total check

App: Terminal

- run `SELECT SUM(overdue_count) AS total_overdue FROM attorney_overdue_summary;`
- read output as total_overdue
- expect {{total_overdue}} matches "(?m)^\\s*10\\s*$"
- run `\dt`
- run `\dv`
- run `\q`
- run `tail -n +2 exports/overdue_cases.csv | wc -l`
- read output as export_rows
- expect {{export_rows}} matches "(?m)^\\s*10\\s*$"

Expected: both are 10.

## Sub-task 15 — Backup and final listing

Table: Final files
| path |
|---|
| backups/legal_cases_backup.sql |
| exports/overdue_cases.csv |
| raw/cases_raw.csv |
| summaries/overdue_report.md |
| summaries/summary_chen.txt |
| summaries/summary_import.psv |
| summaries/summary_rodriguez.txt |
| summaries/summary_shah.txt |

App: Terminal

- run `pg_dump -d legal_cases -t cases -t case_audit -t attorney_overdue_summary -f backups/legal_cases_backup.sql`
- run `grep -c "CREATE TABLE" backups/legal_cases_backup.sql`
- read output as create_count
- expect {{create_count}} matches "(?m)^\\s*3\\s*$"
- run `ls -lh backups`
- run `find ~/Documents/legal_data -type f | sort`
- for each row in "Final files":
  - expect output contains "/legal_data/{{path}}"

Expected: `3`, then 8 files listed.

> UNSUPPORTED: "Stop the recording, then submit as usual." — the guide does not name the recording tool or the submission place, so there is no window, label or key to write this with.

### If something goes wrong

AutoScript v1 stops at the failing step and has no conditional (§9), so these fixes are kept as notes for the person watching the run.

relation "cases" already exists — you ran the step twice. Run `DROP TABLE cases CASCADE;` and redo from sub-task 4.

No such file on \copy — you started psql outside ~/Documents/legal_data. Run `\q`, `cd ~/Documents/legal_data`, then `psql legal_cases` again.

psql: command not found — run `brew services start postgresql@16` (or your version) and check your PATH.

## Routine: write attorney summary (attorney, file)

- App: Terminal
- run `awk -F, -v a="{{attorney}}" 'NR>1 && $3==a {n++; list=list (n>1 ? "; " : "") $2; if ($5+0 > max) {max=$5+0; top=$2}} END {print "Attorney: " a; print "Overdue cases: " n; print "Max days overdue: " max; print "Most overdue case: " top; print "Cases: " list}' exports/overdue_cases.csv > summaries/{{file}}`