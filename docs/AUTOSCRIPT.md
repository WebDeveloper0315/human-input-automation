# AutoScript — a language for work steps

A proposal, not yet an implementation. It exists so the work guides in
`refer/AutoScript/` can be rewritten in a form this application can run, and so
that form can be argued with *before* a parser is built to it.

---

## 1. What the work actually is

Five real guides were read end to end. They are not five different kinds of
work; they are one kind of work with different applications bolted on.

| Guide | Applications | Steps | Code blocks | Data tables (rows) | Checks | "repeat…" |
|---|---|---|---|---|---|---|
| 1 Legal cases | Terminal, psql | 15 sub-tasks | 19 | – | 12 stated expectations | 3 near-identical awk lines |
| 2 Portfolio map | Coggle (canvas), Chrome, XnView | 23 | – | 1 (8) | 2 | 6 |
| 3 Classroom posters | Finder, Preview, Greenshot, Posterazor, TextEdit | 32 | 1 | – | 8 | 4 wizard passes |
| 4 HR analysis | TextEdit, Postman, JASP, GeoGebra | 22 | 1 | – (18 inline) | 3 | 18 API sends |
| 5 Warehouse | GeoGebra, Trello, Spotify | 60 | – | 2 (18) | 3 | 16 cards, 45 songs |

Seven properties hold across all five:

1. **A task is an ordered list of stages, each in a named application.** The
   application changes often and is always stated. It is the primary context;
   everything else is relative to it.
2. **Three kinds of step, and only three.** Send input (type, press, click,
   drag); observe something on screen; assert that what was observed is what
   was expected.
3. **Tables drive most of the volume.** 8 branches × 4 children, 8 zones, 16
   cards, 18 employees, 45 songs. Writing those out step by step would be
   thousands of lines nobody will maintain. Tables and loops are not a
   convenience here, they are the difference between a usable document and an
   unusable one.
4. **Observed values feed later steps.** Guide 3 reads pixel dimensions off an
   inspector and types them into a checklist. Guide 4 reads an HTTP status per
   request and builds a CSV out of 18 of them. Without variables, those
   deliverables cannot be produced at all.
5. **Expectations are stated constantly** — `COPY 30`, `UPDATE 8`, "31 lines",
   "at least 128×128", "all MATCH". They are the author already telling us
   where the work can go wrong. They are the natural place to stop.
6. **Repetition is near-identical, not identical.** Four Posterazor passes
   differing in file, orientation and width. Three awk lines differing in a
   name. That is a routine with parameters, not copy-paste.
7. **Recovery is part of the work.** Guide 1 ends with three named failures and
   what to do about each.

A language that has applications, ordered steps, a closed verb set, variables,
tables, loops, parameterised routines, observation and assertions covers all
five guides. A language missing any one of them does not.

## 2. The decision

**AutoScript is a small declarative language hosted inside Markdown.**

The container is ordinary Markdown — the guides are already Markdown, and its
headings, fenced blocks and tables are exactly the three data shapes the work
uses. Inside that, each step is one list item with a defined grammar and a
closed set of about twenty verbs.

### Why not something that already exists

* **Python, or any scripting language.** Ruled out on a rule this project
  already holds: a profile is data, and loading one can never execute anything
  (`docs/PROFILE-FORMAT.md`). A work document that is a program means a
  document that can do anything the moment it is opened. AutoScript is data all
  the way down: substitution, never evaluation.
* **Robot Framework.** The closest existing fit — keyword-driven, tabular,
  variables, readable. Rejected for three reasons: its keywords are Python, so
  it reintroduces exactly the execution model above; its column-separated
  syntax is unpleasant to hand-write; and adopting it would mean adopting its
  runner rather than the engine, timing and emergency stop already built here.
* **Gherkin.** Human-readable and has example tables, but its steps are free
  text bound to code by regex. "Click the plus" would mean whatever a step
  definition decided it meant. This work needs the opposite: a step that does
  not parse should be an error, not a guess.
* **YAML or JSON.** Machine-friendly and hostile to the person writing 45 songs
  by hand. The author of these guides writes prose documents; asking for three
  levels of significant indentation per step is asking them to stop.

### Why Markdown specifically

The guides are already in it, so translation is rewriting lines rather than
changing medium. A stage is an `##` heading. A literal to type is a fenced
block — which is how guide 1 already writes its SQL. A data table is a Markdown
table — which is how guides 2 and 5 already write theirs. And the document
stays a document: readable by a person who has never seen this spec, reviewable
in a diff, printable as the work instruction it also is.

## 3. The shape of a document

````markdown
# Overdue case report

Runs on: macOS
Recorded: yes

## Prepare the database

App: Terminal

- run `brew services list | grep postgres`
- expect output contains "postgres"
- run `mkdir -p ~/Documents/legal_data/{raw,exports,summaries,backups}`
- run `cd ~/Documents/legal_data`

## Import the cases

Block: cases_csv

```
case_id,case_name,attorney
1,Harborline Logistics v. Meridian Corp,Priya Shah
```

- run `cat > raw/cases_raw.csv <<'EOF'`
- type block "cases_csv"
- run `EOF`
- run `wc -l raw/cases_raw.csv`
- expect output contains "31"
````

`# ` is the task. `## ` is a stage. `App:` sets the application for the steps
that follow it and stays in force until the next one. A list item is a step.
Anything that is not a directive, a step, a table or a block is prose, and is
ignored — so the notes and tips that make a guide readable survive translation.

## 4. Steps

