# AutoScript — a language for work steps

A specification, not yet an implementation. It exists so the work guides in
`refer/AutoScript/` can be rewritten in a form this application can run.

The program's job is to **read and perform** AutoScript. It does not write it:
a guide is turned into a script separately, by a person or an assistant, and
the result is what the program is handed. That is why this document is precise
about what is legal rather than forgiving about what might be meant — and why
§12 is written to be handed to an assistant doing the conversion.

---

## 1. What the work is

Five real guides were read end to end. They are one kind of work with different
applications bolted on.

| Guide | Applications | Steps | Data rows | Checks |
|---|---|---|---|---|
| 1 Legal cases | Terminal, psql | 15 sub-tasks, 19 command blocks | – | 12 |
| 2 Portfolio map | Coggle, Chrome, XnView | 23 | 8 | 2 |
| 3 Classroom posters | Finder, Preview, Greenshot, Posterazor, TextEdit | 32 | – | 8 |
| 4 HR analysis | TextEdit, Postman, JASP, GeoGebra | 22 | 18 | 3 |
| 5 Warehouse | GeoGebra, Trello, Spotify | 60 | 18 | 3 |

Seven properties hold across all of them, and each is a language requirement:

1. **A task is ordered stages, each in a named application.** The application
   changes often and is always stated.
2. **Every step is one of three things**: move or press something, look at the
   screen, or check what was seen.
3. **Tables carry most of the volume** — 16 Trello cards, 18 API sends, 45
   songs. Without tables and loops these documents are unmaintainable.
4. **Observed values feed later steps.** Guide 3 reads pixel sizes off an
   inspector and types them into a checklist; guide 4 reads 18 HTTP statuses
   and builds a CSV from them.
5. **Expectations are stated constantly** — `COPY 30`, `31 lines`, `at least
   128×128`, `all MATCH`. They are where a run should stop.
6. **Repetition is near-identical, not identical** — four Posterazor passes
   differing in file, orientation and width. That is a routine with parameters.
7. **Recovery is part of the work** — guide 1 names three failures and fixes.

## 2. The decision

**AutoScript is a declarative language of motor primitives, hosted in
Markdown.**

Two halves, and both matter:

*Motor primitives* because the thing performing the work is a humanoid robot,
and the script is its behaviour. A robot does not "run a command": it presses
`command`+`space`, types `t-e-r-m-i-n-a-l` one key at a time, and presses
Enter. It does not "click Save": it moves a hand along a curved path to a
point, and presses a button. The script says what the body does. Anything that
hides that — a verb that means "somehow achieve this" — is the wrong altitude
for this project.

*Markdown* because the guides are already Markdown, and its headings, fenced
blocks and tables are exactly the three data shapes this work uses. The
document stays readable as a document, reviewable in a diff, and printable as
the work instruction it also is.

### Why not something that already exists

* **Python, or any scripting language.** Ruled out on a rule this project has
  held from the start: a profile is data, and loading one can never execute
  anything. A work document is a profile. AutoScript substitutes; it never
  evaluates.
* **Robot Framework.** The closest existing fit, and rejected because its
  keywords are Python (the same problem), its column syntax is unpleasant to
  write by hand, and adopting it means adopting its runner instead of the
  engine, timing, typing style and emergency stop already built here.
* **Gherkin.** Its steps are free text bound to code by regex, so "click the
  plus" means whatever a step definition decided. This needs the opposite: a
  step that does not parse must be an error, not a guess.
* **YAML or JSON.** Machine-friendly, and hostile to whoever hand-writes 45
  songs.

## 3. The two worked examples

Both are from the request, written in AutoScript.

**Deleting a file:**

```markdown
App: Finder

- screenshot
- find "quarterly_report.pdf" as file
- move to {{file}}
- right-click
- screenshot
- find "Move to Trash" as menu_item
- move to {{menu_item}}
- left-click
```

**Opening Terminal from Spotlight:**

```markdown
App: Finder

- key-click cmd+space
- wait 300 ms
- type "terminal"
- key-click enter
- wait for window "Terminal"
```

