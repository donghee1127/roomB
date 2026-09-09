# -*- coding: utf-8 -*-
"""연구개발 기관 컨소시엄 다이어그램 (허브-스포크, 중앙 = 두산전자)"""
from PIL import Image, ImageDraw, ImageFont

W, H = 2400, 1270
NAVY = (17, 26, 43)
INK = (38, 44, 58)
GRAY = (120, 128, 140)
ORANGE = (226, 138, 46)
BLUE = (58, 108, 178)
TEAL = (26, 150, 150)
GREEN = (44, 150, 92)
PURPLE = (124, 92, 172)
CLAY = (192, 92, 120)
SLATE = (98, 112, 132)
LINE = (170, 180, 194)

cv = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(cv)
FONT = "C:/Windows/Fonts/malgun.ttf"
FONTB = "C:/Windows/Fonts/malgunbd.ttf"
def f(sz, b=True): return ImageFont.truetype(FONTB if b else FONT, sz)
def T(x, y, s, fnt, fill, anchor="mm"): d.text((x, y), s, font=fnt, fill=fill, anchor=anchor)
def rrect(box, r, fill=None, outline=None, width=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)

# ---------------- 제목 ----------------
d.rectangle([0, 0, W, 90], fill=NAVY)
T(40, 45, "연구개발 기관 컨소시엄 및 역할 분담", f(33), "white", "lm")
T(W - 40, 45, "주관 1 · 공동 5 · 수요 1", f(19), ORANGE, "rm")

# ---------------- 중앙 : 두산전자 ----------------
cx, cy = W // 2, 690
cw, ch = 690, 372
rrect([cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2], 20,
      fill=(244, 246, 250), outline=ORANGE, width=6)