| Verb | Example | Notes |
|---|---|---|
| `open` | `open "https://coggle.it"` | URL, file path, or application |
| `type` | `type "Portfolio Strategy 2024"` | Goes through the run's typing style |
| `type block` | `type block "cases_csv"` | A fenced block by name |
| `press` | `press enter` · `press cmd+s` | Named keys and chords |
| `run` | ``run `psql -l` `` | Type it and press Enter. Terminal apps only |
| `click` | `click "New Diagram"` · `click button "Send"` · `click menu "File > New Folder"` | Optional role: button, menu, tab, icon, field |
| `double-click` | `double-click "Water_cycle_diagram.png"` | |
| `right-click` | `right-click "{{Branch}}"` | |
| `hover` | `hover "centre node"` | Reveals the controls Coggle only shows on hover |
| `drag` | `drag "stock chart.png" to "Large-Cap"` · `drag region around "diagram"` | |
| `set` | `set "Width" to 594` | A labelled field |
| `choose` | `choose "PNG" from "Format"` | Dropdown, radio group, colour picker |
| `tick` / `untick` | `tick "Std. deviation"` | Checkboxes. Not `check`, which reads as an assertion |
| `read` | `read "Image size" as water_px` | Names what was seen |
| `record` | `record {{employee_id}}, {{status}} into "ApiLog"` | Appends an observation to a table |
| `wait` | `wait for "Save"` · `wait 2 s` | |
| `expect` | `expect output contains "COPY 30"` · `expect {{pages}} == 6` | |
| `do` | `do "save as" with name="x.pdf", folder="Print_PDFs"` | Calls a routine |
| `for each` | `for each row in "Zones":` | Indented steps below it |
| `repeat` | `repeat 4 times:` | Indented steps below it |

Arguments are `"quoted"` for labels and values, `` `backticked` `` for literal
text to send, `{{name}}` for substitution, and bare numbers. The keywords
(`to`, `from`, `as`, `in`, `with`, `contains`, `times`) are fixed.

## 5. Tables, blocks, routines, variables

**Tables** are Markdown tables introduced by `Table: <name>`. Columns become
variables inside a `for each`:

```markdown
Table: Zones

| Zone | Size | Area | Capacity |
|---|---|---|---|
| A Bulk Storage North | 12×8 | 96 | 38 |
| B Bulk Storage South | 10×9 | 90 | 36 |

- for each row in "Zones":
  - click menu "Text"
  - type "Area: {{Area}} sq m, Capacity: {{Capacity}} pallets"
```

**Blocks** are fenced blocks introduced by `Block: <name>`, typed verbatim by
`type block`. Substitution applies inside them, which is what makes guide 4's
eighteen API bodies one block instead of eighteen.

**Routines** are `## Routine: <name>` stages with named parameters, called with
`do`. Guide 3's four Posterazor passes are one routine called four times; guide
1's three awk lines are one routine called three times.

**Variables** come from three places and nowhere else: a table column inside a
loop, a routine parameter, and `read ... as`. There is no arithmetic and no
expression language. If a document needs a number computed, the author writes
the number — as these guides already do.

## 6. Finding things on screen

`click "New Diagram"` is the whole problem. Four ways to resolve a name to a
point, cheapest and most reliable first:

1. **The accessibility tree.** macOS `AXUIElement`, Windows UI Automation,
   AT-SPI on Linux. Gives real element names, roles and rectangles. Exact, no
   guessing, no model. It covers native applications and Chrome, which exposes
   its tree to assistive technology. This application already requires macOS
   Accessibility permission for input, so on the machine this work runs on the
   permission is already granted.
2. **Text on screen.** Screenshot, OCR, match the label, click the middle of
   its box. Local and small — Tesseract is already installed on this machine;
   RapidOCR or PaddleOCR-ONNX are better on UI text and still tens of
   megabytes. This is what covers canvas applications that expose nothing:
   **Coggle and GeoGebra draw their nodes; there is no button called "+" to
   find.**
3. **A picture of the element.** Template matching for things with no text at
   all: the Greenshot menu-bar icon, Coggle's hover-plus, a download arrow.
   Deterministic and fast.
4. **A vision-language model.** Last, not first. Slowest, largest, least
   predictable, and the only one that can answer "which of these is the colour
   picker" when the other three fail.

The important claim: **most of this work does not need a model.** A terminal
task is entirely tiers 1-2. A wizard like Posterazor is tier 1. The model earns
its place on canvas applications and on reading unstructured screens, not on
every click.

### The screen map

Names in a document are resolved through a per-application **screen map** that
lives beside it: `"Large-Cap"` → how to find it. An entry can be an
accessibility query, a piece of text to OCR for, a reference image, or a point
captured with the position picker built for that purpose. This is where the
per-application mess is confined, so the document stays about the work.

## 7. When a step fails

Nothing is best-effort. A step that cannot find its target, or an `expect` that
does not hold, stops the run at that step and reports which line of which
document failed and what was on screen at the time. The engine's existing
emergency stop applies throughout, unchanged.

Version 1 stops. Recovery — guide 1's three named failures — needs a `when`
conditional and is deliberately deferred until the straight-line case is solid.

## 8. What it cannot do, on purpose

* No arithmetic, no expressions, no branching in v1, no user-defined verbs.
* No code execution. `run` types a command into a terminal window; it never
  hands a string to a shell from inside this process. The distinction matters:
  everything this application does remains synthetic input that the user
  started and can stop, and a document remains data.
* Because `run` types real commands, a document is as dangerous as the commands
  in it. Every run has a dry run that prints every command and every keystroke
  first, and that is not optional advice — it is the intended way to use this.
