# AutoScript — a language for work steps

A specification, not yet an implementation. It exists so the work guides in
`refer/AutoScript/` can be rewritten in a form this application can run.

The program's job is to **read and perform** AutoScript. It does not write it:
a guide is turned into a script separately, by a person or an assistant, and
the result is what the program is handed. That is why this document is precise
about what is legal rather than forgiving about what might be meant — and why
§10 is written to be handed to an assistant doing the conversion.

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
| `type` | `type "terminal"` · `type block "cases_csv"` | One character at a time, with this run's typing style |
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
| `expect` | `expect output contains "COPY 30"` · `expect {{pages}} == 6` · `expect "Save" exists` |

### Structure

| Construct | Example |
|---|---|
| Task | `# Overdue case report` (one, at the top) |
| Stage | `## Sub-task 4 — Create the table` |
| Application | `App: Terminal` — sticky until the next one |
| Loop | `for each row in "Zones":` with indented steps |
| Repeat | `repeat 4 times:` with indented steps |
| Routine | `## Routine: save as` with `{{parameters}}`, called by `do` |
| Table | `Table: Zones` followed by a Markdown table |
| Block | `Block: cases_csv` followed by a fenced block |

Arguments are `"quoted"` for names and values, `` `backticked` `` for literal
text to send, `{{name}}` for substitution, bare numbers for counts and
coordinates. The keywords (`to`, `as`, `in`, `from`, `with`, `contains`,
`times`, `exists`) are fixed.

## 5. One piece of sugar, and its expansion

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

It is legal only when the current `App:` is declared a terminal. It is sugar,
not a shortcut past the typing: the characters still go one at a time, with
this run's mistakes and pauses, because that is what the robot's hands do.

## 6. Variables

Three sources and no others: a table column inside `for each`, a routine
parameter, and `find` / `read ... as`. A position variable holds a point; a
text variable holds a string.

There is no arithmetic and no expression language. Where a guide needs a
computed number it already writes the number, and so does the script.

## 7. Finding things on screen

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

## 8. When a step fails

Nothing is best-effort. A step that cannot find its target, or an `expect` that
does not hold, stops the run at that step and reports which line of which
document failed and what was on screen. The engine's emergency stop applies
throughout, unchanged.

Version 1 stops. Recovery — guide 1's three named failures — needs a `when`
conditional, and waits until the straight-line case is solid.

## 9. What it cannot do, on purpose

* No arithmetic, no expressions, no branching in v1, no user-defined verbs.
* No code execution. `run` types a command into a terminal window; it never
  hands a string to a shell from inside this process. Everything the
  application does stays synthetic input that the user started and can stop,
  and a document stays data.
* Because `run` types real commands, a document is as dangerous as the commands
  in it. Every run has a dry run that prints every keystroke first, and that is
  the intended way to use this, not advice.

## 10. Converting a guide into AutoScript

For whoever — person or assistant — turns a guide into a script.

1. **One stage per sub-task**, keeping the guide's own heading text.
2. **State the application** whenever it changes, before the first step that
   needs it.
3. **Write what the body does, not what the user means.** "Right-click the file
   and choose Move to Trash" is six steps: screenshot, find, move, right-click,
   find, move, left-click. Never one.
4. **Take a fresh `screenshot` after anything that changes the screen** — a
   click that opens a menu, a window that appears — and before the `find` that
   depends on it.
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
10. **Invent nothing.** If a step cannot be written with the verbs in §4, leave
    the guide's sentence in as prose and say so — a missing verb is a
    conversation about the language, not a reason to guess.
