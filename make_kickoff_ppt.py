# -*- coding: utf-8 -*-
"""
레이돔 일체형 위성통신 지상단말국 빔조향 송·수신 안테나 모듈 개발
Kick-off 발표자료 (주관기관 실무책임자용)
"""
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn

# ---------- 색상 팔레트 ----------
NAVY = RGBColor(0x11, 0x1A, 0x2B)
DARK_BG = RGBColor(0x15, 0x1B, 0x27)
PANEL = RGBColor(0x1E, 0x27, 0x39)
PANEL2 = RGBColor(0x25, 0x30, 0x45)
ORANGE = RGBColor(0xE8, 0x83, 0x3A)
BLUE = RGBColor(0x4F, 0x9D, 0xD6)
WHITE = RGBColor(0xF5, 0xF6, 0xF8)
GRAY = RGBColor(0xB4, 0xBC, 0xCA)
GREEN = RGBColor(0x63, 0xC1, 0x9C)

SLIDE_W = Inches(13.333)
SLIDE_H = Inches(7.5)
FONT = "맑은 고딕"

prs = Presentation()
prs.slide_width = SLIDE_W
prs.slide_height = SLIDE_H
blank = prs.slide_layouts[6]


def add_bg(slide, color=DARK_BG):
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, SLIDE_W, SLIDE_H)
    s.fill.solid(); s.fill.fore_color.rgb = color
    s.line.fill.background(); s.shadow.inherit = False
    slide.shapes._spTree.remove(s._element)
    slide.shapes._spTree.insert(2, s._element)
    return s


def bar(slide, top=True):
    y = 0 if top else SLIDE_H - Inches(0.10)
    b = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, y, SLIDE_W, Inches(0.10))
    b.fill.solid(); b.fill.fore_color.rgb = ORANGE
    b.line.fill.background(); b.shadow.inherit = False


def tb(slide, left, top, width, height, text, size=18, color=WHITE, bold=False,
       align=PP_ALIGN.LEFT, anchor=None, font=FONT, line_spacing=1.0):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame; tf.word_wrap = True
    if anchor is not None:
        tf.vertical_anchor = anchor
    lines = text.split("\n") if isinstance(text, str) else text
    for i, ln in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align; p.line_spacing = line_spacing
        r = p.add_run(); r.text = ln
        r.font.size = Pt(size); r.font.bold = bold
        r.font.color.rgb = color; r.font.name = font
    return box


def title(slide, t, kicker=None):
    if kicker:
        tb(slide, Inches(0.7), Inches(0.33), Inches(11.8), Inches(0.4),
           kicker, size=13, color=ORANGE, bold=True)
    tb(slide, Inches(0.7), Inches(0.66), Inches(12.0), Inches(0.9),
       t, size=29, color=WHITE, bold=True)
    ln = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.72), Inches(1.5),
                                Inches(1.1), Pt(3))
    ln.fill.solid(); ln.fill.fore_color.rgb = ORANGE
    ln.line.fill.background(); ln.shadow.inherit = False


def bullets(slide, left, top, width, height, items, size=17, gap=8,
            line_spacing=1.22):
    box = slide.shapes.add_textbox(left, top, width, height)
    tf = box.text_frame; tf.word_wrap = True
    for i, it in enumerate(items):
        text, lvl = (it if isinstance(it, tuple) else (it, 0))
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.level = lvl; p.line_spacing = line_spacing
        p.space_after = Pt(gap)
        mark = "▸ " if lvl == 0 else ("· " if lvl == 1 else "   – ")
        r = p.add_run(); r.text = mark + text
        r.font.size = Pt(size - lvl * 1)
        r.font.color.rgb = WHITE if lvl == 0 else GRAY
        r.font.bold = (lvl == 0)
        r.font.name = FONT
    return box


def panel(slide, left, top, width, height, fill=PANEL, line=None):
    s = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height)
    s.adjustments[0] = 0.045
    s.fill.solid(); s.fill.fore_color.rgb = fill
    if line is not None:
        s.line.color.rgb = line; s.line.width = Pt(1.25)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def panel_header(slide, left, top, width, text, color=ORANGE, size=15):
    tb(slide, left + Inches(0.22), top + Inches(0.12), width - Inches(0.4),
       Inches(0.45), text, size=size, color=color, bold=True)


