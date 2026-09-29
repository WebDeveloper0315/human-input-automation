# Warehouse reorganization: zones, Trello board and shift playlists

Platform: macOS

## Part 1: GeoGebra (about 15 min)

Open GeoGebra Classic, choose Geometry, and turn on the grid.

- do "open app from Spotlight" with app_name="GeoGebra Classic", window_title="GeoGebra Classic"
  > CHECK: GeoGebra Classic - the Spotlight name and window title may include the version, e.g. "GeoGebra Classic 6"
- App: GeoGebra Classic
- screenshot
- find icon "Main menu" as main_menu
  > CHECK: Main menu - the hamburger button has no visible text; its accessibility name is a guess, and it may need a reference image in the screen map
- move to {{main_menu}}
- left-click
- screenshot
- find menu "Perspectives" as perspectives
  > CHECK: Perspectives - the menu entry name in GeoGebra Classic 6 is from memory
- move to {{perspectives}}
- left-click
- screenshot
- find item "Geometry" as geometry
- move to {{geometry}}
- left-click
- wait 1 s

Geometry hides the Algebra view, which holds the Input field. The steps below show it, so that the grid, the zones and the text can be typed in exactly.

- screenshot
- find icon "Main menu" as main_menu_again
- move to {{main_menu_again}}
- left-click
- screenshot
- find menu "View" as view_menu
- move to {{view_menu}}
- left-click
- screenshot
- find checkbox "Algebra" as algebra_view
  > CHECK: Algebra - the View entries may be plain items rather than checkboxes, and there may be a separate "Input Bar" entry instead
- move to {{algebra_view}}
- left-click
- key-click esc
- wait for field "Input"
  > CHECK: Input - the empty input row of the Algebra view shows the placeholder "Input…"; the exact text is a guess
- find field "Input" as input_field
- move to {{input_field}}
- left-click
- type `ShowGrid(true)`
- key-click enter

> UNSUPPORTED: "Use the Polygon tool to draw each rectangle. Click the four corners, then click the first point again to close it." Reason: the corners are GeoGebra canvas coordinates. No verb turns a canvas coordinate into a pointer position, there is no arithmetic to compute one, and an empty grid point has no label for `find`. Substitute below: the Polygon command, typed into the Input field, gives the same rectangle with the same corners.

Place the zones apart so they don't overlap:

Table: Zones

| letter | name | size | poly | corners | area | capacity | tx | ty |
|---|---|---|---|---|---|---|---|---|
| A | Bulk Storage North | 12×8 | zoneA | (0,0),(12,0),(12,8),(0,8) | 96 | 38 | 0.5 | 1 |
| B | Bulk Storage South | 10×9 | zoneB | (14,0),(24,0),(24,9),(14,9) | 90 | 36 | 14.5 | 1 |
| C | Medium Goods East | 7×6 | zoneC | (26,0),(33,0),(33,6),(26,6) | 42 | 25 | 26.5 | 1 |
| D | Medium Goods West | 8×5 | zoneD | (35,0),(43,0),(43,5),(35,5) | 40 | 24 | 35.5 | 1 |
| E | Small Parts Aisle 1 | 5×4 | zoneE | (0,12),(5,12),(5,16),(0,16) | 20 | 18 | 0.5 | 13 |
| F | Small Parts Aisle 2 | 6×3 | zoneF | (7,12),(13,12),(13,15),(7,15) | 18 | 16 | 7.5 | 13 |
| G | Cold Storage | 9×7 | zoneG | (15,12),(24,12),(24,19),(15,19) | 63 | 19 | 15.5 | 13 |
| H | Returns Processing | 4×4 | zoneH | (26,12),(30,12),(30,16),(26,16) | 16 | 11 | 26.5 | 13 |

I checked all the capacity numbers (area × factor, rounded), and they match the sub-tasks.

- for each row in "Zones":
  - type `{{poly}} = Polygon({{corners}})`
  - key-click enter
  - screenshot
  - expect "{{poly}} = {{area}}" exists
    > CHECK: {{poly}} = {{area}} - assumes the Algebra view shows the value (e.g. "zoneA = 96") and not the definition; GeoGebra may also render the area as "96.00"

