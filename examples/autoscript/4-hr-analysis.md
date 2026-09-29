# HR compensation analysis

Platform: macOS

Converted from the guide "HR analysis" (TextEdit, Postman, JASP, GeoGebra Classic).

## 1. Create `hr_compensation_data.csv` (sub-task 1)

Open TextEdit. Go to Format → Make Plain Text, paste the data below, and save it to the Desktop as `hr_compensation_data.csv`.

This data meets every rule in the brief: 6 employees per department, all values inside the given ranges, and Engineering paid more.

The guide pastes. The robot types the block one character at a time.

Block: hr_csv

```
employee_id,department,base_salary,annual_bonus,years_of_service,performance_score
E001,Engineering,86000,9500,12,4.5
E002,Engineering,78500,8200,8,4.0
E003,Engineering,92000,11000,17,5.0
E004,Engineering,71000,7000,5,3.5
E005,Engineering,83500,8800,14,4.0
E006,Engineering,67500,6200,3,3.0
E007,Marketing,62000,5400,7,3.5
E008,Marketing,55500,4100,4,3.0
E009,Marketing,70500,6600,13,4.0
E010,Marketing,48000,2000,1,2.0
E011,Marketing,66000,5900,10,4.5
E012,Marketing,58500,4700,6,2.5
E013,Operations,52000,3200,3,2.5
E014,Operations,64500,5000,11,3.5
E015,Operations,59000,4300,8,3.0
E016,Operations,73500,7200,19,4.5
E017,Operations,50500,2600,2,2.0
E018,Operations,61000,4800,9,5.0
```

The same 18 rows as a table, for the loops in stages 2 and 4. Keep it identical to the block above. `status_pattern` is not part of the CSV. It holds the status check for each request in stage 2: the guide requires 200 for E001 and only asks to look at the code for the others.

Table: Employees

| employee_id | department | base_salary | annual_bonus | years_of_service | performance_score | status_pattern |
|---|---|---|---|---|---|---|
| E001 | Engineering | 86000 | 9500 | 12 | 4.5 | ^200$ |
| E002 | Engineering | 78500 | 8200 | 8 | 4.0 | ^[0-9][0-9][0-9]$ |
| E003 | Engineering | 92000 | 11000 | 17 | 5.0 | ^[0-9][0-9][0-9]$ |
| E004 | Engineering | 71000 | 7000 | 5 | 3.5 | ^[0-9][0-9][0-9]$ |
| E005 | Engineering | 83500 | 8800 | 14 | 4.0 | ^[0-9][0-9][0-9]$ |
| E006 | Engineering | 67500 | 6200 | 3 | 3.0 | ^[0-9][0-9][0-9]$ |
| E007 | Marketing | 62000 | 5400 | 7 | 3.5 | ^[0-9][0-9][0-9]$ |
| E008 | Marketing | 55500 | 4100 | 4 | 3.0 | ^[0-9][0-9][0-9]$ |
| E009 | Marketing | 70500 | 6600 | 13 | 4.0 | ^[0-9][0-9][0-9]$ |
| E010 | Marketing | 48000 | 2000 | 1 | 2.0 | ^[0-9][0-9][0-9]$ |
| E011 | Marketing | 66000 | 5900 | 10 | 4.5 | ^[0-9][0-9][0-9]$ |
| E012 | Marketing | 58500 | 4700 | 6 | 2.5 | ^[0-9][0-9][0-9]$ |
| E013 | Operations | 52000 | 3200 | 3 | 2.5 | ^[0-9][0-9][0-9]$ |
| E014 | Operations | 64500 | 5000 | 11 | 3.5 | ^[0-9][0-9][0-9]$ |
| E015 | Operations | 59000 | 4300 | 8 | 3.0 | ^[0-9][0-9][0-9]$ |
| E016 | Operations | 73500 | 7200 | 19 | 4.5 | ^[0-9][0-9][0-9]$ |
| E017 | Operations | 50500 | 2600 | 2 | 2.0 | ^[0-9][0-9][0-9]$ |
| E018 | Operations | 61000 | 4800 | 9 | 5.0 | ^[0-9][0-9][0-9]$ |

The four numeric columns, used by Descriptives and Correlation in stage 3.

