# OLED Screen Designer

A GUI tool for visually designing layouts for SSD1306 and similar OLED displays. Renders elements through PIL/Pillow to a 1-bit canvas that accurately matches what the physical display will show, then exports ready-to-use Python drawing code.  Fair warning: much of this code was AI generated, and there *is* bugs, report them if you find any and I will do my best to fix them in a timely manner. Thank you!

## Features

- WYSIWYG canvas scaled 4× from real OLED pixel coordinates
- Supports multiple common OLED sizes: 128×64, 128×32, 96×16, 64×48
- Element types: **Text**, **Rectangle**, **Line**, **Ellipse**
- `{tag}` syntax in text elements — previewed with fake data, emitted verbatim in generated code
- Drag, nudge (arrow keys), resize via handles, copy/paste, undo/redo
- Grid overlay (8px and 16px)
- Save/load layouts as JSON
- Generates PIL `ImageDraw` Python code ready to embed in your display driver

## Requirements

```
pillow tkinter
```

All other dependencies in `requirements.txt` are for the broader `display2` project and are not required to run the designer.

## Usage

```bash
python designer_gui.py
```

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+Z` / `Ctrl+Y` | Undo / Redo |
| `Ctrl+C` / `Ctrl+V` | Copy / Paste (offset +4, +4) |
| Arrow keys | Nudge selected element 1 OLED px |
| `Delete` / `Backspace` | Delete selected element |
| `Escape` | Deselect / cancel active tool |

### Dynamic text tags

Use `{tag}` placeholders in text elements to reference runtime data. The designer previews them using the built-in fake data set (version strings, IP, time, etc.). The exported code emits the placeholder verbatim so your display driver can call `.format(**data)` at runtime.

Example: `{time}` previews as `12:34:56` and exports as `"{time}"`.

## Output

The **Generate Code** action produces `draw.*` calls using PIL `ImageDraw` that can be dropped directly into any SSD1306 rendering loop:

```python
draw.text((0, 0), "{time}", fill="white")
draw.rectangle((0, 10, 127, 63), outline="white")
draw.line((0, 10, 127, 10), fill="white")
```

## Screenshot

Last but not least:
![Screenshot](/ss.png)