Label each zone. Right-click the polygon, open Settings → Basic, set the Caption to the zone name, and choose Show Label: Caption.

- for each row in "Zones":
  - screenshot
  - find text "{{poly}} = {{area}}" as zone_entry
  - move to {{zone_entry}}
  - right-click
  - screenshot
  - find menu "Settings" as settings_item
  - move to {{settings_item}}
  - left-click
  - wait for tab "Basic"
  - find tab "Basic" as basic_tab
  - move to {{basic_tab}}
  - left-click
  - screenshot
  - find field "Caption" as caption_field
  - move to {{caption_field}}
  - left-click
  - key-click cmd+a
  - type "{{letter}} {{name}}"
  - key-click enter
  - screenshot
  - find checkbox "Show Label" as show_label
    > CHECK: Show Label - clicking toggles it; this assumes it starts unchecked for a polygon made by a command in Geometry. If it starts checked, this click turns the label off
  - move to {{show_label}}
  - left-click
  - screenshot
  - find item "Name" as label_mode
    > CHECK: Name - assumes the label-mode dropdown next to Show Label shows "Name" at first; it may show "Name & Value" or have another role
  - move to {{label_mode}}
  - left-click
  - screenshot
  - find item "Caption" as caption_mode
  - move to {{caption_mode}}
  - left-click
  - screenshot
  - find icon "Close" as close_settings
    > CHECK: Close - the Settings panel's close control is an X with no text; its name is a guess
  - move to {{close_settings}}
  - left-click

> UNSUPPORTED: "Use the Text tool to click inside each zone and type, for example: `Area: 96 sq m, Capacity: 38 pallets`." Reason: "inside each zone" is a canvas position, with the same problem as the Polygon tool above. Substitute below: the Text command, placed at the point (tx, ty) inside each zone from the Zones table.

- screenshot
- find field "Input" as input_field_again
- move to {{input_field_again}}
- left-click
- for each row in "Zones":
  - type `Text("Area: {{area}} sq m, Capacity: {{capacity}} pallets", ({{tx}}, {{ty}}))`
  - key-click enter

Add a title and legend. Add a text box saying Warehouse Storage Zones at the top. Add a small text box as a legend, for example: "Area = L × W; Capacity = Area × factor (rounded)".

- type `Text("Warehouse Storage Zones", (0, 22))`
- key-click enter
- type `Text("Area = L × W; Capacity = Area × factor (rounded)", (32, 20))`
- key-click enter

Save the file. Use Menu → Save, name it Warehouse_Zones, and save it on the Desktop. It must end in .ggb.

- key-click cmd+s
- wait for field "Save As:"
  > CHECK: Save As: - assumes GeoGebra Classic opens the standard macOS save panel; it may open its own dialog instead
- key-click cmd+a
- type "Warehouse_Zones"
- key-click cmd+shift+d
- wait 500 ms
- key-click enter
- wait 2 s
- App: Finder
- key-click cmd+space
- wait 300 ms
- type "Finder"
- key-click enter
- wait 1 s
- key-click cmd+shift+d
- wait for window "Desktop"
- expect "Warehouse_Zones.ggb" exists
  > CHECK: Warehouse_Zones.ggb - Finder hides extensions by default, so it may show only "Warehouse_Zones"

## Part 2: Trello (about 20 min)

Click Create → Board and name it Warehouse Reorganization Q2 2025.

- do "open app from Spotlight" with app_name="Trello", window_title="Trello"
  > CHECK: Trello - assumes the Trello desktop app is installed; if the board is used in a browser, the app and window title are different
- App: Trello
- screenshot
- find button "Create" as create_button
- move to {{create_button}}
- left-click
- screenshot
- find item "Create board" as create_board
- move to {{create_board}}
- left-click
- wait for field "Board title"
- find field "Board title" as board_title
- move to {{board_title}}
- left-click
- type "Warehouse Reorganization Q2 2025"
- key-click enter
  > CHECK: enter - assumes Enter submits the Create board form; otherwise the form's own "Create" button must be clicked, and it has the same label as the header button

Create four lists: To Plan, In Progress, Awaiting Review, Done.

