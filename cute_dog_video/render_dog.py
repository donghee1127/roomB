import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import imageio

random.seed(7)

W, H = 720, 1280
FPS = 15
DURATION = 60.0
N_FRAMES = int(FPS * DURATION)

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_PATH = os.path.join(OUT_DIR, "cute_dog_roll.mp4")

BODY_BASE = (250, 191, 130)
BODY_SHADOW = (200, 132, 74)
EAR_BASE = (232, 165, 100)
EAR_SHADOW = (182, 112, 58)
SNOUT_BASE = (255, 240, 220)
SNOUT_SHADOW = (236, 200, 165)
PAW_BASE = (250, 191, 130)
PAW_SHADOW = (200, 132, 74)
TAIL_BASE = (250, 191, 130)
TAIL_SHADOW = (200, 132, 74)
NOSE_BASE = (95, 65, 55)
NOSE_SHADOW = (40, 25, 22)
EYE_BASE = (55, 40, 38)
EYE_SHADOW = (15, 10, 10)
BLUSH = (255, 130, 130)
OUTLINE = (120, 70, 40, 70)

ACTOR = 480
CX = ACTOR // 2
GROUND_ROW = 430
FLOOR_Y = int(H * 0.60)
HOME_X = W // 2


# ---------------------------------------------------------------- sprites --

def sphere_sprite(w, h, base, shadow, highlight=(255, 255, 255),
                   light=(-0.55, -0.65, 0.62), spec=0.55, ao=0.30, outline=OUTLINE):
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    nx = (xx + 0.5) / w * 2 - 1
    ny = (yy + 0.5) / h * 2 - 1
    r2 = nx * nx + ny * ny
    mask = r2 <= 1.0
    nz = np.zeros_like(nx)
    nz[mask] = np.sqrt(np.clip(1 - r2[mask], 0, 1))

    lx, ly, lz = light
    ln = math.sqrt(lx * lx + ly * ly + lz * lz)
    lx, ly, lz = lx / ln, ly / ln, lz / ln
    diffuse = np.clip(nx * lx + ny * ly + nz * lz, 0, 1)
    edge = 1 - nz
    diffuse = np.clip(diffuse * (1 - ao * edge * 0.6), 0, 1)

    base_a = np.array(base, dtype=np.float32)
    shadow_a = np.array(shadow, dtype=np.float32)
    col = shadow_a[None, None, :] + (base_a - shadow_a)[None, None, :] * diffuse[..., None]

    spec_t = np.clip((diffuse - 0.74) / 0.26, 0, 1) ** 2 * spec
    hl = np.array(highlight, dtype=np.float32)
    col = col * (1 - spec_t[..., None]) + hl[None, None, :] * spec_t[..., None]

    alpha = np.clip((1 - r2) * 40, 0, 1) * np.where(mask, 1.0, 0.0)
    rgba = np.dstack([np.clip(col, 0, 255), alpha * 255]).astype(np.uint8)
    img = Image.fromarray(rgba, "RGBA")

    if outline:
        a = img.split()[3]
        dilated = a.filter(ImageFilter.MaxFilter(5))
        ring = Image.new("RGBA", img.size, outline)
        ring.putalpha(dilated)
        img = Image.alpha_composite(ring, img)
    return img


BODY_SPR = sphere_sprite(300, 280, BODY_BASE, BODY_SHADOW)
EAR_SPR = sphere_sprite(120, 150, EAR_BASE, EAR_SHADOW, spec=0.4)
SNOUT_SPR = sphere_sprite(130, 105, SNOUT_BASE, SNOUT_SHADOW, spec=0.3, ao=0.15)
PAW_SPR = sphere_sprite(76, 64, PAW_BASE, PAW_SHADOW, spec=0.4)
TAIL_SPR = sphere_sprite(64, 96, TAIL_BASE, TAIL_SHADOW, spec=0.4)
NOSE_SPR = sphere_sprite(30, 22, NOSE_BASE, NOSE_SHADOW, spec=0.5, ao=0.1, outline=None)
EYE_SPR = sphere_sprite(44, 44, EYE_BASE, EYE_SHADOW, spec=0.85, ao=0.1, outline=None)


