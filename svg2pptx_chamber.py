"""chamber_6g_concept_vertical_v2.svg -> editable PPTX (native shapes / text boxes).

Usage: python svg2pptx_chamber.py [input.svg] [output.pptx]
1 SVG px = 1/96 inch, so the slide is 10.42" x 31.25" and the layout is 1:1.
"""
import math, re, sys, io
from xml.sax.saxutils import escape
from lxml import etree
from pptx import Presentation
from pptx.util import Emu
from PIL import Image, ImageDraw

SRC = sys.argv[1] if len(sys.argv) > 1 else "chamber_6g_concept_vertical_v2.svg"
OUT = sys.argv[2] if len(sys.argv) > 2 else "chamber_6g_concept_vertical_v2.pptx"
NS = "{http://www.w3.org/2000/svg}"
EMU = 9525  # per px @96dpi
FONT = "Malgun Gothic"
A = 'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"'
P = 'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"'

# ---------------------------------------------------------------- matrices
def mul(m, n):
    a, b, c, d, e, f = m; A_, B, C, D, E, F = n
    return (a*A_ + c*B, b*A_ + d*B, a*C + c*D, b*C + d*D, a*E + c*F + e, b*E + d*F + f)

def app(m, x, y):
    a, b, c, d, e, f = m
    return (a*x + c*y + e, b*x + d*y + f)

I = (1, 0, 0, 1, 0, 0)

def parse_tf(s):
    m = I
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        v = [float(x) for x in re.split(r"[\s,]+", args.strip()) if x]
        if name == "translate":
            t = (1, 0, 0, 1, v[0], v[1] if len(v) > 1 else 0)
        elif name == "rotate":
            r = math.radians(v[0]); t = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
        elif name == "matrix":
            t = tuple(v)
        elif name == "scale":
            t = (v[0], 0, 0, v[1] if len(v) > 1 else v[0], 0, 0)
        else:
            continue
        m = mul(m, t)
    return m

def is_similarity(m):
    a, b, c, d, _, _ = m
    return abs(a - d) < 1e-6 and abs(b + c) < 1e-6

def rot_deg(m):
    return math.degrees(math.atan2(m[1], m[0]))

# ---------------------------------------------------------------- styles
def parse_defs(root):
    grads, markers = {}, {}
    for g in root.iter(NS + "linearGradient"):
        x1, x2 = float(g.get("x1", 0)), float(g.get("x2", 1))
        y1, y2 = float(g.get("y1", 0)), float(g.get("y2", 0))
        ang = math.degrees(math.atan2(y2 - y1, x2 - x1)) % 360
        stops = [(float(s.get("offset")), s.get("stop-color").lstrip("#"), float(s.get("stop-opacity", 1)))
                 for s in g.iter(NS + "stop")]
        grads[g.get("id")] = (ang, stops)
    for mk in root.iter(NS + "marker"):
        markers[mk.get("id")] = float(mk.get("markerWidth", 6))
    return grads, markers

STYLE_KEYS = ["fill", "stroke", "stroke-width", "stroke-dasharray", "opacity", "fill-opacity",
              "font-size", "font-weight", "font-style", "text-anchor", "stroke-linejoin"]

def inherit(el, parent):
    st = dict(parent)
    st.pop("opacity", None); st.pop("filter", None)
    st["_opacity"] = parent.get("_opacity", 1.0) * float(el.get("opacity", 1))
    st["_shadow"] = parent.get("_shadow", False) or el.get("filter") is not None
    for k in STYLE_KEYS:
        if el.get(k) is not None and k != "opacity":
            st[k] = el.get(k)
    for k in ("marker-start", "marker-end"):
        st[k] = el.get(k)
    return st

def color_xml(hexc, alpha):
    al = f'<a:alpha val="{int(alpha*100000)}"/>' if alpha < 0.999 else ""
    return f'<a:srgbClr val="{hexc.upper()}">{al}</a:srgbClr>'