A new board must be empty. If Trello added its own template lists, the next check stops the run.

- wait for button "Add a list" up to 20 s
  > CHECK: Add a list - the button text may be "+ Add a list"
- expect "To Do" does not exist
- find button "Add a list" as add_list
- move to {{add_list}}
- left-click
- wait for field "Enter list name…"
  > CHECK: Enter list name… - placeholder text from memory, including the ellipsis character
- type "To Plan"
- key-click enter
- key-click esc

Put all 16 cards in To Plan. Name them like "Zone A – Layout Marking" and "Zone A – Rack Installation".

The cards go in before the other three lists exist. Every list has its own "Add a card" button, and `find` cannot pick the one in To Plan while there are four.

Table: Cards

| zone | zone_name | task | area | capacity | assignee | due |
|---|---|---|---|---|---|---|
| A | Bulk Storage North | Layout Marking | 96 | 38 | Maria Chen | 5/5/2025 |
| A | Bulk Storage North | Rack Installation | 96 | 38 | Diego Ramirez | 5/13/2025 |
| B | Bulk Storage South | Layout Marking | 90 | 36 | Aisha Patel | 5/6/2025 |
| B | Bulk Storage South | Rack Installation | 90 | 36 | Tom Nguyen | 5/14/2025 |
| C | Medium Goods East | Layout Marking | 42 | 25 | Maria Chen | 5/7/2025 |
| C | Medium Goods East | Rack Installation | 42 | 25 | Diego Ramirez | 5/15/2025 |
| D | Medium Goods West | Layout Marking | 40 | 24 | Aisha Patel | 5/8/2025 |
| D | Medium Goods West | Rack Installation | 40 | 24 | Tom Nguyen | 5/16/2025 |
| E | Small Parts Aisle 1 | Layout Marking | 20 | 18 | Maria Chen | 5/9/2025 |
| E | Small Parts Aisle 1 | Rack Installation | 20 | 18 | Diego Ramirez | 5/17/2025 |
| F | Small Parts Aisle 2 | Layout Marking | 18 | 16 | Aisha Patel | 5/10/2025 |
| F | Small Parts Aisle 2 | Rack Installation | 18 | 16 | Tom Nguyen | 5/18/2025 |
| G | Cold Storage | Layout Marking | 63 | 19 | Maria Chen | 5/11/2025 |
| G | Cold Storage | Rack Installation | 63 | 19 | Diego Ramirez | 5/19/2025 |
| H | Returns Processing | Layout Marking | 16 | 11 | Aisha Patel | 5/12/2025 |
| H | Returns Processing | Rack Installation | 16 | 11 | Tom Nguyen | 5/20/2025 |

- screenshot
- find button "Add a card" as add_card
  > CHECK: Add a card - the button text may be "+ Add a card"
- move to {{add_card}}
- left-click
- wait for field "Enter a title for this card…"
  > CHECK: Enter a title for this card… - placeholder text from memory
- for each row in "Cards":
  - type "Zone {{zone}} – {{task}}"
  - key-click enter
- key-click esc

Table: Later lists

| list |
|---|
| In Progress |
| Awaiting Review |
| Done |

- screenshot
- find button "Add another list" as add_another_list
  > CHECK: Add another list - the button text after the first list may be "+ Add another list"
- move to {{add_another_list}}
- left-click
- wait for field "Enter list name…"
- for each row in "Later lists":
  - type "{{list}}"
  - key-click enter
- key-click esc
- screenshot
- expect "To Plan" exists
- expect "In Progress" exists
- expect "Awaiting Review" exists
- expect "Done" exists

In each card's description, type:
`Zone A (Bulk Storage North) | Area: 96 sq m | Pallet capacity: 38 | Assignee: Maria Chen`
The four team members aren't real Trello users, so write the assignee as text in the description.

Set each card's Dates → Due date in 2025.