def rot(img, deg):
    return img.rotate(deg, resample=Image.BICUBIC, expand=False)


def scaled(img, sx, sy):
    w, h = img.size
    return img.resize((max(1, int(w * sx)), max(1, int(h * sy))), Image.BICUBIC)


def paste_c(base, sprite, cx, cy):
    w, h = sprite.size
    base.alpha_composite(sprite, (int(cx - w / 2), int(cy - h / 2)))


# ---------------------------------------------------------------- face -----

def draw_eyes(actor, cx, cy, spread, state, tilt=0.0):
    d = ImageDraw.Draw(actor)
    for side in (-1, 1):
        ex, ey = cx + side * spread, cy
        if state == "blink" or state == "closed" or state == "sleepy_closed":
            w = 20
            d.arc([ex - w, ey - 6, ex + w, ey + 14], 190, 350, fill=(60, 40, 35, 255), width=4)
        elif state == "happy":
            w = 15
            d.arc([ex - w, ey - 2, ex + w, ey + 20], 190, 350, fill=(60, 40, 35, 255), width=5)
        elif state == "dizzy":
            for k in range(3):
                rr = 4 + k * 3
                ang0 = (k * 60) % 360
                d.arc([ex - rr, ey - rr, ex + rr, ey + rr], ang0, ang0 + 300,
                      fill=(60, 40, 35, 255), width=2)
        elif state == "sleepy":
            w = 16
            d.arc([ex - w, ey, ex + w, ey + 16], 200, 340, fill=(60, 40, 35, 255), width=5)
        else:
            e = rot(EYE_SPR, tilt)
            paste_c(actor, e, ex, ey)


def draw_mouth(actor, cx, cy, state):
    d = ImageDraw.Draw(actor)
    if state == "open":
        d.ellipse([cx - 9, cy - 6, cx + 9, cy + 10], fill=(120, 55, 60, 255))
    elif state == "happy":
        d.arc([cx - 22, cy - 14, cx + 22, cy + 16], 20, 160, fill=(90, 45, 40, 255), width=4)
    elif state == "flat":
        d.line([cx - 10, cy + 2, cx + 10, cy + 2], fill=(90, 45, 40, 255), width=3)
    else:
        d.arc([cx - 12, cy - 8, cx, cy + 8], 20, 160, fill=(90, 45, 40, 255), width=3)
        d.arc([cx, cy - 8, cx + 12, cy + 8], 20, 160, fill=(90, 45, 40, 255), width=3)