def fill_xml(st, grads, closed=True):
    f = st.get("fill", "#000000")
    if not closed or f in ("none", None):
        return "<a:noFill/>"
    op = st["_opacity"] * float(st.get("fill-opacity", 1))
    m = re.match(r"url\(#(\w+)\)", f)
    if m and m.group(1) in grads:
        ang, stops = grads[m.group(1)]
        gs = "".join(f'<a:gs pos="{int(o*100000)}">{color_xml(c, a*op)}</a:gs>' for o, c, a in stops)
        return f'<a:gradFill rotWithShape="1"><a:gsLst>{gs}</a:gsLst><a:lin ang="{int(ang*60000)}" scaled="0"/></a:gradFill>'
    return f"<a:solidFill>{color_xml(f.lstrip('#'), op)}</a:solidFill>"

def ln_xml(st, markers):
    s = st.get("stroke")
    if s in (None, "none"):
        return "<a:ln><a:noFill/></a:ln>"
    w = float(st.get("stroke-width", 1))
    dash = ""
    if st.get("stroke-dasharray"):
        d = [float(x) for x in re.split(r"[\s,]+", st["stroke-dasharray"].strip())]
        dash = '<a:prstDash val="sysDash"/>' if d[0] <= 3.5 else '<a:prstDash val="dash"/>'
    join = '<a:round/>' if st.get("stroke-linejoin") == "round" else ""
    ends = ""
    for key, tag in (("marker-start", "headEnd"), ("marker-end", "tailEnd")):
        if st.get(key):
            ends += f'<a:{tag} type="triangle" w="med" len="med"/>'
    return (f'<a:ln w="{int(w*EMU)}"><a:solidFill>{color_xml(s.lstrip("#"), st["_opacity"])}</a:solidFill>'
            f"{dash}{join}{ends}</a:ln>")

def effect_xml(st):
    if not st.get("_shadow"):
        return ""
    return ('<a:effectLst><a:outerShdw blurRad="57150" dist="19050" dir="5400000" algn="t" rotWithShape="0">'
            '<a:srgbClr val="1B2A41"><a:alpha val="18000"/></a:srgbClr></a:outerShdw></a:effectLst>')

# ---------------------------------------------------------------- path geometry
def arc_to_beziers(x1, y1, rx, ry, phi, fa, fs, x2, y2):
    if rx == 0 or ry == 0:
        return [("L", [(x2, y2)])]
    phi = math.radians(phi); cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp*dx + sp*dy, -sp*dx + cp*dy
    lam = x1p**2/rx**2 + y1p**2/ry**2
    if lam > 1:
        rx *= math.sqrt(lam); ry *= math.sqrt(lam)
    num = rx*rx*ry*ry - rx*rx*y1p*y1p - ry*ry*x1p*x1p
    den = rx*rx*y1p*y1p + ry*ry*x1p*x1p
    co = math.sqrt(max(0, num/den)) * (-1 if fa == fs else 1)
    cxp, cyp = co*rx*y1p/ry, -co*ry*x1p/rx
    cx = cp*cxp - sp*cyp + (x1 + x2)/2
    cy = sp*cxp + cp*cyp + (y1 + y2)/2
    def ang(u, v):
        return math.atan2(u[0]*v[1] - u[1]*v[0], u[0]*v[0] + u[1]*v[1])
    t1 = ang((1, 0), ((x1p - cxp)/rx, (y1p - cyp)/ry))
    dt = ang(((x1p - cxp)/rx, (y1p - cyp)/ry), ((-x1p - cxp)/rx, (-y1p - cyp)/ry))
    if not fs and dt > 0: dt -= 2*math.pi
    if fs and dt < 0: dt += 2*math.pi
    n = max(1, int(math.ceil(abs(dt) / (math.pi/2))))
    d = dt / n; k = 4/3*math.tan(d/4); out = []
    def pt(t):
        return (cx + rx*math.cos(t)*cp - ry*math.sin(t)*sp, cy + rx*math.cos(t)*sp + ry*math.sin(t)*cp)
    def der(t):
        return (-rx*math.sin(t)*cp - ry*math.cos(t)*sp, -rx*math.sin(t)*sp + ry*math.cos(t)*cp)
    t = t1
    for _ in range(n):
        p0, p3 = pt(t), pt(t + d); d0, d3 = der(t), der(t + d)
        out.append(("C", [(p0[0] + k*d0[0], p0[1] + k*d0[1]), (p3[0] - k*d3[0], p3[1] - k*d3[1]), p3]))
        t += d
    return out