def table(slide, left, top, width, height, data, col_widths=None,
          header_fill=PANEL2, size=11.5, header_size=12):
    rows, cols = len(data), len(data[0])
    gf = slide.shapes.add_table(rows, cols, left, top, width, height)
    tbl = gf.table
    # kill default style banding
    tblPr = tbl._tbl.find(qn('a:tblPr'))
    if tblPr is not None:
        tblPr.set('firstRow', '0'); tblPr.set('bandRow', '0')
    if col_widths:
        for i, w in enumerate(col_widths):
            tbl.columns[i].width = w
    for r in range(rows):
        tbl.rows[r].height = Inches(0.36) if r else Inches(0.42)
        for c in range(cols):
            cell = tbl.cell(r, c)
            cell.margin_left = Inches(0.08); cell.margin_right = Inches(0.06)
            cell.margin_top = Inches(0.03); cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            if r == 0:
                cell.fill.fore_color.rgb = header_fill
            else:
                cell.fill.fore_color.rgb = PANEL if r % 2 else DARK_BG
            para = cell.text_frame.paragraphs[0]
            para.alignment = PP_ALIGN.LEFT if c == 0 else PP_ALIGN.CENTER
            run = para.add_run(); run.text = str(data[r][c])
            run.font.name = FONT
            run.font.size = Pt(header_size if r == 0 else size)
            run.font.bold = (r == 0 or c == 0)
            run.font.color.rgb = ORANGE if r == 0 else (WHITE if c == 0 else GRAY)
    return tbl


def new_slide(kicker_page=None):
    s = prs.slides.add_slide(blank)
    add_bg(s); bar(s, top=False)
    return s


def footer(slide, page):
    tb(slide, Inches(0.7), SLIDE_H - Inches(0.5), Inches(9), Inches(0.35),
       "레이돔 일체형 위성통신 지상단말국 빔조향 송·수신 안테나 모듈 개발  |  Kick-off",
       size=9, color=GRAY)
    tb(slide, SLIDE_W - Inches(1.4), SLIDE_H - Inches(0.5), Inches(0.9), Inches(0.35),
       str(page), size=10, color=GRAY, align=PP_ALIGN.RIGHT)


# ============================================================
# 1. 표지
# ============================================================
s = new_slide()
add_bg(s, NAVY); bar(s, top=True); bar(s, top=False)
tb(s, Inches(1.0), Inches(0.95), Inches(11), Inches(0.5),
   "소재부품기술개발사업 (패키지형·슈퍼을)  /  통합형 세부과제", size=15, color=ORANGE, bold=True)
tb(s, Inches(1.0), Inches(2.25), Inches(11.4), Inches(2.2),
   "고출력·광대역 레이돔 일체형\n위성통신 지상단말국용 빔조향 송·수신 안테나 모듈 개발",
   size=32, color=WHITE, bold=True, line_spacing=1.15)
tb(s, Inches(1.0), Inches(4.5), Inches(11), Inches(0.5),
   "과제번호 RS-2026-25548760   |   연구개발기간 2026.07 ~ 2032.12 (6년 6개월)",
   size=15, color=GRAY)
tb(s, Inches(1.0), Inches(5.95), Inches(11), Inches(0.9),
   "착수 Kick-off Meeting\n주관연구개발기관 ㈜두산전자사업 수지  ·  실무책임자 박동희 수석",
   size=14, color=WHITE, line_spacing=1.3)
tb(s, Inches(1.0), Inches(6.95), Inches(6), Inches(0.4), "2026. 07", size=12, color=GRAY)

# ============================================================
# 2. 목차
# ============================================================
s = new_slide()
title(s, "발표 순서", kicker="CONTENTS")
left = [
    "1.  과제 개요",
    "2.  추진 배경 및 필요성",
    "3.  최종 목표 및 핵심 개발기술",
    "4.  정량적 성능 목표",
]
right = [
    "5.  연구개발 추진체계",
    "6.  연차별 과제 내용 (1~3단계)",
    "7.  기관별 과제수행 계획",
    "8.  1차년도 중점 추진사항 · 협의안건",
]
panel(s, Inches(0.9), Inches(2.0), Inches(5.7), Inches(4.4))
panel(s, Inches(6.95), Inches(2.0), Inches(5.5), Inches(4.4))
bullets(s, Inches(1.2), Inches(2.45), Inches(5.2), Inches(3.6),
        [(x, 0) for x in left], size=18, gap=16)
