"""
tft/tft_overlay.py
Right-Top: Stats | Action | Clock | Items(20px) | Carousel(15px)
Right-Bot: Econ(115) | Rolldown(115) | Bench/Sell(90) | Upgrade/Risk(180)
Augment select only in BottomStrip COMP/BUY, not in BENCH/SELL.
"""
import tkinter as tk
import tkinter.font as tk_font
import time
import re
import logging
_log=logging.getLogger("rc.tft.overlay")
BG="#0b0b12"; BG_SEC="#111119"; BG_FIELD="#16161f"; BORDER="#252535"; LABEL_C="#9090aa"
C={"action":"#ff2244","board":"#4affaa","items":"#4ab0ff","carousel":"#ffd700",
   "econ":"#a8c023","rolldown":"#ff9944","placement":"#c77dff","upgrade":"#44ffcc",
   "risk":"#ff4a6a","clock":"#ffdd00","stats":"#d0d0e0","live":"#a8e6cf","bench":"#c77dff"}
_LBL=("Consolas",10,"bold"); _LBL_HD=("Consolas",12,"bold")
_VAL_LG=("Segoe UI",14,"bold"); _BODY=("Segoe UI",12)
TAG_RE=re.compile(r'\[A\](.*?)\[/A\]|\[E\](.*?)\[/E\]|\[T\](.*?)\[/T\]',re.DOTALL)
_ROW_COLORS={"A":"#ff5533","B":"#ffcc22","C":"#cc66ff","D":"#33aaff"}
_ROW_TO_GAMEROW={"A":4,"B":3,"C":2,"D":1}
_CELL_BG={"A":"#5a1a10","B":"#4a3a08","C":"#3a1a4a","D":"#0a2a4a"}
_CELL_BG_EMPTY="#1c1c2e"; _CELL_BORDER="#2a2a48"
_ITEM_NAMES={"IE":"Infinity Edge","BT":"Bloodthirster","RB":"Guinsoo's Rageblade","JG":"Jeweled Gauntlet","DC":"Rabadon's Deathcap","BB":"Blue Buff","SS":"Spear of Shojin","GS":"Giant Slayer","LW":"Last Whisper","TR":"Titan's Resolve","WM":"Warmog's Armor","SC":"Sunfire Cape","DB":"Dragon's Claw","GG":"Gargoyle Stoneplate","RD":"Redemption","BV":"Bramble Vest","IS":"Ionic Spark","RH":"Runaan's Hurricane","HJ":"Hand of Justice","RF":"Rapid Firecannon","ZP":"Zephyr","SR":"Shroud of Stillness","AS":"Archangel's Staff","QS":"Quicksilver","GA":"Guardian Angel","MR":"Morellonomicon","SH":"Statikk Shiv"}

# Set 17 unit roster — (name, cost) for ROSTER panel
_SET17_UNITS = [
    ("Cho'Gath",1),("Lissandra",1),("Maokai",1),("Meepsie",1),("Nunu & Willump",1),("Riven",1),
    ("Blitzcrank",2),("Briar",2),("Fizz",2),("Gragas",2),("Nasus",2),("Poppy",2),("Rammus",2),("Urgot",2),
    ("Akali",3),("Ekko",3),("Ezreal",3),("Gnar",3),("Kai'Sa",3),("Morgana",3),("Samira",3),
    ("Shen",3),("Talon",3),("Vex",3),
    ("Aatrox",4),("Corki",4),("Diana",4),("Gwen",4),("Jhin",4),("Karma",4),
    ("Leona",4),("Lulu",4),("Viktor",4),("Xayah",4),
    ("Aurelion Sol",5),("Bel'Veth",5),("Jinx",5),("Miss Fortune",5),("Rhaast",5),("Yasuo",5),("Zoe",5),
]
_UNIT_COST_COLORS={1:"#909090",2:"#22bb22",3:"#3388ff",4:"#cc44ff",5:"#ffaa00"}
_UNIT_COST_BG    ={1:"#1a1a1a",2:"#0a1a0a",3:"#0a0a2a",4:"#1a0a2a",5:"#1a1200"}

def _write_unit_presence(board_confirmed, extra_present, manual_level=None):
    """Atomic write of manually confirmed unit presence + current level."""
    import json as _j, time as _t
    from pathlib import Path as _P
    try:
        fp = _P(__file__).parent.parent / "data" / "unit_presence.json"
        # Preserve existing manual_level if not explicitly updating
        _existing = {}
        try:
            if fp.exists(): _existing = _j.loads(fp.read_text(encoding="utf-8"))
        except Exception: pass
        _lv = manual_level if manual_level is not None else _existing.get("manual_level")
        _d = {
            "board_confirmed": sorted(str(u) for u in board_confirmed),
            "extra_present":   sorted(str(u) for u in extra_present),
            "timestamp": int(_t.time()),
        }
        if _lv is not None: _d["manual_level"] = _lv
        tmp = fp.with_suffix(".tmp")
        tmp.write_text(_j.dumps(_d, indent=2), encoding="utf-8")
        tmp.replace(fp)
    except Exception:
        pass
def _expand_items(text):
    if not text: return ""
    codes=re.findall(r'\b([A-Z]{2,3})\b',text); expanded=[]
    for c in codes:
        f=_ITEM_NAMES.get(c)
        if f: expanded.append(f"{c} = {f}")
    return "\n".join(expanded) if expanded else ""

def _tempo_context(stage, rnd, level):
    """Set 17 tempo context for ACTION bar.
    Stage/round timing milestones based on standard Set 17 level curve.
    Conservative wording — exact meta timing varies by comp and patch.
    """
    # Set 17 standard level-up timing milestones
    _TEMPO = {
        (2,1): "Lv4 if strong pairs",
        (2,3): "Econ to 20g+",
        (2,5): "Lv5 if strong board",
        (3,1): "Realm of Gods — grab carry component",
        (3,2): "Lv6 + roll to stabilize",
        (3,5): "Lv7 or roll aggressive",
        (4,1): "Lv7/8 — tempo rolldown",
        (4,2): "Fast 8 rolldown (50g+)",
        (4,4): "God Boon armory — pick carry item or emblem",
        (4,5): "Lv9 if econ aug + streak",
        (5,1): "Lv9 standard timing",
        (5,2): "Roll for 2-star 4/5 costs",
        (5,5): "Final stabilize or all-in",
        (6,1): "Cap board — 5-cost upgrades",
    }
    tip = _TEMPO.get((stage, rnd), "")
    # Gold + interest from vision
    gold_str = ""
    try:
        import json as _j; from pathlib import Path as _P
        _ld = _j.loads((_P(__file__).parent.parent / "data" / "tft_live_data.json").read_text())
        _g = _ld.get("gold")
        if _g and isinstance(_g, (int, float)) and _g > 0:
            interest = min(5, int(_g) // 10)
            gold_str = f"{int(_g)}g +{interest}i"
    except Exception:
        pass
    parts = [p for p in [tip, gold_str] if p]
    return " | ".join(parts) if parts else ""

class _Tooltip:
    def __init__(self,widget,text_func):
        self._widget=widget;self._text_func=text_func;self._tw=None
        widget.bind("<Enter>",self._show);widget.bind("<Leave>",self._hide)
    def _show(self,event):
        text=self._text_func()
        if not text: return
        x=event.x_root+12;y=event.y_root+8;self._tw=tw=tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True);tw.attributes("-topmost",True);tw.wm_geometry(f"+{x}+{y}")
        tk.Label(tw,text=text,bg="#1a1a2a",fg="#d0d0e0",font=("Segoe UI",9),justify="left",relief="solid",borderwidth=1,padx=6,pady=4).pack()
    def _hide(self,event):
        if self._tw: self._tw.destroy();self._tw=None
def _bind_right_click(w,cb):
    def _h(e): cb(); return "break"
    w.bind("<Button-3>",_h)
    for c in w.winfo_children(): _bind_right_click(c,cb)
def _strip(t): return re.sub(r'\[/?[AET]\]','',t) if t else ""
def _write_rich(w,text,bc):
    w.configure(state="normal");w.delete("1.0","end")
    if text and len(text)>200: text=text[:197]+"...";text=text or "\u2014"
    if TAG_RE.search(text):
        pos=0
        for m in TAG_RE.finditer(text):
            if m.start()>pos: w.insert("end",_strip(text[pos:m.start()]),"base")
            a,e,t=m.group(1),m.group(2),m.group(3)
            if a: w.insert("end",a,"ally")
            elif e: w.insert("end",e,"enemy")
            elif t: w.insert("end",t,"time")
            pos=m.end()
        if pos<len(text): w.insert("end",_strip(text[pos:]),"base")
    else: w.insert("end",_strip(text),"base")
    w.configure(state="disabled")
