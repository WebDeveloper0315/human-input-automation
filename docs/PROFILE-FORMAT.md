# Profile format (schema 1)

A profile is a saved automation: a name, a durable way to find the target
application again, and the plan to run against it.

**A profile is pure data.** It contains no commands, no scripts and no code, and
nothing in the load path can start automation — see [Security](#security-model).

## Storage

One JSON file per profile, named by the profile's id:

```
<data directory>/human-input-automation/profiles/
├── 4f3e1a....json
└── e0e2a5....json
```

| Platform | Data directory |
| --- | --- |
| Windows | `%APPDATA%` |
| macOS | `~/Library/Application Support` |
| Linux/other | `$XDG_DATA_HOME`, else `~/.local/share` |

Profiles are never stored in the source tree. The directory is injectable
(`ProfileRepository(path)`), which is how the tests avoid the real one.

**Filenames are never derived from the profile name.** The id is 32 lowercase
hex characters, so a profile called `../../.bashrc`, `CON` or a 500-character
string is still stored as `4f3e….json`. Path traversal is prevented by
construction, not by sanitising user text.

**Writes are atomic.** The payload is written to a temporary file in the same
directory, flushed, `fsync`ed, then moved into place with `os.replace`. An
interrupted save leaves the previous version intact — never a truncated file.

## Example

```json
{
  "schema": 1,
  "id": "e0e2a5d67c754004a1451b016187a86b",
  "name": "Open Search",
  "description": "Focus search and type",
  "created_at": "2026-09-01T15:22:29+00:00",
  "updated_at": "2026-09-01T15:22:29+00:00",
  "target": {
    "platform": "linux",
    "display_server": "x11",
    "process_name": "editor",
    "app_id": "org.example.editor",
    "title": "Notes - Editor",
    "title_pattern": null,
    "handle_hint": "0x1800004"
  },
  "plan": {
    "actions": [
      { "type": "type_text", "delay_after_ms": null, "text": "Hello, world." },
      { "type": "key_press", "delay_after_ms": null, "key": "enter", "count": 1 }
    ],
    "timing": {
      "char_delay_ms": 80.0, "char_jitter_ms": 35.0,
      "min_delay_ms": 20.0, "max_delay_ms": 250.0,
      "word_pause_ms": 0.0, "word_pause_jitter_ms": 0.0,
      "punctuation_pause_ms": 0.0, "punctuation_pause_jitter_ms": 0.0,
      "punctuation_chars": ".,;:!?",
      "action_delay_ms": 120.0, "action_jitter_ms": 40.0,
      "mouse_move_duration_ms": 200.0, "mouse_move_jitter_ms": 50.0
    },
    "limits": {
      "max_actions": 500, "max_text_length": 5000,
      "max_total_characters": 20000, "max_run_duration_s": 300.0
    },
    "options": {
      "dry_run": false, "seed": null,
      "require_focus_verification": false, "reverify_focus": true
    }
  }
}
```

## Schema versioning

`"schema"` is **required** and must be an integer. The version is never inferred
from which fields are present.

* This build writes and reads **schema 1**.
* A newer version is rejected explicitly:
  `Unsupported profile schema version: 2`. Nothing is downgraded or ignored.
* Older versions are handled by a migration registry
  (`serialization.MIGRATIONS`, `from_version -> upgrade function`). It is empty
  today because only version 1 exists; adding version 2 means adding one entry,
  not touching every caller. A migration that fails to advance the version is an
  error rather than an infinite loop.

## Actions

`"type"` is the action's `kind`, the same identifier the engine dispatches on,
so the stored format cannot drift from the domain model. Supported types:

`type_text`, `key_press`, `key_down`, `key_up`, `shortcut`, `mouse_move`,
`mouse_click`, `mouse_down`, `mouse_up`, `wait`

Every action also carries `delay_after_ms` (`null` = use the timing profile).
Keys are written by name (`"enter"`, `"ctrl"`, `"a"`); `"meta"` is the platform
command modifier (Command / Windows key / Super).

Encoding is generic over each action's dataclass fields, so a field added to an
action in future is written out automatically instead of silently disappearing
from saved profiles — a test asserts the encoded keys match the declared fields
for every action type.

## Target identity

The most important distinction in this format.

| Persistent — stored | Transient — never stored as identity |
| --- | --- |
| `platform` | native window handle / `HWND` / X11 id |
| `display_server` | process id |
| `process_name` | window capabilities |
| `app_id` (bundle id / WM_CLASS) | focus state |
| `title`, `title_pattern` | display-server capability state, run state |

`handle_hint` is the single exception, and it is only ever a *hint*: the
resolver accepts it only when the window it points at **also** matches the saved
application identity. Window ids are reused, and after a restart the window
behind one may belong to a different program entirely.

Process ids are deliberately not stored: they change on every restart, so
treating one as identity would either fail always or match the wrong process.

`dry_run` is written as `false` and always decoded as `false`: whether a run is
a rehearsal is a decision made when it is started, not a saved property.

## Resolution

Matching priority (`application/profiles/resolver.py`), highest first:

1. **Handle hint confirmed by application identity** — the hint matches a live
   window *and* that window's `app_id`/`process_name` matches.
2. **Application id**, exact, case-insensitive.
3. **Process name**, exact, case-insensitive.
4. **Title pattern** (regex) or **exact title**.

Rule 4 only *narrows* the windows found by rules 2–3. A window belonging to a
different application that happens to share a title is never the target. A title
is used on its own only when the profile records no application identity at all.
There is no fuzzy matching.

Outcomes:

| Result | Meaning |
| --- | --- |
| `TARGET_RESOLVED` | Exactly one window matched, and it accepts input. |
| `TARGET_UNRESOLVED` | Nothing matched — the application is not running, the stale handle belongs to something else, or the profile was saved on another platform. |
| `TARGET_AMBIGUOUS` | Several windows matched. The user picks; the resolver never chooses. |
| `TARGET_CAPABILITY_BLOCKED` | The window exists but this platform will not let us send input to it. |
| `PROFILE_INVALID` | The plan failed validation on this host. |

Only `TARGET_RESOLVED` produces a runnable plan. Every other state loads and
displays fine but leaves Start disabled. **The currently focused window is never
used as a fallback.**

## Validation

```
JSON → structural validation → migration → domain validation → resolve → run
```

* **Structural** (`serialization.py`): schema version, required fields, types,
  known action types, known enum values, finite numbers, valid regexes, sane
  limits. `bool` is rejected where a number is expected, and non-finite numbers
  are refused on both read and write.
* **Domain**: the existing `validate_plan()` — limits, coordinates, platform key
  gaps, target capabilities. Profiles do not duplicate it.

**Unknown fields are rejected**, in actions and in every structural object:
silently ignoring a key means silently ignoring the user's intent. Forward
compatibility is the schema version's job, not lenient parsing.

```
{"type": "TeleportToMars"}  →  Unknown action type: TeleportToMars. Known types: key_down, key_press, ...
{"type": "wait", "duration_ms": 10, "shell": "rm -rf /"}  →  unknown field(s): shell
```

## Import and export

Export writes a profile to any file the user chooses. Import reads it, validates
it, and stores it — assigning a **fresh id if the id already exists**, so an
import can never overwrite an existing profile. Import never runs anything.

```bash
python -m human_input_automation --profiles                 # list stored profiles
python -m human_input_automation --validate-profile x.json  # validate, never execute
```

## Security model

Profile files are treated as untrusted input.

* Profiles describe only the predefined domain actions above. There is no
  `command`, `shell`, `exec`, `script`, `python` or `eval` field, and adding one
  would require a deliberate, separately designed feature.
* Loading, importing, validating, resolving and listing are all side-effect free
  with respect to the keyboard and mouse. Only the existing Run/Start path sends
  input, and it still requires the user to press Start.
* A profile cannot bypass platform restrictions: the resolved target carries the
  live capabilities, and the same validation and capability gates apply as to
  any other run. A Wayland session does not become more permissive because a
  profile asked it to.