bullets(s, Inches(7.25), Inches(2.45), Inches(5.0), Inches(3.6),
        [(x, 0) for x in right], size=18, gap=16)
footer(s, 2)

# ============================================================
# 3. 과제 개요
# ============================================================
s = new_slide()
title(s, "과제 개요", kicker="OVERVIEW")
data = [
    ["구분", "내용"],
    ["사업 체계", "산업통상부 · 소재부품기술개발(패키지형/슈퍼을) · 전문기관 KIAT"],
    ["총괄과제", "저유전·저손실 신소재 하이브리드 적층구조 기반 레이돔 일체형\n위성통신 지상단말국 송수신 모듈 개발 (RS-2026-25548737)"],
    ["세부과제(본 발표)", "고출력·광대역 레이돔 일체형 위성통신 지상단말국용\n빔조향 송·수신 안테나 모듈 개발 (RS-2026-25548760)"],
    ["연구개발기간", "2026.07.01 ~ 2032.12.31 (6년 6개월) · 3단계 / 7개 연차"],
    ["연구개발비", "총 약 144.4억원 (정부지원 102억원, 기관부담 약 42억원)"],
    ["과제 유형 / TRL", "혁신제품형 · 대형통합형 / 착수 TRL 3 → 종료 TRL 7"],
    ["수행기관", "주관 ㈜두산전자사업 수지 + 공동 5개 기관 + 수요기업 ㈜알에프닛시"],
]
table(s, Inches(0.9), Inches(1.95), Inches(11.55), Inches(4.7), data,
      col_widths=[Inches(2.5), Inches(9.05)], size=12.5, header_size=13)
tb(s, Inches(0.9), Inches(6.75), Inches(11.5), Inches(0.4),
   "핵심어 : Unit-Module 안테나 · LEO 위성 · 레이돔 · 메타표면 · 전자식 빔조향(ESA)",
   size=11.5, color=GRAY)
footer(s, 3)

# ============================================================
# 4. 배경 및 필요성
# ============================================================
s = new_slide()
title(s, "추진 배경 및 필요성", kicker="WHY")
panel(s, Inches(0.9), Inches(1.95), Inches(5.75), Inches(4.7))
panel_header(s, Inches(0.9), Inches(1.95), Inches(5.75), "시장 · 정책 환경")
bullets(s, Inches(1.15), Inches(2.55), Inches(5.3), Inches(4.0), [
    "6G 시대 지상망–위성망 통합 3차원 네트워크(NTN) 필수화",
    "LEO 위성통신 단말 시장 : '23년 64억$ → '32년 400억$ (CAGR 20%)",
    "위성 안테나 시장 CAGR 약 11%, 부가가치 중심이 지상 단말로 이동",
    "Starlink·Kuiper 등 대규모 위성군 구축으로 단말 수요 급증",
    "통신 주권·국방 전술통신과 직결되는 국가 전략기술",
], size=14, gap=9)
panel(s, Inches(6.85), Inches(1.95), Inches(5.6), Inches(4.7))
panel_header(s, Inches(6.85), Inches(1.95), Inches(5.6), "기술적 문제 및 국산화 필요성")
bullets(s, Inches(7.1), Inches(2.55), Inches(5.1), Inches(4.0), [
    "기존 단말 : 안테나·RF·레이돔 분리구조 → 경로손실·임피던스 불연속",
    "배열 확장 시 위상오차 누적, 발열·전력분배 한계",
    "핵심기술(BFIC·빔포밍·패키징) 해외 의존, 공급망 리스크",
    "글로벌 ESA 시장 80%+ 해외기업(Kymeta·Thales 등) 점유",
    "→ 레이돔–메타표면–안테나–RF 통합 Full ESA 자립화 시급",
], size=14, gap=9)
footer(s, 4)

# ============================================================
# 5. 최종 목표
# ============================================================
s = new_slide()
title(s, "최종 목표 및 핵심 개발기술", kicker="GOAL")
tb(s, Inches(0.9), Inches(1.8), Inches(11.6), Inches(0.7),
   "고출력·광대역 특성을 갖는 메타-레이돔 통합 송·수신 모듈 개발 (세계 최고 수준)",
   size=16, color=ORANGE, bold=True)
