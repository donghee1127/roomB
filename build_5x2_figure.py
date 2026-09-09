# -*- coding: utf-8 -*-
"""과제 3페이지 개념도를 5:2 비율 레이아웃으로 재구성.
원본의 소형 이미지(3D 렌더/플롯 등)는 잘라서 그대로 사용(무왜곡),
상자·화살표·글자는 새로 그림."""
import numpy as np
from pypdf import PdfReader
from PIL import Image, ImageDraw, ImageFont

SRC = PdfReader("과제계획서.pdf").pages[2].images[1].image.convert("RGB")

def crop(b):
    return SRC.crop(b)

# ---- 소형 이미지 크롭 (원본 1992x1536 기준) ----
C = {
 "S1": crop((14, 82, 470, 392)),
 "S2": crop((535, 90, 905, 398)),
 "S3": crop((1058, 96, 1478, 410)),
 "S4": crop((1548, 104, 1988, 396)),
 "P1a": crop((1090, 602, 1320, 890)),
 "P1b": crop((1345, 610, 1566, 872)),
 "P1c": crop((1650, 636, 1912, 878)),
 "P2a": crop((36, 1150, 626, 1286)),
 "P2b": crop((632, 1164, 905, 1350)),
 "P2c": crop((96, 1357, 546, 1451)),
 "P3a": crop((1078, 1152, 1370, 1416)),
 "P3b": crop((1436, 1156, 1720, 1424)),
 "P3c": crop((1736, 1196, 1984, 1422)),
}

W, H = 2500, 1000
NAVY = (17, 26, 43)
INK = (34, 40, 55)
GRAY = (110, 118, 130)
BLUE = (74, 114, 184)
GREEN = (44, 150, 92)
ORANGE = (224, 138, 46)
BROWN = (140, 78, 44)
CYAN = (31, 166, 222)

cv = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(cv)

FONT = "C:/Windows/Fonts/malgun.ttf"
FONTB = "C:/Windows/Fonts/malgunbd.ttf"
def f(sz, bold=True):
    return ImageFont.truetype(FONTB if bold else FONT, sz)

def ctext(x, y, s, font, fill, anchor="mm"):
    d.text((x, y), s, font=font, fill=fill, anchor=anchor)

def rrect(box, radius, fill=None, outline=None, width=2):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)

def fit(im, cw, ch):
    im = im.copy()
    im.thumbnail((cw, ch), Image.LANCZOS)
    return im

def paste_center(im, cx, cy, cw, ch, frame=True):
    th = fit(im, cw, ch)
    x = int(cx - th.width / 2); y = int(cy - th.height / 2)
    if frame:
        d.rectangle([x - 3, y - 3, x + th.width + 2, y + th.height + 2],
                    fill="white", outline=(210, 214, 220), width=1)
    cv.paste(th, (x, y))

# ================= 제목 =================
d.rectangle([0, 0, W, 84], fill=NAVY)
ctext(30, 42, "과제 최종목표", f(30), ORANGE, "lm")
ctext(255, 43, "고출력·광대역 특성을 갖는 메타-레이돔 통합 송·수신 모듈 개발",
      f(29), "white", "lm")

# ================= 밴드 1 : 단계적 배열 확장 =================
b1y0, b1y1 = 100, 452
ctext(30, b1y0 + 14, "1  단계적 배열 확장", f(23), INK, "lm")
ctext(258, b1y0 + 16, "2×2 Unit Cell → 8×8 Sub-array → Unit Module → N×Unit Module",
      f(16, bold=False), GRAY, "lm")
stages = [
    ("서브어레이 설계", BLUE, "S1"),
    ("단위 모듈 설계", GREEN, "S2"),
    ("확장형 단위 모듈 설계", ORANGE, "S3"),
    ("통합 안테나 시스템", BLUE, "S4"),
]
n = 4
gap = 78
cardw = (W - 60 - gap * (n - 1)) // n
cy0 = b1y0 + 40
cardh = b1y1 - cy0
for i, (name, col, key) in enumerate(stages):
    x = 30 + i * (cardw + gap)
    rrect([x, cy0, x + cardw, cy0 + cardh], 14, fill=(248, 249, 251),
          outline=col, width=3)
    d.rounded_rectangle([x, cy0, x + cardw, cy0 + 44], 14, fill=col)
    d.rectangle([x, cy0 + 30, x + cardw, cy0 + 44], fill=col)
    ctext(x + cardw / 2, cy0 + 22, name, f(19), "white", "mm")
    paste_center(C[key], x + cardw / 2, cy0 + 44 + (cardh - 44) / 2,
                 cardw - 26, cardh - 60, frame=False)