Note what is *not* hidden. Locating is its own step and yields a position.
Moving is its own step. Clicking happens where the pointer already is, because
that is what a hand does — and it is why `left-click` takes no argument.

## 4. The primitives

### Moving and pressing

| Verb | Example | Means |
|---|---|---|
| `move to` | `move to {{file}}` · `move to 1204,640` · `move to "Save"` | Travel the pointer there along a human path |
| `left-click` | `left-click` · `left-click twice` | Press and release where the pointer is |
| `right-click` | `right-click` | |
| `middle-click` | `middle-click` | |
| `press-button` / `release-button` | `press-button left` | The two halves of a drag |
| `scroll` | `scroll down 3` · `scroll up 1` | Wheel notches |
| `type` | `type "terminal"` · `type block "cases_csv"` · `type table "Captured sizes"` | One character at a time, with this run's typing style. A table is typed as CSV |
| `key-click` | `key-click enter` · `key-click cmd+space` · `key-click ctrl+a` | One key or one chord |
| `key-down` / `key-up` | `key-down shift` | Holding a modifier across other steps |
| `wait` | `wait 300 ms` · `wait for "Save"` · `wait for window "Terminal"` | |

`move to "Save"` is shorthand for `find "Save" as _it` then `move to {{_it}}`.
It is allowed because it reads well, and it expands to the primitives — nothing
is hidden by it.

### Looking

| Verb | Example | Means |
|---|---|---|
| `screenshot` | `screenshot` | Take a fresh picture; `find` and `read` work from the most recent one |
| `find` | `find "Move to Trash" as menu_item` | Locate something, store its position |
| `read` | `read "Image size" as water_px` · `read output as result` | Store text |
| `record` | `record {{employee_id}}, {{status}} into "ApiLog"` | Append an observation to a table |

### Checking

| Verb | Example |
|---|---|
| `expect` | `expect output contains "COPY 30"` · `expect {{pages}} == 6` · `expect "Save" exists` — the full list is §5.9 |

### Structure

| Construct | Example |
|---|---|
| Task | `# Overdue case report` (one, at the top) |
| Platform | `Platform: macOS` — optional; a script for one platform is refused on another |
| Stage | `## Sub-task 4 — Create the table` |
| Application | `App: Terminal` — sticky until the next one; also allowed as a step, `- App: Finder` |
| Loop | `- for each row in "Zones":` with nested steps |
| Repeat | `- repeat 4 times:` with nested steps |
| Routine | `## Routine: save into Captures (filename, folder)`, called by `do` |
| Table | `Table: Zones` followed by a Markdown table |
| Block | `Block: cases_csv` followed by a fenced block |

## 5. Exact rules

Written for the parser, and for whoever — person or assistant — writes the
scripts it reads. Anything not allowed here is an error with a line number,
never a guess.

### 5.1 Lines

* `# ` is the task title: exactly one, first heading in the document.
* `## ` starts a stage. `## Routine: <name> (<param>, <param>)` starts a
  routine instead; the parentheses are required, empty for none.
* `App:`, `Platform:`, `Table:` and `Block:` at the start of a line are
  directives. `App:` may also be written as a step, `- App: Finder`, which is
  how a routine or a loop body changes application.
* A `-` or `*` list item is a step. **A numbered item (`1.`) is prose**: guides
  number their instructions, and keeping those lines as they were is how the
  guide survives inside the script. Every conversion so far did exactly this.
* `###` and deeper headings are prose - a heading inside a stage.
* `Table:` and `Block:` may be followed directly by their table or fenced
  block, or after blank lines.
* **Everything else is prose and is ignored** — including other `Word: value`
  lines such as `Runs on:`, `Expected:` or `Tip:`, and `>` quotes. This is what
  lets a guide's notes and warnings survive conversion untouched.
* A note for the author is never a list item. `- This lists the folder` is an
  unknown verb, `This`; write the note as a plain line or a `>` quote.

### 5.2 Nesting

`for each` and `repeat` end with a colon, and their body is the list items
nested under them — indented at least two spaces further. Bodies may nest. A
nested list anywhere else is an error, not an accident to be tolerated.

