# Classroom poster materials — capture

Sections A–D of `refer/AutoScript/3.md`, translated into AutoScript. Guide 1 is
sixty terminal commands and shows almost none of the language; this excerpt is
the opposite — Finder, Preview and a menu-bar application — so it shows what
the motor primitives look like when there is no terminal to hide behind.

Every `find` below comes after a `screenshot` or a `wait for` with no input in
between (§5.6), and every name that could appear twice on screen carries a role
or a window (§5.7).

Platform: macOS

## A. Folders

App: Finder

- key-click cmd+shift+d
- wait for window "Desktop"
- key-click cmd+shift+n
- wait 400 ms
- type "Classroom_Poster_Materials"
- key-click enter
- key-click cmd+down
- wait for window "Classroom_Poster_Materials"
- key-click cmd+shift+n
- wait 400 ms
- type "Captures"
- key-click enter
- key-click cmd+shift+n
- wait 400 ms
- type "Print_PDFs"
- key-click enter

> The guide says "Use Finder > File > New Folder". The keyboard equivalent is
> the same action with fewer places to go wrong. Where the menu is wanted
> instead, it is: screenshot, `find menu "File"`, move, left-click, then the
> same again for `find item "New Folder"`.

## Routine: save into Captures (filename)

Greenshot's save dialog, reached after a region has been captured.

- wait for field "File name"
- find field "File name" as name_field
- move to {{name_field}}
- left-click
- key-click cmd+a
- type "{{filename}}"
- key-click cmd+shift+g
- wait for field "Go to the folder"
- type "~/Desktop/Classroom_Poster_Materials/Captures"
- key-click enter
- wait 400 ms
- key-click enter
- wait for window "Preview"

## Routine: capture a diagram (source, region, filename)

Opens `source` in Preview, captures `region` with Greenshot and saves it. The
two corners of each region come from the screen map, which is where "the
diagram, without Preview's title bar and toolbar" is written down once.

- App: Finder
- screenshot
- find item "{{source}}" in window "Desktop" as diagram
- move to {{diagram}}
- left-click twice
- wait for window "{{source}}"
- App: Greenshot
- screenshot
- find icon "Greenshot" as greenshot
- move to {{greenshot}}
- left-click
- wait for item "Capture region"
- find item "Capture region" as capture_region
- move to {{capture_region}}
- left-click
- wait 300 ms
- screenshot
- find "{{region}} top left" as top_left
- find "{{region}} bottom right" as bottom_right
- move to {{top_left}}
- press-button left
- move to {{bottom_right}}
- release-button left
- do "save into Captures" with filename="{{filename}}"

## B–C. Capture both diagrams

The guide writes sections B and C out twice, differing only in three names.

Table: Diagrams

| source | region | filename |
|---|---|---|
| Water_cycle_diagram.png | water cycle diagram | captured_water_cycle.png |
| Plant_cell_structure.png | plant cell diagram | captured_plant_cell.png |

- for each row in "Diagrams":
  - do "capture a diagram" with source="{{source}}", region="{{region}}", filename="{{filename}}"

## D. Check resolution

- for each row in "Diagrams":
  - App: Finder
  - key-click cmd+shift+g
  - wait for field "Go to the folder"
  - type "~/Desktop/Classroom_Poster_Materials/Captures"
  - key-click enter
  - wait for window "Captures"
  - find item "{{filename}}" in window "Captures" as captured
  - move to {{captured}}
  - left-click twice
  - wait for window "{{filename}}"
  - App: Preview
  - key-click cmd+i
  - wait for text "Image size"
  - read "Image size" as size
  - expect {{size}} matches "\d+ × \d+"
  - record file={{filename}}, size={{size}} into "Captured sizes"
  - key-click cmd+i

The checklist in section J is typed out of `Captured sizes` with
`type table "Captured sizes"` — which is the whole reason the sizes were read
into a table rather than glanced at.