cards = [
    ("① 안테나–RF 통합 송수신 모듈", [
        "Tx·Rx 통합 아키텍처 / 시스템 통합",
        "열해석·SI/PI 기반 성능 최적화",
        "256ch↑ 송신 / 384ch↑ 수신급",
    ]),
    ("② 저유전·저손실 확장형 배열구조", [
        "8×8 sub-array → Unit Module → N×Module",
        "고이득·광대역 커버리지 배열안테나",
        "위상/진폭 오차 보정·실시간 캘리브레이션",
    ]),
    ("③ 빔조향 레이돔–메타표면 구조", [
        "전파 투과특성 최적화 메타표면",
        "레이돔 소재·열·환경 구조해석",
        "레이돔 일체형 방사패턴 왜곡 최소화",
    ]),
]
x = Inches(0.9)
for h, items in cards:
    panel(s, x, Inches(2.6), Inches(3.75), Inches(4.0))
    panel_header(s, x, Inches(2.6), Inches(3.75), h, color=BLUE, size=13)
    bullets(s, x + Inches(0.18), Inches(3.2), Inches(3.45), Inches(3.2),
            [(i, 1) for i in items], size=12.5, gap=8)
    x += Inches(3.95)
footer(s, 5)

# ============================================================
# 6. 성능 목표
# ============================================================
s = new_slide()
title(s, "정량적 성능 목표", kicker="TARGET SPEC")
data = [
    ["평가 항목", "단위", "국내수준", "1단계", "2단계", "3단계(최종)", "세계최고"],
    ["동작주파수 Rx", "GHz", "17.7~21.2", "18.5~20.5", "18~21", "17.7~21.2", "동등"],
    ["동작주파수 Tx", "GHz", "27.5~31", "28~30", "27.5~30", "27.5~31", "동등"],
    ["배열안테나 이득", "dBi", "-", "≥ 9", "≥ 24", "≥ 27", "27 (美)"],
    ["빔조향 범위", "deg", "-", "≥ 40", "≥ 60", "≥ 65", "65 (美)"],
    ["EIRP", "dBW", "-", "≥ 18", "≥ 30", "≥ 30", "30 (美)"],
    ["배열 규모 (Tx)", "소자", "-", "≥ 64", "≥ 512", "≥ 1,024", "단계 확장"],
    ["RF 레이돔 투과손실", "dB", "1.5", "≤ 1.0", "≤ 0.7", "≤ 0.5", "0.2 (美)"],
]
table(s, Inches(0.85), Inches(1.95), Inches(11.65), Inches(4.5), data,
      col_widths=[Inches(2.7), Inches(1.0), Inches(1.7), Inches(1.55),
                  Inches(1.5), Inches(1.75), Inches(1.4)],
      size=11.5, header_size=11.5)
tb(s, Inches(0.85), Inches(6.65), Inches(11.6), Inches(0.5),
   "평가방법 : 전 항목 공인 시험성적서 기준  ·  기준설정 근거 : Anokiwave(Qorvo)·SpaceX 등 상용 단말 벤치마킹",
   size=10.5, color=GRAY)
footer(s, 6)

# ============================================================
# 7. 추진체계
# ============================================================
s = new_slide()
title(s, "연구개발 추진체계", kicker="STRUCTURE")
# 단계 구성
stg = [
    ("1단계", "2026~2027 (1~2차년)", "Unit cell 설계 · 측정환경 구축\n8×8 sub-array 확장 · 레이돔/메타표면 기본설계"),
    ("2단계", "2028~2030 (3~5차년)", "Unit Module → N×Module 스케일업\n정밀 보정 · 자동측정 · 양산공정 설립"),
    ("3단계", "2031~2032 (6~7차년)", "실환경 성능검증 · 환경/신뢰성 평가\n지능형 자율운용 · 사업화 Scalable 모듈"),
]
x = Inches(0.9)
for h, per, body in stg:
    panel(s, x, Inches(1.9), Inches(3.75), Inches(2.15), fill=PANEL)
    tb(s, x + Inches(0.2), Inches(2.02), Inches(3.4), Inches(0.4), h, size=15,
       color=ORANGE, bold=True)
    tb(s, x + Inches(0.2), Inches(2.42), Inches(3.4), Inches(0.35), per, size=10.5,
       color=GRAY)
    tb(s, x + Inches(0.2), Inches(2.8), Inches(3.4), Inches(1.1), body, size=10.5,
       color=WHITE, line_spacing=1.2)
    x += Inches(3.95)