### 5.3 Arguments and escaping

| Form | For | Escaping |
|---|---|---|
| `"text"` | Names, labels, values | `\"` for a quote, `\\` for a backslash |
| `` `text` `` | Literal keystrokes and commands | Use ``` `` two backticks `` ``` to fence text that contains one |
| `{{name}}` | Substitution | `\{{` for a literal `{{` |
| `12`, `1204,640` | Counts, durations, positions | — |

Inside quotes, **only `\"` and `\\` are escapes**; a backslash before anything
else stays as written. That is what lets a pattern read as it would anywhere
else: `"\d+ × \d+"` is the regular expression `\d+ × \d+`.

Substitution happens in quoted strings, in backticked literals and in blocks.
Only `{{name}}`, where `name` is letters, digits and underscores, is
substituted — so shell braces (`{raw,exports}`) and awk's `{n++}` pass through
untouched. It is read left to right, so a substitution may sit right against a
brace: `{"score":{{score}}}` needs no space before its last `}`. An unknown
`{{name}}` is an error before anything runs.

### 5.4 Keys

`key-click`, `key-down` and `key-up` take one key or a chord joined with `+`:

* Named keys: `enter`, `tab`, `esc`, `space`, `backspace`, `delete`, `up`,
  `down`, `left`, `right`, `home`, `end`, `page_up`, `page_down`, `f1`–`f12`.
* Modifiers: `cmd`, `ctrl`, `alt` (also `option`), `shift`.
* Any single printable character: `a`, `/`, `+`.

`cmd` is Command on macOS, the Windows key on Windows and Super on Linux —
**not** Ctrl. A shortcut is therefore a fact about one platform, which is what
`Platform:` is for: `cmd+c` copies on macOS and opens something else entirely
on Windows.

### 5.5 Positions

`x,y` in the coordinate space the pointer itself uses: logical points on
macOS, which on a Retina display are half the pixels a screenshot shows. The
position picker captures in exactly this space, so a number taken from it is a
number a script can use.

### 5.6 Screenshots go stale

`find`, `read` (except `read output`), `expect "…" exists` and the label form
of `move to` all look at **the most recent screenshot**. Any step that sends
input — a click, a key, typing, a movement, a scroll — may change the screen,
so after one, that screenshot is stale.

**Using a stale screenshot is a validation error**, reported before anything
runs. Take a `screenshot`, or `wait for` something, which takes its own.

This is the rule most easily broken when converting a guide, and the one whose
failure is silent: a position read off the old screen is a real position,
pointing at the wrong thing.

How it is followed through a script:

* **A loop is checked for its second time round too.** A `find` at the top of a
  loop body may be safe the first time, because a screenshot came before the
  loop, and stale every later time, because the body's own click came after it.
* **A routine starts knowing nothing** about the screen, whoever called it.
* **A `do` leaves the screen as the routine left it.** A routine that ends with
  `wait for` hands back a current screenshot; one that ends with a click does
  not.

### 5.7 `find`

```
find [role] "label" [in window "Title"] as name
find [role] containing "part of a label" [in window "Title"] as name
```

Roles: `button`, `menu`, `item`, `field`, `checkbox`, `tab`, `icon`, `text`,
`window`. The result is the centre of what was found.

**A label matches the whole of what is on screen**, compared after three
normalisations and no others: runs of whitespace become one space, `…` and
`...` are the same, and curly quotes are the same as straight ones. Case
matters. So `"Save"` does not match `Save As…`, and `"Graphics ..."` does match
`Graphics…`.

`containing` matches part of a label instead - for text that is only partly
known in advance, such as `My Playlist #7` or a header reading
`25 songs, about 1 hr 30 min`. The same forms work in `wait for`,
`expect … exists` and `move to`.

* No match: the step fails.
* **More than one match: the step fails**, listing where each one was. Add a
  role, or a window, until only one is left. Picking one is exactly the guess
  this language exists to avoid.

### 5.8 Terminal output