def draw_blush(actor, cx, cy, spread, amount):
    if amount <= 0:
        return
    layer = Image.new("RGBA", actor.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    a = int(140 * min(1.0, amount))
    for side in (-1, 1):
        bx = cx + side * spread
        d.ellipse([bx - 20, cy - 11, bx + 20, cy + 11], fill=(BLUSH[0], BLUSH[1], BLUSH[2], a))
    layer = layer.filter(ImageFilter.GaussianBlur(4))
    actor.alpha_composite(layer)


# ---------------------------------------------------------------- poses ----

def new_actor():
    return Image.new("RGBA", (ACTOR, ACTOR), (0, 0, 0, 0))


def draw_sit(p):
    actor = new_actor()
    sx, sy = p["squash"]
    bx, by = CX, 300

    tail = rot(TAIL_SPR, p["tail"])
    paste_c(actor, tail, bx + 148, by - 20)

    body = scaled(BODY_SPR, sx, sy)
    paste_c(actor, body, bx, by)

    ear_l = rot(EAR_SPR, -18 + p["ear_l"])
    ear_r = rot(EAR_SPR, 18 + p["ear_r"])
    paste_c(actor, ear_l, bx - 92, by - 152)
    paste_c(actor, ear_r, bx + 92, by - 152)

    paw_l = rot(PAW_SPR, p["paw_fl"])
    paw_r = rot(PAW_SPR, -p["paw_fr"])
    paste_c(actor, paw_l, bx - 96, by + 96)
    paste_c(actor, paw_r, bx + 96, by + 96)

    snout = SNOUT_SPR
    paste_c(actor, snout, bx, by - 38)
    draw_blush(actor, bx, by - 8, 62, p["blush"])
    draw_eyes(actor, bx, by - 62, 40, p["eye"])
    paste_c(actor, NOSE_SPR, bx, by - 44)
    draw_mouth(actor, bx, by - 18, p["mouth"])
    return actor


def draw_flat(p, variant):
    actor = new_actor()
    sx, sy = p["squash"]
    bx, by = CX, 300

    tail_x = bx + (150 if variant == "side" else 10)
    tail_y = by + (10 if variant == "side" else 130)
    tail_ang = p["tail"] * (1.6 if variant == "back" else 1.0)
    paste_c(actor, rot(TAIL_SPR, tail_ang), tail_x, tail_y)

    body = scaled(BODY_SPR, 1.18 * sx, 0.82 * sy)
    paste_c(actor, body, bx, by)

    kick = p["leg_kick"]
    if variant == "side":
        paste_c(actor, rot(PAW_SPR, -40 + kick * 22), bx - 118, by - 40)
        paste_c(actor, rot(PAW_SPR, 40 - kick * 18), bx + 118, by - 30)
        paste_c(actor, rot(PAW_SPR, -20 - kick * 14), bx - 92, by + 92)
        paste_c(actor, rot(PAW_SPR, 20 + kick * 14), bx + 92, by + 92)
        ear_l, ear_r = -80, 70
    else:
        paste_c(actor, rot(PAW_SPR, -70 + kick * 26), bx - 130, by - 70)
        paste_c(actor, rot(PAW_SPR, 70 - kick * 26), bx + 130, by - 70)
        paste_c(actor, rot(PAW_SPR, -110 - kick * 20), bx - 70, by - 120)
        paste_c(actor, rot(PAW_SPR, 110 + kick * 20), bx + 70, by - 120)
        ear_l, ear_r = -60, 60

    paste_c(actor, rot(EAR_SPR, ear_l + p["ear_l"]), bx - 96, by - 96)
    paste_c(actor, rot(EAR_SPR, ear_r + p["ear_r"]), bx + 96, by - 96)

    fx, fy = bx + (18 if variant == "side" else 0), by - 12
    paste_c(actor, SNOUT_SPR, fx, fy)
    draw_blush(actor, fx, fy + 30, 60, p["blush"])
    draw_eyes(actor, fx, fy - 24, 38, p["eye"])
    paste_c(actor, NOSE_SPR, fx, fy - 6)
    draw_mouth(actor, fx, fy + 20, p["mouth"])
    return actor


def draw_ball(p):
    actor = new_actor()
    sx, sy = p["squash"]
    bx, by = CX, CX

    paste_c(actor, rot(TAIL_SPR, 40), bx - 6, by + 118)

    body = scaled(BODY_SPR, 0.92 * sx, 0.90 * sy)
    paste_c(actor, body, bx, by)

    paste_c(actor, rot(scaled(EAR_SPR, 0.6, 0.55), -100), bx - 116, by - 84)
    paste_c(actor, rot(scaled(EAR_SPR, 0.6, 0.55), 100), bx + 116, by - 84)

    fx, fy = bx, by + 22
    paste_c(actor, SNOUT_SPR, fx, fy)
    draw_blush(actor, fx, fy + 26, 56, p["blush"])
    draw_eyes(actor, fx, fy - 22, 36, p["eye"])
    paste_c(actor, NOSE_SPR, fx, fy - 4)
    draw_mouth(actor, fx, fy + 16, p["mouth"])
    return actor


# ---------------------------------------------------------------- timeline -

def ease(u):
    u = min(1.0, max(0.0, u))
    return u * u * (3 - 2 * u)


def bounce_arc(u, hops):
    u = min(1.0, max(0.0, u))
    return abs(math.sin(u * hops * math.pi))


def base_pose():
    return dict(mode="sit", x=HOME_X, bounce=0.0, rotation=0.0,
                squash=(1.0, 1.0), ear_l=0.0, ear_r=0.0, tail=0.0,
                paw_fl=0.0, paw_fr=0.0, leg_kick=0.0, eye="open",
                mouth="neutral", blush=0.15, dark=0.0)


CP0 = HOME_X
CP1 = HOME_X + 150
CP2 = CP1 - 190
CP3 = CP2 + 170
CP4 = CP3 - 170
CP5 = HOME_X + 6


def get_pose(t):
    p = base_pose()
    breathe = math.sin(t * 1.3)
    idle_sq = (1 + 0.018 * breathe, 1 - 0.018 * breathe)
    p["tail"] = 14 * math.sin(t * 2.4)
    p["ear_l"] = 6 * math.sin(t * 1.7)
    p["ear_r"] = 6 * math.sin(t * 1.7 + 0.6)
    blink = (t % 2.8) < 0.12

    def roll_segment(t0, t1, x_from, x_to, hops, spin, direction):
        u = (t - t0) / (t1 - t0)
        eu = ease(u)
        p["mode"] = "ball"
        p["x"] = x_from + (x_to - x_from) * eu
        p["bounce"] = 46 * bounce_arc(u, hops)
        p["rotation"] = direction * spin * u
        sq = 1 + 0.10 * math.sin(u * hops * math.pi * 2)
        p["squash"] = (1 - 0.08 * sq, 1 + 0.08 * sq)
        p["eye"] = "dizzy" if hops >= 3 else "happy"
        p["mouth"] = "open"
        p["blush"] = 0.5
        return p

    if t < 3.2:
        u = t / 3.2
        p["mode"] = "sit"
        p["x"] = HOME_X
        p["squash"] = idle_sq
        p["eye"] = "blink" if blink else "open"
        p["mouth"] = "neutral"
        p["blush"] = 0.15
        p["paw_fl"] = 4 * math.sin(t * 1.1)
        p["paw_fr"] = 4 * math.sin(t * 1.1 + 0.7)

    elif t < 3.8:
        u = (t - 3.2) / 0.6
        p["mode"] = "sit"
        p["x"] = HOME_X
        sq = ease(u)
        p["squash"] = (1 + 0.16 * sq, 1 - 0.22 * sq)
        p["eye"] = "happy"
        p["mouth"] = "open"
        p["blush"] = 0.3

    elif t < 6.8:
        roll_segment(3.8, 6.8, HOME_X, HOME_X + 150, 3, 900, +1)

    elif t < 7.6:
        u = (t - 6.8) / 0.8
        p["mode"] = "sit"
        p["x"] = CP1
        sq = (1 - u) * math.sin(u * math.pi)
        p["squash"] = (1 + 0.22 * sq, 1 - 0.28 * sq)
        p["eye"] = "happy" if u < 0.6 else ("blink" if blink else "open")
        p["mouth"] = "happy"
        p["blush"] = 0.4 * (1 - u) + 0.15

    elif t < 10.6:
        u = (t - 7.6) / 3.0
        p["mode"] = "flat_side"
        p["x"] = CP1
        settle = ease(min(1.0, u * 4))
        p["squash"] = (0.9 + 0.1 * settle, 0.9 + 0.1 * settle)
        p["leg_kick"] = math.sin(t * 5.0)
        p["tail"] = 20 * math.sin(t * 4.0)
        p["eye"] = "happy" if (u * 3) % 1 < 0.7 else ("blink" if blink else "happy")
        p["mouth"] = "happy" if math.sin(t * 3) > 0 else "open"
        p["blush"] = 0.55

    elif t < 13.6:
        roll_segment(10.6, 13.6, CP1, CP2, 3, 900, -1)

    elif t < 17.6:
        u = (t - 13.6) / 4.0
        p["mode"] = "flat_back"
        p["x"] = CP2
        settle = ease(min(1.0, u * 4))
        p["squash"] = (0.92 + 0.08 * settle, 0.9 + 0.1 * settle)
        p["leg_kick"] = math.sin(t * 6.0)
        p["tail"] = 26 * math.sin(t * 5.0)
        p["eye"] = "happy"
        p["mouth"] = "open" if math.sin(t * 4) > 0.2 else "happy"
        p["blush"] = 0.7

    elif t < 20.6:
        u = (t - 17.6) / 3.0
        p["mode"] = "sit"
        p["x"] = CP2
        hop = bounce_arc((u * 3) % 1, 1)
        p["bounce"] = 30 * hop
        p["squash"] = (1 - 0.1 * hop, 1 + 0.12 * hop)
        p["paw_fl"] = 30 * math.sin(t * 6)
        p["paw_fr"] = 30 * math.sin(t * 6 + 1)
        p["eye"] = "happy"
        p["mouth"] = "happy"
        p["blush"] = 0.5

    elif t < 23.6:
        roll_segment(20.6, 23.6, CP2, CP3, 3, 1080, +1)

    elif t < 27.6:
        u = (t - 23.6) / 4.0
        p["mode"] = "sit"
        p["x"] = CP3 + 10 * math.sin(t * 3)
        p["squash"] = idle_sq
        p["eye"] = "dizzy"
        p["mouth"] = "open" if u < 0.7 else "neutral"
        p["blush"] = 0.35
        p["ear_l"] += 10 * math.sin(t * 3)
        p["ear_r"] += 10 * math.sin(t * 3 + 1)

    elif t < 30.6:
        roll_segment(27.6, 30.6, CP3, CP4, 2, 720, -1)

    elif t < 34.6:
        u = (t - 30.6) / 4.0
        p["mode"] = "flat_side"
        p["x"] = CP4
        p["squash"] = (1.0, 1.0)
        p["leg_kick"] = 0.5 * math.sin(t * 2.2)
        p["tail"] = 14 * math.sin(t * 2.0)
        p["eye"] = "blink" if blink else "happy"
        p["mouth"] = "happy"
        p["blush"] = 0.4

    elif t < 38.2:
        u = (t - 34.6) / 3.6
        p["mode"] = "sit"
        p["x"] = CP4
        stretch = math.sin(u * math.pi) if u < 0.6 else 0
        p["squash"] = (1 - 0.08 * stretch, 1 + 0.16 * stretch)
        p["paw_fl"] = -60 * stretch
        p["paw_fr"] = 60 * stretch
        p["eye"] = "sleepy" if u > 0.6 else ("blink" if blink else "open")
        p["mouth"] = "open" if 0.15 < u < 0.45 else "neutral"
        p["blush"] = 0.2

    elif t < 44.0:
        u = (t - 38.2) / 5.8
        p["mode"] = "sit"
        p["x"] = CP4
        p["squash"] = idle_sq
        p["eye"] = "sleepy"
        p["mouth"] = "flat"
        p["blush"] = 0.15
        p["ear_l"] = 4 * math.sin(t * 0.9)
        p["ear_r"] = 4 * math.sin(t * 0.9 + 0.5)
        p["tail"] = 6 * math.sin(t * 1.0)

    elif t < 47.0:
        u = (t - 44.0) / 3.0
        eu = ease(u)
        p["mode"] = "ball"
        p["x"] = CP4 + (CP5 - CP4) * eu
        p["bounce"] = 6 * (1 - eu) * abs(math.sin(u * math.pi * 2))
        p["rotation"] = 30 * eu
        p["squash"] = (1 - 0.05 * eu, 1 - 0.08 * eu)
        p["eye"] = "sleepy" if u < 0.7 else "sleepy_closed"
        p["mouth"] = "flat"
        p["blush"] = 0.15

    else:
        u = (t - 47.0) / 13.0
        breathe2 = math.sin(t * 0.9)
        p["mode"] = "ball"
        p["x"] = HOME_X + 6
        p["bounce"] = 0
        p["squash"] = (1 + 0.02 * breathe2, 1 - 0.03 * breathe2)
        p["eye"] = "sleepy_closed"
        p["mouth"] = "flat"
        p["blush"] = 0.12
        p["tail"] = 4 * math.sin(t * 0.8)
        p["dark"] = ease(min(1.0, (t - 58.0) / 2.0)) * 0.28 if t > 58.0 else 0.0

    return p


# ---------------------------------------------------------------- particles

class Particles:
    def __init__(self):
        self.items = []

    def spawn_sparkle(self, x, y):
        self.items.append(dict(kind="spark", x=x, y=y, vy=-70, vx=random.uniform(-20, 20),
                                life=0.5, age=0.0))

    def spawn_dust(self, x, y):
        self.items.append(dict(kind="dust", x=x, y=y, vy=-10, vx=random.uniform(-40, 40),
                                life=0.45, age=0.0))

    def spawn_z(self, x, y, size=1.0):
        self.items.append(dict(kind="z", x=x, y=y, vy=-24, vx=6, life=2.4, age=0.0, size=size))

    def update(self, dt):
        for it in self.items:
            it["age"] += dt
            it["x"] += it["vx"] * dt
            it["y"] += it["vy"] * dt
        self.items = [it for it in self.items if it["age"] < it["life"]]

    def draw(self, frame):
        layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(layer)
        for it in self.items:
            k = 1 - it["age"] / it["life"]
            a = int(255 * max(0, k))
            if it["kind"] == "spark":
                s = 4 + 4 * k
                x, y = it["x"], it["y"]
                d.line([x - s, y, x + s, y], fill=(255, 240, 190, a), width=2)
                d.line([x, y - s, x, y + s], fill=(255, 240, 190, a), width=2)
            elif it["kind"] == "dust":
                r = 5 + 10 * (1 - k)
                d.ellipse([it["x"] - r, it["y"] - r, it["x"] + r, it["y"] + r],
                          fill=(255, 255, 255, int(a * 0.5)))
            elif it["kind"] == "z":
                s = 14 * it.get("size", 1.0)
                x, y = it["x"], it["y"]
                d.line([x - s, y - s, x + s, y - s], fill=(120, 90, 160, a), width=3)
                d.line([x + s, y - s, x - s, y + s], fill=(120, 90, 160, a), width=3)
                d.line([x - s, y + s, x + s, y + s], fill=(120, 90, 160, a), width=3)
        frame.alpha_composite(layer)


# ---------------------------------------------------------------- backdrop -

def make_background():
    bg = Image.new("RGB", (W, H))
    top = np.array([214, 224, 250], dtype=np.float32)
    bot = np.array([255, 219, 232], dtype=np.float32)
    grad = np.linspace(0, 1, H).reshape(H, 1, 1)
    arr = top.reshape(1, 1, 3) * (1 - grad) + bot.reshape(1, 1, 3) * grad
    arr = np.repeat(arr, W, axis=1).astype(np.uint8)
    bg = Image.fromarray(arr, "RGB").convert("RGBA")

    bokeh = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bokeh)
    rng = random.Random(11)
    palette = [(255, 250, 210), (255, 255, 255), (200, 230, 255), (255, 210, 225)]
    for _ in range(16):
        x = rng.uniform(0, W)
        y = rng.uniform(0, H * 0.7)
        r = rng.uniform(14, 46)
        c = rng.choice(palette)
        bd.ellipse([x - r, y - r, x + r, y + r], fill=(c[0], c[1], c[2], rng.randint(18, 38)))
    bokeh = bokeh.filter(ImageFilter.GaussianBlur(18))
    bg.alpha_composite(bokeh)

    mat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    md = ImageDraw.Draw(mat)
    mx, my = HOME_X, FLOOR_Y + 60
    md.ellipse([mx - 260, my - 90, mx + 260, my + 90], fill=(255, 197, 197, 130))
    md.ellipse([mx - 190, my - 62, mx + 190, my + 62], fill=(255, 214, 205, 110))
    mat = mat.filter(ImageFilter.GaussianBlur(22))
    bg.alpha_composite(mat)

    vg = Image.new("L", (W, H), 0)
    vd = ImageDraw.Draw(vg)
    vd.ellipse([-140, -140, W + 140, H + 140], fill=255)
    vg = vg.filter(ImageFilter.GaussianBlur(160))
    vg = Image.eval(vg, lambda v: 255 - v)
    shade = Image.new("RGBA", (W, H), (40, 30, 60, 0))
    shade.putalpha(vg.point(lambda v: int(v * 0.35)))
    bg.alpha_composite(shade)

    return bg