Table: Numeric columns

| column |
|---|
| base_salary |
| annual_bonus |
| years_of_service |
| performance_score |

The graph bounds for stage 4. The guide writes −1 with a Unicode minus sign. The robot types an ASCII hyphen.

Table: Graphics bounds

| field | value |
|---|---|
| xMin: | -1 |
| xMax: | 21 |
| yMin: | 0 |
| yMax: | 100000 |

Make Plain Text is chosen from the menu, not with cmd+shift+t. The shortcut toggles, so on a document that is already plain it would make it rich text. From the menu, a missing "Make Plain Text" item stops the run instead.

- do "new plain text document"
- App: TextEdit
- type block "hr_csv"
- key-click cmd+s
- do "save on Desktop in dialog" with filename="hr_compensation_data.csv"
- App: TextEdit
- wait for window "hr_compensation_data.csv"
  > CHECK: hr_compensation_data.csv - the title drops ".csv" if Finder hides extensions. TextEdit may also ask whether to keep ".csv" or use ".txt". Either case makes this wait fail and stops the run.

If the file already exists on the Desktop, macOS asks whether to replace it, and the wait above fails.

## 2. Postman (sub-tasks 2–5)

1. Click **New → HTTP Request**. Set the method to **POST** and the URL to `https://httpbin.org/post`.

- do "launch app" with app_name="Postman"
- App: Postman
- wait for window "Postman" up to 60 s
  > CHECK: Postman - the main window title may include the workspace name, and a sign-in screen may appear first.
- key-click cmd+t
  > CHECK: cmd+t - Postman's New Tab shortcut, used in place of New → HTTP Request. Assumed to open an HTTP request tab.
- wait for button "GET"
  > CHECK: GET - the method selector. "GET" may also appear as text in the sidebar history.
- find button "GET" as method_menu
- move to {{method_menu}}
- left-click
- wait for item "POST"
- find item "POST" as post_item
- move to {{post_item}}
- left-click
- screenshot
- find field "Enter URL or paste text" as url_field
  > CHECK: Enter URL or paste text - placeholder text of the URL field. It differs between Postman versions.
- move to {{url_field}}
- left-click
- type "https://httpbin.org/post"

Enter is not pressed here, because Enter in the URL field sends the request.

2. Go to **Body → raw → JSON**. Postman adds the `Content-Type: application/json` header for you. Check it on the Headers tab.

- screenshot
- find tab "Body" as body_tab
- move to {{body_tab}}
- left-click
- screenshot
- find text "raw" as raw_option
  > CHECK: raw - a radio button. §5.7 has no radio role, so "text" is used.
- move to {{raw_option}}
- left-click
- screenshot
- find button "Text" as format_menu
  > CHECK: Text - the body format dropdown that appears after "raw". Assumed to show "Text" by default.
- move to {{format_menu}}
- left-click
- wait for item "JSON"
- find item "JSON" as json_item
- move to {{json_item}}
- left-click
- screenshot
- find tab "Headers" as headers_tab
  > CHECK: Headers - the tab label includes a count, for example "Headers (9)".
- move to {{headers_tab}}
- left-click
- screenshot
- expect "application/json" exists
  > CHECK: application/json - Postman may list the automatic Content-Type header under a collapsed "hidden" row that must be opened first.
- screenshot
- find tab "Body" as body_tab_again
- move to {{body_tab_again}}
- left-click

3. Paste this body and click **Send**. Check that the status shows **200 OK**. (The E001 body in the guide is exactly what the routine "send employee" types for the first row.)
4. Change the values to E002's row and send again. Repeat through E018, and look at the status code each time.

Each row replaces the whole body and sends it. The status code is read and recorded into ApiLog for step 5. For E001, the status must be 200. For every other row, it only has to be a three-digit code.

- for each row in "Employees":
  - do "send employee" with employee_id="{{employee_id}}", department="{{department}}", base_salary="{{base_salary}}", annual_bonus="{{annual_bonus}}", years_of_service="{{years_of_service}}", performance_score="{{performance_score}}", status_pattern="{{status_pattern}}"

5. In TextEdit, save `api_validation_log.csv` to the Desktop, with the columns employee_id and response_status. Write all 18 rows, and use the real code if any request did not return 200.