# 컨소시엄
panel(s, Inches(0.9), Inches(4.25), Inches(11.55), Inches(2.4), fill=PANEL2)
panel_header(s, Inches(0.9), Inches(4.25), Inches(11.55),
             "컨소시엄 : 주관 ㈜두산전자사업 수지 (총괄) + 공동 5 + 수요기업", color=ORANGE)
bullets(s, Inches(1.15), Inches(4.85), Inches(11.0), Inches(1.7), [
    ("KETI 한국전자기술연구원 : 빔조향 고이득 배열안테나 · 안테나 Unit Module · 캘리브레이션", 1),
    ("KTL 한국산업기술시험원 : 표준·규격 분석 · NF–FF 변환 정밀측정 · 측정 불확도", 1),
    ("UNIST · 국립금오공대 산학협력단 : 메타표면 유닛셀/수퍼셀 · 방열 레이돔 EM 모델링", 1),
    ("㈜알에프텍(공동·수요) : 레이돔 소재 DB·구조설계·성형/공정·양산성   |   ㈜알에프닛시 : 수요기업", 1),
], size=12, gap=6)
footer(s, 7)

# ============================================================
# 8. 연차별 - 1단계
# ============================================================
s = new_slide()
title(s, "연차별 과제 내용 ①  1단계 (2026~2027)", kicker="ANNUAL PLAN")
panel(s, Inches(0.9), Inches(1.95), Inches(5.75), Inches(4.75))
panel_header(s, Inches(0.9), Inches(1.95), Inches(5.75), "1차년도 (2026, 6개월)")
bullets(s, Inches(1.15), Inches(2.5), Inches(5.35), Inches(4.1), [
    "송수신 모듈 구조 설계 및 기본 성능기준 수립",
    "모듈 아키텍처/버짓 설계, 단일 채널 기초 검증",
    "단일 안테나 성능 확보 + 2×2 Unit cell 구조 설계",
    "2×2 Unit cell 기반 메타표면(음의 굴절률) 연구",
    "지상용 위상배열 표준·규격(ETSI/3GPP NTN) 동향 분석",
    "방열 레이돔 소재 선행조사 · 기초 열해석 · 소재특성 DB",
], size=13, gap=7)
panel(s, Inches(6.85), Inches(1.95), Inches(5.6), Inches(4.75))
panel_header(s, Inches(6.85), Inches(1.95), Inches(5.6), "2차년도 (2027)")
bullets(s, Inches(7.1), Inches(2.5), Inches(5.1), Inches(4.1), [
    "패키징 기술 고도화 + 8×8 sub-array 개발·성능측정",
    "Shared-aperture 안테나 구조 연구",
    "메타표면 유닛셀 굴절률·결합 제어, 광대역 특성",
    "위상배열 시제품 정밀 측정절차(OTA) 개발",
    "NF–FF 변환 시스템용 도파관형 프로브 검증방법 연구",
    "레이돔 소재 EM 모델링 · 구조(단층/다층/샌드위치) 설계",
], size=13, gap=7)
tb(s, Inches(0.9), Inches(6.8), Inches(11.5), Inches(0.4),
   "1단계 목표 : 기초 단위구조 설계·측정환경 구축 · 8×8 sub-array 확장 · 시제품 정밀측정 절차 확립",
   size=11, color=ORANGE)
footer(s, 8)

# ============================================================
# 9. 연차별 - 2단계
# ============================================================
s = new_slide()
title(s, "연차별 과제 내용 ②  2단계 (2028~2030)", kicker="ANNUAL PLAN")
cols = [
    ("3차년도 (2028)", [
        "8×8 sub-array 기반 Unit Module 확장 설계",
        "Unit module 기반 빔조향 메타표면 연구",
        "평면 NF–FF 변환 정밀 측정시스템 구축",
        "다층 라미네이트 레이돔 기본형상·EM 분석",
    ]),
    ("4차년도 (2029)", [
        "N×Unit Module 확장 및 안테나 구조 안정화",
        "온라인 자동보정(Self-Calibration) 루프 구현",
        "NF–FF 변환 자동 측정 프로그램·통합 GUI 개발",
        "다층 레이돔 등가화 유효매질 EM 모델링",
    ]),
    ("5차년도 (2030)", [
        "N×Unit Module 안테나·메타표면 제작·성능 최적화",
        "통합 캘리브레이션 기법·보정모델 고도화",
        "측정 불확도 예산(Budget) 개발",
        "평판형 레이돔 형상설계 · 양산성 검토·공정 설립",
    ]),
]
x = Inches(0.9)
for h, items in cols:
    panel(s, x, Inches(1.95), Inches(3.75), Inches(4.6))
    panel_header(s, x, Inches(1.95), Inches(3.75), h, color=BLUE, size=13)
    bullets(s, x + Inches(0.18), Inches(2.55), Inches(3.45), Inches(3.9),
            [(i, 1) for i in items], size=11.5, gap=9)
    x += Inches(3.95)
