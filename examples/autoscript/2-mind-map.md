# Portfolio Strategy 2024 mind map

Platform: macOS

This script assumes Coggle is already open and signed in, in the only tab of a
Chrome window, and that XnView MP is installed.

## Routine: add node (parent, label)

Coggle draws its own interface. The "+" appears only while the pointer is over a node.

- screenshot
- find item "{{parent}}" as parent_node
> CHECK: {{parent}} - for "Portfolio Strategy 2024", Coggle also shows the diagram name in its header and in the Chrome tab title, so the screen map entry must be limited to the canvas
- move to {{parent_node}}
- wait for icon "Add branch +"
> CHECK: Add branch + - the hover "+" has no text; it needs a reference image, and the centre node may show more than one "+"
- find icon "Add branch +" as plus
- move to {{plus}}
- left-click
- wait 300 ms
- type "{{label}}"
- key-click enter
> CHECK: enter - not confirmed that Enter ends node editing in Coggle rather than adding a line break or a sibling node
- wait for item "{{label}}"

## Routine: colour node (label, colour)

- screenshot
- find item "{{label}}" as target
- move to {{target}}
- right-click
- wait for icon "Colour {{colour}}"
> CHECK: Colour {{colour}} - Coggle's swatches have no text, so each colour needs a reference image. Also not confirmed that right-click opens the colour menu, or that the palette has teal, brown, magenta, light green and navy
- find icon "Colour {{colour}}" as swatch
- move to {{swatch}}
- left-click
- wait 300 ms

## Routine: download icon (node, query)

- screenshot
- find field "Search" as search_box
> CHECK: Search - SVG Repo's search box placeholder may read "Search..." or "Search SVG vectors"
- move to {{search_box}}
- left-click
- key-click cmd+a
- type "{{query}}"
- key-click enter
- wait for item "First search result" up to 20 s
> CHECK: First search result - there is no fixed text for this; the screen map must define it as a position or region
- find item "First search result" as result
- move to {{result}}
- left-click
- wait for button "Download PNG" up to 20 s
> CHECK: Download PNG - not confirmed that SVG Repo icon pages have a PNG button, or what it is called
> UNSUPPORTED: "Pick PNG if the icon page offers it." - AutoScript v1 has no branching, so the script always picks PNG and stops if there is no PNG button.
> UNSUPPORTED: "choose 256 or 512 px if a size option appears." - this is also conditional; no size is chosen, and the size is checked later in XnView.
- find button "Download PNG" as png_button
- move to {{png_button}}
- left-click
- App: Chrome
- wait for text "Download bubble file name" up to 30 s
> CHECK: Download bubble file name - Chrome's download bubble, top right; its layout differs between Chrome versions
- read "Download bubble file name" as file
- record node="{{node}}", file={{file}} into "IconFiles"

## Routine: check icon (file)

- screenshot
- find item "{{file}}" in window "XnView MP" as thumbnail
- move to {{thumbnail}}
- left-click twice
- wait 1 s
- wait for text "Status bar image size" up to 10 s
> CHECK: Status bar image size - the region of XnView MP's status bar that shows the size in viewer mode, for example "512x512x32"
- read "Status bar image size" as size
- expect {{size}} matches "(?<![0-9])(12[89]|1[3-9][0-9]|[2-9][0-9]{2}|[1-9][0-9]{3,}) *[x×] *(12[89]|1[3-9][0-9]|[2-9][0-9]{2}|[1-9][0-9]{3,})(?![0-9])"
> UNSUPPORTED: "Confirm each ... looks clear." - no verb judges visual quality.
- key-click esc
> CHECK: esc - not confirmed that Esc closes XnView MP's viewer and returns to the browser
- wait 500 ms

## Routine: attach icon (node, file)

Finder's Downloads window and the Coggle canvas must both be visible, side by side, for the drag to work.

- App: Finder
- key-click cmd+option+l
- wait for window "Downloads"
- find item "{{file}}" in window "Downloads" as icon_file
- find item "{{node}}" as node_target
> CHECK: {{node}} - the Coggle node must not be covered by the Finder window, and it is found while Finder is the current application
- move to {{icon_file}}
- press-button left
- move to {{node_target}}
- release-button left
- wait 2 s