- do "new plain text document"
- App: TextEdit
- type table "ApiLog"
  > CHECK: ApiLog - assumes `type table` types the header row "employee_id,response_status" before the 18 rows (§5.10 does not say).
- screenshot
- expect "employee_id,response_status" exists
- expect "E018" exists
- key-click cmd+s
- do "save on Desktop in dialog" with filename="api_validation_log.csv"
- App: TextEdit
- wait for window "api_validation_log.csv"
  > CHECK: api_validation_log.csv - same title and extension caveats as in stage 1.

## 3. JASP (sub-tasks 6–11)

1. **Open → Computer → Browse** and pick `hr_compensation_data.csv`. Check that `department` is nominal and the other four value columns are scale.

- do "launch app" with app_name="JASP"
- App: JASP
- wait for window "JASP" up to 60 s
- find icon "Main menu" as main_menu
  > CHECK: Main menu - JASP's top-left file menu button is an icon with no text label. It needs a screen-map entry (image or point).
- move to {{main_menu}}
- left-click
- wait for item "Open"
- find item "Open" as open_item
- move to {{open_item}}
- left-click
- wait for item "Computer"
- find item "Computer" as computer_item
- move to {{computer_item}}
- left-click
- wait for button "Browse"
  > CHECK: Browse - may be a folder button labelled "Browse" or "Browse…".
- find button "Browse" as browse_button
- move to {{browse_button}}
- left-click
- wait for button "Open"
  > CHECK: Open - the button of the macOS open panel. Assumes JASP uses the native panel.
- key-click cmd+shift+g
- wait 500 ms
- type "~/Desktop/hr_compensation_data.csv"
- key-click enter
- wait 500 ms
- key-click enter
- wait for text "performance_score" up to 30 s

> UNSUPPORTED: "Check that `department` is nominal and the other four value columns are scale." - JASP shows the measurement type only as an icon beside each column header. No verb in §4 can check which icon belongs to which column.

2. **Descriptives:** add the 4 numeric columns. Under Statistics, tick Mean, Median, Std. deviation, Minimum and Maximum.

- screenshot
- find button "Descriptives" as descriptives_button
  > CHECK: Descriptives - in some JASP versions this ribbon button opens a menu ("Descriptive Statistics") instead of the analysis directly.
- move to {{descriptives_button}}
- left-click
- wait for "Descriptives Variables arrow"
  > CHECK: Descriptives Variables arrow - the arrow beside the Variables box has no label. It needs a screen-map entry.
- for each row in "Numeric columns":
  - do "move variable" with variable="{{column}}", arrow="Descriptives Variables arrow"
- screenshot
- find button "Statistics" as statistics_section
  > CHECK: Statistics - the collapsible section header in the Descriptives options. "Descriptive Statistics" in the results may also match if matching is by substring.
- move to {{statistics_section}}
- left-click
- wait for checkbox "Median"
- find checkbox "Median" as median_box
- move to {{median_box}}
- left-click

> UNSUPPORTED: "tick Mean, Std. deviation, Minimum and Maximum" - JASP ticks these four by default, so clicking them would untick them. Only Median is clicked. No verb can read whether a checkbox is ticked, so the defaults cannot be checked.

3. **Regression → Correlation:** add the same 4 columns. Pearson is already selected.

- screenshot
- find button "Regression" as regression_menu
- move to {{regression_menu}}
- left-click
- wait for "Classical Correlation"
  > CHECK: Classical Correlation - the menu lists "Correlation" under both Classical and Bayesian. The screen map must point at the Classical one.
- find "Classical Correlation" as correlation_item
- move to {{correlation_item}}
- left-click
- wait for "Correlation Variables arrow"
  > CHECK: Correlation Variables arrow - unlabelled arrow. Needs a screen-map entry.
- for each row in "Numeric columns":
  - do "move variable" with variable="{{column}}", arrow="Correlation Variables arrow"

4. **Grouping variable:** add a computed column, for example named `eng_group`, as a nominal (text) column, with this R code: `ifelse(department == "Engineering", "Engineering", "Other")`. To add it, click the **+** after the last column header, or right-click a header and insert a computed column. The script uses the +.