tb(s, Inches(0.9), Inches(6.7), Inches(11.5), Inches(0.4),
   "2단계 목표 : Unit Module 스케일업·정밀보정 · 자동측정/빔조향 최적화 · 상용화 양산공정 설립",
   size=11, color=ORANGE)
footer(s, 9)

# ============================================================
# 10. 연차별 - 3단계
# ============================================================
s = new_slide()
title(s, "연차별 과제 내용 ③  3단계 (2031~2032)", kicker="ANNUAL PLAN")
panel(s, Inches(0.9), Inches(1.95), Inches(5.75), Inches(4.75))
panel_header(s, Inches(0.9), Inches(1.95), Inches(5.75), "6차년도 (2031)")
bullets(s, Inches(1.15), Inches(2.5), Inches(5.35), Inches(4.1), [
    "실환경 기반 N×Unit Module·메타표면 성능검증·최적화",
    "안테나–RF 통합 모듈 OTA 측정검증 (EIRP·G/T)",
    "환경변화 대응 실시간 캘리브레이션 기법 고도화",
    "Adaptive 빔포밍 기반 실시간 빔조향 제어",
    "평판형 레이돔 BSE/TL 성능 개선",
    "3GPP Rel. 기반 개정표준 분석 · Scalable 배치 연구",
], size=13, gap=7)
panel(s, Inches(6.85), Inches(1.95), Inches(5.6), Inches(4.75))
panel_header(s, Inches(6.85), Inches(1.95), Inches(5.6), "7차년도 (2032)")
bullets(s, Inches(7.1), Inches(2.5), Inches(5.1), Inches(4.1), [
    "레이돔–메타표면 통합형 N×Module 안테나 최적화",
    "통합 위성통신 모듈 성능·신뢰성 평가 (환경시험)",
    "지능형 자율운용 시스템 완성 · 통합 운용 GUI",
    "개발품 Specification · QC 매뉴얼 확립",
    "표준 스펙·라이브러리 기반 사업화 Scalable 모듈",
    "시제품 활용 Scalable 구조 모듈 표준 라이브러리 구축",
], size=13, gap=7)
tb(s, Inches(0.9), Inches(6.8), Inches(11.5), Inches(0.4),
   "3단계 목표 : 실환경 통합 성능검증 · 상용화 대비 환경/신뢰성 평가체계 · 지능형 자율운용 완성",
   size=11, color=ORANGE)
footer(s, 10)

# ============================================================
# 11. 기관별 - 주관
# ============================================================
s = new_slide()
title(s, "기관별 과제수행 계획 ①  주관기관", kicker="RESPONSIBILITY")
panel(s, Inches(0.9), Inches(1.9), Inches(11.55), Inches(1.15), fill=PANEL2)
tb(s, Inches(1.15), Inches(2.02), Inches(11.0), Inches(0.9),
   "㈜두산전자사업 수지  ·  연구책임자 이영주 상무 / 실무책임자 박동희 수석  ·  참여연구자 56명  ·  약 79.8억원",
   size=13, color=WHITE, bold=True, line_spacing=1.2)
bullets(s, Inches(1.05), Inches(3.3), Inches(11.3), Inches(3.4), [
    "과제 총괄 — 컨소시엄 조정, 일정·성능·예산 관리, 시스템 통합",
    "위성통신 지상단말용 송·수신 모듈 설계·제작·검증 (회로·패키징·적층구조)",
    ("저유전·저손실 하이브리드 PCB, 미세공정, BFIC 기반 다채널 빔포밍, SI/PI·열 통합해석", 1),
    "빔조향 배열안테나 구조 설계 및 성능 최적화, 빔조향 제어·캘리브레이션 기술",
    "광대역 CP anisotropic 메타표면 설계 및 방열 레이돔 열해석·EM M&S",
    "레이돔–메타표면 통합형 고이득 안테나 구조 설계·검증, 메타레이돔 Sparsity·BSE/TL 개선",
    "통합 위성통신 모듈 신뢰성 확보 시험절차 확립 · 사업화(SET 제조사 RFQ)",
], size=13, gap=7)
footer(s, 11)

