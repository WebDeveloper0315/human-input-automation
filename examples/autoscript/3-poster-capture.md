# Classroom poster materials — capture

Sections A–D of `refer/AutoScript/3.md`, translated into AutoScript. Guide 1 is
sixty terminal commands and shows almost none of the language; this excerpt is
the opposite — Finder, Preview and a menu-bar application — so it shows what
the motor primitives look like when there is no terminal to hide behind.

Runs on: macOS

## A. Folders

App: Finder

- key-click cmd+shift+d
- wait for window "Desktop"
- screenshot
- find "empty desktop area" as empty
- move to {{empty}}
- left-click
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
> the same action with fewer places to go wrong; where the menu is wanted
> instead it is four steps - screenshot, find "File", move, left-click - and
> the same again for the item.

## B. Water cycle capture

App: Finder

- screenshot
- find "Water_cycle_diagram.png" as diagram
- move to {{diagram}}
- left-click twice
- wait for window "Water_cycle_diagram.png"

App: Greenshot

- screenshot
- find "Greenshot menu bar icon" as greenshot
- move to {{greenshot}}
- left-click
- wait 300 ms
- screenshot
- find "Capture region" as capture_region
- move to {{capture_region}}
- left-click
- wait 300 ms

Now the region itself. The two corners come from the screen map, which is where
"the diagram, without Preview's title bar and toolbar" is written down once.

- find "water cycle diagram top left" as top_left
- find "water cycle diagram bottom right" as bottom_right
- move to {{top_left}}
- press-button left
- move to {{bottom_right}}
- release-button left
- wait for "Save"

## Routine: save into Captures

Takes `filename`.

- screenshot
- find "File name" as name_field
- move to {{name_field}}
- left-click
- key-click cmd+a
- type "{{filename}}"
- key-click cmd+shift+g
- wait 300 ms
- type "~/Desktop/Classroom_Poster_Materials/Captures"
- key-click enter
- wait 400 ms
- key-click enter
- wait for window "Preview"

## B. Save it

- do "save into Captures" with filename="captured_water_cycle.png"

## C. Plant cell capture

Same again, with the other file. The guide repeats itself here; the script does
not have to.

## Routine: capture a diagram

Takes `source`, `region`, `filename`.

- App: Finder
- screenshot
- find "{{source}}" as diagram
- move to {{diagram}}
- left-click twice
- wait for window "{{source}}"
- App: Greenshot
- screenshot
- find "Greenshot menu bar icon" as greenshot
- move to {{greenshot}}
- left-click
- wait 300 ms
- screenshot
- find "Capture region" as capture_region
- move to {{capture_region}}
- left-click
- find "{{region}} top left" as top_left
- find "{{region}} bottom right" as bottom_right
- move to {{top_left}}
- press-button left
- move to {{bottom_right}}
- release-button left
- wait for "Save"
- do "save into Captures" with filename="{{filename}}"

Table: Diagrams

| source | region | filename |
|---|---|---|
| Water_cycle_diagram.png | water cycle diagram | captured_water_cycle.png |
| Plant_cell_structure.png | plant cell diagram | captured_plant_cell.png |

- for each row in "Diagrams":
  - do "capture a diagram" with source="{{source}}", region="{{region}}", filename="{{filename}}"

## D. Check resolution

App: Preview

- for each row in "Diagrams":
  - App: Finder
  - screenshot
  - find "{{filename}}" as captured
  - move to {{captured}}
  - left-click twice
  - wait for window "{{filename}}"
  - App: Preview
  - key-click cmd+i
  - wait 400 ms
  - screenshot
  - read "Image size" as size
  - expect {{size}} matches "\d+ × \d+"
  - record {{filename}}, {{size}} into "Captured sizes"
  - key-click cmd+i

The checklist in section J is then typed out of `Captured sizes`, which is the
whole reason the sizes were read into a table rather than glanced at.