def _make_txt(p,fg,font=None):
    bf=tk_font.Font(family="Segoe UI",size=12,weight="bold")
    w=tk.Text(p,bg=BG_SEC,fg=fg,font=font or _BODY,wrap="word",bd=0,highlightthickness=0,insertbackground=BG_SEC,state="disabled",cursor="arrow",padx=8,pady=2,height=3)
    w.tag_configure("ally",foreground="#44ff88",font=bf);w.tag_configure("enemy",foreground="#ff4444",font=bf)
    w.tag_configure("time",foreground="#ffdd00",font=bf);w.tag_configure("base",foreground=fg)
    return w
def _sec(p,row,label,color,minsize=80):
    f=tk.Frame(p,bg=BG_SEC,highlightbackground=BORDER,highlightthickness=1)
    f.grid(row=row,column=0,sticky="nsew",pady=(2,0))
    tk.Label(f,text=label,bg=BG_SEC,fg=LABEL_C,font=_LBL_HD,anchor="w").pack(anchor="w",padx=8,pady=(4,0))
    txt=_make_txt(f,color);txt.pack(fill="both",expand=True,pady=(0,4))
    p.rowconfigure(row,weight=1,minsize=minsize);return txt
def _bar(p,row,label,color,minsize=40):
    f=tk.Frame(p,bg=BG,highlightbackground=BORDER,highlightthickness=1)
    f.grid(row=row,column=0,sticky="nsew",pady=(2,0))
    tk.Label(f,text=label,bg=BG,fg=LABEL_C,font=_LBL,anchor="w").pack(side="left",padx=(8,4),pady=(5,5))
    var=tk.StringVar(value="\u2014")
    lbl=tk.Label(f,textvariable=var,bg=BG,fg=color,font=_VAL_LG,anchor="w",wraplength=220,justify="left")
    lbl.pack(side="left",fill="both",expand=True,padx=(0,8),pady=(3,3))
    p.rowconfigure(row,weight=0,minsize=minsize);return var,lbl
def _parse_placement(text):
    rows={"A":[],"B":[],"C":[],"D":[]}
    if not text or text=="\u2014": return rows
    chunks=re.split(r'[,;]+',text)
    pat=re.compile(r"([A-Za-z][A-Za-z'\- ]*?)\s+([A-Da-d])(\d)\s*(.*)",re.IGNORECASE)
    for chunk in chunks:
        m=pat.search(chunk.strip())
        if m:
            name=m.group(1).strip();rl=m.group(2).upper();col=m.group(3);items=m.group(4).strip();entry=f"{name} {col}"
            if items: entry+=f" {items}"
            if rl in rows: rows[rl].append(entry)
    if not any(rows.values()):
        rm={"4":"A","3":"B","2":"C","1":"D"}
        for m in re.finditer(r'(\w+)\s*(?:->|\u2192)\s*col\s*(\d+)\s*row\s*(\d)',text,re.IGNORECASE):
            rl=rm.get(m.group(3))
            if rl: rows[rl].append(f"{m.group(1)} {m.group(2)}")
    return rows
def _parse_board_units(text,whitelist=None):
    grid={}
    if not text or text=="\u2014": return grid
    wl_lower=set()
    if whitelist:
        for u in whitelist:
            if u and u not in ("empty","unknown","SPECTATING"): wl_lower.add(str(u).lower().split()[0].strip())
    chunks=re.split(r'[,;]+',text)
    pat=re.compile(r"([A-Za-z][A-Za-z'\- ]*?)\s+([A-Da-d])(\d)",re.IGNORECASE)
    for chunk in chunks:
        m=pat.search(chunk.strip())
        if m:
            name=m.group(1).strip();rl=m.group(2).upper();col=int(m.group(3));gr=_ROW_TO_GAMEROW.get(rl,1)
            if 1<=col<=7:
                if wl_lower:
                    nl=name.lower()
                    if not any(nl.startswith(w) or w.startswith(nl) for w in wl_lower): continue
                grid[(gr,col)]=(name[:8] if len(name)>8 else name,rl)
    return grid