def draw_ground_shadow(frame, x, bounce):
    k = max(0.25, 1 - bounce / 90)
    w = int(190 * k)
    h = int(46 * k)
    layer = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([x - w, FLOOR_Y - h // 2, x + w, FLOOR_Y + h // 2],
              fill=(90, 60, 90, int(90 * k)))
    layer = layer.filter(ImageFilter.GaussianBlur(10))
    frame.alpha_composite(layer)


# ---------------------------------------------------------------- render ---

def compose_actor(p):
    mode = p["mode"]
    if mode == "sit":
        return draw_sit(p)
    if mode == "flat_side":
        return draw_flat(p, "side")
    if mode == "flat_back":
        return draw_flat(p, "back")
    return draw_ball(p)


def main():
    bg = make_background()
    particles = Particles()
    writer = imageio.get_writer(OUT_PATH, fps=FPS, codec="libx264",
                                 quality=8, macro_block_size=16,
                                 ffmpeg_params=["-pix_fmt", "yuv420p"])

    last_spark_seg = -1

    for i in range(N_FRAMES):
        t = i / FPS
        p = get_pose(t)
        actor = compose_actor(p)
        if p["mode"] == "ball" and abs(p.get("rotation", 0)) > 0.01:
            actor = rot(actor, p["rotation"])

        frame = bg.copy()
        draw_ground_shadow(frame, p["x"], p["bounce"])

        gy = FLOOR_Y - p["bounce"]
        if p["mode"] == "ball":
            top_left = (int(p["x"] - ACTOR / 2), int(gy - (ACTOR - 60)))
        else:
            top_left = (int(p["x"] - ACTOR / 2), int(gy - GROUND_ROW))
        frame.alpha_composite(actor, top_left)

        seg_id = int(t)
        if p["mode"] == "ball" and abs(p.get("rotation", 0)) > 0.01 and int(t * 8) != last_spark_seg:
            last_spark_seg = int(t * 8)
            particles.spawn_sparkle(p["x"] + random.uniform(-40, 40),
                                     gy - 60 + random.uniform(-20, 20))
        if t > 48.0 and int(t) % 3 == 0 and (t - int(t)) < (1.0 / FPS):
            particles.spawn_z(p["x"] + 90, gy - 220, size=0.9 + 0.3 * random.random())

        particles.update(1.0 / FPS)
        particles.draw(frame)

        if p.get("dark", 0) > 0:
            dark = Image.new("RGBA", frame.size, (10, 8, 20, int(255 * p["dark"])))
            frame.alpha_composite(dark)

        rgb = frame.convert("RGB")
        writer.append_data(np.asarray(rgb))

        if i % 60 == 0:
            print(f"frame {i}/{N_FRAMES}  t={t:5.1f}s  mode={p['mode']}")

    writer.close()
    print("saved to", OUT_PATH)


if __name__ == "__main__":
    main()
