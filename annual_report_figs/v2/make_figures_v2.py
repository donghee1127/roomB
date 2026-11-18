# -*- coding: utf-8 -*-
"""
연차보고서 그림 v2 (보고서 본문 수치와 일치하는 버전)
 1. 링크 버짓        : fig1a_leo_geometry, fig1b_link_budget_flow
 2. RF 성능 지표     : fig2a_tx_p1db, fig2b_rx_nf_cascade
 3. EIRP / 분배 구조 : fig3a_eirp_budget, fig3b_power_distribution
 4. BFIC 다채널 구조 : fig4a_bfic_rf_chain, fig4b_tile_structure
 5. 단일 채널 연구   : fig5_test_setup
 6. 종합             : fig6_summary_flow
실행: python make_figures_v2.py
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, Arc, Rectangle, Polygon

OUT = os.path.dirname(os.path.abspath(__file__))
plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "font.size": 10, "axes.edgecolor": "#8a8986", "axes.labelcolor": "#0b0b0b",
    "xtick.color": "#52514e", "ytick.color": "#52514e",
    "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "savefig.dpi": 220, "savefig.bbox": "tight", "figure.facecolor": "white",
})

TX, RX, AQ, YE, VI = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8986"
TX_L, RX_L, GR_L, AQ_L, YE_L = "#e3eefb", "#fde9e0", "#f1f0ec", "#ddf3ea", "#fdf1d6"


def save(fig, name):
    fig.savefig(os.path.join(OUT, name))
    plt.close(fig)
    print("saved", name)


def box(ax, x, y, w, h, text, fc="white", ec=INK2, fs=9, bold=False, lw=1.0, tc=INK, ls="-"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.12",
                                fc=fc, ec=ec, lw=lw, ls=ls))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
                color=tc, fontweight="bold" if bold else "normal", linespacing=1.35)


def arrow(ax, x1, y1, x2, y2, c=INK2, lw=1.2, ls="-", rad=0.0):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="-|>", color=c, lw=lw, ls=ls, shrinkA=0, shrinkB=0,
                                mutation_scale=11, connectionstyle=f"arc3,rad={rad}"))


def line(ax, xs, ys, c=INK2, lw=1.1, ls="-"):
    ax.plot(xs, ys, color=c, lw=lw, ls=ls, solid_capstyle="butt")


def canvas(w, h, figsize):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off"); ax.set_aspect("equal")
    return fig, ax


def antenna(ax, x, y, c=INK2, s=0.28):
    """수직 급전선 + 위로 열린 V자 안테나 심볼 (x, y = 급전점)"""
    line(ax, [x, x], [y, y + s], c=c)
    ax.add_patch(Polygon([[x, y + s], [x - s * 0.8, y + s * 2.1], [x + s * 0.8, y + s * 2.1]],
                         closed=True, fc="white", ec=c, lw=1.1))


def satellite(ax, x, y):
    ax.add_patch(Rectangle((x - 0.85, y - 0.09), 0.55, 0.18, fc=TX_L, ec=TX, lw=1))
    ax.add_patch(Rectangle((x + 0.30, y - 0.09), 0.55, 0.18, fc=TX_L, ec=TX, lw=1))
    ax.add_patch(Rectangle((x - 0.2, y - 0.2), 0.4, 0.4, fc=INK2, ec=INK, lw=1))


# ================= 공통 수치 (본문과 동일) =================
R_E, ALT, EL = 6371.0, 550.0, 25.0


def slant(el_deg):
    e = np.radians(el_deg)
    return np.sqrt((R_E + ALT) ** 2 - (R_E * np.cos(e)) ** 2) - R_E * np.sin(e)


def fspl(f, d):
    return 92.45 + 20 * np.log10(f) + 20 * np.log10(d)


D_MAX = slant(EL)                                # 1,124 km
L_TX, L_RX = fspl(31.0, D_MAX), fspl(21.2, D_MAX)  # 183.3 / 180.0 dB


# ---------------------------------------------------------------- 1-a
def fig1a():
    fig, ax = canvas(15, 8.4, (10.5, 5.9))
    T = (3.0, 2.0)
    C, R_EARTH, R_ORB = (3.0, -40.0), 42.0, 47.5
    ax.add_patch(Circle(C, R_EARTH, fc=GR_L, ec=MUTED, lw=1.2))
    ax.add_patch(Circle(C, R_ORB, fill=False, ec=MUTED, lw=1.0, ls="--"))
    ax.text(8.6, 7.62, "LEO 궤도 (고도 550 km)", fontsize=9.5, color=INK2, rotation=-6.5)

    # 수평선, 천정, 최저 앙각 경로
    line(ax, [T[0], 14.6], [T[1], T[1]], c=MUTED, lw=0.9, ls=":")
    ax.text(14.5, 2.12, "수평선", fontsize=8.5, color=MUTED, ha="right", va="bottom")
    # 앙각 25° 광선과 궤도 교점
    e = np.radians(EL)
    b = 2 * (np.cos(e) * (T[0] - C[0]) + np.sin(e) * (T[1] - C[1]))
    cc = (T[0] - C[0]) ** 2 + (T[1] - C[1]) ** 2 - R_ORB ** 2
    t = (-b + np.sqrt(b * b - 4 * cc)) / 2
    S2 = (T[0] + t * np.cos(e), T[1] + t * np.sin(e))
    S1 = (T[0], C[1] + R_ORB)

    line(ax, [T[0], S1[0]], [T[1], S1[1] - 0.25], c=AQ, lw=2)
    line(ax, [T[0], S2[0]], [T[1], S2[1]], c=RX, lw=2)
    satellite(ax, *S1)
    satellite(ax, *S2)

    # 단말
    ax.add_patch(Rectangle((T[0] - 0.45, T[1] - 0.05), 0.9, 0.16, fc=TX, ec=INK, lw=0.8))
    ax.text(T[0], T[1] - 0.45, "단말 (평판형 능동 위상배열)", ha="center", va="top", fontsize=9.5, fontweight="bold")

    # 각도 표시
    ax.add_patch(Arc(T, 4.6, 4.6, theta1=0, theta2=EL, color=RX, lw=1.2))
    ax.text(T[0] + 2.55, T[1] + 0.45, "앙각 25°", fontsize=9.5, color=RX, fontweight="bold")
    ax.add_patch(Arc(T, 2.8, 2.8, theta1=EL, theta2=90, color=INK2, lw=1.2))
    ax.text(T[0] + 0.62, T[1] + 1.55, "조향각\n65°", fontsize=9, color=INK2, ha="left")

    # 천정 경로 라벨
    ax.text(T[0] + 0.2, 5.35, "천정 (보어사이트)\nd = 550 km\nFSPL  Tx 177.1 dB / Rx 173.8 dB",
            fontsize=9, color=AQ, ha="left", va="center", fontweight="bold", linespacing=1.4)
    # 경사 경로 라벨 (선 아래쪽)
    mx, my = (T[0] + S2[0]) / 2 + 0.6, (T[1] + S2[1]) / 2 + 0.3
    ax.text(mx + 0.55, my - 0.95, f"최대 경사거리 d = {D_MAX:,.0f} km\nFSPL  Tx {L_TX:.1f} dB / Rx {L_RX:.1f} dB",
            fontsize=9, color=RX, rotation=EL, rotation_mode="anchor", ha="center", va="top",
            fontweight="bold", linespacing=1.4)
    ax.text(S2[0], S2[1] + 0.4, "설계 기준 (최악 조건)", fontsize=9, color=RX, ha="center", va="bottom")

    ax.text(0.2, 0.35, "※ 개념도 (축척 무시).  FSPL은 Tx 31 GHz, Rx 21.2 GHz 기준", fontsize=8, color=MUTED)
    ax.set_title("LEO 위성 링크 기하 구조 및 설계 기준 조건", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig1a_leo_geometry.png")


# ---------------------------------------------------------------- 1-b
def fig1b():
    fig, ax = canvas(16.4, 6.6, (12.5, 5.0))
    xs = [2.5, 5.3, 8.1, 10.9, 13.7]
    w, h = 2.4, 2.25
    rows = [
        (3.75, "업링크\n(단말 → 위성)", TX, TX_L, [
            "목표 링크 품질\nQPSK 3/4, 40 Msps\n필요 Es/N0 5.0 dB",
            "필요 C/N0\n81.0 dBHz",
            "경로 및 위성 조건\nFSPL 183.3 dB\n부가 손실 7.0 dB\n위성 G/T 13 dB/K",
            "필요 EIRP\n29.7 dBW\n(요구치 30 dBW)",
            "채널 요구치\n평균 출력 +2.8 dBm\nOP1dB ≥ +12 dBm"]),
        (0.55, "다운링크\n(위성 → 단말)", RX, RX_L, [
            "목표 링크 품질\nQPSK 3/4, 50 Msps\n필요 Es/N0 5.0 dB",
            "필요 C/N0\n82.0 dBHz",
            "경로 및 위성 조건\nFSPL 180.0 dB\n부가 손실 5.0 dB\n위성 EIRP 38 dBW",
            "필요 G/T\n0.4 dB/K\n(안테나 이득 27 dBi)",
            "채널 요구치\n시스템 NF ≤ 3.75 dB\nBFIC NF ≤ 2.9 dB"]),
    ]
    for y, label, c, cl, items in rows:
        box(ax, 0.1, y, 2.0, h, label, fc=c, ec=c, tc="white", bold=True, fs=10)
        for i, (x, t) in enumerate(zip(xs, items)):
            hl = i in (3, 4)
            box(ax, x, y, w, h, t, fc=cl if hl else "white", ec=c if hl else INK2,
                lw=1.6 if hl else 1.0, fs=9, bold=(i == 3))
            if i:
                arrow(ax, xs[i - 1] + w, y + h / 2, x, y + h / 2)
        arrow(ax, 2.1, y + h / 2, xs[0], y + h / 2)
    ax.text(8.2, 6.35, "C/N0 = EIRP - FSPL - L + G/T - k,   Es/N0 = C/N0 - 10·log Rs",
            ha="center", fontsize=9.5, color=INK2)
    ax.set_title("링크 버짓 기반 송수신 모듈 요구사항 도출 흐름", fontsize=13, fontweight="bold", pad=2)
    save(fig, "fig1b_link_budget_flow.png")


# ---------------------------------------------------------------- 2-a
def fig2a():
    G, OP1 = 15.0, 12.0
    p = 2.0
    r = (10 ** (2 * p / 20) - 1) ** (1 / (2 * p))  # 1 dB 압축 시 G·Vin/Vsat
    psat = OP1 - 20 * np.log10(r * 10 ** (-1 / 20))
    pin = np.linspace(-25, 6, 400)
    vin_lin = 10 ** ((pin + G - psat) / 20)
    pout = psat + 20 * np.log10(vin_lin / (1 + vin_lin ** (2 * p)) ** (1 / (2 * p)))

    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    ax.plot(pin, pin + G, color=MUTED, ls="--", lw=1.1, label="선형 외삽 (소신호 이득 15 dB)")
    ax.plot(pin, pout, color=TX, lw=2.2, label="채널 출력 특성")
    ax.axhline(OP1, color=RX, lw=1.2)
    ax.axhline(6.0, color=AQ, lw=1.2)
    ax.axhline(2.8, color=YE, lw=1.2, ls="-.")
    ax.text(-24.5, OP1 + 0.4, "OP1dB ≥ +12 dBm (요구치)", color=RX, fontsize=9.5, fontweight="bold")
    ax.text(-24.5, 6.0 + 0.4, "최대 채널 출력 +6 dBm (테이퍼 중심 채널)", color=AQ, fontsize=9.5, fontweight="bold")
    ax.text(-24.5, 2.8 - 1.1, "평균 채널 출력 +2.8 dBm", color="#b07800", fontsize=9.5, fontweight="bold")
    # 백오프 표시
    xb = 0.0
    ax.annotate("", xy=(xb, OP1), xytext=(xb, 6.0),
                arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=1.1, mutation_scale=10))
    ax.text(xb + 0.4, 9.0, "백오프 6 dB\n(16APSK 이상)", fontsize=9, va="center")
    # 1 dB 압축점
    pin1 = OP1 + 1 - G
    ax.plot([pin1], [OP1], "o", color=RX, ms=6, zorder=5)
    ax.annotate("1 dB 압축점", xy=(pin1, OP1), xytext=(pin1 - 6.5, OP1 + 3.2), fontsize=9,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.set_xlim(-25, 6); ax.set_ylim(-12, 20)
    ax.set_xlabel("채널 입력 전력 (dBm)"); ax.set_ylabel("채널 출력 전력 (dBm)")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_title("송신 채널 출력 특성과 OP1dB 요구치", fontsize=12.5, fontweight="bold")
    fig.text(0.07, -0.04, "※ 이득 15 dB, OP1dB +12 dBm 가정의 개념 곡선 (Rapp 모델, p = 2)", fontsize=8, color=MUTED)
    save(fig, "fig2a_tx_p1db.png")


# ---------------------------------------------------------------- 2-b
def fig2b():
    stages = [  # 이름, 이득 dB, NF dB
        ("방사소자–BFIC\n전송선로", -0.5, 0.5),
        ("BFIC Rx 채널\n(LNA·위상기·VGA)", 20.0, 2.9),
        ("결합망\n(급전망 손실)", -2.0, 2.0),
        ("하향변환단", 20.0, 10.0),
    ]
    cumF, cumG, F, Gl = [], [], 1.0, 1.0
    for _, g, nf in stages:
        F += (10 ** (nf / 10) - 1) / Gl
        Gl *= 10 ** (g / 10)
        cumF.append(10 * np.log10(F)); cumG.append(10 * np.log10(Gl))

    fig, ax = canvas(16, 6.4, (12.5, 5.0))
    xs = [1.9, 5.3, 8.7, 12.1]
    w, h, y = 2.9, 1.7, 3.5
    antenna(ax, 0.75, y + h / 2)
    arrow(ax, 0.75, y + h / 2, xs[0], y + h / 2)
    for i, ((name, g, nf), x) in enumerate(zip(stages, xs)):
        hl = i == 1
        box(ax, x, y, w, h, name, fc=RX_L if hl else "white", ec=RX if hl else INK2,
            lw=1.6 if hl else 1.0, fs=9.5, bold=hl)
        ax.text(x + w / 2, y + h + 0.2, f"G = {g:+.1f} dB,  NF = {nf:.1f} dB", ha="center", fontsize=9,
                color=RX if hl else INK2, fontweight="bold" if hl else "normal")
        if i:
            arrow(ax, xs[i - 1] + w, y + h / 2, x, y + h / 2)
        # 누적값
        box(ax, x + 0.25, 1.15, w - 0.5, 1.45,
            f"누적 NF  {cumF[i]:.2f} dB\n누적 이득  {cumG[i]:+.1f} dB",
            fc=GR_L, ec=GR_L, fs=9)
        line(ax, [x + w / 2, x + w / 2], [y, 2.6], c=MUTED, lw=0.8, ls=":")
    ax.text(0.75, y + h / 2 - 0.35, "ANT", ha="center", fontsize=8.5, color=INK2)
    ax.text(8.0, 0.45,
            f"시스템 NF = {cumF[-1]:.2f} dB  (요구치 ≤ 3.75 dB)   —   결합망 손실 2 dB는 BFIC 이득 20 dB로 보상됨",
            ha="center", fontsize=10, fontweight="bold", color=RX)
    ax.text(8.0, 6.15, "F_sys = F₁ + (F₂ - 1)/G₁ + (F₃ - 1)/(G₁G₂) + …", ha="center", fontsize=9.5, color=INK2)
    ax.set_title("수신 체인 종속 잡음지수 배분 (Friis)", fontsize=13, fontweight="bold", pad=2)
    save(fig, "fig2b_rx_nf_cascade.png")


# ---------------------------------------------------------------- 3-a
def fig3a():
    steps = [("채널 평균 출력", 2.8, "abs"), ("배열 이득\n20·log 1,024", 60.2, "d"),
             ("소자 이득", 5.0, "d"), ("급전 손실", -2.0, "d"), ("스캔 손실\n(65°)", -4.5, "d"),
             ("부정합\n(VSWR 2:1)", -0.5, "d"), ("오차·온도\n마진", -1.0, "d"), ("EIRP", None, "tot")]
    fig, ax = plt.subplots(figsize=(10, 5.2))
    level = 0.0
    for i, (name, v, kind) in enumerate(steps):
        if kind == "abs":
            bottom, height, col = 0, v, YE; level = v
            lab = f"+{v:.1f} dBm"
        elif kind == "tot":
            bottom, height, col = 0, level, TX
            lab = f"{level:.1f} dBm\n(= {level - 30:.1f} dBW)"
        else:
            bottom = level if v >= 0 else level + v
            height = abs(v); col = AQ if v >= 0 else RX
            lab = f"{v:+.1f} dB"; level += v
        ax.bar(i, height, bottom=bottom, color=col, width=0.62, zorder=3)
        ax.text(i, bottom + height + 1.2, lab, ha="center", va="bottom", fontsize=9, fontweight="bold")
        if 0 < i < len(steps) - 1:
            ax.plot([i - 0.31 - 0.38, i - 0.31], [bottom + (height if v < 0 else 0)] * 2,
                    color=MUTED, lw=0.8, ls=":")
    ax.axhline(60, color=RX, lw=1.2, ls="--", zorder=2)
    ax.text(2.6, 56.3, "요구 EIRP 30 dBW (60 dBm)", color=RX, fontsize=9.5, fontweight="bold")
    ax.set_xticks(range(len(steps))); ax.set_xticklabels([s[0] for s in steps], fontsize=9)
    ax.set_ylim(0, 80); ax.set_ylabel("전력 레벨 (dBm)")
    ax.grid(axis="x", visible=False)
    ax.set_title("송신 EIRP 버짓 (1,024소자, 65° 조향 최악 조건)", fontsize=12.5, fontweight="bold")
    ax.text(-0.45, -17, "※ 진폭 테이퍼 적용 시 중심 채널은 +3 dB 높은 약 +6 dBm 필요.  소자 이득 5 dBi는 가정값",
            fontsize=8, color=MUTED)
    save(fig, "fig3a_eirp_budget.png")


# ---------------------------------------------------------------- 3-b
def fig3b():
    fig = plt.figure(figsize=(12, 8.2))
    ax = fig.add_axes([0.0, 0.36, 1.0, 0.62])
    ax.set_xlim(0, 16); ax.set_ylim(0, 7.2); ax.axis("off"); ax.set_aspect("equal")

    yc = 3.5
    box(ax, 0.1, yc - 0.55, 1.5, 1.1, "공통 입력\n+13.9 dBm", fc=TX_L, ec=TX, fs=9, bold=True)
    # 구동증폭기 (삼각형)
    ax.add_patch(Polygon([[1.95, yc - 0.42], [1.95, yc + 0.42], [2.65, yc]], closed=True, fc="white", ec=INK, lw=1.1))
    ax.text(2.3, yc - 0.75, "구동\n증폭기", ha="center", va="top", fontsize=8.5)
    line(ax, [1.6, 1.95], [yc, yc]); line(ax, [2.65, 3.0], [yc, yc])

    def split(x, y, dy, dx=1.4):
        ax.add_patch(Circle((x, y), 0.17, fc=VI, ec=VI))
        line(ax, [x, x], [y - dy, y + dy], c=VI)
        for s in (-1, 1):
            line(ax, [x, x + dx], [y + s * dy, y + s * dy], c=VI)
        return [(x + dx, y - dy), (x + dx, y + dy)]

    lv1 = split(3.0, yc, 1.6)
    lv2 = [p for (x, y) in lv1 for p in split(x, y, 0.8)]
    leaves = [p for (x, y) in lv2 for p in split(x, y, 0.4)]
    for (x, y) in leaves[1:]:
        ax.text(x + 0.1, y, "···", va="center", fontsize=11, color=VI)
    ax.text(5.8, 7.0, "Wilkinson 분배기 이진 트리\n기판 8단 (1:256)", ha="center", va="top", fontsize=9.5,
            color=VI, fontweight="bold")
    ax.text(5.8, -0.05, "이론 분배손실 24.1 dB + 초과손실 1.2 ~ 2.0 dB", ha="center", va="bottom", fontsize=9, color=VI)

    # BFIC 상세 (최하단 leaf 하나)
    lx, ly = leaves[0]
    bx, bw, bh = 9.0, 2.4, 2.6
    by = 0.15
    line(ax, [lx, 8.6, 8.6, bx], [ly, ly, by + bh / 2, by + bh / 2], c=VI)
    box(ax, bx, by, bw, bh, "", fc=TX_L, ec=TX, lw=1.5)
    ax.text(bx + bw / 2, by + bh - 0.25, "BFIC (Tx)", ha="center", va="top", fontsize=9.5, fontweight="bold", color=TX)
    ax.text(bx + bw / 2, by + 0.25, "칩 내부 1:4 분배\n+ 채널별 증폭", ha="center", va="bottom", fontsize=8.5)
    ys = np.linspace(by + 0.45, by + bh - 0.45, 4)
    for yy in ys:
        line(ax, [bx + bw, 13.3], [yy, yy], c=TX)
        ax.add_patch(Polygon([[13.3, yy], [13.85, yy + 0.22], [13.85, yy - 0.22]], closed=True, fc="white", ec=TX, lw=1.1))
    ax.text(14.05, by + bh / 2, "방사소자\n×4", va="center", fontsize=9)
    ax.text(bx + bw / 2, by + bh + 0.55, "BFIC 256개 × 4채널\n= 1,024 소자", ha="center", va="bottom",
            fontsize=9.5, fontweight="bold", color=TX)

    # 전력 레벨 다이어그램
    a2 = fig.add_axes([0.08, 0.06, 0.88, 0.26])
    pos = [0, 1, 2, 3]
    lev = [13.9, -12.2, 2.8, 2.8]
    a2.step(pos, lev, where="post", color=TX, lw=2)
    a2.plot(pos[:3], lev[:3], "o", color=TX)
    labels = ["공통 입력\n+13.9 dBm", "BFIC 입력\n-12.2 dBm", "채널 출력 (평균)\n+2.8 dBm"]
    for x, v, t in zip(pos[:3], lev[:3], labels):
        a2.text(x + 0.05, v + 2.5, t, fontsize=9, va="bottom")
    a2.annotate("", xy=(1, -12.2), xytext=(1, 13.9), arrowprops=dict(arrowstyle="-|>", color=VI, lw=1))
    a2.text(1.05, 1.0, "분배망 -26.1 dB", color=VI, fontsize=9)
    a2.text(2.05, -6.5, "BFIC 이득 +15 dB", color=TX, fontsize=9)
    a2.set_xlim(-0.2, 3.2); a2.set_ylim(-20, 28)
    a2.set_xticks([]); a2.set_ylabel("전력 (dBm)")
    a2.set_title("송신 경로 전력 레벨 (BFIC 이득 15 dB 가정)", fontsize=10.5, fontweight="bold", loc="left")
    fig.suptitle("송신 전력 분배 구조 및 구동 전력 레벨", fontsize=13, fontweight="bold", y=1.0)
    save(fig, "fig3b_power_distribution.png")


# ---------------------------------------------------------------- 4-a
def fig4a():
    fig, ax = canvas(16, 9.6, (12.5, 7.5))
    bh = 0.62
    # ---- Tx
    box(ax, 1.7, 5.2, 11.0, 4.2, "", fc="white", ec=TX, lw=1.5, ls="--")
    ax.text(1.85, 9.2, "Tx BFIC  (Stampede2731, 27.5 ~ 31 GHz)", fontsize=10, fontweight="bold", color=TX, va="top")
    box(ax, 0.05, 6.95 - 0.4, 1.35, 0.8, "RF IN", fc=TX_L, ec=TX, fs=9, bold=True)
    box(ax, 2.0, 5.75, 1.15, 3.0, "1:4\n분배기", fc=GR_L, fs=9)
    arrow(ax, 1.4, 6.95, 2.0, 6.95)
    tx_rows = [8.35, 7.55, 6.75, 5.95]
    tx_blocks = [(3.65, 1.25, "VGA"), (5.4, 1.6, "위상천이기\n6-bit"), (7.5, 1.2, "구동증폭"), (9.2, 1.1, "PA")]
    for yy in tx_rows:
        prev = 3.15
        for x, w, t in tx_blocks:
            arrow(ax, prev, yy, x, yy, lw=1)
            box(ax, x, yy - bh / 2, w, bh, t, fc=TX_L if t == "PA" else "white", ec=TX if t == "PA" else INK2, fs=8)
            prev = x + w
        line(ax, [prev, 13.6], [yy, yy], c=TX)
        ax.add_patch(Polygon([[13.6, yy], [14.2, yy + 0.25], [14.2, yy - 0.25]], closed=True, fc="white", ec=TX, lw=1.1))
    ax.text(14.35, 7.15, "방사소자\n×4", fontsize=9, va="center")
    cap_y = 5.3
    for (x, w, _), cap in zip(tx_blocks, ["진폭 테이퍼", "빔 조향", "", "OP1dB ≥ +12 dBm"]):
        if cap:
            ax.text(x + w / 2, cap_y, cap, ha="center", fontsize=8, color=TX)

    # ---- 제어부
    box(ax, 1.7, 4.2, 11.0, 0.7, "디지털 제어부 :  SPI 인터페이스  ·  빔 테이블 메모리  ·  동기 Latch  ·  온도 센서",
        fc=YE_L, ec=YE, fs=9, bold=True)
    for x in (4.3, 6.2):
        line(ax, [x, x], [4.9, 5.2], c=YE, ls="--")
        line(ax, [x, x], [3.95, 4.2], c=YE, ls="--")

    # ---- Rx
    box(ax, 1.7, 0.1, 11.0, 3.85, "", fc="white", ec=RX, lw=1.5, ls="--")
    ax.text(1.85, 3.78, "Rx BFIC  (Blueway1721, 17.7 ~ 21.2 GHz)", fontsize=10, fontweight="bold", color=RX, va="top")
    rx_rows = [2.95, 2.15, 1.35, 0.55]
    rx_blocks = [(2.1, 1.1, "LNA"), (3.8, 1.6, "위상천이기\n6-bit"), (5.9, 1.25, "VGA")]
    for yy in rx_rows:
        ax.add_patch(Polygon([[1.05, yy], [0.45, yy + 0.25], [0.45, yy - 0.25]], closed=True, fc="white", ec=RX, lw=1.1))
        prev = 1.05
        for x, w, t in rx_blocks:
            arrow(ax, prev, yy, x, yy, lw=1)
            box(ax, x, yy - bh / 2, w, bh, t, fc=RX_L if t == "LNA" else "white", ec=RX if t == "LNA" else INK2, fs=8)
            prev = x + w
        arrow(ax, prev, yy, 7.65, yy, lw=1)
    box(ax, 7.65, 0.3, 1.2, 2.9, "4:1\n결합기", fc=GR_L, fs=9)
    box(ax, 13.4, 1.75 - 0.4, 1.5, 0.8, "RF OUT", fc=RX_L, ec=RX, fs=9, bold=True)
    arrow(ax, 8.85, 1.75, 13.4, 1.75)
    ax.text(0.2, 3.35, "방사소자 ×4", fontsize=9)
    ax.text(10.6, 2.05, "LNA 최전단 배치 → 후단 손실의\n잡음지수 영향 최소화", fontsize=8.5, color=RX, ha="center")
    ax.set_title("BFIC 기반 다채널 송수신 RF Chain 구성 (칩당 4채널 가정)", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig4a_bfic_rf_chain.png")


# ---------------------------------------------------------------- 4-b
def fig4b():
    fig, ax = canvas(16.5, 7.6, (12.5, 5.8))
    # ---- (a) 단면 적층 구조
    x0, x1 = 0.4, 8.4
    layers = [  # y, h, fc, label
        (5.0, 0.55, "#f6f5f1", "안테나 기판"),
        (4.4, 0.6, TX_L, "급전망 층 (스트립라인 · Wilkinson)"),
        (3.8, 0.6, "#f6f5f1", "디지털 제어 · 전원 배선 층"),
    ]
    for y, h, fc, lab in layers:
        ax.add_patch(Rectangle((x0, y), x1 - x0, h, fc=fc, ec=INK2, lw=0.9))
    # 방사소자 (패치)
    px = np.linspace(x0 + 0.6, x1 - 1.4, 4)
    for x in px:
        ax.add_patch(Rectangle((x, 5.55), 0.8, 0.12, fc=YE, ec=INK, lw=0.6))
    # BFIC
    for xb in (px[0] + 0.4, px[2] + 0.4):
        ax.add_patch(Rectangle((xb - 0.2, 3.25), 2.0, 0.55, fc=INK2, ec=INK, lw=0.8))
        ax.text(xb + 0.8, 3.52, "BFIC", color="white", ha="center", va="center", fontsize=8.5, fontweight="bold")
    # 비아 (BFIC → 방사소자)
    for x in px:
        line(ax, [x + 0.4, x + 0.4], [3.8, 5.55], c=RX, lw=1.4)
    # 방열
    ax.add_patch(Rectangle((x0, 3.05), x1 - x0, 0.2, fc="#c9c7c0", ec=INK2, lw=0.6))
    ax.add_patch(Rectangle((x0, 2.45), x1 - x0, 0.6, fc="#dcdad4", ec=INK2, lw=0.8))
    for x in np.linspace(x0 + 0.2, x1 - 0.3, 14):
        ax.add_patch(Rectangle((x, 1.45), 0.18, 1.0, fc="#dcdad4", ec=INK2, lw=0.6))
    # 라벨
    labs = [(5.62, "방사소자 (패치)"), (5.27, "안테나 기판"), (4.7, "급전망 층 (스트립라인)"),
            (4.1, "제어 · 전원 배선 층"), (3.52, "BFIC (배면 실장)"), (3.15, "열 계면 물질 (TIM)"),
            (2.0, "방열판")]
    for y, t in labs:
        line(ax, [x1, x1 + 0.35], [y, y], c=MUTED, lw=0.7)
        ax.text(x1 + 0.45, y, t, va="center", fontsize=8.5)
    ax.text(px[1] + 1.2, 4.7, "수직 비아", fontsize=8.5, color=RX, ha="center", va="center", fontweight="bold",
            bbox=dict(fc="white", ec=RX, lw=0.6, pad=2))
    ax.text((x0 + x1) / 2, 0.95, "(a) 타일 단면 적층 구조", ha="center", fontsize=10.5, fontweight="bold")

    # ---- (b) 상면 배치
    gx, gy, s = 11.6, 2.0, 1.05
    cols = [TX_L, AQ_L, YE_L, RX_L]
    for bi, (cx, cy) in enumerate([(0, 0), (2, 0), (0, 2), (2, 2)]):
        ax.add_patch(Rectangle((gx + cx * s - 0.02, gy + cy * s - 0.02), 2 * s, 2 * s, fc=cols[bi], ec=TX, lw=1.3, ls="--"))
    for i in range(4):
        for j in range(4):
            ax.add_patch(Rectangle((gx + i * s + 0.3, gy + j * s + 0.3), 0.45, 0.45, fc=YE, ec=INK, lw=0.6))
    # 치수
    ax.annotate("", xy=(gx + 0.525 + s, gy + 4 * s + 0.25), xytext=(gx + 0.525, gy + 4 * s + 0.25),
                arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=0.9, mutation_scale=8))
    ax.text(gx + 0.525 + s / 2, gy + 4 * s + 0.4, "d", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.text(gx + 2 * s, gy - 0.35,
            "점선 영역 = BFIC 1개 (2 × 2 소자)\nTx: d = 5.0 mm → 10 × 10 mm\nRx: d = 7.4 mm → 14.8 × 14.8 mm",
            ha="center", va="top", fontsize=8.8, linespacing=1.4)
    ax.text(gx + 2 * s, 7.3, "(b) 상면 소자 및 BFIC 배치", ha="center", fontsize=10.5, fontweight="bold")
    ax.set_title("타일형 능동 위상배열 모듈 구조", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig4b_tile_structure.png")


# ---------------------------------------------------------------- 5
def fig5():
    fig, ax = canvas(16, 9.4, (12.5, 7.4))
    rows = [
        (7.0, "(a) S-파라미터 측정", [("VNA\nPort 1", "white"), ("평가보드 (EVB)\nDUT", TX_L), ("VNA\nPort 2", "white")],
         "이득 · 평탄도 · VSWR\n위상/진폭 상태 스윕 → RMS 오차\n채널 간 격리도"),
        (3.9, "(b) 출력 특성 측정", [("신호\n발생기", "white"), ("구동\n증폭기", "white"), ("결합기 +\n입력 전력계", "white"),
                                 ("평가보드 (EVB)\nDUT (Tx)", TX_L), ("감쇠기", "white"), ("전력계 /\n스펙트럼 분석기", "white")],
         "입력 전력 스윕\n→ OP1dB, Psat\n이득 압축 특성"),
        (0.8, "(c) 잡음지수 측정", [("잡음원\n(ENR 보정)", "white"), ("평가보드 (EVB)\nDUT (Rx)", RX_L), ("NF 분석기", "white")],
         "Y-factor 방식\n→ NF, 이득\n(또는 VNA cold-source)"),
    ]
    h = 1.5
    for y, title, blocks, meas in rows:
        ax.text(0.1, y + h + 0.35, title, fontsize=10.5, fontweight="bold")
        n = len(blocks)
        avail = 11.4
        w = 1.55 if n > 3 else 2.3
        gap = (avail - n * w) / (n - 1)
        prev = None
        for i, (t, fc) in enumerate(blocks):
            x = 0.2 + i * (w + gap)
            dut = "DUT" in t
            box(ax, x, y, w, h, t, fc=fc, ec=TX if fc == TX_L else (RX if fc == RX_L else INK2),
                lw=1.5 if dut else 1.0, fs=8.8, bold=dut)
            if prev is not None:
                arrow(ax, prev, y + h / 2, x, y + h / 2)
            prev = x + w
            if dut:
                box(ax, x + w / 2 - 0.75, y + h + 0.15, 1.5, 0.45, "제어 PC (SPI)", fc=YE_L, ec=YE, fs=7.8)
        box(ax, 12.2, y, 3.7, h, meas, fc=GR_L, ec=GR_L, fs=8.8)
        line(ax, [prev, 12.2], [y + h / 2, y + h / 2], c=MUTED, lw=0.8, ls=":")
    ax.text(0.1, 0.15, "※ 측정 결과에서 평가보드의 커넥터 및 전송선로 손실을 디임베딩하여 칩 단위 특성을 산출함",
            fontsize=8.5, color=MUTED)
    ax.set_title("단일 채널 특성 측정 구성", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig5_test_setup.png")


# ---------------------------------------------------------------- 6
def fig6():
    fig, ax = canvas(16.1, 6.6, (12.5, 5.2))
    items = [
        ("① 링크 버짓", "LEO 550 km\n최저 앙각 25°\n(65° 조향)", TX_L, TX),
        ("② 시스템 요구치", "EIRP 30 dBW\nG/T 0.4 dB/K\n시스템 NF ≤ 3.75 dB", TX_L, TX),
        ("③ 채널 요구치", "Tx OP1dB ≥ +12 dBm\nRx NF ≤ 2.9 dB\nRx 이득 ≥ 20 dB", TX_L, TX),
        ("④ 다채널 구조", "Tx 1,024ch / BFIC 256\nRx 512ch / BFIC 128\n기업형 분배망", AQ_L, AQ),
        ("⑤ 단일 채널 검증", "이득 · OP1dB · NF\nRMS 위상 / 진폭 오차\nVSWR · 격리도", YE_L, YE),
        ("⑥ 차년도", "타일 모듈 제작\n채널 교정 · 열 검증\n배열 방사 패턴", "white", MUTED),
    ]
    w, gap, y, h = 2.35, 0.3, 2.0, 2.9
    for i, (t, body, fc, ec) in enumerate(items):
        x = 0.1 + i * (w + gap)
        box(ax, x, y, w, h, "", fc=fc, ec=ec, lw=1.5, ls="--" if i == 5 else "-")
        ax.text(x + w / 2, y + h - 0.35, t, ha="center", va="top", fontsize=10, fontweight="bold")
        ax.text(x + w / 2, y + h / 2 - 0.3, body, ha="center", va="center", fontsize=8.8, linespacing=1.45)
        if i:
            arrow(ax, x - gap, y + h / 2, x, y + h / 2)
    # 상단 구분
    groups = [(0, 2, "링크 버짓 설계", TX), (3, 3, "모듈 아키텍처", AQ), (4, 4, "단일 채널 연구", "#b07800")]
    for a, b, t, c in groups:
        xa, xb = 0.1 + a * (w + gap), 0.1 + b * (w + gap) + w
        line(ax, [xa, xa, xb, xb], [5.15, 5.35, 5.35, 5.15], c=c, lw=1.3)
        ax.text((xa + xb) / 2, 5.5, t, ha="center", fontsize=10, fontweight="bold", color=c)
    # 피드백
    x5 = 0.1 + 4 * (w + gap) + w / 2
    x3 = 0.1 + 2 * (w + gap) + w / 2
    ax.annotate("", xy=(x3, y - 0.05), xytext=(x5, y - 0.05),
                arrowprops=dict(arrowstyle="-|>", color=RX, lw=1.3, mutation_scale=11,
                                connectionstyle="arc3,rad=-0.35"))
    ax.text((x3 + x5) / 2, 0.55, "측정값 반영 → 버짓 재검증", ha="center", fontsize=9.5, color=RX, fontweight="bold")
    ax.set_title("모듈 아키텍처 / 버짓 설계 및 단일 채널 연구 흐름", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig6_summary_flow.png")


if __name__ == "__main__":
    for f in (fig1a, fig1b, fig2a, fig2b, fig3a, fig3b, fig4a, fig4b, fig5, fig6):
        f()