## Steps 1–9: Build the mind map in Coggle

App: Coggle

- screenshot
- find button "New Diagram" as new_diagram
> CHECK: New Diagram - the Coggle dashboard button may read "Create Diagram" or "+ New Diagram"
- move to {{new_diagram}}
- left-click
- wait for item "Central node" up to 15 s
> CHECK: Central node - a blank diagram's centre node may show placeholder text or none; the screen map must define it
- find item "Central node" as centre
- move to {{centre}}
- left-click
- wait 300 ms
- type "Portfolio Strategy 2024"
- key-click enter
> CHECK: enter - same as in "add node": not confirmed that Enter ends editing
- wait for item "Portfolio Strategy 2024"
> CHECK: Portfolio Strategy 2024 - may match twice (canvas and header)

Colours: right-click a node, or use its colour/palette option, and pick the colour. This script uses right-click. The branch takes the branch colour, and each child takes its own colour.

Table: Branches

| branch | colour |
|---|---|
| Large-Cap Equities | blue |
| Growth Equities | purple |
| Fixed Income | teal |
| Real Estate | orange |
| International | brown |
| Alternatives | magenta |
| Cash & Equivalents | light green |
| Retirement Accounts | navy |

- for each row in "Branches":
  - do "add node" with parent="Portfolio Strategy 2024", label="{{branch}}"
  - do "colour node" with label="{{branch}}", colour="{{colour}}"

Table: Children

| branch | child | colour |
|---|---|---|
| Large-Cap Equities | Apple AAPL | green |
| Large-Cap Equities | Microsoft MSFT | green |
| Large-Cap Equities | Johnson & Johnson JNJ | green |
| Large-Cap Equities | Procter & Gamble PG | green |
| Growth Equities | NVDA | red |
| Growth Equities | TSLA | red |
| Growth Equities | AMZN | yellow |
| Growth Equities | META | yellow |
| Fixed Income | Treasury | green |
| Fixed Income | Municipal | green |
| Fixed Income | Corporate Bond ETF | yellow |
| Fixed Income | High Yield | red |
| Real Estate | REIT Index | yellow |
| Real Estate | RE ETF | yellow |
| Real Estate | Rental | red |
| Real Estate | Crowdfunded RE | red |
| International | Developed ETF | yellow |
| International | European Blue Chips | yellow |
| International | Emerging ETF | red |
| International | Asian Growth | red |
| Alternatives | Gold ETF | yellow |
| Alternatives | Commodities | yellow |
| Alternatives | Bitcoin | red |
| Alternatives | Private Equity | red |
| Retirement Accounts | 401k | green |
| Retirement Accounts | HSA | green |
| Retirement Accounts | Roth IRA | yellow |
| Retirement Accounts | SEP IRA | yellow |

> UNSUPPORTED: "Cash & Equivalents | light green | all 4 children green" - the guide never names the four children, so there is no text to type. Add four rows to "Children" once the names are known.

- for each row in "Children":
  - do "add node" with parent="{{branch}}", label="{{child}}"
  - do "colour node" with label="{{child}}", colour="{{colour}}"

## Steps 10–17: Download 8 icons from SVG Repo

Pick PNG if the icon page offers it. Coggle accepts PNG/JPG images more reliably than SVG. The task also asks for at least 128×128 pixels, so choose 256 or 512 px if a size option appears. All 8 files go to Downloads, Chrome's default download folder.

App: Chrome

- key-click cmd+t
- key-click cmd+l
- type "svgrepo.com"
- key-click enter
- wait for field "Search" up to 20 s

Table: Icons

| node | query |
|---|---|
| Large-Cap Equities | stock chart |
| Growth Equities | upward trend |
| Fixed Income | certificate |
| Real Estate | building |
| International | globe |
| Alternatives | diamond |
| Cash & Equivalents | wallet |
| Retirement Accounts | piggy bank |

- for each row in "Icons":
  - do "download icon" with node="{{node}}", query="{{query}}"

Close the SVG Repo tab so the Coggle tab is showing again.