# ============================================================
# 12. 기관별 - KETI / KTL
# ============================================================
s = new_slide()
title(s, "기관별 과제수행 계획 ②  공동기관 (1)", kicker="RESPONSIBILITY")
panel(s, Inches(0.9), Inches(1.95), Inches(5.75), Inches(4.75))
panel_header(s, Inches(0.9), Inches(1.95), Inches(5.75),
             "KETI 한국전자기술연구원")
tb(s, Inches(1.15), Inches(2.5), Inches(5.3), Inches(0.35),
   "책임 유종인 수석  ·  약 49.1억원", size=11.5, color=GRAY)
bullets(s, Inches(1.15), Inches(2.95), Inches(5.35), Inches(3.6), [
    "단일 안테나 → 2×2 Unit cell → 8×8 sub-array → Unit Module → N×Module 안테나 확장 설계",
    "고이득 메타표면 안테나 모듈 통합구조 및 급전계수 맵핑 빔조향",
    "계층형 빔포밍 가중치 제어 · 그룹/온라인 캘리브레이션",
    "실환경 능동 캘리브레이션·실시간 빔조향, 최종 위성통신 지상국용 안테나 모듈 개발",
], size=12, gap=7)
panel(s, Inches(6.85), Inches(1.95), Inches(5.6), Inches(4.75))
panel_header(s, Inches(6.85), Inches(1.95), Inches(5.6),
             "KTL 한국산업기술시험원")
tb(s, Inches(7.1), Inches(2.5), Inches(5.1), Inches(0.35),
   "책임 이재석 책임  ·  약 6.5억원", size=11.5, color=GRAY)
bullets(s, Inches(7.1), Inches(2.95), Inches(5.1), Inches(3.6), [
    "지상용 위상배열 표준·규격 분석(ETSI·3GPP TS38.101-5/38.108 등) → 성능 파라미터 도출",
    "위상배열 안테나 시제품 정밀 측정절차·OTA 시험절차 개발",
    "평면 NF–FF 변환 알고리즘(FFT)·측정시스템·자동화 프로그램·역투영 알고리즘",
    "도파관형 프로브 교정법 · 측정 불확도 예산 · 통합모듈 신뢰성 평가절차",
    "산업부 산하 공공 종합시험인증기관 측정 인프라 활용",
], size=12, gap=7)
footer(s, 12)

# ============================================================
# 13. 기관별 - UNIST / 알에프텍 / 금오공대
# ============================================================
s = new_slide()
title(s, "기관별 과제수행 계획 ③  공동기관 (2)", kicker="RESPONSIBILITY")
cards = [
    ("UNIST 울산과학기술원", "책임 변강일  ·  약 9.1억원  ·  2차년도 참여", [
        "다층·비등방성 메타표면 유닛셀/수퍼셀 설계",
        "광대역 CP·편파변환, 빔조향 메타표면",
        "Grating lobe 억제 · 메타레이돔 Sparsity 개선",
        "메타레이돔 통합 Sparse 배열안테나 제작·측정",
    ]),
    ("㈜알에프텍 (공동·수요)", "책임 김성열 상무  ·  약 8.7억원", [
        "레이돔 소재 전기적·기계적 특성 DB 구축",
        "안테나–레이돔 연계 구조설계·메타표면 통합",
        "경량·광대역·고강도 레이돔, 고정밀 성형/코팅",
        "양산성 검토·공정 설립, 시제품·환경시험·사업화",
    ]),
    ("국립금오공대 산학협력단", "책임 임태흥  ·  약 4.9억원  ·  2차년도 참여", [
        "방열 특성 레이돔 소재 EM 모델링·성능 분석",
        "다층 라미네이트 레이돔 형상 설계·EM 분석",
        "등가화 기반 유효매질 EM 모델링·최적화",
        "평판형 레이돔 형상설계·열영향 분석·성능검증",
    ]),
]
x = Inches(0.9)
for h, sub, items in cards:
    panel(s, x, Inches(1.95), Inches(3.75), Inches(4.7))
    panel_header(s, x, Inches(1.95), Inches(3.75), h, color=BLUE, size=12.5)
    tb(s, x + Inches(0.2), Inches(2.5), Inches(3.4), Inches(0.5), sub, size=9.5,
       color=GRAY, line_spacing=1.15)
    bullets(s, x + Inches(0.18), Inches(3.05), Inches(3.45), Inches(3.4),
            [(i, 1) for i in items], size=11, gap=8)
    x += Inches(3.95)