- for each row in "Cards":
  - do "open card" with card_title="Zone {{zone}} – {{task}}"
  - find field "Add a more detailed description…" as description_field
    > CHECK: Add a more detailed description… - placeholder text from memory
  - move to {{description_field}}
  - left-click
  - wait 500 ms
  - type "Zone {{zone}} ({{zone_name}}) | Area: {{area}} sq m | Pallet capacity: {{capacity}} | Assignee: {{assignee}}"
  - screenshot
  - find button "Save" as save_description
  - move to {{save_description}}
  - left-click
  - screenshot
  - find button "Dates" as dates_button
    > CHECK: Dates - in the newer card layout, Dates may be under a "+ Add" button
  - move to {{dates_button}}
  - left-click
  - wait for field "Due date"
    > CHECK: Due date - assumes the date input is named "Due date" and its checkbox is already ticked; the date and time inputs may be two fields
  - find field "Due date" as due_field
  - move to {{due_field}}
  - left-click
  - key-click cmd+a
  - type "{{due}}"
    > CHECK: {{due}} - assumes the date input accepts M/D/YYYY (US locale)
  - screenshot
  - find button "Save" as save_dates
  - move to {{save_dates}}
  - left-click
  - wait 500 ms
  - key-click esc

Open a few cards on camera to show that the data is correct. This covers the "verify" sub-task.

Table: Spot checks

| zone | zone_name | task | area | capacity | assignee | due_shown |
|---|---|---|---|---|---|---|
| A | Bulk Storage North | Layout Marking | 96 | 38 | Maria Chen | May 5, 2025 |
| D | Medium Goods West | Rack Installation | 40 | 24 | Tom Nguyen | May 16, 2025 |
| H | Returns Processing | Rack Installation | 16 | 11 | Tom Nguyen | May 20, 2025 |

- for each row in "Spot checks":
  - do "open card" with card_title="Zone {{zone}} – {{task}}"
  - expect "Zone {{zone}} ({{zone_name}}) | Area: {{area}} sq m | Pallet capacity: {{capacity}} | Assignee: {{assignee}}" exists
    > CHECK: description text - fails if the card wraps the description over two lines and it is read as two pieces of text
  - expect "{{due_shown}}" exists
    > CHECK: {{due_shown}} - Trello may show the due date with a time, e.g. "May 5, 2025, 12:00 PM"
  - wait 3 s
  - key-click esc

## Part 3: Spotify (about 15 min)

Click + → Create playlist and name it Warehouse Day Shift.

- do "open app from Spotlight" with app_name="Spotify", window_title="Spotify"
- App: Spotify
- do "create playlist" with playlist="Warehouse Day Shift"

Search for 25 upbeat songs and add each one, for example "Uptown Funk", "Happy", "Can't Stop the Feeling!", "Shut Up and Dance", "Don't Stop Me Now". Check that the track count reaches 25.

**Warehouse Day Shift (25 upbeat songs)**

Table: Day Shift songs

| title | artist |
|---|---|
| Uptown Funk | Mark Ronson ft. Bruno Mars |
| Happy | Pharrell Williams |
| Can't Stop the Feeling! | Justin Timberlake |
| Shut Up and Dance | WALK THE MOON |
| Don't Stop Me Now | Queen |
| September | Earth, Wind & Fire |
| Hey Ya! | OutKast |
| Mr. Brightside | The Killers |
| Levitating | Dua Lipa |
| Blinding Lights | The Weeknd |
| Walking on Sunshine | Katrina & The Waves |
| I Gotta Feeling | The Black Eyed Peas |
| Dancing Queen | ABBA |
| Shake It Off | Taylor Swift |
| Treasure | Bruno Mars |
| Good as Hell | Lizzo |
| Dynamite | BTS |
| On Top of the World | Imagine Dragons |
| Counting Stars | OneRepublic |
| Wake Me Up | Avicii |
| Sugar | Maroon 5 |
| Timber | Pitbull ft. Kesha |
| Moves Like Jagger | Maroon 5 ft. Christina Aguilera |
| Eye of the Tiger | Survivor |
| Livin' on a Prayer | Bon Jovi |

- for each row in "Day Shift songs":
  - do "add song" with title="{{title}}", artist="{{artist}}", playlist="Warehouse Day Shift"
- do "check track count" with playlist="Warehouse Day Shift", count_text="25 songs"

Create Warehouse Evening Shift and add 20 relaxed songs, for example "Banana Pancakes", "Sunday Morning", "Put Your Records On", "Riptide". Check that it shows 20.