- App: Chrome
- key-click cmd+w
- App: Coggle
- wait for item "Portfolio Strategy 2024" up to 10 s
> CHECK: cmd+w - assumes Coggle is the only other tab, so closing SVG Repo shows it

## Step 18: Check the icons in XnView

The size shows in the status bar or under Image > Properties. This script reads the status bar.

App: Finder

- key-click cmd+space
- wait 300 ms
- type "XnView MP"
- key-click enter
- wait for window "XnView MP" up to 20 s
> CHECK: XnView MP - the window title may include the current folder path

App: XnView MP

- screenshot
- find item "Downloads" in window "XnView MP" as downloads
> CHECK: Downloads - XnView MP's folder tree may name it differently, for example under the user's home folder
- move to {{downloads}}
- left-click
- wait 1 s
- for each row in "IconFiles":
  - do "check icon" with file="{{file}}"

## Steps 19–21: Attach the icons in Coggle

Drag each icon file from Finder onto its node. The node's image option, a file upload, is the guide's other method and is not used here. Before this stage, arrange Finder and Chrome side by side so no node is covered.

- for each row in "IconFiles":
  - do "attach icon" with node="{{node}}", file="{{file}}"

## Steps 22–25: Finish and export

Add a 9th branch called Legend, with 3 children. The guide gives no colour for the Legend branch itself, so it keeps Coggle's default.

App: Coggle

- do "add node" with parent="Portfolio Strategy 2024", label="Legend"

Table: Legend

| entry | colour |
|---|---|
| Low Risk — green | green |
| Medium Risk — yellow | yellow |
| High Risk — red | red |

- for each row in "Legend":
  - do "add node" with parent="Legend", label="{{entry}}"
  - do "colour node" with label="{{entry}}", colour="{{colour}}"

> UNSUPPORTED: "Drag the nodes into a clean circle around the centre so no labels overlap." - the guide gives no target positions, and no verb can judge overlap.

- screenshot
- find icon "Download" as download_icon
> CHECK: Download - Coggle's top-right download control is an icon with no text; it needs a reference image
- move to {{download_icon}}
- left-click
- wait for item "PNG"
> CHECK: PNG - the menu entry may read "Download as PNG image"
- find item "PNG" as png_item
- move to {{png_item}}
- left-click
- App: Chrome
- wait for text "Download bubble file name" up to 60 s
- read "Download bubble file name" as png_file

Rename the file to Portfolio_Strategy_2024.png and move it to the Desktop. Finder preselects the name without its extension, so the extension is kept.

App: Finder

- key-click cmd+option+l
- wait for window "Downloads"
- find item "{{png_file}}" in window "Downloads" as png_icon
- move to {{png_icon}}
- left-click
- key-click enter
- wait 300 ms
- type "Portfolio_Strategy_2024"
- key-click enter
- wait 500 ms
- key-click cmd+c
- key-click cmd+shift+d
- wait for window "Desktop"
- key-click cmd+option+v
- wait for item "Portfolio_Strategy_2024.png" in window "Desktop"
> CHECK: Portfolio_Strategy_2024.png - if Finder hides extensions, the label shows without ".png"

Open the PNG in XnView and check that every label is readable and the colours are visible.

App: XnView MP

- key-click cmd+o
- wait for button "Open"
> CHECK: Open - not confirmed that XnView MP uses cmd+o and the standard macOS open dialog
- key-click cmd+shift+g
- wait 500 ms
- type "~/Desktop/Portfolio_Strategy_2024.png"
- key-click enter
- wait 500 ms
- key-click enter
- wait 2 s
- screenshot
- expect "Portfolio Strategy 2024" exists
> CHECK: Portfolio Strategy 2024 - the title bar shows "Portfolio_Strategy_2024.png", and OCR may read that as a second match
- for each row in "Branches":
  - expect "{{branch}}" exists
- for each row in "Children":
  - expect "{{child}}" exists
- expect "Legend" exists
- for each row in "Legend":
  - expect "{{entry}}" exists

> UNSUPPORTED: "check that ... the colours are visible." - no verb checks colour.