`output` is the text a terminal printed since Enter was last pressed in it,
whether by `run` or by `key-click enter`. It is read from the terminal's own
text, not off a screenshot, so it is exact and does not go stale.
`read output as name` keeps it for later.

### 5.9 Every form of `expect`

| Form | Holds when |
|---|---|
| `expect output contains "t"` | The output includes `t` |
| `expect output does not contain "t"` | It does not |
| `expect output matches "pattern"` | The pattern matches anywhere in it |
| `expect "label" exists` | `find "label"` would find exactly one |
| `expect "label" does not exist` | It would find none |
| `expect {{v}} contains "t"` | The variable's text includes `t` |
| `expect {{v}} matches "pattern"` | The pattern matches anywhere in it (Python `re` syntax) |
| `expect {{v}} == "t"` · `!=` | Exact text equality |
| `expect {{v}} == 6` · `!=` `>` `>=` `<` `<=` | Numeric comparison; a value that is not a number fails |

Nothing else. There is no `and` and no `or`: two things to check are two
`expect` steps, and a failure then says which one.

### 5.10 `record`

```
record name={{value}}, other="text" into "Table"
```

Columns are named. The table is created by its first `record` and every later
one must use the same columns. It can be looped over with `for each` - once
something has been recorded into it, which the validator checks - and typed
out with `type table "Table"`: **a header row of the column names first, then
one row per record**, as CSV. A declared `Table:` never changes and cannot be
recorded into.

### 5.11 `wait`

* `wait 300 ms` · `wait 2 s`
* `wait for [role] "label" [in window "Title"] [up to 30 s]` — takes the same
  arguments as `find` (§5.7), and takes screenshots until exactly one match is
  there, for up to 10 s unless `up to` says otherwise. It leaves its last
  screenshot as the current one, so a `find` straight after it is not stale.
  Not appearing in time is a failure.
* `wait for window "Title"` — the same, for a window.

### 5.12 Terminals

`run` is legal when the current application is a terminal: `Terminal`,
`iTerm2`, `Windows Terminal`, `PowerShell`, `Command Prompt`,
`GNOME Terminal`, `Konsole` or `xterm` — or any application declared one with
`App: Warp (terminal)`.

### 5.13 Routines

* Called as `do "save into Captures" with filename="x.png", folder="Captures"`.
  Every parameter given exactly once, none extra.
* A routine may call another, never itself, directly or through others.
* A routine may change application. The application in force after `do` is
  the one the routine left, so a script that cares says `App:` again.
* **A routine sees only its parameters and the names it sets itself** - never
  its caller's. Whatever a routine needs, it is given.
* A routine that uses `run` or `output` says which terminal it is in with its
  own `- App:` step; it cannot know what its caller had open.

## 6. One piece of sugar, and its expansion

Guide 1 is sixty shell commands. Writing each as `type` + `key-click enter`
doubles its length for no gain, so:

```markdown
- run `psql -l`
```

**expands to exactly**

```markdown
- type `psql -l`
- key-click enter
```

It is legal only in a terminal (§5.12). It is sugar,
not a shortcut past the typing: the characters still go one at a time, with
this run's mistakes and pauses, because that is what the robot's hands do.

## 7. Variables

Three sources and no others: a table column inside `for each`, a routine
parameter, and `find` / `read ... as`. A position variable holds a point; a
text variable holds a string; neither can be used as the other.

A name must be set before the step that uses it. Names set in one stage are
there in the next, and a name set inside a loop is there after it.

There is no arithmetic and no expression language. Where a guide needs a
computed number it already writes the number, and so does the script.

## 8. Finding things on screen

`find "Move to Trash"` is the hard part. Four ways to turn a name into a point,
cheapest and most reliable first:

1. **The accessibility tree.** macOS `AXUIElement`, Windows UI Automation,
   AT-SPI on Linux. Real element names, roles and rectangles — exact, no
   guessing, no model. Covers native applications and Chrome. This application
   already requires macOS Accessibility permission for input, so on the machine
   this work runs on it is already granted.