- do "create playlist" with playlist="Warehouse Evening Shift"

**Warehouse Evening Shift (20 relaxed songs)**

Table: Evening Shift songs

| title | artist |
|---|---|
| Banana Pancakes | Jack Johnson |
| Sunday Morning | Maroon 5 |
| Put Your Records On | Corinne Bailey Rae |
| Riptide | Vance Joy |
| Better Together | Jack Johnson |
| Budapest | George Ezra |
| Yellow | Coldplay |
| Let Her Go | Passenger |
| Photograph | Ed Sheeran |
| Rivers and Roads | The Head and the Heart |
| Ho Hey | The Lumineers |
| Somewhere Only We Know | Keane |
| Bloom | The Paper Kites |
| I'm Yours | Jason Mraz |
| Sweater Weather | The Neighbourhood |
| Location | Khalid |
| Electric Feel | MGMT |
| Island in the Sun | Weezer |
| The Night We Met | Lord Huron |
| Here Comes the Sun | The Beatles |

- for each row in "Evening Shift songs":
  - do "add song" with title="{{title}}", artist="{{artist}}", playlist="Warehouse Evening Shift"
- do "check track count" with playlist="Warehouse Evening Shift", count_text="20 songs"

## Routine: open app from Spotlight (app_name, window_title)

- App: Finder
- key-click cmd+space
- wait 300 ms
- type "{{app_name}}"
- key-click enter
- wait for window "{{window_title}}" up to 30 s

## Routine: open card (card_title)

- App: Trello
- screenshot
- find text "{{card_title}}" as card
  > CHECK: {{card_title}} - with 16 cards in one list, the lower cards may be below the visible area of the list, and nothing here scrolls to them
- move to {{card}}
- left-click
- wait for text "Description"

## Routine: create playlist (playlist)

- App: Spotify
- key-click cmd+n
  > CHECK: cmd+n - used instead of the guide's "+ → Create playlist"; assumes Spotify's New Playlist shortcut is Cmd+N
- wait for text "My Playlist #"
  > CHECK: My Playlist # - the new playlist is named "My Playlist #<n>" with an unknown number; this works only if find matches part of a label
- find text "My Playlist #" as new_title
- move to {{new_title}}
- left-click
- wait for field "Add a name"
  > CHECK: Add a name - the name field in the "Edit details" dialog; label from memory
- find field "Add a name" as name_field
- move to {{name_field}}
- left-click
- key-click cmd+a
- type "{{playlist}}"
- screenshot
- find button "Save" as save_details
- move to {{save_details}}
- left-click
- wait for item "{{playlist}}"

## Routine: add song (title, artist, playlist)

- App: Spotify
- key-click cmd+k
  > CHECK: cmd+k - Spotify's shortcut to focus the search field; older versions used Cmd+L
- wait 300 ms
- key-click cmd+a
- type "{{title}} {{artist}}"
- key-click enter
- wait for text "Top result" up to 15 s
- find item "{{title}}" as song
  > CHECK: {{title}} - the title also appears on the "Top result" card, and Spotify often lists a longer title (e.g. "Uptown Funk (feat. Bruno Mars)", "Happy - From \"Despicable Me 2\"", "Timber (feat. Ke$ha)"), sometimes with curly apostrophes; the role item is meant to pick the row in the Songs list
- move to {{song}}
- right-click
- screenshot
- find menu "Add to playlist" as add_to_playlist
- move to {{add_to_playlist}}
- left-click
- screenshot
- find menu "{{playlist}}" as target_playlist
- move to {{target_playlist}}
- left-click
- wait for text "Added to {{playlist}}" up to 10 s
  > CHECK: Added to {{playlist}} - the confirmation toast text is from memory

## Routine: check track count (playlist, count_text)

- App: Spotify
- screenshot
- find item "{{playlist}}" as playlist_entry
- move to {{playlist_entry}}
- left-click
- wait for text "{{count_text}}" up to 15 s
  > CHECK: {{count_text}} - the header may show one piece of text such as "25 songs, about 1 hr 30 min"
- expect "{{count_text}}" exists