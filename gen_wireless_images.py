# -*- coding: utf-8 -*-
"""
'유비쿼터스 커넥티비티' 슬라이드용 인포그래픽 4종 생성
1. ISTN (위성-지상 통합망)
2. 두산에너빌리티 - 무선 센서/통신 원전 모니터링
3. 두산밥캣 - 5G 초저지연 원격조종 Max Control System
4. 두산로보틱스 - 로봇 관절 무선화 60GHz 모듈
"""
import math
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 2400, 1350

NAVY = (0x11, 0x1A, 0x2B)
DARK_BG = (0x15, 0x1B, 0x27)
DARK_BG2 = (0x0D, 0x12, 0x1D)
PANEL = (0x1E, 0x27, 0x39)
PANEL2 = (0x25, 0x30, 0x45)
ORANGE = (0xE8, 0x83, 0x3A)
BLUE = (0x4F, 0x9D, 0xD6)
LBLUE = (0x9D, 0xCB, 0xEC)
WHITE = (0xF5, 0xF6, 0xF8)
GRAY = (0xB4, 0xBC, 0xCA)
DGRAY = (0x6C, 0x76, 0x8C)
GREEN = (0x63, 0xC1, 0x9C)
TEAL = (0x3E, 0xB6, 0xB0)
RED = (0xD8, 0x5A, 0x5A)
PURPLE = (0x9B, 0x8C, 0xD6)

FONT_R = "C:/Windows/Fonts/malgun.ttf"
FONT_B = "C:/Windows/Fonts/malgunbd.ttf"


def f(sz, b=True):
    return ImageFont.truetype(FONT_B if b else FONT_R, sz)


def new_canvas():
    return Image.new("RGB", (W, H), DARK_BG)


def vgrad(im, box, top_c, bot_c):
    x0, y0, x1, y1 = box
    h = y1 - y0
    dr = ImageDraw.Draw(im)
    for i in range(h):
        t = i / max(h - 1, 1)
        c = tuple(int(top_c[k] + (bot_c[k] - top_c[k]) * t) for k in range(3))
        dr.line([(x0, y0 + i), (x1, y0 + i)], fill=c)


def header(d, title, sub, kicker):
    d.rectangle([0, 0, W, 150], fill=NAVY)
    d.rectangle([0, 150, W, 156], fill=ORANGE)
    d.text((60, 34), kicker, font=f(20), fill=ORANGE)
    d.text((60, 62), title, font=f(40), fill=WHITE)
    d.text((60, 112), sub, font=f(19, b=False), fill=GRAY)


def T(d, x, y, s, fnt, fill, anchor="mm"):
    d.text((x, y), s, font=fnt, fill=fill, anchor=anchor)