- screenshot
- find button "+" as add_column
  > CHECK: + - the data grid must be visible. If the Correlation options panel covers it, the guide does not say how to close the panel.
- move to {{add_column}}
- left-click
- wait for field "Name"
  > CHECK: Name - the name field of the new-column popup. Its label or placeholder may differ.
- find field "Name" as name_field
- move to {{name_field}}
- left-click
- type "eng_group"
- screenshot
- find icon "R" as r_option
  > CHECK: R - the "computed with R code" option. It may be an icon with no text.
- move to {{r_option}}
- left-click
- screenshot
- find icon "Nominal" as nominal_option
  > CHECK: Nominal - the column-type choice. The guide says "nominal (text)", and JASP versions call it "Nominal" or "Text".
- move to {{nominal_option}}
- left-click
- screenshot
- find button "Create Column" as create_column
  > CHECK: Create Column - the confirm button of the popup.
- move to {{create_column}}
- left-click
- wait for "R code editor"
  > CHECK: R code editor - the code box above the grid has no label. It needs a screen-map entry.
- find "R code editor" as r_editor
- move to {{r_editor}}
- left-click
- type `ifelse(department == "Engineering", "Engineering", "Other")`
- screenshot
- find button "Compute column" as compute_button
  > CHECK: Compute column - the button that applies the R code.
- move to {{compute_button}}
- left-click
- wait 1 s

5. **T-Tests → Independent Samples T-Test:** use `base_salary` as the dependent variable and `eng_group` as the grouping variable.

- screenshot
- find button "T-Tests" as ttests_menu
- move to {{ttests_menu}}
- left-click
- wait for "Classical Independent Samples T-Test"
  > CHECK: Classical Independent Samples T-Test - listed under both Classical and Bayesian. The screen map must point at the Classical one.
- find "Classical Independent Samples T-Test" as ttest_item
- move to {{ttest_item}}
- left-click
- wait for "T-Test Dependent Variables arrow"
  > CHECK: T-Test Dependent Variables arrow, T-Test Grouping Variable arrow - unlabelled arrows. They need screen-map entries.
- do "move variable" with variable="base_salary", arrow="T-Test Dependent Variables arrow"
- do "move variable" with variable="eng_group", arrow="T-Test Grouping Variable arrow"
- App: JASP

6. **Regression → Linear Regression:** use `base_salary` as the dependent variable, with `years_of_service` and `performance_score` as covariates.

- screenshot
- find button "Regression" as regression_menu_again
- move to {{regression_menu_again}}
- left-click
- wait for "Classical Linear Regression"
  > CHECK: Classical Linear Regression - listed under both Classical and Bayesian. The screen map must point at the Classical one.
- find "Classical Linear Regression" as linreg_item
- move to {{linreg_item}}
- left-click
- wait for "Regression Dependent Variable arrow"
  > CHECK: Regression Dependent Variable arrow, Regression Covariates arrow - unlabelled arrows. They need screen-map entries.
- do "move variable" with variable="base_salary", arrow="Regression Dependent Variable arrow"
- do "move variable" with variable="years_of_service", arrow="Regression Covariates arrow"
- do "move variable" with variable="performance_score", arrow="Regression Covariates arrow"
- App: JASP

7. **File → Save As** → Desktop → `hr_salary_analysis.jasp`.

- screenshot
- find icon "Main menu" as main_menu_again
- move to {{main_menu_again}}
- left-click
- wait for item "Save As"
- find item "Save As" as save_as_item
- move to {{save_as_item}}
- left-click
- wait for item "Computer"
  > CHECK: Computer, Browse - assumes Save As shows the same Computer → Browse panel as Open.
- find item "Computer" as save_computer_item
- move to {{save_computer_item}}
- left-click
- wait for button "Browse"
- find button "Browse" as save_browse_button
- move to {{save_browse_button}}
- left-click
- do "save on Desktop in dialog" with filename="hr_salary_analysis.jasp"
- App: JASP
- wait for window "hr_salary_analysis.jasp" up to 30 s
  > CHECK: hr_salary_analysis.jasp - assumes JASP shows the file name in the window title.

## 4. GeoGebra Classic (sub-tasks 12–16)