def parse_path(d):
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|-?\d*\.?\d+(?:e-?\d+)?", d)
    i, cmd = 0, None; x = y = sx = sy = 0; prev_c = prev_q = None; segs = []
    def num():
        nonlocal i
        v = float(toks[i]); i += 1; return v
    while i < len(toks):
        if re.match(r"[A-Za-z]", toks[i]):
            cmd = toks[i]; i += 1
        rel = cmd.islower(); C = cmd.upper()
        ox, oy = (x, y) if rel else (0, 0)
        if C == "Z":
            segs.append(("Z", [])); x, y = sx, sy; prev_c = prev_q = None; continue
        if C == "M":
            x, y = num() + ox, num() + oy; sx, sy = x, y; segs.append(("M", [(x, y)]))
            cmd = "l" if rel else "L"; prev_c = prev_q = None; continue
        if C == "L":
            x, y = num() + ox, num() + oy; segs.append(("L", [(x, y)])); prev_c = prev_q = None
        elif C == "H":
            x = num() + (x if rel else 0); segs.append(("L", [(x, y)])); prev_c = prev_q = None
        elif C == "V":
            y = num() + (y if rel else 0); segs.append(("L", [(x, y)])); prev_c = prev_q = None
        elif C == "C":
            p1 = (num() + ox, num() + oy); p2 = (num() + ox, num() + oy); p = (num() + ox, num() + oy)
            segs.append(("C", [p1, p2, p])); prev_c = p2; x, y = p; prev_q = None
        elif C == "S":
            p1 = (2*x - prev_c[0], 2*y - prev_c[1]) if prev_c else (x, y)
            p2 = (num() + ox, num() + oy); p = (num() + ox, num() + oy)
            segs.append(("C", [p1, p2, p])); prev_c = p2; x, y = p; prev_q = None
        elif C == "Q":
            q = (num() + ox, num() + oy); p = (num() + ox, num() + oy)
            segs.append(("Q", [q, p])); prev_q = q; x, y = p; prev_c = None
        elif C == "T":
            q = (2*x - prev_q[0], 2*y - prev_q[1]) if prev_q else (x, y)
            p = (num() + ox, num() + oy); segs.append(("Q", [q, p])); prev_q = q; x, y = p; prev_c = None
        elif C == "A":
            rx, ry, phi, fa, fs = num(), num(), num(), num(), num(); p = (num() + ox, num() + oy)
            segs += arc_to_beziers(x, y, rx, ry, phi, int(fa), int(fs), p[0], p[1]); x, y = p
            prev_c = prev_q = None
    return segs

def rect_segs(x, y, w, h, rx=0):
    if rx <= 0:
        return [("M", [(x, y)]), ("L", [(x + w, y)]), ("L", [(x + w, y + h)]), ("L", [(x, y + h)]), ("Z", [])]
    r = min(rx, w/2, h/2); k = 0.5523*r
    return [("M", [(x + r, y)]), ("L", [(x + w - r, y)]),
            ("C", [(x + w - r + k, y), (x + w, y + r - k), (x + w, y + r)]), ("L", [(x + w, y + h - r)]),
            ("C", [(x + w, y + h - r + k), (x + w - r + k, y + h), (x + w - r, y + h)]), ("L", [(x + r, y + h)]),
            ("C", [(x + r - k, y + h), (x, y + h - r + k), (x, y + h - r)]), ("L", [(x, y + r)]),
            ("C", [(x, y + r - k), (x + r - k, y), (x + r, y)]), ("Z", [])]