def dashed_line(d, p1, p2, fill, width=3, dash=14, gap=10):
    x1, y1 = p1
    x2, y2 = p2
    dist = math.hypot(x2 - x1, y2 - y1)
    if dist == 0:
        return
    ux, uy = (x2 - x1) / dist, (y2 - y1) / dist
    n = int(dist // (dash + gap)) + 1
    pos = 0.0
    for _ in range(n):
        sx, sy = x1 + ux * pos, y1 + uy * pos
        epos = min(pos + dash, dist)
        ex, ey = x1 + ux * epos, y1 + uy * epos
        d.line([(sx, sy), (ex, ey)], fill=fill, width=width)
        pos += dash + gap


def arrow_head(d, tip, direction, size, fill):
    ang = math.atan2(direction[1], direction[0])
    a1 = ang + math.radians(150)
    a2 = ang - math.radians(150)
    p1 = (tip[0] + size * math.cos(a1), tip[1] + size * math.sin(a1))
    p2 = (tip[0] + size * math.cos(a2), tip[1] + size * math.sin(a2))
    d.polygon([tip, p1, p2], fill=fill)


def wifi_arcs(d, x, y, color, n=3, r0=14, gap=11, a0=-50, a1=50, width=5):
    for i in range(n):
        r = r0 + i * gap
        d.arc([x - r, y - r, x + r, y + r], a0, a1, fill=color, width=width)


def radial_ping(d, cx, cy, color, n=3, r0=10, gap=14, width=4):
    for i in range(n):
        r = r0 + i * gap
        bbox = [cx - r, cy - r, cx + r, cy + r]
        d.ellipse(bbox, outline=color, width=width)


def rrect(d, box, r, fill=None, outline=None, width=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def footer_tag(d, text):
    tw = d.textlength(text, font=f(17, b=False))
    d.rounded_rectangle([W - tw - 90, H - 60, W - 30, H - 20], 10, fill=PANEL2, outline=DGRAY, width=2)
    T(d, W - tw - 60 + tw / 2, H - 40, text, f(17, b=False), GRAY)


# ============================================================
# 1. ISTN — Integrated Satellite Terrestrial Network
# ============================================================
def draw_istn():
    im = new_canvas()
    d = ImageDraw.Draw(im)
    header(d, "ISTN : 위성–지상 통합 네트워크",
           "Integrated Satellite Terrestrial Network — 저궤도 위성으로 여는 유비쿼터스 커넥티비티",
           "GLOBAL TREND")

    sky_top, sky_bot = 176, 980
    vgrad(im, [0, sky_top, W, sky_bot], (0x07, 0x0A, 0x16), (0x16, 0x2A, 0x45))
    d = ImageDraw.Draw(im)

    import random
    random.seed(7)
    for _ in range(140):
        sx = random.randint(0, W)
        sy = random.randint(sky_top, sky_bot - 250)
        r = random.choice([1, 1, 1, 2])
        br = random.randint(120, 255)
        d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=(br, br, br))

    ground_y = 980
    d.rectangle([0, ground_y, W, H], fill=(0x10, 0x2A, 0x22))
    vgrad(im, [0, ground_y, W, ground_y + 60], (0x1c, 0x3a, 0x30), (0x10, 0x2a, 0x22))
    d = ImageDraw.Draw(im)

    # mountains (left, 음영지역)
    mtn_pts = [(0, ground_y)]
    peaks = [(120, 760), (320, 860), (520, 720), (760, 900), (980, 800)]
    for p in peaks:
        mtn_pts.append(p)
    mtn_pts.append((1000, ground_y))
    d.polygon(mtn_pts, fill=(0x24, 0x30, 0x30))
    for p in peaks[:5]:
        if p[1] < 800:
            d.polygon([(p[0]-40,p[1]+40),(p[0],p[1]),(p[0]+40,p[1]+40)], fill=(0x35,0x45,0x45))

    # sea (middle, 해상)
    d.rectangle([1000, 860, 1750, ground_y], fill=(0x0d, 0x28, 0x3c))
    for i, yy in enumerate(range(880, ground_y, 26)):
        amp = 8
        pts = []
        for xx in range(1000, 1751, 20):
            pts.append((xx, yy + amp * math.sin(xx / 40 + i)))
        d.line(pts, fill=(0x1c, 0x46, 0x63), width=3)

    # city skyline (right, 지상 통신망)
    import random as r2
    r2.seed(3)
    bx = 1780
    while bx < W - 40:
        bw = r2.randint(50, 95)
        bh = r2.randint(90, 260)
        d.rectangle([bx, ground_y - bh, bx + bw, ground_y], fill=(0x1b, 0x24, 0x36))
        for wy in range(ground_y - bh + 14, ground_y - 10, 26):
            for wx in range(bx + 8, bx + bw - 8, 20):
                if r2.random() > 0.4:
                    d.rectangle([wx, wy, wx + 8, wy + 12], fill=ORANGE if r2.random() > 0.85 else LBLUE)
        bx += bw + 14

    labels_ground = [(500, ground_y + 45, "산간 음영지역"), (1370, ground_y + 45, "해상 음영지역"),
                      (2130, ground_y + 45, "지상 통신망 (Terrestrial)")]
    for lx, ly, lt in labels_ground:
        tw = d.textlength(lt, font=f(19))
        rrect(d, [lx - tw/2 - 16, ly - 22, lx + tw/2 + 16, ly + 20], 10, fill=PANEL, outline=DGRAY, width=2)
        T(d, lx, ly - 1, lt, f(19), WHITE)

    # LEO satellites
    sats = [(430, 330), (860, 250), (1300, 300), (1720, 260), (2080, 360)]
    # inter-satellite links
    for i in range(len(sats) - 1):
        dashed_line(d, sats[i], sats[i+1], LBLUE, width=3, dash=10, gap=8)

    def satellite(px, py, s=1.0):
        bw, bh = 46*s, 30*s
        d.rectangle([px-bw/2, py-bh/2, px+bw/2, py+bh/2], fill=WHITE, outline=GRAY, width=2)
        pw, ph = 34*s, 58*s
        d.rectangle([px-bw/2-pw-6*s, py-ph/2, px-bw/2-6*s, py+ph/2], fill=BLUE, outline=LBLUE, width=2)
        d.rectangle([px+bw/2+6*s, py-ph/2, px+bw/2+pw+6*s, py+ph/2], fill=BLUE, outline=LBLUE, width=2)
        for gx in range(int(px-bw/2-pw-6*s), int(px-bw/2-6*s), int(8*s)):
            d.line([(gx, py-ph/2), (gx, py+ph/2)], fill=LBLUE, width=1)
        for gx in range(int(px+bw/2+6*s), int(px+bw/2+pw+6*s), int(8*s)):
            d.line([(gx, py-ph/2), (gx, py+ph/2)], fill=LBLUE, width=1)
        d.arc([px-6*s, py-bh/2-26*s, px+26*s, py-bh/2+6*s], 180, 320, fill=GRAY, width=int(4*s))

    ground_targets = [(500, ground_y - 10), (1370, ground_y - 10), (2130, ground_y - 260)]
    for i, (sx, sy) in enumerate(sats):
        satellite(sx, sy, 1.05)
    for gx, gy in ground_targets:
        nearest = min(sats, key=lambda p: (p[0]-gx)**2 + (p[1]-gy)**2)
        dashed_line(d, nearest, (gx, gy), ORANGE, width=3, dash=12, gap=9)
        radial_ping(d, gx, gy, ORANGE, n=2, r0=10, gap=12, width=3)

    tw = d.textlength("저궤도 위성 (LEO) 군집", font=f(21))
    rrect(d, [1160-tw/2-18, 176+20, 1160+tw/2+18, 176+68], 10, fill=PANEL, outline=BLUE, width=2)
    T(d, 1160, 176+44, "저궤도 위성 (LEO) 군집", f(21), LBLUE)

    footer_tag(d, "위성 ↔ 지상망 통합으로 통신 음영지역 해소")
    im.save("1_ISTN.png")
    print("saved 1_ISTN.png", im.size)


# ============================================================
# 2. 두산에너빌리티 — 무선 센서/통신 원전 모니터링
# ============================================================
def draw_energy():
    im = new_canvas()
    d = ImageDraw.Draw(im)
    header(d, "두산에너빌리티 — 원전 통합 모니터링",
           "무선 센서/통신 기술을 활용한 원자력발전소 설비 실시간 모니터링",
           "DOOSAN ENERBILITY")

    vgrad(im, [156, H, W, H], DARK_BG, DARK_BG)
    d = ImageDraw.Draw(im)
    import random as r3
    r3.seed(11)
    for gx in range(80, W-40, 70):
        for gy in range(220, 1220, 70):
            if r3.random() > 0.55:
                d.ellipse([gx-2, gy-2, gx+2, gy+2], fill=(0x1c, 0x24, 0x35))
    d.rectangle([0, 1240, W, H], fill=(0x18, 0x1E, 0x2C))
    d.line([(0, 1240), (W, 1240)], fill=DGRAY, width=2)

    # containment dome + building
    cx, base_y = 780, 1240
    d.rectangle([cx-260, base_y-420, cx+260, base_y], fill=(0x2a, 0x33, 0x47), outline=DGRAY, width=3)
    d.pieslice([cx-260, base_y-820, cx+260, base_y-300], 180, 360, fill=(0x33, 0x3e, 0x55), outline=DGRAY, width=3)
    # cooling tower
    tx = cx+430
    d.polygon([(tx-160, base_y), (tx-95, base_y-540), (tx-60, base_y-630), (tx-25, base_y-540),
               (tx+40, base_y)], fill=(0x2a, 0x33, 0x47), outline=DGRAY, width=3)
    ccx, ccy = tx-60, base_y-660
    for ddx, ddy, rr in [(-26,-8,24),(2,-26,30),(30,-6,22),(-10,14,20),(18,16,17)]:
        d.ellipse([ccx+ddx-rr, ccy+ddy-rr, ccx+ddx+rr, ccy+ddy+rr], fill=(0xC7,0xCE,0xDA))
    # radiation trefoil badge
    bx, by = cx, base_y-620
    d.ellipse([bx-34, by-34, bx+34, by+34], fill=(0x20,0x26,0x34), outline=ORANGE, width=3)
    for k in range(3):
        ang = math.radians(90 + k*120)
        px, py = bx + 20*math.cos(ang), by + 20*math.sin(ang)
        d.pieslice([px-14, py-14, px+14, py+14], 0, 360, fill=ORANGE)
    d.ellipse([bx-7, by-7, bx+7, by+7], fill=(0x20,0x26,0x34))

    T(d, cx, base_y+40, "원자력발전소 설비 (원자로 / 냉각탑 / 배관)", f(20), GRAY)

    # sensor nodes on the plant
    sensors = [
        (cx-190, base_y-140, "진동 센서"),
        (cx-30, base_y-500, "방사선 센서"),
        (cx+180, base_y-100, "압력 센서"),
        (tx-100, base_y-200, "온도 센서"),
        (cx+230, base_y-420, "배관 누설 감지"),
    ]
    gw_x, gw_y = 1560, 660
    for (sx, sy, name) in sensors:
        d.ellipse([sx-16, sy-16, sx+16, sy+16], fill=WHITE, outline=TEAL, width=3)
        wifi_arcs(d, sx, sy-18, TEAL, n=3, r0=12, gap=10, a0=200, a1=340, width=4)
        tw = d.textlength(name, font=f(16, b=False))
        rrect(d, [sx-tw/2-10, sy+22, sx+tw/2+10, sy+52], 8, fill=PANEL, outline=DGRAY, width=1)
        T(d, sx, sy+37, name, f(16, b=False), WHITE)
        dashed_line(d, (sx, sy), (gw_x, gw_y), GREEN, width=2, dash=10, gap=8)

    # gateway hub
    rrect(d, [gw_x-90, gw_y-70, gw_x+90, gw_y+70], 16, fill=PANEL2, outline=GREEN, width=3)
    T(d, gw_x, gw_y-30, "무선 게이트웨이", f(19), WHITE)
    T(d, gw_x, gw_y+2, "Wireless Gateway", f(14, b=False), GRAY)
    wifi_arcs(d, gw_x, gw_y-72, GREEN, n=3, r0=14, gap=12, a0=200, a1=340, width=4)
    radial_ping(d, gw_x+70, gw_y+50, GREEN, n=2, r0=8, gap=10, width=2)

    # link to control room
    ctrl_x, ctrl_y = 2080, 660
    dashed_line(d, (gw_x+90, gw_y), (ctrl_x-160, ctrl_y), ORANGE, width=4, dash=14, gap=10)
    arrow_head(d, (ctrl_x-160, ctrl_y), (1, 0), 16, ORANGE)

    # control room monitor
    rrect(d, [ctrl_x-160, ctrl_y-220, ctrl_x+180, ctrl_y+220], 14, fill=(0x0e,0x13,0x1f), outline=ORANGE, width=3)
    d.rectangle([ctrl_x-160, ctrl_y-220, ctrl_x+180, ctrl_y-184], fill=ORANGE)
    T(d, ctrl_x+10, ctrl_y-202, "통합 모니터링 관제센터", f(17), NAVY)
    gx0, gy0 = ctrl_x-130, ctrl_y+170
    axes_w, axes_h = 280, 320
    d.line([(gx0, gy0), (gx0, gy0-axes_h)], fill=DGRAY, width=2)
    d.line([(gx0, gy0), (gx0+axes_w, gy0)], fill=DGRAY, width=2)
    chart = [0, 40, 25, 70, 50, 90, 60, 100, 75, 55, 85]
    pts = [(gx0 + i*(axes_w/(len(chart)-1)), gy0 - v*0.95) for i, v in enumerate(chart)]
    d.line(pts, fill=GREEN, width=4)
    for p in pts:
        d.ellipse([p[0]-4, p[1]-4, p[0]+4, p[1]+4], fill=WHITE)
    T(d, ctrl_x+10, ctrl_y-165+140+50, "", f(10), WHITE)

    footer_tag(d, "다중 무선 센서 → 게이트웨이 → 실시간 관제센터 전송")
    im.save("2_Doosan_Enerbility_원전모니터링.png")
    print("saved 2_Doosan_Enerbility_원전모니터링.png", im.size)


# ============================================================
# 3. 두산밥캣 — Max Control System (5G 초저지연 원격조종)
# ============================================================
def draw_bobcat():
    im = new_canvas()
    d = ImageDraw.Draw(im)
    header(d, "두산밥캣 — MAX Control System",
           "5G 기반 초저지연(Ultra-Low Latency) 건설장비 원격 조종 기술",
           "DOOSAN BOBCAT")

    base_y = 1220
    d.rectangle([0, base_y, W, H], fill=(0x18,0x1E,0x2C))
    d.line([(0, base_y), (W, base_y)], fill=DGRAY, width=2)
    import random as r4
    r4.seed(5)
    for gx in range(80, W-40, 70):
        for gy in range(220, base_y-20, 70):
            if r4.random() > 0.55:
                d.ellipse([gx-2, gy-2, gx+2, gy+2], fill=(0x1c, 0x24, 0x35))

    # --- operator station (left) ---
    ox = 420
    # desk
    d.rectangle([ox-280, base_y-40, ox+280, base_y-10], fill=(0x2a,0x33,0x47))
    # monitors
    for i, mx in enumerate([-150, 150]):
        mxx = ox+mx
        rrect(d, [mxx-140, base_y-700, mxx+140, base_y-90], 12, fill=(0x0e,0x13,0x1f), outline=BLUE, width=3)
        d.rectangle([mxx-125, base_y-680, mxx+125, base_y-110], fill=(0x10,0x2a,0x3c))
        # camera-feed grid
        for gxi in range(2):
            for gyi in range(2):
                gx0 = mxx-120+gxi*130
                gy0 = base_y-670+gyi*290
                d.rectangle([gx0, gy0, gx0+120, gy0+275], outline=TEAL, width=2)
        d.rectangle([mxx-16, base_y-90, mxx+16, base_y-60], fill=(0x2a,0x33,0x47))
    # operator silhouette
    px, py = ox, base_y-40
    d.ellipse([px-28, py-190, px+28, py-134], fill=(0x3a,0x44,0x5c))
    d.polygon([(px-70, py-30), (px-60, py-140), (px+60, py-140), (px+70, py-30)], fill=(0x3a,0x44,0x5c))
    T(d, ox, base_y+40, "원격 관제실 (조종석)", f(20), GRAY)
    T(d, ox, base_y+70, "Remote Control Station", f(15, b=False), DGRAY)

    # --- 5G tower (middle) ---
    tx, ty = 1200, base_y-40
    P = 650
    d.line([(tx, ty), (tx, ty-P)], fill=(0x8a,0x93,0xa6), width=10)
    arm_fracs = [0.11, 0.31, 0.50]
    for i, frac in enumerate(arm_fracs):
        yy = ty - P + P*frac
        wid = 150 - i*22
        d.line([(tx-wid, yy), (tx+wid, yy)], fill=(0x8a,0x93,0xa6), width=8)
        d.line([(tx-wid, yy), (tx, ty-P+18)], fill=(0x6c,0x76,0x8c), width=4)
        d.line([(tx+wid, yy), (tx, ty-P+18)], fill=(0x6c,0x76,0x8c), width=4)
    wifi_arcs(d, tx, ty-P, ORANGE, n=4, r0=24, gap=24, a0=200, a1=340, width=6)
    wifi_arcs(d, tx, ty-P, ORANGE, n=4, r0=24, gap=24, a0=20, a1=160, width=6)
    tw = d.textlength("5G", font=f(30))
    rrect(d, [tx-60, ty-P-60, tx+60, ty-P-10], 10, fill=ORANGE, outline=None)
    T(d, tx, ty-P-35, "5G", f(30), NAVY)
    lbl = "초저지연 통신 (Ultra-Low Latency)"
    tw = d.textlength(lbl, font=f(20))
    rrect(d, [tx-tw/2-20, ty-P+30, tx+tw/2+20, ty-P+74], 10, fill=PANEL, outline=ORANGE, width=2)
    T(d, tx, ty-P+52, lbl, f(20), WHITE)

    # command / feedback arrows
    dashed_line(d, (ox+290, base_y-560), (tx-160, ty-P+120), BLUE, width=4, dash=14, gap=10)
    arrow_head(d, (tx-160, ty-P+120), (1, -0.35), 16, BLUE)
    T(d, (ox+tx)/2+20, base_y-650, "제어 명령", f(16, b=False), LBLUE)
    dashed_line(d, (tx-160, ty-P+230), (ox+290, base_y-460), GREEN, width=4, dash=14, gap=10)
    arrow_head(d, (ox+290, base_y-460), (-1, 0.2), 16, GREEN)
    T(d, (ox+tx)/2+20, base_y-380, "영상/센서 피드백", f(16, b=False), GREEN)

    # --- equipment (right): skid steer loader ---
    lx, ly = 1850, base_y-10
    body_col = (0xE8, 0x83, 0x3A)
    d.rounded_rectangle([lx-285, ly-285, lx+180, ly-105], 22, fill=body_col)
    d.rectangle([lx-210, ly-225, lx+60, ly-135], fill=(0x10,0x2a,0x3c))
    d.rectangle([lx-202, ly-217, lx+15, ly-142], outline=(0x9d,0xcb,0xec), width=3)
    # arm + bucket
    d.line([(lx+135, ly-240), (lx+345, ly-60)], fill=(0x2a,0x33,0x47), width=38)
    d.polygon([(lx+315, ly-90), (lx+450, ly-45), (lx+420, ly+30), (lx+292, ly-7)], fill=(0x2a,0x33,0x47))
    # wheels
    for wx in [lx-210, lx+15]:
        d.ellipse([wx-67, ly-105, wx+67, ly+27], fill=(0x1a,0x1e,0x28), outline=(0x44,0x4c,0x5c), width=8)
        d.ellipse([wx-24, ly-63, wx+24, ly-15], fill=(0x44,0x4c,0x5c))
    # antenna + ping on equipment
    d.line([(lx-150, ly-285), (lx-150, ly-360)], fill=GRAY, width=5)
    radial_ping(d, lx-150, ly-366, ORANGE, n=3, r0=12, gap=14, width=3)

    T(d, lx-30, base_y+40, "무인 원격조종 건설장비 (스키드로더)", f(20), GRAY)
    T(d, lx-30, base_y+70, "Remotely Operated Equipment", f(15, b=False), DGRAY)

    footer_tag(d, "조종석 ↔ 5G ↔ 장비 : 실시간 동기화 원격 제어")
    im.save("3_Doosan_Bobcat_MaxControl.png")
    print("saved 3_Doosan_Bobcat_MaxControl.png", im.size)


# ============================================================
# 4. 두산로보틱스 — 로봇 관절 무선화 60GHz 모듈
# ============================================================
def draw_robotics():
    im = new_canvas()
    d = ImageDraw.Draw(im)
    header(d, "두산로보틱스 — 로봇 관절 무선화",
           "협동로봇 관절 통신 무선화를 위한 60GHz 밀리미터파(mmWave) 모듈",
           "DOOSAN ROBOTICS")

    mid_x = W // 2
    d.line([(mid_x, 190), (mid_x, H-40)], fill=DGRAY, width=2)

    import random as r5
    r5.seed(9)
    for gx in range(80, W-40, 70):
        for gy in range(280, H-160, 70):
            if r5.random() > 0.55:
                d.ellipse([gx-2, gy-2, gx+2, gy+2], fill=(0x1c, 0x24, 0x35))

    def base_and_label(cx, title_txt, color):
        base_y = H - 150
        d.rectangle([cx-140, base_y, cx+140, base_y+30], fill=(0x2a,0x33,0x47), outline=DGRAY, width=2)
        tw = d.textlength(title_txt, font=f(22))
        rrect(d, [cx-tw/2-20, 210, cx+tw/2+20, 258], 10, fill=color[0], outline=color[1], width=2)
        T(d, cx, 234, title_txt, f(22), color[2])
        return base_y

    def arm_chain(cx, base_y, wireless):
        joints = []
        x, y = cx, base_y
        seglen = [270, 250, 220, 160]
        angle = -90
        angles_delta = [0, -35, 50, -40]
        for i, L in enumerate(seglen):
            angle += angles_delta[i]
            nx = x + L * math.cos(math.radians(angle))
            ny = y + L * math.sin(math.radians(angle))
            joints.append((x, y))
            # link
            perp = math.radians(angle+90)
            wgt = 26 - i*3
            dx, dy = wgt*math.cos(perp), wgt*math.sin(perp)
            poly = [(x+dx,y+dy), (nx+dx,ny+dy), (nx-dx,ny-dy), (x-dx,y-dy)]
            d.polygon(poly, fill=(0x3a,0x44,0x5c), outline=(0x55,0x60,0x78))
            if not wireless:
                cabledx, cabledy = (wgt+10)*math.cos(perp), (wgt+10)*math.sin(perp)
                d.line([(x+cabledx,y+cabledy), (nx+cabledx,ny+cabledy)], fill=RED, width=6)
            x, y = nx, ny
        joints.append((x, y))
        for i, (jx, jy) in enumerate(joints):
            r = 30 if i == 0 else 22
            d.ellipse([jx-r, jy-r, jx+r, jy+r], fill=(0x25,0x30,0x45), outline=(0x8a,0x93,0xa6), width=4)
            if wireless and i > 0:
                d.ellipse([jx-10, jy-10, jx+10, jy+10], fill=GREEN)
                wifi_arcs(d, jx, jy-14, GREEN, n=2, r0=16, gap=10, a0=200, a1=340, width=3)
            elif not wireless and i > 0:
                d.ellipse([jx-9, jy-9, jx+9, jy+9], fill=RED)
        # gripper at end
        ex, ey = joints[-1]
        d.line([(ex-22, ey), (ex-22, ey-46)], fill=(0x8a,0x93,0xa6), width=10)
        d.line([(ex+22, ey), (ex+22, ey-46)], fill=(0x8a,0x93,0xa6), width=10)
        return joints

    # LEFT: wired (before)
    lcx = mid_x - 560
    lbase = base_and_label(lcx+40, "기존 : 유선 (Wired)", (PANEL, RED, RED))
    arm_chain(lcx+40, lbase, wireless=False)
    T(d, lcx+40, lbase+55, "케이블 꼬임·단선 위험 / 가동범위 제약", f(17, b=False), GRAY)

    # RIGHT: wireless (after)
    rcx = mid_x + 560
    rbase = base_and_label(rcx-40, "적용 : 무선 (60GHz Wireless)", (PANEL, GREEN, GREEN))
    arm_chain(rcx-40, rbase, wireless=True)
    T(d, rcx-40, rbase+55, "케이블 제거 / 자유로운 다축 회전 구현", f(17, b=False), GRAY)

    # 60GHz module zoom-in callout on right arm
    mod_x, mod_y = rcx-40+40, rbase-330
    rrect(d, [mod_x+70, mod_y-70, mod_x+330, mod_y+70], 14, fill=PANEL2, outline=GREEN, width=3)
    d.line([(mod_x+20, mod_y), (mod_x+70, mod_y)], fill=GREEN, width=3)
    chip_x, chip_y = mod_x+150, mod_y
    d.rectangle([chip_x-40, chip_y-30, chip_x+40, chip_y+30], fill=(0x10,0x2a,0x22), outline=GREEN, width=3)
    for k in range(4):
        yy = chip_y-20+k*13
        d.line([(chip_x-40, yy), (chip_x-52, yy)], fill=GREEN, width=3)
        d.line([(chip_x+40, yy), (chip_x+52, yy)], fill=GREEN, width=3)
    wifi_arcs(d, chip_x+90, chip_y, GREEN, n=3, r0=10, gap=10, a0=-40, a1=40, width=4)
    T(d, mod_x+255, mod_y-48, "60GHz mmWave", f(18), WHITE)
    T(d, mod_x+255, mod_y+45, "무선 관절 통신 모듈", f(16, b=False), GRAY)

    footer_tag(d, "관절부 유선 배선 제거 → 60GHz 모듈로 데이터 무선 전송")
    im.save("4_Doosan_Robotics_60GHz모듈.png")
    print("saved 4_Doosan_Robotics_60GHz모듈.png", im.size)


if __name__ == "__main__":
    draw_istn()
    draw_energy()
    draw_bobcat()
    draw_robotics()