1. Go to **View → Spreadsheet**. Enter the years in A1:A18 and the salaries in B1:B18, each in the same order as the CSV. The years and salaries come from the Employees table, whose row order is the CSV's.

- do "launch app" with app_name="GeoGebra Classic"
- App: GeoGebra Classic
- wait for window "GeoGebra Classic" up to 60 s
  > CHECK: GeoGebra Classic - the guide's menus match GeoGebra Classic 5. The app and window names may differ (for example "GeoGebra Classic 5").
- key-click cmd+shift+s
  > CHECK: cmd+shift+s - GeoGebra's shortcut for View → Spreadsheet. It toggles, so it assumes the spreadsheet is closed at start.
- wait for "Spreadsheet cell A1"
  > CHECK: Spreadsheet cell A1, B1, B18 - GeoGebra draws its own grid, so the cells need screen-map entries (points).
- find "Spreadsheet cell A1" as cell_a1
- move to {{cell_a1}}
- left-click
- for each row in "Employees":
  - type "{{years_of_service}}"
  - key-click enter
  > CHECK: enter - assumes Enter commits the cell and moves down one row.
- screenshot
- find "Spreadsheet cell B1" as cell_b1
- move to {{cell_b1}}
- left-click
- for each row in "Employees":
  - type "{{base_salary}}"
  - key-click enter

2. Select A1:B18, then right-click → **Create → List of Points**. This makes `l1`.

- screenshot
- find "Spreadsheet cell A1" as cell_a1_again
- move to {{cell_a1_again}}
- left-click
- screenshot
- find "Spreadsheet cell B18" as cell_b18
- move to {{cell_b18}}
- key-down shift
- left-click
- key-up shift
- right-click
- wait for item "Create"
- find item "Create" as create_item
- move to {{create_item}}
- wait for item "List of Points"
- find item "List of Points" as list_item
- move to {{list_item}}
- left-click
- wait 500 ms
- screenshot
- expect "l1" exists
  > CHECK: l1 - the Algebra view shows "l1 = {…}". This only works if `exists` matches the label as a word, not as a substring.

3. In the Input bar, type `FitLine(l1)` and press Enter to draw the regression line.

- screenshot
- find field "Input:" as input_bar
  > CHECK: Input: - the label of the Input bar in Classic 5. In Classic 6 it is a placeholder in the Algebra view.
- move to {{input_bar}}
- left-click
- type `FitLine(l1)`
  > CHECK: FitLine(l1) - the Input bar can auto-close brackets and pop up command suggestions while typing, which could change the text.
- key-click enter

4. Right-click an empty part of the graph → **Graphics…**. On the Basic tab, set xMin −1, xMax 21, yMin 0, yMax 100000. On the xAxis tab, set the label to `Years of Service`. On the yAxis tab, set the label to `Base Salary`.

- screenshot
- find "Empty graphics area" as graph_blank
  > CHECK: Empty graphics area - a point in the Graphics view with no object on it. Needs a screen-map entry (point).
- move to {{graph_blank}}
- right-click
- wait for item "Graphics ..."
  > CHECK: Graphics ... - the menu item may be written "Graphics…" (one ellipsis character) or "Graphics ...".
- find item "Graphics ..." as graphics_item
- move to {{graphics_item}}
- left-click
- wait for tab "Basic"
- find tab "Basic" as basic_tab
- move to {{basic_tab}}
- left-click
- for each row in "Graphics bounds":
  - do "set field" with field="{{field}}", value="{{value}}"
- screenshot
- find tab "xAxis" as xaxis_tab
- move to {{xaxis_tab}}
- left-click
- do "set field" with field="Label:", value="Years of Service"
- App: GeoGebra Classic
- screenshot
- find tab "yAxis" as yaxis_tab
- move to {{yaxis_tab}}
- left-click
- do "set field" with field="Label:", value="Base Salary"
- App: GeoGebra Classic

5. Check that all 18 points and the line are visible. Then go to **File → Export → Graphics View as Picture (png)** and save to the Desktop as `salary_regression_plot.png`.

- screenshot

> UNSUPPORTED: "Check that all 18 points and the line are visible." - this means counting drawn points and seeing a line on a canvas. No `expect` form in §5.9 can check that.

The guide does not close the Graphics settings window. If it stays in front, the File menu below may belong to it rather than to the main window.