# ---------------------------------------------------------------- shape writer
class Writer:
    def __init__(self, slide, grads, markers):
        self.slide, self.grads, self.markers = slide, grads, markers
        self.nid = 100
        self.stack = [slide.shapes._spTree]
        self.bboxes = [[]]

    def _id(self):
        self.nid += 1; return self.nid

    def _add(self, xml, bbox):
        el = etree.fromstring(xml)
        self.stack[-1].append(el); self.bboxes[-1].append(bbox)
        return el

    def group_begin(self, name):
        gid = self._id()
        el = etree.fromstring(
            f'<p:grpSp {P} {A}><p:nvGrpSpPr><p:cNvPr id="{gid}" name="{escape(name)}"/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            f'<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/><a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr></p:grpSp>')
        self.stack[-1].append(el); self.stack.append(el); self.bboxes.append([])
        return el

    def group_end(self):
        el = self.stack.pop(); bbs = self.bboxes.pop()
        if not bbs:
            el.getparent().remove(el); return
        if len(bbs) == 1:  # unwrap single-child groups
            child = el[-1]; el.addprevious(child); el.getparent().remove(el)
            self.bboxes[-1].append(bbs[0]); return
        x0 = min(b[0] for b in bbs); y0 = min(b[1] for b in bbs)
        x1 = max(b[2] for b in bbs); y1 = max(b[3] for b in bbs)
        xf = el.find(".//{http://schemas.openxmlformats.org/drawingml/2006/main}xfrm")
        vals = dict(x=str(int(x0)), y=str(int(y0)), cx=str(max(1, int(x1 - x0))), cy=str(max(1, int(y1 - y0))))
        xf[0].set("x", vals["x"]); xf[0].set("y", vals["y"]); xf[1].set("cx", vals["cx"]); xf[1].set("cy", vals["cy"])
        xf[2].set("x", vals["x"]); xf[2].set("y", vals["y"]); xf[3].set("cx", vals["cx"]); xf[3].set("cy", vals["cy"])
        self.bboxes[-1].append((x0, y0, x1, y1))

    def sp(self, name, off, ext, geom, st, closed=True, rot=0, text=""):
        x, y = off; cx, cy = ext
        rot_attr = f' rot="{int((rot % 360)*60000)}"' if abs(rot) > 0.01 else ""
        xml = (f'<p:sp {P} {A}><p:nvSpPr><p:cNvPr id="{self._id()}" name="{escape(name)}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
               f'<p:spPr><a:xfrm{rot_attr}><a:off x="{int(x)}" y="{int(y)}"/><a:ext cx="{max(1,int(cx))}" cy="{max(1,int(cy))}"/></a:xfrm>'
               f'{geom}{fill_xml(st, self.grads, closed)}{ln_xml(st, self.markers)}{effect_xml(st)}</p:spPr>'
               f'<p:txBody><a:bodyPr rtlCol="0" anchor="ctr"/><a:lstStyle/><a:p><a:endParaRPr lang="ko-KR"/></a:p></p:txBody></p:sp>')
        self._add(xml, (x, y, x + cx, y + cy))

    def preset(self, name, prst, m, x, y, w, h, st, adj=None):
        """axis-aligned box (x,y,w,h) in local coords under similarity matrix m."""
        sc = math.hypot(m[0], m[1])
        cx, cy = app(m, x + w/2, y + h/2)
        W, H = w*sc*EMU, h*sc*EMU
        av = f'<a:gd name="adj" fmla="val {int(adj)}"/>' if adj is not None else ""
        geom = f'<a:prstGeom prst="{prst}"><a:avLst>{av}</a:avLst></a:prstGeom>'
        self.sp(name, (cx*EMU - W/2, cy*EMU - H/2), (W, H), geom, st, rot=rot_deg(m))

    def freeform(self, name, m, segs, st):
        segs = [(c, [app(m, *p) for p in pts]) for c, pts in segs]
        pts = [p for _, ps in segs for p in ps]
        x0 = min(p[0] for p in pts); y0 = min(p[1] for p in pts)
        x1 = max(p[0] for p in pts); y1 = max(p[1] for p in pts)
        W, H = max((x1 - x0)*EMU, 1), max((y1 - y0)*EMU, 1)
        def P_(p):
            return f'<a:pt x="{int((p[0]-x0)*EMU)}" y="{int((p[1]-y0)*EMU)}"/>'
        body = ""; closed = False
        for c, ps in segs:
            if c == "M": body += f"<a:moveTo>{P_(ps[0])}</a:moveTo>"
            elif c == "L": body += f"<a:lnTo>{P_(ps[0])}</a:lnTo>"
            elif c == "C": body += f"<a:cubicBezTo>{''.join(P_(p) for p in ps)}</a:cubicBezTo>"
            elif c == "Q": body += f"<a:quadBezTo>{''.join(P_(p) for p in ps)}</a:quadBezTo>"
            elif c == "Z": body += "<a:close/>"; closed = True
        geom = (f'<a:custGeom><a:avLst/><a:gdLst/><a:ahLst/><a:cxnLst/><a:rect l="0" t="0" r="r" b="b"/>'
                f'<a:pathLst><a:path w="{int(W)}" h="{int(H)}">{body}</a:path></a:pathLst></a:custGeom>')
        self.sp(name, (x0*EMU, y0*EMU), (W, H), geom, st, closed=closed)

    def line(self, name, m, x1, y1, x2, y2, st):
        (X1, Y1), (X2, Y2) = app(m, x1, y1), app(m, x2, y2)
        fh = ' flipH="1"' if X2 < X1 else ""; fv = ' flipV="1"' if Y2 < Y1 else ""
        ox, oy = min(X1, X2)*EMU, min(Y1, Y2)*EMU
        cx, cy = abs(X2 - X1)*EMU, abs(Y2 - Y1)*EMU
        xml = (f'<p:cxnSp {P} {A}><p:nvCxnSpPr><p:cNvPr id="{self._id()}" name="{escape(name)}"/><p:cNvCxnSpPr/><p:nvPr/></p:nvCxnSpPr>'
               f'<p:spPr><a:xfrm{fh}{fv}><a:off x="{int(ox)}" y="{int(oy)}"/><a:ext cx="{int(cx)}" cy="{int(cy)}"/></a:xfrm>'
               f'<a:prstGeom prst="line"><a:avLst/></a:prstGeom>{ln_xml(st, self.markers)}</p:spPr></p:cxnSp>')
        self._add(xml, (ox, oy, ox + cx, oy + cy))

    def text(self, m, x, y, txt, st):
        fs = float(st.get("font-size", 16)) * math.hypot(m[0], m[1])
        X, Y = app(m, x, y)
        anchor = st.get("text-anchor", "start")
        wide = sum(1.0 if ord(ch) > 0x2E80 else 0.62 for ch in txt) * fs + 8
        if anchor == "middle": left, algn = X - wide/2, "ctr"
        elif anchor == "end": left, algn = X - wide, "r"
        else: left, algn = X, "l"
        h = fs * 1.4
        top = Y - fs*0.36 - h/2  # centre the line box on the glyph's visual centre
        b = ' b="1"' if st.get("font-weight") in ("700", "bold") else ""
        it = ' i="1"' if st.get("font-style") == "italic" else ""
        col = st.get("fill", "#000000").lstrip("#")
        xml = (f'<p:sp {P} {A}><p:nvSpPr><p:cNvPr id="{self._id()}" name="Text: {escape(txt[:30])}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
               f'<p:spPr><a:xfrm><a:off x="{int(left*EMU)}" y="{int(top*EMU)}"/><a:ext cx="{int(wide*EMU)}" cy="{int(h*EMU)}"/></a:xfrm>'
               f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>'
               f'<p:txBody><a:bodyPr wrap="none" lIns="0" tIns="0" rIns="0" bIns="0" anchor="ctr" rtlCol="0"><a:noAutofit/></a:bodyPr><a:lstStyle/>'
               f'<a:p><a:pPr algn="{algn}"/><a:r><a:rPr lang="ko-KR" altLang="en-US" sz="{int(round(fs*0.75*100))}"{b}{it} dirty="0">'
               f'<a:solidFill>{color_xml(col, st["_opacity"])}</a:solidFill>'
               f'<a:latin typeface="{FONT}"/><a:ea typeface="{FONT}"/><a:cs typeface="{FONT}"/></a:rPr>'
               f'<a:t>{escape(txt)}</a:t></a:r></a:p></p:txBody></p:sp>')
        self._add(xml, (left*EMU, top*EMU, (left + wide)*EMU, (top + h)*EMU))

    def picture(self, png_bytes, m, x, y, w, h, name):
        X, Y = app(m, x, y); sc = math.hypot(m[0], m[1])
        pic = self.slide.shapes.add_picture(io.BytesIO(png_bytes), Emu(int(X*EMU)), Emu(int(Y*EMU)),
                                            Emu(int(w*sc*EMU)), Emu(int(h*sc*EMU)))
        pic.name = name
        el = pic._element; el.getparent().remove(el)
        self.stack[-1].append(el); self.bboxes[-1].append((X*EMU, Y*EMU, (X + w*sc)*EMU, (Y + h*sc)*EMU))

# ---------------------------------------------------------------- absorber pattern raster
def absorber_png(w, h, scale=4):
    s = 14*scale
    img = Image.new("RGB", (int(w*scale), int(h*scale)), "#16223A"); d = ImageDraw.Draw(img)
    for gy in range(0, int(h*scale) + s, s):
        for gx in range(0, int(w*scale) + s, s):
            c = (gx + s/2, gy + s/2)
            d.polygon([(gx, gy), (gx + s, gy), c], fill="#3D6AA8")
            d.polygon([(gx + s, gy), (gx + s, gy + s), c], fill="#2B4F82")
            d.polygon([(gx, gy + s), (gx + s, gy + s), c], fill="#1C3358")
            d.polygon([(gx, gy), (gx, gy + s), c], fill="#335C93")
    buf = io.BytesIO(); img.save(buf, "PNG"); return buf.getvalue()

# ---------------------------------------------------------------- walker
SECTION_NAMES = {"translate(0,570)": "01 Side View 테스트베드", "translate(40,1710)": "03-① Azimuth 0°",
                 "translate(40,2095)": "03-② Azimuth 10°", "translate(40,2480)": "03-③ Azimuth 30°"}

def walk(el, m, st, w, counter):
    tag = el.tag.replace(NS, "")
    if tag in ("defs",):
        return
    st = inherit(el, st)
    m = mul(m, parse_tf(el.get("transform")))
    f = lambda k, dflt=0: float(el.get(k, dflt))
    counter[tag] = counter.get(tag, 0) + 1
    name = f"{tag} {counter[tag]}"
    if tag in ("svg", "g"):
        grouped = tag == "g" and len(el) > 1
        if grouped:
            w.group_begin(SECTION_NAMES.get(el.get("transform", ""), f"Group {counter[tag]}"))
        for ch in el:
            if isinstance(ch.tag, str):
                walk(ch, m, st, w, counter)
        if grouped:
            w.group_end()
    elif tag == "rect":
        x, y, wd, ht, rx = f("x"), f("y"), f("width"), f("height"), f("rx")
        if st.get("fill") == "url(#abs)":
            w.picture(absorber_png(wd, ht), m, x, y, wd, ht, "Pyramid 흡수체 (pattern)")
        elif is_similarity(m):
            adj = rx / min(wd, ht) * 100000 if rx else None
            w.preset(name, "roundRect" if rx else "rect", m, x, y, wd, ht, st, adj)
        else:
            w.freeform(name, m, rect_segs(x, y, wd, ht, rx), st)
    elif tag in ("circle", "ellipse"):
        cx, cy = f("cx"), f("cy")
        rx = f("r") if tag == "circle" else f("rx"); ry = f("r") if tag == "circle" else f("ry")
        w.preset(name, "ellipse", m, cx - rx, cy - ry, 2*rx, 2*ry, st)
    elif tag == "line":
        w.line(name, m, f("x1"), f("y1"), f("x2"), f("y2"), st)
    elif tag in ("polygon", "polyline"):
        nums = [float(v) for v in re.split(r"[\s,]+", el.get("points").strip())]
        pts = list(zip(nums[::2], nums[1::2]))
        segs = [("M", [pts[0]])] + [("L", [p]) for p in pts[1:]] + ([("Z", [])] if tag == "polygon" else [])
        w.freeform(name, m, segs, st)
    elif tag == "path":
        w.freeform(name, m, parse_path(el.get("d")), st)
    elif tag == "text":
        w.text(m, f("x"), f("y"), "".join(el.itertext()), st)

def main():
    root = etree.parse(SRC).getroot()
    W, H = float(root.get("width")), float(root.get("height"))
    grads, markers = parse_defs(root)
    prs = Presentation()
    prs.slide_width, prs.slide_height = Emu(int(W*EMU)), Emu(int(H*EMU))
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    w = Writer(slide, grads, markers)
    walk(root, I, {"fill": "#000000", "_opacity": 1.0}, w, {})
    prs.save(OUT)
    print("saved", OUT)

if __name__ == "__main__":
    main()
