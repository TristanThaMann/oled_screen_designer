#!/usr/bin/env python3
"""
designer_gui.py — Interactive OLED screen designer 

Renders elements through real PIL ImageDraw → 1-bit → scaled-up PhotoImage,
so the canvas matches what the physical SSD1306 actually shows.

{tag} syntax is previewed from FAKE_DATA; emitted verbatim in generated code.

Shortcuts:
  Ctrl+Z / Ctrl+Y   undo / redo
  Ctrl+C / Ctrl+V   copy / paste (offset +4,+4)
  Arrow keys        nudge 1 OLED px
  Delete/Backspace  delete selected
  Escape            deselect / cancel tool
"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import json, math, os, copy

import PIL.Image
import PIL.ImageDraw
import PIL.ImageFont
import PIL.ImageTk

# ── constants ────────────────────────────────────────────────────────────────
SCALE    = 4       # OLED pixel → canvas pixel
HANDLE_R = 4       # selection handle half-size (canvas px)

SEL_COLOR  = '#00cc44'
GRID_COL8  = '#181818'
GRID_COL16 = '#242424'
HANDLE_COL = '#00cc44'

# Common OLED sizes (label → (w, h))
OLED_SIZES = {
    '128×64 (SSD1306)': (128, 64),
    '128×32 (SSD1306)': (128, 32),
    '96×16':            (96,  16),
    '64×48':            (64,  48),
}
DEFAULT_SIZE = '128×64 (SSD1306)'

FAKE_DATA = {
    'version':       '1.2.3',
    'cce_version':   '2.3.4',
    'fwmsc_version': '1.2.3',
    'build':         '42',
    'ip':            '192.168.1.50',
    'port':          '502',
    'slave':         '1',
    'date':          '07 Apr 26',
    'time':          '12:34:56',
    'model':         '2.6.1',
    'status':        'OK',
}

# ── PIL font loading ──────────────────────────────────────────────────────────
FONT_OPTIONS = ['default', 'Courier New', 'Arial', 'Helvetica', 'DejaVuSans', 'FreeMono']

_FONT_SEARCH_PATHS = [
    '/System/Library/Fonts/',
    '/System/Library/Fonts/Supplemental/',
    '/Library/Fonts/',
    os.path.expanduser('~/Library/Fonts/'),
    '/usr/share/fonts/truetype/',
    '/usr/share/fonts/truetype/dejavu/',
    '/usr/share/fonts/truetype/freefont/',
]
_FONT_FILE_NAMES = {
    'Courier New': ['Courier New.ttf', 'CourierNew.ttf', 'cour.ttf'],
    'Arial':       ['Arial.ttf', 'arial.ttf'],
    'Helvetica':   ['Helvetica.ttc', 'helvetica.ttf'],
    'DejaVuSans':  ['DejaVuSans.ttf'],
    'FreeMono':    ['FreeMono.ttf'],
}
_font_cache = {}

def _load_pil_font(font_name, size):
    key = (font_name, size)
    if key in _font_cache:
        return _font_cache[key]
    font = None
    if font_name != 'default':
        for fname in _FONT_FILE_NAMES.get(font_name, []):
            for folder in _FONT_SEARCH_PATHS:
                path = os.path.join(folder, fname)
                if os.path.exists(path):
                    try:
                        font = PIL.ImageFont.truetype(path, size)
                        break
                    except Exception:
                        pass
            if font:
                break
        if font is None:
            print(f'[designer] font "{font_name}" not found, using default')
    if font is None:
        font = PIL.ImageFont.load_default()
    _font_cache[key] = font
    return font


# ── element base ─────────────────────────────────────────────────────────────

class Element:
    _counter = 0

    def __init__(self, x, y):
        Element._counter += 1
        self.eid      = Element._counter
        self.x        = int(x)
        self.y        = int(y)
        self.selected = False

    def tag(self): return f'e{self.eid}'

    def preview(self, text):
        try:    return text.format(**FAKE_DATA)
        except: return text  # noqa: E722

    # canvas coords from OLED coords
    def _sx(self): return self.x * SCALE
    def _sy(self): return self.y * SCALE

    def handles(self):                          return []
    def apply_resize(self, *_):                 pass
    def hit_test(self, cx, cy):                 raise NotImplementedError
    def pil_draw(self, draw):                   raise NotImplementedError
    def to_dict(self):                          raise NotImplementedError
    def code_line(self):                        raise NotImplementedError
    def label(self):                            return self.type_name

    def start_props(self):
        return {p: getattr(self, p) for p in self.PROPS}


# ── text ─────────────────────────────────────────────────────────────────────

class TextElement(Element):
    type_name = 'Text'
    PROPS     = ['x', 'y', 'text', 'size', 'font_name', 'fill']

    def __init__(self, x, y, text='Label', size=8, font_name='default', fill='white'):
        super().__init__(x, y)
        self.text      = text
        self.size      = int(size)
        self.font_name = font_name
        self.fill      = fill

    def label(self):
        t = self.text[:14] + ('…' if len(self.text) > 14 else '')
        return f'Text  "{t}"'

    def _pil_font(self):
        return _load_pil_font(self.font_name, self.size)

    def _text_bbox_oled(self):
        """Bounding box of rendered text in OLED pixels."""
        tmp = PIL.Image.new('1', (256, 64))
        d   = PIL.ImageDraw.Draw(tmp)
        bb  = d.textbbox((self.x, self.y), self.preview(self.text), font=self._pil_font())
        return bb  # (x0, y0, x1, y1) in OLED coords

    def hit_test(self, cx, cy):
        try:
            x0, y0, x1, y1 = self._text_bbox_oled()
            return (x0*SCALE <= cx <= x1*SCALE and y0*SCALE <= cy <= y1*SCALE)
        except Exception:
            return (self._sx() <= cx <= self._sx() + 60 and
                    self._sy() <= cy <= self._sy() + self.size * SCALE)

    def pil_draw(self, draw):
        draw.text((self.x, self.y), self.preview(self.text),
                  fill=1, font=self._pil_font())

    def draw_overlay(self, cv):
        """Selection box drawn in tkinter on top of the PIL image."""
        if not self.selected: return
        try:
            x0, y0, x1, y1 = self._text_bbox_oled()
            cv.create_rectangle(x0*SCALE - 1, y0*SCALE - 1,
                                x1*SCALE + 1, y1*SCALE + 1,
                                outline=SEL_COLOR, tags=self.tag())
        except Exception:
            pass

    def to_dict(self):
        return {'type': 'Text', 'x': self.x, 'y': self.y,
                'text': self.text, 'size': self.size,
                'font_name': self.font_name, 'fill': self.fill}

    def code_line(self):
        if self.font_name == 'default':
            font_arg = ''
        else:
            font_arg = f', font=ImageFont.truetype("{self.font_name}", {self.size})'
        return (f'draw.text(({self.x}, {self.y}), "{self.text}", '
                f'fill="{self.fill}"{font_arg})')


# ── rectangle ─────────────────────────────────────────────────────────────────

class RectElement(Element):
    type_name = 'Rectangle'
    PROPS     = ['x', 'y', 'w', 'h', 'outline', 'fill']

    def __init__(self, x, y, w=30, h=15, outline='white', fill=''):
        super().__init__(x, y)
        self.w = int(w); self.h = int(h)
        self.outline = outline; self.fill = fill

    def label(self): return f'Rect  {self.w}×{self.h}'

    def handles(self):
        sx, sy = self._sx(), self._sy()
        ex, ey = (self.x + self.w)*SCALE, (self.y + self.h)*SCALE
        return [(sx, sy), (ex, sy), (sx, ey), (ex, ey)]

    def apply_resize(self, idx, ddx, ddy, sp):
        x0, y0, w0, h0 = sp['x'], sp['y'], sp['w'], sp['h']
        if idx == 0:
            self.x = x0+ddx; self.y = y0+ddy
            self.w = max(2, w0-ddx); self.h = max(2, h0-ddy)
        elif idx == 1:
            self.y = y0+ddy
            self.w = max(2, w0+ddx); self.h = max(2, h0-ddy)
        elif idx == 2:
            self.x = x0+ddx
            self.w = max(2, w0-ddx); self.h = max(2, h0+ddy)
        elif idx == 3:
            self.w = max(2, w0+ddx); self.h = max(2, h0+ddy)

    def hit_test(self, cx, cy):
        sx, sy = self._sx(), self._sy()
        return sx <= cx <= (self.x+self.w)*SCALE and sy <= cy <= (self.y+self.h)*SCALE

    def pil_draw(self, draw):
        fill = 1 if self.fill else 0
        draw.rectangle((self.x, self.y, self.x+self.w, self.y+self.h),
                       outline=1, fill=fill)

    def draw_overlay(self, cv): pass   # shape visible in PIL image

    def to_dict(self):
        return {'type': 'Rectangle', 'x': self.x, 'y': self.y,
                'w': self.w, 'h': self.h, 'outline': self.outline, 'fill': self.fill}

    def code_line(self):
        x2, y2 = self.x+self.w, self.y+self.h
        fa = f', fill="{self.fill}"' if self.fill else ''
        return f'draw.rectangle(({self.x}, {self.y}, {x2}, {y2}), outline="{self.outline}"{fa})'


# ── line ──────────────────────────────────────────────────────────────────────

class LineElement(Element):
    type_name = 'Line'
    PROPS     = ['x', 'y', 'dx', 'dy', 'fill']

    def __init__(self, x, y, dx=24, dy=0, fill='white'):
        super().__init__(x, y)
        self.dx = int(dx); self.dy = int(dy); self.fill = fill

    def label(self): return f'Line  ({self.x},{self.y})→({self.x+self.dx},{self.y+self.dy})'

    def handles(self):
        return [( self._sx(), self._sy() ),
                ( (self.x+self.dx)*SCALE, (self.y+self.dy)*SCALE )]

    def apply_resize(self, idx, ddx, ddy, sp):
        if idx == 0:
            self.x = sp['x']+ddx; self.y = sp['y']+ddy
            self.dx = sp['dx']-ddx; self.dy = sp['dy']-ddy
        elif idx == 1:
            self.dx = sp['dx']+ddx; self.dy = sp['dy']+ddy

    def hit_test(self, cx, cy):
        sx, sy   = self._sx(), self._sy()
        ex, ey   = (self.x+self.dx)*SCALE, (self.y+self.dy)*SCALE
        ddx, ddy = ex-sx, ey-sy
        if ddx == 0 and ddy == 0:
            return math.hypot(cx-sx, cy-sy) < 6
        t = max(0.0, min(1.0, ((cx-sx)*ddx+(cy-sy)*ddy)/(ddx*ddx+ddy*ddy)))
        return math.hypot(cx-(sx+t*ddx), cy-(sy+t*ddy)) < 6

    def pil_draw(self, draw):
        draw.line((self.x, self.y, self.x+self.dx, self.y+self.dy), fill=1)

    def draw_overlay(self, cv): pass

    def to_dict(self):
        return {'type': 'Line', 'x': self.x, 'y': self.y,
                'dx': self.dx, 'dy': self.dy, 'fill': self.fill}

    def code_line(self):
        x2, y2 = self.x+self.dx, self.y+self.dy
        return f'draw.line(({self.x}, {self.y}, {x2}, {y2}), fill="{self.fill}")'


# ── ellipse ───────────────────────────────────────────────────────────────────

class EllipseElement(Element):
    type_name = 'Ellipse'
    PROPS     = ['x', 'y', 'w', 'h', 'outline']

    def __init__(self, x, y, w=20, h=20, outline='white'):
        super().__init__(x, y)
        self.w = int(w); self.h = int(h); self.outline = outline

    def label(self): return f'Ellipse  {self.w}×{self.h}'

    def handles(self):
        sx, sy = self._sx(), self._sy()
        ex, ey = (self.x+self.w)*SCALE, (self.y+self.h)*SCALE
        return [(sx, sy), (ex, sy), (sx, ey), (ex, ey)]

    def apply_resize(self, idx, ddx, ddy, sp):
        x0, y0, w0, h0 = sp['x'], sp['y'], sp['w'], sp['h']
        if idx == 0:
            self.x = x0+ddx; self.y = y0+ddy
            self.w = max(2, w0-ddx); self.h = max(2, h0-ddy)
        elif idx == 1:
            self.y = y0+ddy
            self.w = max(2, w0+ddx); self.h = max(2, h0-ddy)
        elif idx == 2:
            self.x = x0+ddx
            self.w = max(2, w0-ddx); self.h = max(2, h0+ddy)
        elif idx == 3:
            self.w = max(2, w0+ddx); self.h = max(2, h0+ddy)

    def hit_test(self, cx, cy):
        rx, ry = self.w*SCALE/2, self.h*SCALE/2
        mx, my = self._sx()+rx, self._sy()+ry
        if rx == 0 or ry == 0: return False
        return ((cx-mx)/rx)**2 + ((cy-my)/ry)**2 <= 1.0

    def pil_draw(self, draw):
        draw.ellipse((self.x, self.y, self.x+self.w, self.y+self.h), outline=1)

    def draw_overlay(self, cv): pass

    def to_dict(self):
        return {'type': 'Ellipse', 'x': self.x, 'y': self.y,
                'w': self.w, 'h': self.h, 'outline': self.outline}

    def code_line(self):
        x2, y2 = self.x+self.w, self.y+self.h
        return f'draw.ellipse(({self.x}, {self.y}, {x2}, {y2}), outline="{self.outline}")'


# ── registry ─────────────────────────────────────────────────────────────────

_ELEM_CLASSES = {c.type_name: c
                 for c in (TextElement, RectElement, LineElement, EllipseElement)}

def _elem_from_dict(d):
    cls = _ELEM_CLASSES.get(d.get('type'))
    if cls is None: return None
    return cls(**{k: v for k, v in d.items() if k != 'type'})


# ── designer app ─────────────────────────────────────────────────────────────

class DesignerApp:

    def __init__(self, root):
        self.root        = root
        self.elements    = []
        self.selected    = None
        self.active_tool = tk.StringVar(value='')
        self.snap_var    = tk.BooleanVar(value=False)
        self.screen_name = tk.StringVar(value='my_screen')
        self._status_var = tk.StringVar(value='x: -  y: -')
        self._size_var   = tk.StringVar(value=DEFAULT_SIZE)
        self._prop_vars      = {}
        self._elem_combo_var = None
        self._clipboard      = None
        self._undo_stack     = []
        self._redo_stack     = []
        self._tk_image       = None   # keep PhotoImage reference alive
        self._updating_layers = False

        # OLED dimensions (may change when size selector changes)
        self.oled_w, self.oled_h = OLED_SIZES[DEFAULT_SIZE]

        # drag / resize state
        self._drag_start_canvas = None
        self._drag_start_props  = None
        self._resize_state      = None

        root.title('OLED Screen Designer')
        root.configure(bg='#1a1a1a')
        root.resizable(True, True)
        self._build_ui()
        self._redraw()

    # ── computed canvas dims ──────────────────────────────────────────────────
    @property
    def cw(self): return self.oled_w * SCALE
    @property
    def ch(self): return self.oled_h * SCALE

    # ── UI ───────────────────────────────────────────────────────────────────

    def _build_ui(self):
        root = self.root

        # ── right column: properties + layers + code (full height) ───────────
        # Pack right column FIRST so it claims its space before the left col.
        right_col = tk.Frame(root, bg='#252525', width=210)
        right_col.pack(side='right', fill='both', expand=True)
        right_col.pack_propagate(False)

        # properties + layers (top portion of right column)
        rp = tk.Frame(right_col, bg='#252525', padx=8, pady=8)
        rp.pack(side='top', fill='x')

        tk.Label(rp, text='PROPERTIES', bg='#252525', fg='#777',
                 font=('Courier', 9, 'bold')).pack(pady=(4, 4))

        self._elem_combo_var = tk.StringVar(value='— none —')
        self.elem_combo = ttk.Combobox(rp, textvariable=self._elem_combo_var,
                                       state='readonly', font=('Courier', 9), width=21)
        self.elem_combo.pack(fill='x', pady=(0, 8))
        self.elem_combo.bind('<<ComboboxSelected>>', self._on_combo_select)

        self.prop_frame = tk.Frame(rp, bg='#252525')
        self.prop_frame.pack(fill='x')

        tk.Frame(rp, bg='#444', height=1).pack(fill='x', pady=8)
        tk.Label(rp, text='LAYERS', bg='#252525', fg='#777',
                 font=('Courier', 9, 'bold')).pack()

        lc = tk.Frame(rp, bg='#252525')
        lc.pack(fill='x', pady=(4, 2))
        for sym, cmd in (('▲', self._layer_up), ('▼', self._layer_down)):
            tk.Button(lc, text=sym, font=('Courier', 9), bg='#383838',
                      fg='white', relief='flat', width=3,
                      command=cmd).pack(side='left', padx=2)

        lf = tk.Frame(rp, bg='#252525')
        lf.pack(fill='x')
        self.layer_lb = tk.Listbox(lf, bg='#111', fg='#888',
                                   selectbackground='#1a3a2a',
                                   selectforeground=SEL_COLOR,
                                   font=('Courier', 8), relief='flat',
                                   activestyle='none', height=8)
        lsb = tk.Scrollbar(lf, command=self.layer_lb.yview, bg='#252525')
        self.layer_lb.configure(yscrollcommand=lsb.set)
        lsb.pack(side='right', fill='y')
        self.layer_lb.pack(fill='both', expand=True)
        self.layer_lb.bind('<<ListboxSelect>>', self._on_layer_select)

        tk.Frame(right_col, bg='#444', height=1).pack(fill='x')

        # code panel (bottom portion of right column, expands to fill)
        cp = tk.Frame(right_col, bg='#0d0d0d')
        cp.pack(side='top', fill='both', expand=True)

        ch = tk.Frame(cp, bg='#0d0d0d')
        ch.pack(fill='x', padx=4, pady=(4, 0))
        tk.Label(ch, text='async def ', bg='#0d0d0d', fg='#555',
                 font=('Courier', 9)).pack(side='left')
        tk.Entry(ch, textvariable=self.screen_name, width=18,
                 bg='#1a1a1a', fg='#7ec8e3', insertbackground='white',
                 font=('Courier', 9), relief='flat').pack(side='left')
        tk.Label(ch, text='(self):', bg='#0d0d0d', fg='#555',
                 font=('Courier', 9)).pack(side='left')
        tk.Button(ch, text='Copy', font=('Courier', 8), bg='#2a2a2a',
                  fg='#aaa', relief='flat', activebackground='#444',
                  command=self._copy_code).pack(side='right', padx=4)
        self.screen_name.trace_add('write', lambda *_: self._update_code())

        self.code_text = tk.Text(cp, height=6, bg='#0d0d0d', fg='#7ec8e3',
                                 font=('Courier', 10), state='disabled',
                                 relief='flat', selectbackground='#2a2a2a',
                                 insertbackground='white')
        csb = tk.Scrollbar(cp, command=self.code_text.yview, bg='#252525')
        self.code_text.configure(yscrollcommand=csb.set)
        csb.pack(side='right', fill='y')
        self.code_text.pack(fill='both', expand=True, padx=4, pady=(2, 4))

        # ── left column: toolbox + canvas ─────────────────────────────────────
        left_col = tk.Frame(root, bg='#1a1a1a')
        left_col.pack(side='left', fill='y')

        # ── toolbox ──────────────────────────────────────────────────────────
        tb = tk.Frame(left_col, bg='#252525', width=130, padx=8, pady=8)
        tb.pack(side='left', fill='y')
        tb.pack_propagate(False)

        tk.Label(tb, text='TOOLBOX', bg='#252525', fg='#777',
                 font=('Courier', 9, 'bold')).pack(pady=(4, 8))

        for name in _ELEM_CLASSES:
            tk.Radiobutton(tb, text=name, variable=self.active_tool, value=name,
                           bg='#252525', fg='#ddd', selectcolor='#3a3a3a',
                           activebackground='#252525', activeforeground='white',
                           font=('Courier', 10), indicatoron=True,
                           command=self._deselect).pack(anchor='w', pady=3)

        tk.Frame(tb, bg='#444', height=1).pack(fill='x', pady=8)

        tk.Checkbutton(tb, text='Snap 8px', variable=self.snap_var,
                       bg='#252525', fg='#aaa', selectcolor='#3a3a3a',
                       activebackground='#252525',
                       font=('Courier', 9)).pack(anchor='w', pady=2)

        tk.Frame(tb, bg='#444', height=1).pack(fill='x', pady=8)

        # OLED size selector
        tk.Label(tb, text='OLED size:', bg='#252525', fg='#777',
                 font=('Courier', 8)).pack(anchor='w')
        size_cb = ttk.Combobox(tb, textvariable=self._size_var,
                               values=list(OLED_SIZES.keys()),
                               state='readonly', font=('Courier', 8), width=16)
        size_cb.pack(anchor='w', pady=(2, 8))
        size_cb.bind('<<ComboboxSelected>>', self._on_size_changed)

        tk.Frame(tb, bg='#444', height=1).pack(fill='x', pady=8)

        for label, cmd in (('Clear', self._clear),
                            ('Save…', self._save),
                            ('Load…', self._load)):
            tk.Button(tb, text=label, font=('Courier', 9), bg='#383838',
                      fg='white', activebackground='#555', relief='flat',
                      command=cmd).pack(fill='x', pady=2)

        tk.Frame(tb, bg='#444', height=1).pack(fill='x', pady=8)
        tk.Label(tb, text='{tag} preview:', bg='#252525', fg='#555',
                 font=('Courier', 7)).pack(anchor='w')
        for k, v in FAKE_DATA.items():
            tk.Label(tb, text=f'{{{k}}}={v}', bg='#252525', fg='#3e3e3e',
                     font=('Courier', 7), justify='left').pack(anchor='w')

        # ── canvas ────────────────────────────────────────────────────────────
        cc = tk.Frame(left_col, bg='#1a1a1a', padx=8, pady=8)
        cc.pack(side='left')

        self._size_label = tk.Label(cc, bg='#1a1a1a', fg='#444', font=('Courier', 9))
        self._size_label.pack(anchor='w')
        self._update_size_label()

        self.cv = tk.Canvas(cc, width=self.cw, height=self.ch, bg='#000',
                            highlightthickness=2, highlightbackground='#2e2e2e',
                            cursor='crosshair')
        self.cv.pack()

        sbar = tk.Frame(cc, bg='#111')
        sbar.pack(fill='x', pady=(2, 0))
        tk.Label(sbar, textvariable=self._status_var, bg='#111', fg='#444',
                 font=('Courier', 8), anchor='w').pack(side='left', padx=4)

        # ── bindings ──────────────────────────────────────────────────────────
        self.cv.bind('<ButtonPress-1>',   self._on_press)
        self.cv.bind('<B1-Motion>',       self._on_drag)
        self.cv.bind('<ButtonRelease-1>', self._on_release)
        self.cv.bind('<Motion>',          self._on_motion)
        root.bind('<Delete>',    self._on_delete)
        root.bind('<BackSpace>', self._on_delete)
        root.bind('<Escape>',    self._on_escape)
        root.bind('<Left>',      lambda _: self._nudge(-1, 0))
        root.bind('<Right>',     lambda _: self._nudge(1, 0))
        root.bind('<Up>',        lambda _: self._nudge(0, -1))
        root.bind('<Down>',      lambda _: self._nudge(0, 1))
        root.bind('<Control-z>', lambda _: self._undo())
        root.bind('<Control-Z>', lambda _: self._undo())
        root.bind('<Control-y>', lambda _: self._redo())
        root.bind('<Control-Y>', lambda _: self._redo())
        root.bind('<Control-c>', lambda _: self._copy())
        root.bind('<Control-v>', lambda _: self._paste())

    def _entry_focused(self):
        return isinstance(self.root.focus_get(), tk.Entry)

    def _update_size_label(self):
        self._size_label.config(
            text=f'{self.oled_w}×{self.oled_h} OLED  (×{SCALE} zoom)')

    def _on_size_changed(self, *_):
        w, h = OLED_SIZES[self._size_var.get()]
        self.oled_w, self.oled_h = w, h
        self.cv.config(width=self.cw, height=self.ch)
        self._update_size_label()
        self._redraw()

    # ── coordinate helpers ────────────────────────────────────────────────────

    def _canvas_to_oled(self, cx, cy):
        x = max(0, min(self.oled_w - 1, cx // SCALE))
        y = max(0, min(self.oled_h - 1, cy // SCALE))
        if self.snap_var.get():
            x = (x // 8) * 8
            y = (y // 8) * 8
        return int(x), int(y)

    def _hit_handle(self, cx, cy):
        if self.selected is None: return -1
        for i, (hx, hy) in enumerate(self.selected.handles()):
            if abs(cx - hx) <= HANDLE_R and abs(cy - hy) <= HANDLE_R:
                return i
        return -1

    def _hit(self, cx, cy):
        for elem in reversed(self.elements):
            if elem.hit_test(cx, cy):
                return elem
        return None

    # ── canvas events ─────────────────────────────────────────────────────────

    def _on_press(self, event):
        cx, cy = event.x, event.y
        tool   = self.active_tool.get()

        hidx = self._hit_handle(cx, cy)
        if hidx >= 0:
            self._push_undo()
            self._resize_state = {
                'handle_idx':  hidx,
                'start_cx':    cx,
                'start_cy':    cy,
                'start_props': self.selected.start_props(),
            }
            return

        hit = self._hit(cx, cy)
        if hit:
            if hit is not self.selected:
                self._select(hit)
            self._push_undo()
            self._drag_start_canvas = (cx, cy)
            self._drag_start_props  = (hit.x, hit.y)
            return

        if tool:
            ox, oy = self._canvas_to_oled(cx, cy)
            self._push_undo()
            self._place(tool, ox, oy)
            self.active_tool.set('')
            return

        self._deselect()

    def _on_drag(self, event):
        cx, cy = event.x, event.y

        if self._resize_state is not None and self.selected is not None:
            rs  = self._resize_state
            ddx = (cx - rs['start_cx']) // SCALE
            ddy = (cy - rs['start_cy']) // SCALE
            self.selected.apply_resize(rs['handle_idx'], ddx, ddy, rs['start_props'])
            self._redraw()
            self._sync_props()
            return

        if self.selected is not None and self._drag_start_canvas is not None:
            ddx_o = (cx - self._drag_start_canvas[0]) // SCALE
            ddy_o = (cy - self._drag_start_canvas[1]) // SCALE
            nx = max(0, min(self.oled_w - 1, self._drag_start_props[0] + ddx_o))
            ny = max(0, min(self.oled_h - 1, self._drag_start_props[1] + ddy_o))
            if nx != self.selected.x or ny != self.selected.y:
                self.selected.x, self.selected.y = nx, ny
                self._redraw()
                self._sync_props()

    def _on_release(self, *_):
        self._drag_start_canvas = None
        self._drag_start_props  = None
        self._resize_state      = None

    def _on_delete(self, *_):
        if self._entry_focused(): return
        if self.selected:
            self._push_undo()
            self.elements.remove(self.selected)
            self.selected = None
            self._clear_props()
            self._redraw()

    def _on_escape(self, *_):
        if self._entry_focused(): return
        self.active_tool.set('')
        self._deselect()

    def _on_motion(self, event):
        ox = max(0, min(self.oled_w - 1, event.x // SCALE))
        oy = max(0, min(self.oled_h - 1, event.y // SCALE))
        n  = len(self.elements)
        self._status_var.set(
            f'x:{ox:3d}  y:{oy:3d}  |  {n} element{"s" if n != 1 else ""}')

    # ── selection / placement ─────────────────────────────────────────────────

    def _select(self, elem):
        if self.selected:
            self.selected.selected = False
        self.selected   = elem
        elem.selected   = True
        self._redraw()
        self._build_props(elem)
        self._sync_layer_highlight()
        self._update_elem_combo()

    def _deselect(self):
        if self.selected:
            self.selected.selected = False
            self.selected = None
        self._clear_props()
        self._redraw()
        self._update_elem_combo()

    def _place(self, tool, x, y):
        elem = _ELEM_CLASSES[tool](x, y)
        self.elements.append(elem)
        self._select(elem)

    def _clear(self):
        if not self.elements or messagebox.askyesno('Clear', 'Remove all elements?'):
            self._push_undo()
            self.elements.clear()
            self.selected = None
            self._clear_props()
            self._redraw()

    def _nudge(self, dx, dy):
        if self._entry_focused() or self.selected is None: return
        self._push_undo()
        self.selected.x = max(0, min(self.oled_w - 1, self.selected.x + dx))
        self.selected.y = max(0, min(self.oled_h - 1, self.selected.y + dy))
        self._redraw()
        self._sync_props()

    # ── PIL render + canvas display ───────────────────────────────────────────

    def _render_pil(self):
        """Render all elements to a 1-bit PIL image at OLED resolution."""
        img  = PIL.Image.new('1', (self.oled_w, self.oled_h), 0)
        draw = PIL.ImageDraw.Draw(img)
        for elem in self.elements:
            elem.pil_draw(draw)
        return img

    def _redraw(self):
        cv = self.cv
        cv.delete('all')

        # 1. Render PIL image and display it as a background PhotoImage
        pil_img    = self._render_pil()
        scaled     = pil_img.convert('RGB').resize((self.cw, self.ch),
                                                    PIL.Image.NEAREST)
        self._tk_image = PIL.ImageTk.PhotoImage(scaled)
        cv.create_image(0, 0, anchor='nw', image=self._tk_image)

        # 2. Grid lines on top (subtle — visible through the black background)
        for gx in range(0, self.oled_w + 1, 8):
            col = GRID_COL16 if gx % 16 == 0 else GRID_COL8
            cv.create_line(gx*SCALE, 0, gx*SCALE, self.ch, fill=col)
        for gy in range(0, self.oled_h + 1, 8):
            col = GRID_COL16 if gy % 16 == 0 else GRID_COL8
            cv.create_line(0, gy*SCALE, self.cw, gy*SCALE, fill=col)

        # 3. Per-element selection overlays (text bbox, etc.)
        for elem in self.elements:
            if elem.selected:
                elem.draw_overlay(cv)

        # 4. Resize handles for selected element
        if self.selected:
            for hx, hy in self.selected.handles():
                r = HANDLE_R
                cv.create_rectangle(hx-r, hy-r, hx+r, hy+r,
                                    fill=HANDLE_COL, outline='black')

        self._update_code()
        self._update_layer_list()
        self._update_elem_combo()

    # ── properties panel ──────────────────────────────────────────────────────

    _PROP_CHOICES = {'font_name': FONT_OPTIONS}

    def _clear_props(self):
        for w in self.prop_frame.winfo_children():
            w.destroy()
        self._prop_vars = {}

    def _build_props(self, elem):
        self._clear_props()
        tk.Label(self.prop_frame, text=elem.type_name, bg='#252525', fg='#555',
                 font=('Courier', 8)).grid(row=0, column=0, columnspan=2,
                                           sticky='w', pady=(0, 6))
        for row, prop in enumerate(elem.PROPS, start=1):
            tk.Label(self.prop_frame, text=prop + ':', bg='#252525', fg='#aaa',
                     font=('Courier', 10), anchor='e', width=9).grid(
                     row=row, column=0, sticky='e', pady=2)
            var = tk.StringVar(value=str(getattr(elem, prop)))
            self._prop_vars[prop] = var
            choices = self._PROP_CHOICES.get(prop)
            if choices:
                w = ttk.Combobox(self.prop_frame, textvariable=var,
                                 values=choices, state='readonly',
                                 font=('Courier', 9), width=11)
            else:
                w = tk.Entry(self.prop_frame, textvariable=var, width=12,
                             bg='#111', fg='white', insertbackground='white',
                             font=('Courier', 10), relief='flat')
            w.grid(row=row, column=1, padx=4, pady=2, sticky='w')
            var.trace_add('write', lambda *_, p=prop, v=var, e=elem:
                          self._prop_changed(e, p, v))

    def _prop_changed(self, elem, prop, var):
        raw     = var.get()
        current = getattr(elem, prop)
        if isinstance(current, int):
            try:    setattr(elem, prop, int(raw))
            except: return  # noqa: E722
        else:
            setattr(elem, prop, raw)
        self._redraw()

    def _sync_props(self):
        if not self.selected: return
        for prop, var in self._prop_vars.items():
            new = str(getattr(self.selected, prop))
            if var.get() != new:
                var.set(new)

    # ── element combo ─────────────────────────────────────────────────────────

    def _update_elem_combo(self):
        if self._elem_combo_var is None: return
        labels = [f'#{i+1} {e.label()}' for i, e in enumerate(self.elements)]
        self.elem_combo['values'] = labels
        if self.selected and self.selected in self.elements:
            self._elem_combo_var.set(labels[self.elements.index(self.selected)])
        else:
            self._elem_combo_var.set('— none —')

    def _on_combo_select(self, *_):
        idx = self.elem_combo.current()
        if 0 <= idx < len(self.elements):
            self._select(self.elements[idx])

    # ── layer list ────────────────────────────────────────────────────────────

    def _update_layer_list(self):
        self._updating_layers = True
        try:
            lb = self.layer_lb
            lb.delete(0, 'end')
            for elem in reversed(self.elements):
                lb.insert('end', elem.label())
            self._sync_layer_highlight()
        finally:
            self._updating_layers = False

    def _sync_layer_highlight(self):
        lb = self.layer_lb
        lb.selection_clear(0, 'end')
        if self.selected is not None:
            try:
                idx = list(reversed(self.elements)).index(self.selected)
                lb.selection_set(idx)
                lb.see(idx)
            except ValueError:
                pass

    def _on_layer_select(self, *_):
        if self._updating_layers: return
        sel = self.layer_lb.curselection()
        if not sel: return
        self._select(list(reversed(self.elements))[sel[0]])

    def _layer_up(self):
        if self.selected is None: return
        i = self.elements.index(self.selected)
        if i < len(self.elements) - 1:
            self._push_undo()
            self.elements[i], self.elements[i+1] = self.elements[i+1], self.elements[i]
            self._redraw()

    def _layer_down(self):
        if self.selected is None: return
        i = self.elements.index(self.selected)
        if i > 0:
            self._push_undo()
            self.elements[i], self.elements[i-1] = self.elements[i-1], self.elements[i]
            self._redraw()

    # ── code panel ────────────────────────────────────────────────────────────

    def _update_code(self):
        name  = self.screen_name.get().strip() or 'my_screen'
        lines = [f'async def show_{name}(self):',
                 '    with canvas(self.device) as draw:']
        if self.elements:
            for elem in self.elements:
                line = elem.code_line()
                tag  = '  # ← wire {tag} to Redis' if '{' in line else ''
                lines.append(f'        {line}{tag}')
        else:
            lines.append('        pass')
        self.code_text.configure(state='normal')
        self.code_text.delete('1.0', 'end')
        self.code_text.insert('1.0', '\n'.join(lines))
        self.code_text.configure(state='disabled')

    def _copy_code(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.code_text.get('1.0', 'end').strip())

    # ── undo / redo ───────────────────────────────────────────────────────────

    def _push_undo(self):
        self._undo_stack.append(copy.deepcopy(self.elements))
        self._redo_stack.clear()
        if len(self._undo_stack) > 50:
            self._undo_stack.pop(0)

    def _undo(self):
        if self._entry_focused() or not self._undo_stack: return
        self._redo_stack.append(copy.deepcopy(self.elements))
        self.elements = self._undo_stack.pop()
        self.selected = None
        self._clear_props()
        self._redraw()

    def _redo(self):
        if self._entry_focused() or not self._redo_stack: return
        self._undo_stack.append(copy.deepcopy(self.elements))
        self.elements = self._redo_stack.pop()
        self.selected = None
        self._clear_props()
        self._redraw()

    # ── copy / paste ──────────────────────────────────────────────────────────

    def _copy(self):
        if self._entry_focused(): return
        if self.selected:
            self._clipboard = copy.deepcopy(self.selected)

    def _paste(self):
        if self._clipboard is None: return
        self._push_undo()
        elem = copy.deepcopy(self._clipboard)
        Element._counter += 1
        elem.eid      = Element._counter
        elem.x        = min(self.oled_w - 1, elem.x + 4)
        elem.y        = min(self.oled_h - 1, elem.y + 4)
        elem.selected = False
        self.elements.append(elem)
        self._select(elem)

    # ── save / load ───────────────────────────────────────────────────────────

    def _save(self):
        path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON layout', '*.json'), ('All files', '*.*')],
            initialdir=os.path.dirname(os.path.abspath(__file__)),
            title='Save layout')
        if not path: return
        with open(path, 'w') as f:
            json.dump({
                'screen_name': self.screen_name.get(),
                'oled_size':   self._size_var.get(),
                'oled_w':      self.oled_w,
                'oled_h':      self.oled_h,
                'elements':    [e.to_dict() for e in self.elements],
            }, f, indent=2)

    def _load(self):
        path = filedialog.askopenfilename(
            filetypes=[('JSON layout', '*.json'), ('All files', '*.*')],
            initialdir=os.path.dirname(os.path.abspath(__file__)),
            title='Load layout')
        if not path: return
        try:
            with open(path) as f:
                data = json.load(f)
            self._push_undo()
            self.elements = [e for d in data.get('elements', [])
                             if (e := _elem_from_dict(d)) is not None]
            if 'screen_name' in data:
                self.screen_name.set(data['screen_name'])
            if 'oled_size' in data and data['oled_size'] in OLED_SIZES:
                self._size_var.set(data['oled_size'])
                self._on_size_changed()
            elif 'oled_w' in data and 'oled_h' in data:
                self.oled_w = data['oled_w']
                self.oled_h = data['oled_h']
                self.cv.config(width=self.cw, height=self.ch)
                self._update_size_label()
            self.selected = None
            self._clear_props()
            self._redraw()
        except Exception as ex:
            messagebox.showerror('Load failed', str(ex))


# ── entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    root = tk.Tk()
    DesignerApp(root)
    root.mainloop()