2. **Text on screen.** Screenshot, OCR, match the label, take the middle of its
   box. Local and small. This is what covers applications that draw their own
   interface: **Coggle and GeoGebra have no button called "+" to ask about.**
3. **A picture of the element.** Template matching, for things with no text at
   all: a menu-bar icon, a hover-plus, a download arrow.
4. **A vision-language model.** Last, not first: slowest, largest, least
   predictable, and the only one that can answer "which of these is the colour
   picker" when the other three cannot.

**Most of this work needs no model.** Guide 1 is tiers 1–2 entirely. A wizard
like Posterazor is tier 1. The model earns its place on canvas applications and
on reading unstructured screens, not on every click.

### The screen map

Names resolve through a per-application **screen map** kept beside the script:
`"Large-Cap"` → how to find it. An entry can be an accessibility query, text to
OCR for, a reference image, or a point captured with the position picker. The
per-application mess lives there, so the script stays about the work.

## 9. When a step fails

Nothing is best-effort. A step that cannot find its target, or an `expect` that
does not hold, stops the run at that step and reports which line of which
document failed and what was on screen. The engine's emergency stop applies
throughout, unchanged.

Version 1 stops. Recovery — guide 1's three named failures — needs a `when`
conditional, and waits until the straight-line case is solid.

## 10. What it cannot do, on purpose

* No arithmetic, no expressions, no branching in v1, no user-defined verbs.
* No code execution. `run` types a command into a terminal window; it never
  hands a string to a shell from inside this process. Everything the
  application does stays synthetic input that the user started and can stop,
  and a document stays data.
* Because `run` types real commands, a document is as dangerous as the commands
  in it. Every run has a dry run that prints every keystroke first, and that is
  the intended way to use this, not advice.

## 11. Checking a script

```
human-input-automation --check-script examples/autoscript/*.md
```

Reads and validates each file against everything in §5, and runs nothing. Each
problem is printed as `file:line: severity: code: message`, so an editor can
jump to it; every `> UNSUPPORTED:` note is listed; and the number of `> CHECK:`
notes is given, since those are the labels to confirm in the real application
before a run. The exit status is 1 if any file has an error.

## 12. Converting a guide into AutoScript

For whoever — person or assistant — turns a guide into a script.

1. **One stage per sub-task**, keeping the guide's own heading text.
2. **State the application** whenever it changes, before the first step that
   needs it.
3. **Write what the body does, not what the user means.** "Right-click the file
   and choose Move to Trash" is six steps: screenshot, find, move, right-click,
   find, move, left-click. Never one.
4. **Take a fresh `screenshot` after any input and before the next `find` or
   `read`** (§5.6). Not "after anything that changes the screen" - after
   anything that *could*. The validator enforces it; do not make it.
5. **Turn every stated expectation into an `expect`.** "Expected: COPY 30"
   becomes `expect output contains "COPY 30"`. These are the stopping points;
   a script without them fails silently.
6. **Turn every table into a `Table:` and a `for each`.** If the guide says
   "repeat for the other 7", the table has 8 rows.
7. **Turn near-identical repetition into a `## Routine:`** called with
   parameters. Four Posterazor passes are one routine, not four stages.
8. **Keep the prose.** Anything that is not a directive, a step, a table or a
   block is ignored by the parser, so the notes and warnings that make a guide
   readable should survive into the script.
9. **Use `run` only in a terminal.** Everywhere else, `type` and `key-click`.
10. **Disambiguate `find`** (§5.7) with a role or a window whenever a label
    could appear twice. "File" is a menu, a column header and a word in a
    document all at once.
11. **Never use a list item for a note.** Every `-` line is a step; notes are
    plain lines or `>` quotes. Keep the guide's own numbered lines as they are:
    numbered lines are prose (§5.1).
12. **Use `containing`** (§5.7) when only part of a label is known in advance.
13. **Run `--check-script`** (§11) on the result, and fix what it reports.
14. **Invent nothing.** If a step cannot be written with the verbs in §4, leave
    the guide's sentence in as prose and say so — a missing verb is a
    conversation about the language, not a reason to guess.
