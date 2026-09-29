# Prompt: converting a guide into AutoScript

Paste everything below the line into a new Claude conversation, after
attaching two files:

1. `docs/AUTOSCRIPT.md` - the language
2. the guide to convert, e.g. `refer/AutoScript/2.md`

Save the script Claude returns, then check it before anything else:

```
human-input-automation --check-script path/to/script.md
```

Every error is printed with its line. Paste them back into the same
conversation and ask for a corrected script; repeat until it reports `OK`.

---

You are converting a work guide into AutoScript. The attached `AUTOSCRIPT.md`
is the complete specification of the language; the other attached file is the
guide to convert.

The script will be performed by a humanoid robot operating a Mac with a
keyboard and a mouse. Every step you write is something its body does: a key
press, typed text, a pointer movement, a click, a screenshot. Write what the
body does, never what the user means.

Rules:

1. Follow §5 ("Exact rules") and §12 ("Converting a guide") of the
   specification exactly. Anything §5 does not allow is an error.
2. Use only the verbs in §4. If a step cannot be written with them, keep the
   guide's sentence as a quoted line starting `> UNSUPPORTED:` and say why.
   Do not invent a verb or a variant.
3. After any step that sends input, take a `screenshot` or a `wait for` before
   the next `find` or `read` (§5.6). Check this for every single `find`.
4. Give `find` a role (`button`, `menu`, `item`, `field`, `checkbox`, `tab`,
   `icon`, `text`, `window`) whenever the label could appear more than once on
   screen (§5.7).
5. Every `-` or `*` line is read as a step, so never use one for a note. Keep
   the guide's numbered instructions (`1. Click ...`) as they are - numbered
   lines are prose - and write any note of your own as a plain line or a `>`
   quote.
6. When only part of a label is known in advance (a numbered default name, a
   count followed by more text), use `containing "…"` (§5.7) rather than a
   guess at the whole label.
7. You cannot see the screen. When you are not sure of the exact text of a
   label in the real application, still write your best guess, and put a line
   `> CHECK: <label> - <why you are unsure>` directly under the step.
8. Turn every stated expectation into an `expect`, every table into a
   `Table:` with `for each`, and near-identical repetition into a
   `## Routine:` with parameters.
9. Start with `# <title>`, then `Platform: macOS`. Keep one `## ` stage per
   sub-task, using the guide's own headings. Keep the guide's notes as prose.
10. Prefer keyboard shortcuts to menu navigation where the guide allows it and
    the shortcut is standard on macOS.

Output, in this order:

1. The complete script, as one Markdown code block, with nothing left out -
   every row of every table, every item of every list.
2. After it, a short list headed **Screen map needed**: every label used with
   `find`, `wait for` or `move to "…"`, one per line, with the application it
   is in.
3. A short list headed **Gaps**: every `UNSUPPORTED` and every `CHECK`, and
   anything in the specification you found ambiguous while converting.