class TftBoardCanvas(tk.Frame):
    def __init__(self,parent,cell_w=81,cell_h=23,lpad=34,tpad=14,bpad=10):
        super().__init__(parent,bg=BG_SEC)
        self.CELL_W,self.CELL_H,self.LPAD,self.TPAD,self.BPAD=cell_w,cell_h,lpad,tpad,bpad
        w=lpad+7*cell_w+cell_w//2+8;h=tpad+4*cell_h+bpad+4
        self.canvas=tk.Canvas(self,bg=BG_SEC,width=w,height=h,bd=0,highlightthickness=0)
        self.canvas.pack(expand=True,padx=4,pady=1)
        self._unit_grid={}
        self._confirmed_units=set()   # manually confirmed "on board right now"
        self._presence_cb=None        # callback(name, bool)
        self._heatmap_data={}         # loaded from placement_heatmap.json
        self._heatmap_mode=False      # True = show position frequency overlay
        self.canvas.bind("<Button-1>",self._on_cell_click)
        self._redraw()
    def set_carry_units(self, carries):
        """Set which units are carries/core (for star marker)."""
        self._carry_units = {str(u).lower().split()[0] for u in (carries or [])}

    def set_target_stars(self, stars_map):
        """Set target star levels per unit (e.g. {'Kai\'Sa':3, 'Talon':2})."""
        self._target_stars = {str(k).lower(): v for k, v in (stars_map or {}).items()}

    def set_owned_units(self, owned):
        """Set which units player currently owns (for green outline)."""
        self._owned_units = {str(u).lower().split()[0] for u in (owned or []) if u and u not in ("unknown","empty","SPECTATING")}

    def _get_unit_cost(self, name):
        try:
            import json as _j; from pathlib import Path as _P
            _mf = _P(__file__).parent.parent / "data" / "meta" / "tft_set17_meta.json"
            if _mf.exists():
                _md = _j.loads(_mf.read_text(encoding="utf-8"))
                return _md.get("unit_costs", {}).get(name)
        except Exception: pass
        return None

    def _show_cost_tip(self, event, name, cost):
        if hasattr(self, '_cost_tw') and self._cost_tw:
            self._cost_tw.destroy()
        x = event.x_root + 12; y = event.y_root + 8
        self._cost_tw = tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True); tw.attributes("-topmost", False)
        tw.wm_geometry(f"+{x}+{y}")
        _cc = {1:"#888888",2:"#22aa22",3:"#2288ff",4:"#cc44ff",5:"#ffaa00"}.get(cost, "#cccccc")
        tk.Label(tw, text=f"{name} ({cost}g)", bg="#1a1a2a", fg=_cc,
                 font=("Segoe UI", 10, "bold"), relief="solid", borderwidth=1, padx=8, pady=4).pack()

    def _hide_cost_tip(self, event=None):
        try:
            if hasattr(self, '_cost_tw') and self._cost_tw:
                self._cost_tw.destroy()
        except Exception: pass
        self._cost_tw = None

    # -- Heatmap overlay --------------------------------------------------

    def load_heatmap(self):
        """Load placement_heatmap.json into memory."""
        try:
            import json as _j; from pathlib import Path as _P
            _hf = _P(__file__).parent.parent / "data" / "placement_heatmap.json"
            if _hf.exists():
                _d = _j.loads(_hf.read_text(encoding="utf-8"))
                self._heatmap_data = _d.get("positions", {})
        except Exception: pass

    def toggle_heatmap(self):
        self._heatmap_mode = not self._heatmap_mode
        if self._heatmap_mode: self.load_heatmap()
        self._redraw()
        return self._heatmap_mode

    def _heatmap_color(self, pct: float) -> tuple:
        """Map 0-100% frequency to (fill_color, text_color)."""
        if pct >= 75:  return "#004422", "#00ff88"
        if pct >= 50:  return "#002233", "#00ccff"
        if pct >= 25:  return "#0a1a2a", "#4499bb"
        if pct >= 10:  return "#0a0a1a", "#336677"
        return "#0a0a14", "#223344"

    def _draw_heatmap(self):
        """Render heatmap overlay: historical unit positions with frequency color."""
        cv = self.canvas; cv.delete("all")
        lp,tp,cw,ch = self.LPAD,self.TPAD,self.CELL_W,self.CELL_H
        _ROW_LABEL = {4:"A",3:"B",2:"C",1:"D"}
        # Column headers
        for col in range(1,8):
            cv.create_text(lp+(col-1)*cw+cw//2,tp-5,text=str(col),fill="#667788",font=("Consolas",8,"bold"))
        # Row labels
        for dr,(gr,rl) in enumerate([(4,"A"),(3,"B"),(2,"C"),(1,"D")]):
            y=tp+dr*ch; _xoff=cw//2 if rl in ("A","C") else 0
            cv.create_text(lp-4+_xoff,y+ch//2,text=rl,fill=_ROW_COLORS[rl],font=("Consolas",9,"bold"),anchor="e")
            for col in range(1,8):
                x=lp+_xoff+(col-1)*cw
                cv.create_rectangle(x+1,y+1,x+cw-1,y+ch-1,fill=_CELL_BG_EMPTY,outline=_CELL_BORDER,width=1)
        # Draw all units with frequency > 0
        _CELL_KEY = {f"{r}{c}":(gr,c) for dr,(gr,rl) in enumerate([(4,"A"),(3,"B"),(2,"C"),(1,"D")]) for c in range(1,8) for r in [rl]}
        for unit, udata in self._heatmap_data.items():
            for cell, cdata in (udata.get("cells") or {}).items():
                pct = cdata.get("pct", 0)
                if pct < 5: continue  # skip noise
                key = _CELL_KEY.get(cell)
                if not key: continue
                gr, col = key
                dr = [i for i,(g,_) in enumerate([(4,"A"),(3,"B"),(2,"C"),(1,"D")]) if g==gr]
                if not dr: continue
                rl = ["A","B","C","D"][dr[0]]
                _xoff = cw//2 if rl in ("A","C") else 0
                x = lp + _xoff + (col-1)*cw
                y = tp + dr[0]*ch
                fill, fg = self._heatmap_color(pct)
                cv.create_rectangle(x+1,y+1,x+cw-1,y+ch-1,fill=fill,outline=fg,width=1)
                short = unit[:6]
                cv.create_text(x+cw//2,y+ch//2-4,text=short,fill=fg,font=("Consolas",8,"bold"))
                cv.create_text(x+cw//2,y+ch//2+5,text=f"{pct:.0f}%",fill=fg,font=("Consolas",7))

    def set_presence_callback(self,cb):
        self._presence_cb=cb

    def get_confirmed_units(self):
        return set(self._confirmed_units)

    def reset_confirmed(self):
        self._confirmed_units.clear(); self._redraw()

    def _on_cell_click(self,event):
        """Map canvas click to cell and toggle confirmed state."""
        cx,cy=event.x,event.y
        lp,tp,cw,ch=self.LPAD,self.TPAD,self.CELL_W,self.CELL_H
        row_info=[(4,"A"),(3,"B"),(2,"C"),(1,"D")]
        dr=(cy-tp)//ch
        if dr<0 or dr>=len(row_info): return
        gr,rl=row_info[dr]
        xoff=cw//2 if rl in ("A","C") else 0
        col=(cx-lp-xoff)//cw+1
        if col<1 or col>7: return
        ui=self._unit_grid.get((gr,col))
        if not ui: return
        name,_=ui; nl=name.lower()
        if nl in self._confirmed_units:
            self._confirmed_units.discard(nl); confirmed=False
        else:
            self._confirmed_units.add(nl); confirmed=True
        self._redraw()
        if self._presence_cb:
            try: self._presence_cb(name,confirmed)
            except Exception: pass

    def update_board_units(self,text,whitelist=None):
        self._unit_grid=_parse_board_units(text,whitelist);self._redraw()
    def _redraw(self):
        if self._heatmap_mode: self._draw_heatmap(); return
        cv=self.canvas;cv.delete("all");self._hide_cost_tip();lp,tp,cw,ch=self.LPAD,self.TPAD,self.CELL_W,self.CELL_H
        for col in range(1,8): cv.create_text(lp+(col-1)*cw+cw//2,tp-5,text=str(col),fill="#667788",font=("Consolas",8,"bold"))
        for dr,(gr,rl) in enumerate([(4,"A"),(3,"B"),(2,"C"),(1,"D")]):
            y=tp+dr*ch;_ro=cw//2 if rl in ('A','C') else 0;cv.create_text(lp-4+_ro,y+ch//2,text=rl,fill=_ROW_COLORS[rl],font=("Consolas",9,"bold"),anchor="e")
            _xoff = cw//2 if rl in ('A','C') else 0
            for col in range(1,8):
                x=lp+_xoff+(col-1)*cw;ui=self._unit_grid.get((gr,col))
                if ui:
                    nm,rl2=ui;bg=_CELL_BG.get(rl2,_CELL_BG_EMPTY)
                    # Outline: confirmed (bright green) > owned (pale green) > row color
                    _nl=nm.lower()
                    _confirmed=_nl in self._confirmed_units
                    _owned=hasattr(self,'_owned_units') and _nl in self._owned_units
                    _outline="#00ff88" if _confirmed else ("#44ff88" if _owned else _ROW_COLORS[rl2])
                    _ow=2 if (_confirmed or _owned) else 1
                    cv.create_rectangle(x+1,y+1,x+cw-1,y+ch-1,fill=bg,outline=_outline,width=_ow)
                    _is_carry = hasattr(self, '_carry_units') and nm.lower() in self._carry_units
                    _stars = ""
                    if hasattr(self, '_target_stars'):
                        _sv = self._target_stars.get(nm.lower(), 0)
                        if _sv: _stars = f" {_sv}"
                    _disp = f"\u2605{nm}{_stars}" if _is_carry else f"{nm}{_stars}"
                    _fg = "#FFD700" if _is_carry else "white"
                    cv.create_text(x+cw//2,y+ch//2,text=_disp,fill=_fg,font=("Consolas",9,"bold"))
                    # Cost tooltip tag
                    _tag = f"cell_{gr}_{col}"
                    cv.addtag_withtag(_tag, cv.find_closest(x+cw//2, y+ch//2)[0])
                    _cost = self._get_unit_cost(nm)
                    if _cost:
                        cv.tag_bind(_tag, "<Enter>", lambda e, n=nm, c=_cost: self._show_cost_tip(e, n, c))
                        cv.tag_bind(_tag, "<Leave>", self._hide_cost_tip)
                else: cv.create_rectangle(x+1,y+1,x+cw-1,y+ch-1,fill=_CELL_BG_EMPTY,outline=_CELL_BORDER,width=1)
class TftRightTop(tk.Toplevel):
    GEO={"x":1600,"y":0,"w":320,"h":335}
    def __init__(self,root):
        super().__init__(root);g=self.GEO;self.overrideredirect(True);self.attributes("-topmost",True)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}");self.configure(bg=BG)
        con=tk.Frame(self,bg=BG);con.pack(fill="both",expand=True,padx=1,pady=1);con.columnconfigure(0,weight=1)
        sf=tk.Frame(con,bg=BG_FIELD,highlightbackground=BORDER,highlightthickness=1);sf.grid(row=0,column=0,sticky="nsew")
        sr=tk.Frame(sf,bg=BG_FIELD);sr.pack(fill="x",padx=6,pady=4);self._stats={}
        for col,(k,t) in enumerate([("stage","1-1"),("level","Lv1"),("hp","HP?"),("gold","8P")]):
            lb=tk.Label(sr,text=t,bg=BG_FIELD,fg=C["stats"],font=("Consolas",11,"bold"))
            lb.grid(row=0,column=col,padx=4);self._stats[k]=lb
        for c in range(4): sr.columnconfigure(c,weight=1)
        con.rowconfigure(0,weight=0,minsize=36)
        self._clock_var,_=_bar(con,1,"CLOCK",C["clock"],minsize=36)
        self._clock_base=0.0;self._clock_wall=0.0;self._clock_job=None
        self._force_scan_cb = None
        self._build_command_panel(con, 2)
        self._items_txt=_sec(con,3,"ITEMS",C["items"],minsize=90)

    def set_force_scan_cb(self, cb):
        """Wire force scan callback for AUG button."""
        self._force_scan_cb = cb

    def _build_command_panel(self, parent, row):
        """COMMAND panel: text input to Claude + AUG/God refresh button."""
        f = tk.Frame(parent, bg=BG_SEC,
                     highlightbackground=BORDER, highlightthickness=1)
        f.grid(row=row, column=0, sticky="nsew", pady=(2, 0))

        # Header row: label only (AUG button moved to COMP/BUY panel)
        hdr = tk.Frame(f, bg=BG_SEC)
        hdr.pack(fill="x", padx=4, pady=(4, 2))
        tk.Label(hdr, text="COMMAND", bg=BG_SEC, fg=LABEL_C,
                 font=_LBL_HD, anchor="w").pack(side="left")

        # Entry row
        er = tk.Frame(f, bg=BG_SEC)
        er.pack(fill="x", padx=4, pady=(0, 2))
        self._cmd_entry = tk.Entry(
            er, bg=BG_FIELD, fg="#ffffff", insertbackground="#8888cc",
            font=("Consolas", 9), relief="flat", bd=0,
            highlightthickness=1, highlightbackground=BORDER)
        self._cmd_entry.pack(side="left", fill="x", expand=True, ipady=3)
        self._cmd_entry.bind("<Return>", lambda e: self._send_command())
        tk.Button(
            er, text="→", bg="#0a1a2a", fg="#4ab0ff",
            font=("Consolas", 11, "bold"), relief="flat", bd=0,
            padx=6, pady=0, cursor="hand2",
            activebackground="#1a2a3a", activeforeground="#88ddff",
            command=self._send_command).pack(side="left", padx=(3, 0))
        tk.Button(
            er, text="PUSH", bg="#0a1a0a", fg="#44ff88",
            font=("Consolas", 8, "bold"), relief="flat", bd=0,
            padx=5, pady=0, cursor="hand2",
            activebackground="#1a2a1a", activeforeground="#88ffaa",
            command=self._push_to_planner).pack(side="left", padx=(2, 0))

        # Response area
        self._cmd_resp = tk.Text(
            f, bg=BG_SEC, fg="#aaaacc", font=("Segoe UI", 8),
            wrap="word", bd=0, highlightthickness=0,
            state="disabled", height=2, cursor="arrow")
        self._cmd_resp.pack(fill="both", expand=True, padx=4, pady=(0, 4))
        parent.rowconfigure(row, weight=1, minsize=90)

    def _push_to_planner(self):
        """PUSH button: push current comp to team planner via LCU."""
        if not hasattr(self, '_comp_ctrl_ref') or not self._comp_ctrl_ref:
            self._cmd_set_resp("No comp control wired")
            return
        try:
            result = self._comp_ctrl_ref.push_to_planner()
            self._cmd_set_resp(result)
        except Exception as e:
            self._cmd_set_resp(f"Push error: {e}")

    def set_comp_ctrl_ref(self, ctrl) -> None:
        """Wire the CompControl so PUSH button can call push_to_planner."""
        self._comp_ctrl_ref = ctrl

    def _do_aug_refresh(self):
        """Force scan for augment/god pick — button fallback."""
        if self._force_scan_cb:
            try:
                self._force_scan_cb()
                self._cmd_set_resp("⟳ Aug/God scan fired")
            except Exception as _e:
                self._cmd_set_resp(f"Scan error: {_e}")
        else:
            self._cmd_set_resp("No scan callback wired")

    def _send_command(self):
        """Send entry text to Claude, show response in panel."""
        import threading
        text = self._cmd_entry.get().strip()
        if not text:
            return
        self._cmd_entry.delete(0, "end")
        self._cmd_set_resp("⋯ thinking...")
        threading.Thread(target=self._claude_cmd, args=(text,),
                         daemon=True, name="CmdPanel").start()

    def _cmd_set_resp(self, text):
        """Thread-safe response update."""
        def _apply():
            try:
                self._cmd_resp.configure(state="normal")
                self._cmd_resp.delete("1.0", "end")
                self._cmd_resp.insert("end", text[:300])
                self._cmd_resp.configure(state="disabled")
            except Exception:
                pass
        try:
            self.after(0, _apply)
        except Exception:
            pass

    def _claude_cmd(self, user_text):
        """Background: call Claude Haiku with command + game context."""
        import json as _j, urllib.request as _ur
        from pathlib import Path as _P
        try:
            _root = _P(__file__).parent.parent
            _key = (_root / "API-Key-Claude.txt").read_text(encoding="utf-8").strip()
            _live = {}
            _comp = ""
            try:
                _live = _j.loads((_root / "data" / "tft_live_data.json").read_text())
            except Exception:
                pass
            try:
                _comp = _j.loads((_root / "data" / "comp_state.json").read_text()).get("selected", "")
            except Exception:
                pass
            _ctx = (f"Comp:{_comp} Stage:{_live.get('stage_round','?')} "
                    f"Lv:{_live.get('level','?')} HP:{_live.get('hp','?')}")
            _payload = _j.dumps({
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 120,
                "system": ("Riot Commander TFT overlay assistant. "
                           "User sends quick in-game commands: UI fixes, "
                           "coaching questions, bug notes, coach updates. "
                           "Reply in 1-2 sentences max. Be direct and concise."),
                "messages": [{"role": "user",
                               "content": f"[{_ctx}] {user_text}"}]
            }).encode()
            _req = _ur.Request(
                "https://api.anthropic.com/v1/messages", data=_payload,
                headers={"Content-Type": "application/json",
                         "x-api-key": _key,
                         "anthropic-version": "2023-06-01"})
            with _ur.urlopen(_req, timeout=15) as _r:
                _resp = _j.loads(_r.read().decode())
            _out = _resp["content"][0]["text"].strip()
        except Exception as _e:
            _out = f"Error: {str(_e)[:80]}"
        self._cmd_set_resp(_out)

    def bind_force_scan(self, cb, ai_bar=None):
        """CTRL+Right Click on top panel for force scan."""
        _ai = ai_bar
        def _do():
            cb()
            _write_rich(self._items_txt, "\u21bb Scanning...", "#ffdd00")
            if _ai:
                try: _ai.set_force_scan()
                except Exception: pass
        _bind_ctrl_right_click(self, _do)
    def sync_clock(self,t):
        self._clock_base=t;self._clock_wall=time.monotonic()
        if self._clock_job is None: self._tick()
    def _tick(self):
        if self._clock_wall>0:
            total=max(0,self._clock_base+time.monotonic()-self._clock_wall)
            self._clock_var.set(f"{int(total//60)}:{int(total%60):02d}")
        self._clock_job=self.after(1000,self._tick)
    def destroy_clock(self):
        if self._clock_job:
            try: self.after_cancel(self._clock_job)
            except Exception: pass
    def update(self,data):
        self._stats["stage"].configure(text=f"{data.get('stage','?')}-{data.get('round','?')}")
        self._stats["level"].configure(text=f"Lv{data.get('level','?')}")
        _stage = data.get("stage", 1)
        _api_hp = data.get("health", 0)
        _hp = _api_hp if _api_hp and 0 < _api_hp < 100 else None
        if not _hp:
            try:
                import json as _j; from pathlib import Path as _P
                _ld = _j.loads((_P(__file__).parent.parent / "data" / "tft_live_data.json").read_text())
                _vh = _ld.get("hp")
                if _vh and isinstance(_vh, (int, float)) and 0 < _vh <= 100:
                    # Stage 1 PVE: HP should be near 100 — reject wild misreads
                    if _stage <= 1 and _vh < 50: _vh = None
                    if _vh and 1 <= _vh <= 100: _hp = int(_vh)
            except Exception: pass
        if _hp and 0 < _hp <= 100:
            _hpc = "#44ff88" if _hp > 50 else "#ffdd00" if _hp > 25 else "#ff4a6a"
            self._stats["hp"].configure(text=f"{int(_hp)}HP", fg=_hpc)
        else:
            self._stats["hp"].configure(text="HP?", fg="#9090aa")
        _ao = data.get('alive_others', 7) + 1
        _variant = data.get('variant', '')
        if _variant == 'double_up':
            _teams = (_ao + 1) // 2
            self._stats["gold"].configure(text=f"{_teams}T")
        else:
            self._stats["gold"].configure(text=f"{_ao} Alive")
        _write_rich(self._items_txt,data.get("items","\u2014"),C["items"])

        gt=data.get("game_time_s",0)
        if gt: self.sync_clock(gt)
# ══════════════════════════════════════════════════════════════════════════
#  AI Status Window — 15px tall, shows screenshot timing + progress
# ══════════════════════════════════════════════════════════════════════════
class TftAiStatusBar(tk.Toplevel):
    """15-pixel-tall AI status bar. Shows screenshot countdown + processing state.
    CTRL+Right Click on any panel triggers force scan and animates here."""
    GEO={"x":1600,"y":335,"w":320,"h":20}   # scan bar below clock panel

    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True)
        self.attributes("-topmost", False)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg="#050508")

        self._frame = tk.Frame(self, bg="#050508")
        self._frame.pack(fill="both", expand=True)

        # Status label (fills width)
        self._lbl = tk.Label(
            self._frame, text="AI  IDLE",
            bg="#050508", fg="#444466",
            font=("Consolas", 9), anchor="w",
        )
        self._lbl.pack(side="left", padx=(4, 2), fill="x", expand=True)

        # Countdown label (right-aligned)
        self._cd_var = tk.StringVar(value="")
        self._cd_lbl = tk.Label(
            self._frame, textvariable=self._cd_var,
            bg="#050508", fg="#336655",
            font=("Consolas", 9), anchor="e", width=8,
        )
        self._cd_lbl.pack(side="right", padx=(2, 4))

        self._state    = "idle"       # idle | scanning | done | force
        self._progress = 0            # 0-100
        self._next_scan_at = 0.0      # monotonic time of next scheduled scan
        self._scan_interval = 15.0    # seconds between scans
        self._last_done = 0.0
        self._tick_job = None
        self._tick()

    # -- Public API ------------------------------------------------------
    def set_scanning(self, pct: int = 0):
        """Called when vision scan starts/progresses."""
        self._state    = "scanning"
        self._progress = max(0, min(100, pct))
        self._refresh()

    def set_done(self, result: str = ""):
        """Called when scan completes."""
        self._state        = "done"
        self._progress     = 100
        self._last_done    = time.monotonic()
        self._next_scan_at = time.monotonic() + self._scan_interval
        self._refresh()
        # Fade back to idle after 2s
        self.after(2000, self._set_idle)

    def set_force_scan(self):
        """Flash FORCE indicator when CTRL+Right Click triggers scan."""
        self._state    = "force"
        self._progress = 0
        self._refresh()

    def set_interval(self, seconds: float):
        self._scan_interval = seconds

    def notify_scan_scheduled(self, at_monotonic: float):
        """Tell the bar when the next scan is scheduled."""
        self._next_scan_at = at_monotonic

    def _set_idle(self):
        if self._state in ("done", "force"):
            self._state    = "idle"
            self._progress = 0
            self._refresh()

    def _refresh(self):
        """Update label text and colour based on current state."""
        s = self._state
        p = self._progress
        if s == "scanning":
            bar   = "█" * (p // 10) + "░" * (10 - p // 10)
            text  = f"SCAN  {bar}  {p}%"
            fg    = "#22ccaa"
            cd_fg = "#336655"
        elif s == "force":
            text  = "⚡ FORCE SCAN"
            fg    = "#ffdd00"
            cd_fg = "#ffdd00"
        elif s == "done":
            text  = "✓ DONE"
            fg    = "#44ff88"
            cd_fg = "#44ff88"
        else:
            text  = "AI  IDLE"
            fg    = "#444466"
            cd_fg = "#336655"
        try:
            self._lbl.configure(text=text, fg=fg)
            self._cd_lbl.configure(fg=cd_fg)
        except tk.TclError:
            pass

    def _tick(self):
        """Update countdown timer every second."""
        try:
            now = time.monotonic()
            if self._next_scan_at > now:
                remaining = int(self._next_scan_at - now)
                self._cd_var.set(f"next:{remaining}s")
            elif self._state == "idle":
                self._cd_var.set("")
            self._tick_job = self.after(1000, self._tick)
        except tk.TclError:
            pass


class TftCoachStatusBar(tk.Toplevel):
    """Coach processing status bar. Shows coaching API call state."""
    GEO={"x":1600,"y":355,"w":320,"h":20}

    def __init__(self, root):
        super().__init__(root)
        g = self.GEO
        self.overrideredirect(True)
        self.attributes("-topmost", False)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}")
        self.configure(bg="#060508")

        self._frame = tk.Frame(self, bg="#060508")
        self._frame.pack(fill="both", expand=True)

        self._lbl = tk.Label(
            self._frame, text="COACH  IDLE",
            bg="#060508", fg="#444455",
            font=("Consolas", 9), anchor="w",
        )
        self._lbl.pack(side="left", padx=(4, 2), fill="x", expand=True)

        self._ts_var = tk.StringVar(value="")
        self._ts_lbl = tk.Label(
            self._frame, textvariable=self._ts_var,
            bg="#060508", fg="#334455",
            font=("Consolas", 9), anchor="e", width=8,
        )
        self._ts_lbl.pack(side="right", padx=(2, 4))

        self._state = "idle"
        self._last_action = ""
        self._call_start = 0.0
        self._tick_job = None
        from pathlib import Path as _Path
        self._data_file = _Path(__file__).parent.parent / "data" / "tft_coaching_data.json"
        self._last_mtime = 0.0
        self._tick()

    def set_calling(self, mode: str = ""):
        self._state = "calling"
        self._call_start = time.monotonic()
        self._refresh()

    def set_done(self, action: str = ""):
        self._state = "done"
        self._last_action = (action or "")[:28]
        self._refresh()
        self.after(3000, self._set_idle)

    def _set_idle(self):
        if self._state in ("done", "calling"):
            self._state = "idle"
            self._refresh()

    def _refresh(self):
        s = self._state
        if s == "calling":
            elapsed = int(time.monotonic() - self._call_start)
            text = f"COACH  ⋯  {elapsed}s"
            fg = "#ffaa44"
        elif s == "done":
            act = self._last_action
            text = f"✓ {act}" if act else "✓ COACH DONE"
            fg = "#44ff88"
        else:
            text = "COACH  IDLE"
            fg = "#444455"
        try:
            self._lbl.configure(text=text, fg=fg)
        except tk.TclError:
            pass

    def _tick(self):
        try:
            # Poll file mod time for freshness indicator
            if self._data_file.exists():
                mtime = self._data_file.stat().st_mtime
                if mtime != self._last_mtime:
                    self._last_mtime = mtime
                    import json as _j
                    try:
                        _d = _j.loads(self._data_file.read_text(encoding="utf-8"))
                        _act = _d.get("action", "") or _d.get("econ", "")
                        if _act and self._state == "idle":
                            self._state = "done"
                            self._last_action = str(_act)[:28]
                            self._refresh()
                            self.after(4000, self._set_idle)
                    except Exception:
                        pass
            # Elapsed timer while calling
            if self._state == "calling":
                self._refresh()
            self._tick_job = self.after(1000, self._tick)
        except tk.TclError:
            pass


def _bind_ctrl_right_click(w, cb):
    """Bind CTRL+Right Click recursively for force scan."""
    def _h(e):
        if e.state & 0x4:   # Ctrl modifier
            cb()
            return "break"
    w.bind("<Button-3>", _h)
    try:
        for c in w.winfo_children():
            _bind_ctrl_right_click(c, cb)
    except Exception:
        pass


class TftRightBot(tk.Toplevel):
    GEO={"x":1600,"y":375,"w":320,"h":705}
    def __init__(self,root):
        super().__init__(root);g=self.GEO;self.overrideredirect(True);self.attributes("-topmost",True)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}");self.configure(bg=BG)
        con=tk.Frame(self,bg=BG);con.pack(fill="both",expand=True,padx=1,pady=1);con.columnconfigure(0,weight=1)
        self._econ_txt=_sec(con,0,"ECON",C["econ"],minsize=90)
        self._action_var,self._act_lbl=_bar(con,1,"ACTION",C["action"],minsize=40)
        self._upgrisk_txt=None  # RISK panel removed from TFT
        # -- COMP CONTROL (row 2) --
        from tft.comp_control import CompControl, ChampItemControl
        self._comp_ctrl = CompControl(con, on_select=self._on_comp_select)
        self._comp_ctrl.grid(row=2, column=0, sticky="nsew", pady=(2,0))
        con.rowconfigure(2, weight=2, minsize=140)
        # -- CHAMP/ITEM CONTROL (row 3) --
        self._item_ctrl = ChampItemControl(con)
        self._item_ctrl.grid(row=3, column=0, sticky="nsew", pady=(2,0))
        con.rowconfigure(3, weight=3, minsize=415)
    def set_bottom_strip(self, bottom) -> None:
        """Wire TftBottomStrip so comp selection drives the center board."""
        self._bottom_strip = bottom

    def _on_comp_select(self, name, comp_data):
        """Called when user selects a comp in CompControl."""
        if hasattr(self, '_item_ctrl'):
            self._item_ctrl.set_comp(name, comp_data)
        if hasattr(self, '_bottom_strip') and self._bottom_strip:
            try:
                self._bottom_strip.set_board_from_placement(comp_data or {})
            except Exception:
                pass
        _log.info("RightBot: comp selected -> %s", name or "FLEX")

    def get_comp_ctrl(self):
        return self._comp_ctrl if hasattr(self, '_comp_ctrl') else None

    def get_item_ctrl(self):
        return self._item_ctrl if hasattr(self, '_item_ctrl') else None

    def bind_force_scan(self, cb, ai_bar=None):
        """Bind CTRL+Right Click on this window for force scan."""
        self._ai_bar = ai_bar
        def _do():
            cb()
            if self._ai_bar:
                self._ai_bar.set_force_scan()
        _bind_ctrl_right_click(self, _do)
    def update(self,data):
        act = data.get("action","") or "—"
        try:
            tempo = _tempo_context(data.get("stage",1), data.get("round",1), data.get("level",1))
            self._action_var.set(f"{act}\n{tempo}" if tempo else act)
        except Exception:
            self._action_var.set(act)
        self._act_lbl.configure(fg="#ff2244" if data.get("health",100)<=30 else C["action"])
        _write_rich(self._econ_txt,data.get("econ","\u2014"),C["econ"])
        pass  # GRAPH panel reserved — no auto-output
    def update_live(self,live):
        pass  # CompControl and ChampItemControl are user-driven, not auto-updated
class TftBottomStrip(tk.Toplevel):
    GEO={"x":0,"y":920,"w":1600,"h":160}
    def __init__(self,root):
        super().__init__(root);g=self.GEO;self.overrideredirect(True);self.attributes("-topmost",True)
        self.geometry(f"{g['w']}x{g['h']}+{g['x']}+{g['y']}");self.configure(bg=BG)
        self._is_carousel=False
        bf=tk_font.Font(family="Segoe UI",size=11,weight="bold")
        def _txt(parent,color):
            t=tk.Text(parent,bg=BG_SEC,fg=color,font=("Segoe UI",11),wrap="word",bd=0,highlightthickness=0,insertbackground=BG_SEC,state="disabled",cursor="arrow",padx=10,pady=3,height=5)
            t.pack(fill="both",expand=True,pady=(0,5))
            for tag,col in [("ally","#44ff88"),("enemy","#ff4444"),("time","#ffdd00"),("base",color)]:
                t.tag_configure(tag,foreground=col,font=bf if tag!="base" else None)
            return t
        fl=tk.Frame(self,bg=BG_SEC,highlightbackground=BORDER,highlightthickness=1)
        fl.place(x=1,y=1,width=428,height=158)
        # COMP/BUY header row: label + AUG refresh button
        _cb_hdr = tk.Frame(fl, bg=BG_SEC)
        _cb_hdr.pack(fill="x", padx=4, pady=(4, 0))
        tk.Label(_cb_hdr, text="COMP / BUY", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 9, "bold"), anchor="w").pack(side="left")
        self._aug_btn = tk.Button(
            _cb_hdr, text="AUG ⟳", bg="#1a1400", fg="#ffd700",
            font=("Consolas", 8, "bold"), relief="flat", bd=0,
            padx=8, pady=1, cursor="hand2",
            activebackground="#2a2400", activeforeground="#ffee44",
            command=self._do_aug_refresh_bottom)
        self._aug_btn.pack(side="right")
        self._force_scan_cb_bottom = None
        self._live_txt=_txt(fl,C["live"])
        self._last_live_update = 0.0  # Phase 6 Step 3 Fix 5: timeout guard
        # Start the periodic timeout checker on the Tk event loop.
        # Runs every 10s; only affects the COMP/BUY presentation label.
        self.after(10000, self._tick_live_timeout)
        fc=tk.Frame(self,bg=BG_SEC,highlightbackground=BORDER,highlightthickness=1)
        fc.place(x=431,y=1,width=738,height=158)
        # BOARD header row: label + level selector + OCR debug button
        _bd_hdr = tk.Frame(fc, bg=BG_SEC)
        _bd_hdr.pack(fill="x", padx=4, pady=(3, 0))
        tk.Label(_bd_hdr, text="BOARD", bg=BG_SEC, fg=LABEL_C,
                 font=("Consolas", 10, "bold"), anchor="w").pack(side="left")
        tk.Button(
            _bd_hdr, text="OCR DBG", bg="#0a0a1a", fg="#6677aa",
            font=("Consolas", 7, "bold"), relief="flat", bd=0,
            padx=6, pady=1, cursor="hand2",
            activebackground="#1a1a2a", activeforeground="#99aacc",
            command=self._run_ocr_debug).pack(side="right")
        # Level selector — single-select Lv4-Lv9
        self._manual_level = None
        self._level_btns = {}
        _lv_frame = tk.Frame(_bd_hdr, bg=BG_SEC)
        _lv_frame.pack(side="right", padx=(4, 8))
        # HMAP toggle
        self._hmap_btn = tk.Button(
            _lv_frame, text="HMAP",
            bg="#0a0a1a", fg="#5a4a6a",
            font=("Consolas", 8, "bold"), relief="flat", bd=0,
            padx=5, pady=1, cursor="hand2",
            activebackground="#1a0a2a", activeforeground="#cc88ff",
            command=self._toggle_heatmap_btn)
        self._hmap_btn.pack(side="left", padx=(0, 6))
        for _lv in [4, 5, 6, 7, 8, 9]:
            _btn = tk.Button(
                _lv_frame, text=f"Lv{_lv}",
                bg="#0a0a1a", fg="#5a6a7a",
                font=("Consolas", 8, "bold"), relief="flat", bd=0,
                padx=5, pady=1, cursor="hand2",
                activebackground="#1a2a3a", activeforeground="#44ccff",
                command=lambda l=_lv: self._on_level_click(l))
            _btn.pack(side="left", padx=1)
            self._level_btns[_lv] = _btn
        self._board_canvas=TftBoardCanvas(fc,cell_w=81,cell_h=23,lpad=34,tpad=14,bpad=10)
        self._board_canvas.pack(fill="both",expand=True,pady=(0,2))
        # Right panel: LV PLAN view + UNIT ROSTER toggle
        fr=tk.Frame(self,bg=BG_SEC,highlightbackground=BORDER,highlightthickness=1)
        fr.place(x=1171,y=1,width=428,height=158)
        # Header: plan labels + ROSTER toggle button
        hdr=tk.Frame(fr,bg=BG_SEC)
        hdr.pack(fill="x",padx=4,pady=(3,0))
        self._plan_lbl_left=tk.Label(hdr,text="Lv4 EARLY",bg=BG_SEC,fg=LABEL_C,font=("Consolas",8,"bold"),anchor="w")
        self._plan_lbl_left.pack(side="left",expand=True)
        self._roster_toggle_btn=tk.Button(hdr,text="ROSTER",bg="#0a0a1a",fg="#44aaff",
            font=("Consolas",7,"bold"),relief="flat",bd=0,padx=6,pady=0,cursor="hand2",
            activebackground="#1a1a2a",activeforeground="#88ccff",
            command=self._toggle_roster_view)
        self._roster_toggle_btn.pack(side="right")
        self._plan_lbl_right=tk.Label(hdr,text="Lv7 MID",bg=BG_SEC,fg=LABEL_C,font=("Consolas",8,"bold"),anchor="e")
        self._plan_lbl_right.pack(side="right",expand=True)
        # View container
        self._right_view_container=tk.Frame(fr,bg=BG_SEC)
        self._right_view_container.pack(fill="both",expand=True,padx=2,pady=(0,1))
        # LV PLAN view (default visible)
        self._plan_view=tk.Frame(self._right_view_container,bg=BG_SEC)
        self._plan_view.pack(fill="both",expand=True)
        self._plan_view_active=True
        # Split container inside plan view
        split=tk.Frame(self._plan_view,bg=BG_SEC)
        split.pack(fill="both",expand=True)
        # Left half: Lv4
        lf=tk.Frame(split,bg=BG_SEC)
        lf.pack(side="left",fill="both",expand=True)
        lf.columnconfigure(0,weight=0,minsize=24);lf.columnconfigure(1,weight=1)
        self._lv4_rows={}
        for i,rl in enumerate(["A","B","C","D"]):
            lf.rowconfigure(i,weight=1);color=_ROW_COLORS[rl]
            tk.Label(lf,text=f"{rl}:",bg=BG_SEC,fg=color,font=("Consolas",9,"bold"),anchor="w").grid(row=i,column=0,sticky="w",padx=(2,1),pady=0)
            val=tk.Label(lf,text="\u2014",bg=BG_SEC,fg=color,font=("Segoe UI",8),anchor="w",justify="left")
            val.grid(row=i,column=1,sticky="ew",padx=(0,2),pady=0);self._lv4_rows[rl]=val
        # Red divider (1px vibrant red)
        div=tk.Frame(split,bg="#FF0000",width=1)
        div.pack(side="left",fill="y",padx=0)
        # Right half: Lv7
        rf=tk.Frame(split,bg=BG_SEC)
        rf.pack(side="left",fill="both",expand=True)
        rf.columnconfigure(0,weight=0,minsize=24);rf.columnconfigure(1,weight=1)
        self._lv7_rows={}
        for i,rl in enumerate(["A","B","C","D"]):
            rf.rowconfigure(i,weight=1);color=_ROW_COLORS[rl]
            tk.Label(rf,text=f"{rl}:",bg=BG_SEC,fg=color,font=("Consolas",9,"bold"),anchor="w").grid(row=i,column=0,sticky="w",padx=(2,1),pady=0)
            val=tk.Label(rf,text="\u2014",bg=BG_SEC,fg=color,font=("Segoe UI",8),anchor="w",justify="left")
            val.grid(row=i,column=1,sticky="ew",padx=(0,2),pady=0);self._lv7_rows[rl]=val
        # Keep placement_rows for backward compat (uses lv4 as default)
        self._placement_rows=self._lv4_rows
        # ROSTER view (hidden initially)
        self._roster_view=tk.Frame(self._right_view_container,bg=BG_SEC)
        self._extra_present=set()   # extra units (not in comp) marked present
        self._comp_units_set=set()  # units to exclude from roster (in final comp)
        self._roster_btns={}        # name -> (label, cost)
        self._build_roster_grid()
        self._swap_lbl=tk.Label(fr,text="",bg=BG_SEC,fg="#ff9944",font=("Segoe UI",8),anchor="w")
        self._swap_lbl.pack(anchor="w",padx=4,pady=(0,1))

    def set_force_scan_cb(self, cb) -> None:
        """Wire force scan callback for AUG button in COMP/BUY panel."""
        self._force_scan_cb_bottom = cb

    def _do_aug_refresh_bottom(self):
        """AUG/God refresh from COMP/BUY panel button."""
        cb = getattr(self, "_force_scan_cb_bottom", None)
        if cb:
            try:
                cb()
                _write_rich(self._live_txt, "⟳ Aug/God scan fired", "#ffd700")
            except Exception:
                pass

    def _run_ocr_debug(self):
        """Save full annotated screenshot + OCR crops in background thread."""
        import threading, subprocess as _sp
        def _do():
            try:
                import sys as _sys
                _root = __import__("pathlib").Path(__file__).parent.parent
                _sys.path.insert(0, str(_root))
                _out = _root / "data" / "ocr_debug"
                _out.mkdir(exist_ok=True, parents=True)
                # Run full ocr_debug.py for annotated screenshot
                _py = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
                _script = _root / "ocr_debug.py"
                if _script.exists():
                    _sp.Popen([_py, str(_script)], cwd=str(_root),
                              creationflags=_sp.CREATE_NO_WINDOW)
                else:
                    from tft.tft_ocr_reader import TftOcrReader
                    TftOcrReader().save_debug_crops(str(_out))
            except Exception as _e:
                pass
        threading.Thread(target=_do, daemon=True, name="OcrDebug").start()

    def set_comp_positions(self, comp_data, owned_units=None):
        """Set STATIC board positions from meta DB for selected comp."""
        if not comp_data:
            # Clear all position displays
            self._board_canvas.update_board_units("", None)
            for rl in ["A","B","C","D"]:
                if rl in self._lv4_rows: self._lv4_rows[rl].configure(text="\u2014")
                if rl in self._lv7_rows: self._lv7_rows[rl].configure(text="\u2014")
            return
        pos = comp_data.get("positioning", {})
        # Center board = Lv9 final build
        lv9 = pos.get("lv9", {})
        # Set carry markers + star targets from comp data
        core = comp_data.get("core_units", [])
        self._board_canvas.set_carry_units(core)
        stars = comp_data.get("target_stars", {})
        self._board_canvas.set_target_stars(stars)
        if lv9:
            placement_str = ", ".join(f"{name} {cell}" for name, cell in lv9.items())
            owned = owned_units or []
            self._board_canvas.set_owned_units(owned)
            self._board_canvas.update_board_units(placement_str, None)  # No whitelist filter for static display
        # Left half = Lv4
        lv4 = pos.get("lv4", {})
        lv4_rows = {"A":[],"B":[],"C":[],"D":[]}
        for name, cell in lv4.items():
            rl = cell[0].upper() if cell else ""
            col = cell[1] if len(cell) > 1 else ""
            if rl in lv4_rows: lv4_rows[rl].append(f"{name} {col}")
        for rl in ["A","B","C","D"]:
            if rl in self._lv4_rows:
                self._lv4_rows[rl].configure(text=", ".join(lv4_rows[rl]) if lv4_rows[rl] else "\u2014")
        # Right half = Lv7
        lv7 = pos.get("lv7", {})
        lv7_rows = {"A":[],"B":[],"C":[],"D":[]}
        for name, cell in lv7.items():
            rl = cell[0].upper() if cell else ""
            col = cell[1] if len(cell) > 1 else ""
            if rl in lv7_rows: lv7_rows[rl].append(f"{name} {col}")
        for rl in ["A","B","C","D"]:
            if rl in self._lv7_rows:
                self._lv7_rows[rl].configure(text=", ".join(lv7_rows[rl]) if lv7_rows[rl] else "\u2014")
        _log.info("BottomStrip: static positions set for comp (Lv4/Lv7/Lv9)")


    def set_board_from_placement(self, comp_data: dict) -> None:
        """Feed TFT guide author X board_placement data into the center board canvas."""
        if not comp_data:
            self._board_canvas.update_board_units("", None)
            return
        placements = comp_data.get("board_placement", [])
        carry = comp_data.get("board_carry", "")
        core = set(comp_data.get("core_units", []))
        _ROW_MAP = {4: "A", 3: "B", 2: "C", 1: "D"}
        parts = []
        for p in placements:
            row_lbl = _ROW_MAP.get(p.get("row", 0), "")
            col = p.get("col", 0)
            champ = p.get("champion", "")
            if row_lbl and 1 <= col <= 7 and champ and champ not in ("Unknown", "Shen's Sword", "Training Dummy"):
                parts.append(f"{champ} {row_lbl}{col}")
        board_text = ", ".join(parts)
        # Set carry/core markers
        self._board_canvas.set_carry_units([carry] if carry else [])
        self._board_canvas.set_target_stars(comp_data.get("target_stars", {}))
        self._board_canvas.set_presence_callback(self._on_board_unit_toggle)
        self._board_canvas.reset_confirmed()
        # Update roster: exclude final comp units
        _all_units=comp_data.get("core_units",[])+comp_data.get("flex_units",[])
        self.set_comp_units_for_roster(_all_units)
        self._board_canvas.update_board_units(board_text, None)
        # Lv4/Lv7 labels: A=frontline (board rows 3-4), D=carries (board rows 1-2)
        _lv4 = comp_data.get("lv4", [])
        _lv7 = comp_data.get("lv7", [])
        _items_d = comp_data.get("items", {})

        # Role map: A=frontline B=midline C=support/flex D=carry
        # Uses board_placement role field directly, falls back on row/items
        _role_map = {}
        for _p in placements:
            _ch = _p.get("champion", "")
            _role = _p.get("role", "")
            _row  = _p.get("row", 0)
            if _ch:
                if _role in ("frontline",):            _role_map[_ch] = "A"
                elif _role in ("midline",):            _role_map[_ch] = "B"
                elif _role in ("flex",):               _role_map[_ch] = "C"
                elif _role in ("carry", "backline"):   _role_map[_ch] = "D"
                elif _row >= 4:                        _role_map[_ch] = "A"
                elif _row == 3:                        _role_map[_ch] = "B"
                elif _row == 2:                        _role_map[_ch] = "C"
                else:                                  _role_map[_ch] = "D"

        def _classify(unit_list):
            rows = {"A": [], "B": [], "C": [], "D": []}
            for u in unit_list:
                _r = _role_map.get(u)
                if _r:
                    rows[_r].append(u)
                else:
                    # Fallback: item-carrying = D (carry), else A (frontline)
                    rows["D" if u in _items_d else "A"].append(u)
            return rows

        _lv4_rows_d = _classify(_lv4)
        _lv7_rows_d = _classify(_lv7)

        for _rl in ["A", "B", "C", "D"]:
            if _rl in self._lv4_rows:
                _vals = _lv4_rows_d.get(_rl, [])
                self._lv4_rows[_rl].configure(text=", ".join(_vals) if _vals else "")
            if _rl in self._lv7_rows:
                _vals = _lv7_rows_d.get(_rl, [])
                self._lv7_rows[_rl].configure(text=", ".join(_vals) if _vals else "")

    def _toggle_heatmap_btn(self) -> None:
        """Toggle heatmap overlay on the board canvas."""
        if not hasattr(self, "_board_canvas"): return
        active = self._board_canvas.toggle_heatmap()
        try:
            self._hmap_btn.configure(
                bg="#1a003a" if active else "#0a0a1a",
                fg="#cc88ff" if active else "#5a4a6a",
            )
        except Exception: pass

    def _on_level_click(self, level: int) -> None:
        """Single-select level indicator. Clicking same level again deselects."""
        if self._manual_level == level:
            # Deselect
            self._manual_level = None
            btn = self._level_btns.get(level)
            if btn:
                try: btn.configure(bg="#0a0a1a", fg="#5a6a7a")
                except Exception: pass
        else:
            # Deactivate old
            old_btn = self._level_btns.get(self._manual_level)
            if old_btn:
                try: old_btn.configure(bg="#0a0a1a", fg="#5a6a7a")
                except Exception: pass
            # Activate new
            self._manual_level = level
            new_btn = self._level_btns.get(level)
            if new_btn:
                try: new_btn.configure(bg="#0a2a3a", fg="#00e5ff")
                except Exception: pass
        # Write to presence file
        board_conf = self._board_canvas.get_confirmed_units() if hasattr(self, "_board_canvas") else set()
        _write_unit_presence(board_conf, self._extra_present, self._manual_level)

    def _toggle_roster_view(self):
        """Toggle between LV PLAN and UNIT ROSTER views."""
        self._plan_view_active=not self._plan_view_active
        if self._plan_view_active:
            self._roster_view.pack_forget()
            self._plan_view.pack(fill="both",expand=True)
            self._roster_toggle_btn.configure(text="ROSTER")
            self._plan_lbl_left.pack(side="left",expand=True)
            self._plan_lbl_right.pack(side="right",expand=True)
        else:
            self._plan_view.pack_forget()
            self._plan_lbl_left.pack_forget()
            self._plan_lbl_right.pack_forget()
            self._roster_view.pack(fill="both",expand=True)
            self._roster_toggle_btn.configure(text="PLAN")

    def _build_roster_grid(self):
        """(Re)build unit roster buttons, excluding comp units."""
        for w in list(self._roster_view.winfo_children()):
            try: w.destroy()
            except Exception: pass
        self._roster_btns={}
        COLS=5
        inner=tk.Frame(self._roster_view,bg=BG_SEC)
        inner.pack(fill="both",expand=True,padx=2,pady=2)
        col,row=0,0
        for name,cost in _SET17_UNITS:
            if name in self._comp_units_set: continue
            color=_UNIT_COST_COLORS.get(cost,"#808080")
            bg=_UNIT_COST_BG.get(cost,"#111111")
            is_p=name in self._extra_present
            lbl=tk.Label(inner,text=name[:10],bg=bg,
                fg="#00ff88" if is_p else color,
                font=("Consolas",9,"bold"),relief="flat",bd=0,
                cursor="hand2",anchor="center",
                highlightthickness=1,
                highlightbackground="#00ff88" if is_p else "#2a2a3a",
                padx=2,pady=3)
            lbl.grid(row=row,column=col,padx=1,pady=1,sticky="ew")
            lbl.bind("<Button-1>",lambda e,n=name,c=cost:self._roster_unit_click(n,c))
            self._roster_btns[name]=(lbl,cost)
            inner.columnconfigure(col,weight=1)
            col+=1
            if col>=COLS: col=0;row+=1

    def _roster_unit_click(self,name,cost):
        """Toggle extra unit presence and write to unit_presence.json."""
        if name in self._extra_present:
            self._extra_present.discard(name); present=False
        else:
            self._extra_present.add(name); present=True
        entry=self._roster_btns.get(name)
        if entry:
            lbl,_cost=entry
            color=_UNIT_COST_COLORS.get(_cost,"#808080")
            bg=_UNIT_COST_BG.get(_cost,"#111111")
            try:
                lbl.configure(fg="#00ff88" if present else color,
                    highlightbackground="#00ff88" if present else "#2a2a3a")
            except Exception: pass
        board_conf=self._board_canvas.get_confirmed_units() if hasattr(self,"_board_canvas") else set()
        _write_unit_presence(board_conf,self._extra_present)

    def set_comp_units_for_roster(self,unit_names):
        """Update which units to exclude from roster (they are in the final comp)."""
        self._comp_units_set=set(unit_names or [])
        self._extra_present-=self._comp_units_set
        self._build_roster_grid()

    def _on_board_unit_toggle(self,name,confirmed):
        """Board canvas click → write presence file."""
        confirmed_set=self._board_canvas.get_confirmed_units()
        _write_unit_presence(confirmed_set,self._extra_present)

    def bind_force_scan(self, cb, ai_bar=None):
        """CTRL+Right Click on bottom strip for force scan."""
        _ai = ai_bar
        def _do():
            cb()
            _write_rich(self._live_txt, "\u21bb SCANNING...", "#ffdd00")
            if _ai:
                try: _ai.set_force_scan()
                except Exception: pass
            _log.info("Force scan from bottom strip CTRL+right-click")
        _bind_ctrl_right_click(self, _do)
    def update(self,data):
        event=data.get("round_event","")
        self._is_carousel=event in ("carousel","opening_carousel","realm_of_gods") or data.get("is_carousel",False)
    def update_live(self,live):
        import time as _time
        self._last_live_update = _time.monotonic()  # Phase 6 Step 3 Fix 5
        if live.get("augment_select"):
            take=live.get("aug_take","");why=live.get("aug_why","")
            _write_rich(self._live_txt,f"AUGMENT\nTake: {take}\n{why}" if take else "\u2014","#ffdd00")
            self._swap_lbl.configure(text=live.get("aug_plan","") or "Augment selecting...");return
        comp=live.get("comp","") or "";build=live.get("build","") or "";buy=live.get("buy","") or ""
        parts=[]
        if comp: parts.append(f"Comp: {comp}")
        if build: parts.append(f"Build: {build}")
        if buy: parts.append(f"Buy: {buy}")
        _write_rich(self._live_txt,"\n".join(parts) if parts else "Scanning...",C["live"])
        if self._is_carousel: return
        # Board canvas and Lv4/Lv7 panels are STATIC from comp selection
        # Only update green outlines based on owned units
        owned = live.get("board_units", [])
        if owned and hasattr(self._board_canvas, '_owned_units'):
            self._board_canvas.set_owned_units(owned)
            self._board_canvas._redraw()  # refresh green outlines without changing positions
        swap=live.get("unit_swap","") or "";loss=live.get("loss","") or ""
        sp=[]
        if swap and swap.lower() not in ("none","n/a",""): sp.append(f"Swap: {swap}")
        if loss and loss not in ("N/A","n/a",""): sp.append(f"\u26a0 {loss}")
        self._swap_lbl.configure(text="  ".join(sp) if sp else "")

    def check_live_timeout(self, timeout_s: float = 45.0):
        """Phase 6 Step 3 Fix 5: presentation-layer timeout guard.
        If no update_live() call has arrived within timeout_s seconds,
        replace 'Scanning...' with a neutral placeholder so the panel
        does not appear permanently stale. Safe to call on any poll tick.
        """
        import time as _time
        if self._last_live_update == 0.0:
            return  # never received any update yet -- leave initial state
        elapsed = _time.monotonic() - self._last_live_update
        if elapsed >= timeout_s:
            _write_rich(self._live_txt, "\u2014", C["live"])

    def _tick_live_timeout(self):
        """Periodic Tk callback — calls check_live_timeout and reschedules.
        Self-contained within TftBottomStrip; no authority outside presentation.
        """
        try:
            self.check_live_timeout(timeout_s=45.0)
        except Exception:
            pass
        try:
            self.after(10000, self._tick_live_timeout)
        except Exception:
            pass  # widget destroyed -- stop silently