footer(s, 13)

# ============================================================
# 14. 역할·예산 요약 + 일정
# ============================================================
s = new_slide()
title(s, "기관별 역할·예산 요약", kicker="SUMMARY")
data = [
    ["기관", "구분", "핵심 역할", "연구비(억원)"],
    ["㈜두산전자사업 수지", "주관", "총괄 · 송수신 모듈 · 배열안테나 · 시스템 통합", "약 79.8"],
    ["한국전자기술연구원", "공동", "배열안테나 Unit Module 확장 · 캘리브레이션", "약 49.1"],
    ["한국산업기술시험원", "공동", "표준 분석 · NF–FF 정밀측정 · 불확도", "약 6.5"],
    ["울산과학기술원", "공동", "메타표면 유닛셀/수퍼셀 · 빔조향", "약 9.1"],
    ["㈜알에프텍", "공동·수요", "레이돔 소재·구조·성형/공정 · 양산성", "약 8.7"],
    ["국립금오공대 산학협력단", "공동", "방열 레이돔 EM 모델링 · 평판형 레이돔", "약 4.9"],
    ["㈜알에프닛시", "수요", "수요 연계 · 사업화 요구사항", "-"],
]
table(s, Inches(0.85), Inches(1.9), Inches(11.65), Inches(4.0), data,
      col_widths=[Inches(3.0), Inches(1.5), Inches(5.35), Inches(1.8)],
      size=11, header_size=11.5)
tb(s, Inches(0.85), Inches(6.05), Inches(11.6), Inches(1.0),
   "연차별 정부지원금(백만원) : 1년 810 · 2년 1,230 · 3년 1,700 · 4년 1,700 · 5년 1,700 · 6년 1,530 · 7년 1,530\n"
   "일자리 창출 : 주관 청년 신규채용 7명(2026~2032) + 알에프텍 1명",
   size=10.5, color=GRAY, line_spacing=1.3)
footer(s, 14)

# ============================================================
# 15. 1차년도 중점 + 협의안건
# ============================================================
s = new_slide()
title(s, "1차년도 중점 추진사항 및 협의 안건", kicker="KICK-OFF ACTIONS")
panel(s, Inches(0.9), Inches(1.95), Inches(5.75), Inches(4.75))
panel_header(s, Inches(0.9), Inches(1.95), Inches(5.75),
             "1차년도(2026.07~12) 중점 추진", color=ORANGE)
bullets(s, Inches(1.15), Inches(2.55), Inches(5.35), Inches(4.0), [
    "모듈 아키텍처·링크버짓 확정 및 인터페이스 규격 합의",
    "단일 채널·단일 안테나·2×2 Unit cell 설계 착수",
    "메타표면 유닛셀 / 방열 레이돔 소재 DB 구축",
    "표준·규격(3GPP NTN) 분석 착수, 성능목표 상세화",
    "측정·보정 환경(OTA) 구축 준비",
], size=13, gap=9)
panel(s, Inches(6.85), Inches(1.95), Inches(5.6), Inches(4.75))
panel_header(s, Inches(6.85), Inches(1.95), Inches(5.6),
             "Kick-off 협의 안건", color=GREEN)
bullets(s, Inches(7.1), Inches(2.55), Inches(5.1), Inches(4.0), [
    "기관 간 인터페이스·데이터 규격 및 형상관리 체계",
    "협약·연구비 집행 및 보안등급(일반) 준수사항 공유",
    "정기 기술교류회(월 1회)·단계평가 대응 계획",
    "시제품 제작·측정 리소스 분담 및 일정 동기화",
    "IP·표준화(대응 표준: 3GPP NTN) 공동 전략",
], size=13, gap=9)
tb(s, Inches(0.9), Inches(6.85), Inches(11.5), Inches(0.4),
   "기대효과 : 위성통신 단말 핵심모듈 국산화 · 수입대체 · 글로벌 공급망 진입 · 6G NTN 기술 주도권 확보",
   size=11, color=ORANGE)
footer(s, 15)

out = "레이돔_위성통신_모듈_Kickoff.pptx"
prs.save(out)
print("Saved:", out, "| slides:", len(prs.slides._sldIdLst))