d.rounded_rectangle([cx - cw // 2, cy - ch // 2, cx + cw // 2, cy - ch // 2 + 96],
                    20, fill=NAVY)
d.rectangle([cx - cw // 2, cy - ch // 2 + 62, cx + cw // 2, cy - ch // 2 + 96], fill=NAVY)
T(cx, cy - ch // 2 + 36, "㈜두산전자사업 수지", f(31), "white")
T(cx, cy - ch // 2 + 74, "주관연구개발기관 · 과제 총괄", f(19), ORANGE)
role_c = [
    "과제 총괄 및 컨소시엄 운영·조정",
    "위성통신 지상단말용 송·수신 모듈 설계·제작·검증",
    "확장형 빔조향 배열안테나 구조 설계·최적화",
    "레이돔–메타표면 통합 및 시스템 통합·성능 검증",
]
ty = cy - ch // 2 + 138
for t in role_c:
    d.rectangle([cx - cw // 2 + 34, ty - 6, cx - cw // 2 + 46, ty + 6], fill=ORANGE)
    T(cx - cw // 2 + 60, ty, t, f(18, b=False), INK, "lm")
    ty += 45

# ---------------- 위성 기관 ----------------
SW = 608
def sat(px, py, name, sub, color, roles):
    sh = 96 + len(roles) * 40 + 18
    x0, y0 = px - SW // 2, py - sh // 2
    x1, y1 = px + SW // 2, py + sh // 2
    rrect([x0, y0, x1, y1], 16, fill="white", outline=color, width=4)
    d.rounded_rectangle([x0, y0, x1, y0 + 64], 16, fill=color)
    d.rectangle([x0, y0 + 38, x1, y0 + 64], fill=color)
    T((x0 + x1) // 2, y0 + 21, name, f(21), "white")
    T((x0 + x1) // 2, y0 + 49, sub, f(14), (238, 238, 238))
    ry = y0 + 92
    for t in roles:
        T(x0 + 26, ry, "·", f(16), color, "lm")
        T(x0 + 42, ry, t, f(15.5, b=False), INK, "lm")
        ry += 40
    return (x0, y0, x1, y1)

LX, RX = 448, W - 448
ROWY = [288, 690, 1010]

B = {}
B["KETI"] = sat(LX, ROWY[0], "한국전자기술연구원 (KETI)", "공동연구개발기관", BLUE, [
    "빔조향 고이득 배열안테나 · Unit Module 확장 설계",
    "메타표면 안테나 통합구조 · 계층형 빔포밍·캘리브레이션",
    "최종 위성통신 지상국용 안테나 모듈 개발",
])
B["UNIST"] = sat(LX, ROWY[1], "울산과학기술원 (UNIST)", "공동연구개발기관", PURPLE, [
    "다층·비등방성 메타표면 유닛셀 / 수퍼셀 설계",
    "광대역 원형편파·편파변환 · 빔조향 메타표면",
    "grating lobe 억제 · 메타레이돔 Sparsity 개선",
])
B["KTL"] = sat(LX, ROWY[2], "한국산업기술시험원 (KTL)", "공동연구개발기관", TEAL, [
    "위성단말 표준·규격 분석 (ETSI · 3GPP NTN)",
    "평면 NF–FF 변환 정밀측정 알고리즘·시스템·프로그램",
    "프로브 교정 · 측정 불확도 · 통합모듈 신뢰성 평가",
])
B["RFTECH"] = sat(RX, ROWY[0], "㈜알에프텍", "공동연구개발기관 · 수요", GREEN, [
    "레이돔 소재 전기·기계 특성 DB · 연계 구조 설계",
    "경량·광대역·고강도 레이돔 · 고정밀 성형·코팅·공정",
    "양산성 검토·공정 설립 · 시제품 제작·환경시험",
])
B["KUMOH"] = sat(RX, ROWY[1], "국립금오공과대 산학협력단", "공동연구개발기관", CLAY, [
    "방열 특성 레이돔 소재 EM 모델링·성능 분석",
    "다층 라미네이트 레이돔 형상 설계 · 등가화 매질 모델링",
    "평판형 레이돔 형상 설계 · 열 영향성 분석·검증",
])
B["RFNISSI"] = sat(RX, ROWY[2], "㈜알에프닛시", "수요기업", SLATE, [
    "수요 요구사항 제시 및 개발 방향 연계",
    "개발품 수요 검증 · 사업화 연계",
])

# ---------------- 연결선 ----------------
def edge(box, tx, ty):
    x0, y0, x1, y1 = box
    bx, by = (x0 + x1) / 2, (y0 + y1) / 2
    dx, dy = tx - bx, ty - by
    dx = dx or 1e-6
    ex = x1 if dx > 0 else x0
    ey = by + dy * (ex - bx) / dx
    if not (y0 <= ey <= y1):
        ey = y1 if dy > 0 else y0
        ex = bx + dx * (ey - by) / dy
    return ex, ey

cbox = (cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2)
lbls = {"KETI": "안테나 모듈", "UNIST": "메타표면", "KTL": "측정·인증",
        "RFTECH": "레이돔 제작", "KUMOH": "레이돔 해석", "RFNISSI": "수요·사업화"}
for k, b in B.items():
    bx, by = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
    p1 = edge(cbox, bx, by)
    p2 = edge(b, cx, cy)
    d.line([p1, p2], fill=LINE, width=4)
    d.ellipse([p1[0]-6, p1[1]-6, p1[0]+6, p1[1]+6], fill=ORANGE)
    d.ellipse([p2[0]-6, p2[1]-6, p2[0]+6, p2[1]+6], fill=LINE)
    mx, my = (p1[0]+p2[0])/2, (p1[1]+p2[1])/2
    tw = d.textlength(lbls[k], font=f(15))
    d.rectangle([mx-tw/2-9, my-15, mx+tw/2+9, my+15], fill="white", outline=LINE)
    T(mx, my, lbls[k], f(15), GRAY)

T(40, H - 32,
  "주관  ㈜두산전자사업 수지        공동  KETI · KTL · UNIST · ㈜알에프텍 · 국립금오공과대 산학협력단        수요  ㈜알에프텍 · ㈜알에프닛시",
  f(15, b=False), GRAY, "lm")

cv.save("기관_컨소시엄_다이어그램.png")
print("saved", cv.size)