ADEEP = (46, 84, 150)
for i in range(n - 1):
    x = 30 + i * (cardw + gap)
    gx0 = x + cardw            # 왼쪽 카드 오른쪽 끝
    gx1 = x + cardw + gap      # 오른쪽 카드 왼쪽 끝
    ay = cy0 + cardh / 2
    shaft_x0 = gx0 + 10
    shaft_x1 = gx1 - 30
    d.rectangle([shaft_x0, ay - 15, shaft_x1, ay + 15], fill=ADEEP)
    d.polygon([(shaft_x1, ay - 32), (gx1 - 12, ay), (shaft_x1, ay + 32)],
              fill=ADEEP)

# ================= 밴드 2 : 3대 핵심 개발기술 =================
b2y0 = 484
ctext(30, b2y0 + 14, "2  3대 핵심 개발기술", f(23), INK, "lm")
py0 = b2y0 + 40
py1 = H - 18
HDR = 46

def cap_draw(cx, cy, cap, maxw):
    cf = f(15, bold=False)
    if d.textlength(cap, font=cf) <= maxw:
        ctext(cx, cy, cap, cf, INK, "mm")
        return
    ws = cap.split(" "); m = (len(ws) + 1) // 2
    ctext(cx, cy - 10, " ".join(ws[:m]), cf, INK, "mm")
    ctext(cx, cy + 10, " ".join(ws[m:]), cf, INK, "mm")

def draw_panel(x, pw, title, col, layout):
    rrect([x, py0, x + pw, py1], 12, fill="white", outline=col, width=3)
    d.rounded_rectangle([x, py0, x + pw, py0 + HDR], 12, fill=col)
    d.rectangle([x, py0 + HDR - 14, x + pw, py0 + HDR], fill=col)
    ctext(x + pw / 2, py0 + HDR / 2, title, f(17), "white", "mm")
    ix0, iy0 = x + 12, py0 + HDR + 8
    ix1, iy1 = x + pw - 12, py1 - 10
    layout(ix0, iy0, ix1, iy1)

pg = 24
pw = (W - 60 - pg * 2) // 3
X = [30 + k * (pw + pg) for k in range(3)]

# --- 패널 1 : 3열 ---
def L1(x0, y0, x1, y1):
    subs = [("P1a", "Unit Cell 연구"), ("P1b", "메타표면 개발"), ("P1c", "레이돔 개발")]
    cw = (x1 - x0) / 3
    for j, (k, cap) in enumerate(subs):
        cx = x0 + cw * (j + 0.5)
        paste_center(C[k], cx, (y0 + y1) / 2 - 12, cw - 14, (y1 - y0) - 44)
        cap_draw(cx, y1 - 14, cap, cw - 6)

# --- 패널 2 : 위(넓은 PDN) + 아래 2개 ---
def L2(x0, y0, x1, y1):
    midy = y0 + (y1 - y0) * 0.58
    paste_center(C["P2a"], (x0 + x1) / 2, (y0 + midy) / 2 - 6,
                 (x1 - x0) - 12, (midy - y0) - 30)
    cap_draw((x0 + x1) / 2, midy - 6, "송수신 모듈 PDN 설계·최적화", (x1 - x0))
    cw = (x1 - x0) / 2
    for j, (k, cap) in enumerate([("P2c", "고방열 기판 적용"), ("P2b", "Thermal 해석")]):
        cx = x0 + cw * (j + 0.5)
        paste_center(C[k], cx, (midy + y1) / 2 + 2, cw - 18, (y1 - midy) - 34)
        cap_draw(cx, y1 - 13, cap, cw - 6)

# --- 패널 3 : 3열 ---
def L3(x0, y0, x1, y1):
    subs = [("P3a", "안테나 소자 개발"), ("P3b", "배열 구조 설계 연구"),
            ("P3c", "배열 안테나 개발")]
    cw = (x1 - x0) / 3
    for j, (k, cap) in enumerate(subs):
        cx = x0 + cw * (j + 0.5)
        paste_center(C[k], cx, (y0 + y1) / 2 - 12, cw - 14, (y1 - y0) - 44)
        cap_draw(cx, y1 - 14, cap, cw - 6)

draw_panel(X[0], pw, "전파 투과·빔조향 레이돔–메타표면 구조 개발", BROWN, L1)
draw_panel(X[1], pw, "위성통신용 Tx/Rx 통합 안테나·RF 모듈 개발", CYAN, L2)
draw_panel(X[2], pw, "저유전·저손실 소재 기반 고이득 배열 안테나 개발", GREEN, L3)

cv.save("과제개요_개념도_5x2_재구성.png")
print("saved 과제개요_개념도_5x2_재구성.png", cv.size)