- screenshot
- find menu "File" as file_menu
- move to {{file_menu}}
- left-click
- wait for item "Export"
- find item "Export" as export_item
- move to {{export_item}}
- wait for item "Graphics View as Picture (png, eps) ..."
  > CHECK: Graphics View as Picture (png, eps) ... - the guide writes "(png)". Classic 5 shows a longer label, with or without an ellipsis character.
- find item "Graphics View as Picture (png, eps) ..." as export_png_item
- move to {{export_png_item}}
- left-click
- wait for button "Save"
  > CHECK: Save - the button of GeoGebra's own export dialog, which comes before the macOS save panel. It may be labelled "Export".
- find button "Save" as export_save
- move to {{export_save}}
- left-click
- wait 1 s
- do "save on Desktop in dialog" with filename="salary_regression_plot.png"

## Routine: launch app (app_name)

Opens an application from Spotlight.

- App: Finder
- key-click cmd+space
- wait 300 ms
- type "{{app_name}}"
- wait 500 ms
- key-click enter

## Routine: new plain text document ()

Opens TextEdit, makes a new document and makes it plain text. When TextEdit starts, it may show its Open panel first. cmd+n makes a new document either way.

- do "launch app" with app_name="TextEdit"
- App: TextEdit
- wait 2 s
- key-click cmd+n
- wait for window "Untitled"
  > CHECK: Untitled - the title of a new TextEdit document. It becomes "Untitled 2" if another unsaved document is open.
- find menu "Format" as format_menu
- move to {{format_menu}}
- left-click
- wait for item "Make Plain Text"
- find item "Make Plain Text" as plain_text_item
- move to {{plain_text_item}}
- left-click

## Routine: save on Desktop in dialog (filename)

Fills in a macOS save panel that is already opening. The caller opens it and checks the result.

- wait for button "Save"
- key-click cmd+a
  > CHECK: cmd+a - assumes the name field has focus when the panel opens.
- type "{{filename}}"
- key-click cmd+shift+d
  > CHECK: cmd+shift+d - the standard "go to Desktop" shortcut in macOS file panels. Assumed to work while the name field has focus and in the collapsed panel.
- wait 500 ms
- key-click enter

## Routine: send employee (employee_id, department, base_salary, annual_bonus, years_of_service, performance_score, status_pattern)

Replaces the Postman request body with one employee's row, sends it, and records the status code. The space before the final `}` keeps it apart from the `}}` of the substitution.

- App: Postman
- screenshot
- find "Request body editor" as body_editor
  > CHECK: Request body editor - the code editor under Body → raw has no label. It needs a screen-map entry (point).
- move to {{body_editor}}
- left-click
- key-click cmd+a
- type `{"employee_id":"{{employee_id}}","department":"{{department}}","base_salary":{{base_salary}},"annual_bonus":{{annual_bonus}},"years_of_service":{{years_of_service}},"performance_score":{{performance_score}} }`
  > CHECK: body text - Postman's editor auto-closes brackets and quotes. Typing over them normally gives the right text, but this is not certain.
- key-click cmd+enter
  > CHECK: cmd+enter - Postman's Send shortcut.
- wait 3 s
- screenshot
- read "Response status" as status
  > CHECK: Response status - the screen map must return the code alone ("200"), not "200 OK". Otherwise the expect below stops the run.
- expect {{status}} matches "{{status_pattern}}"
- record employee_id={{employee_id}}, response_status={{status}} into "ApiLog"

## Routine: move variable (variable, arrow)

Moves one variable from JASP's variable list into a box, using that box's arrow.

- App: JASP
- screenshot
- find item "{{variable}}" as variable_pos
- move to {{variable_pos}}
- left-click
- screenshot
- find "{{arrow}}" as arrow_pos
- move to {{arrow_pos}}
- left-click

## Routine: set field (field, value)

Replaces the contents of one field in GeoGebra's Graphics settings.

- App: GeoGebra Classic
- screenshot
- find field "{{field}}" as field_pos
- move to {{field_pos}}
- left-click
- key-click cmd+a
- type "{{value}}"
- key-click enter
  > CHECK: enter - assumes Enter applies the value without closing the settings window.