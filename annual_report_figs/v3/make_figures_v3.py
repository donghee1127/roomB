# -*- coding: utf-8 -*-
"""연차보고서 그림 v3 : 16APSK 2/3 기준, Stampede2731 / Blueway1721 데이터시트 반영.  실행: python make_figures_v3.py"""
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


D_MAX = slant(EL)                                # 1,123 km
L_TX, L_RX = fspl(31.0, D_MAX), fspl(21.2, D_MAX)  # 183.3 / 180.0 dB


# ===================== v3 : 16APSK 2/3, 데이터시트 기반 =====================
GRAY_TXT = INK2


def scan_loss(theta_deg):
    return -12 * np.log10(np.cos(np.radians(theta_deg)))   # cos^1.2


# ---------------------------------------------------------------- 1-a (v2 동일)
def fig1a():
    fig, ax = canvas(15, 8.4, (10.5, 5.9))
    T = (3.0, 2.0)
    C, R_EARTH, R_ORB = (3.0, -40.0), 42.0, 47.5
    ax.add_patch(Circle(C, R_EARTH, fc=GR_L, ec=MUTED, lw=1.2))
    ax.add_patch(Circle(C, R_ORB, fill=False, ec=MUTED, lw=1.0, ls="--"))
    ax.text(8.6, 7.62, "LEO 궤도 (고도 550 km)", fontsize=9.5, color=INK2, rotation=-6.5)
    line(ax, [T[0], 14.6], [T[1], T[1]], c=MUTED, lw=0.9, ls=":")
    ax.text(14.5, 2.12, "수평선", fontsize=8.5, color=MUTED, ha="right", va="bottom")
    e = np.radians(EL)
    b = 2 * (np.cos(e) * (T[0] - C[0]) + np.sin(e) * (T[1] - C[1]))
    cc = (T[0] - C[0]) ** 2 + (T[1] - C[1]) ** 2 - R_ORB ** 2
    t = (-b + np.sqrt(b * b - 4 * cc)) / 2
    S2 = (T[0] + t * np.cos(e), T[1] + t * np.sin(e))
    S1 = (T[0], C[1] + R_ORB)
    line(ax, [T[0], S1[0]], [T[1], S1[1] - 0.25], c=AQ, lw=2)
    line(ax, [T[0], S2[0]], [T[1], S2[1]], c=RX, lw=2)
    satellite(ax, *S1); satellite(ax, *S2)
    ax.add_patch(Rectangle((T[0] - 0.45, T[1] - 0.05), 0.9, 0.16, fc=TX, ec=INK, lw=0.8))
    ax.text(T[0], T[1] - 0.45, "단말 (평판형 능동 위상배열)", ha="center", va="top", fontsize=9.5, fontweight="bold")
    ax.add_patch(Arc(T, 4.6, 4.6, theta1=0, theta2=EL, color=RX, lw=1.2))
    ax.text(T[0] + 2.55, T[1] + 0.45, "앙각 25°", fontsize=9.5, color=RX, fontweight="bold")
    ax.add_patch(Arc(T, 2.8, 2.8, theta1=EL, theta2=90, color=INK2, lw=1.2))
    ax.text(T[0] + 0.62, T[1] + 1.55, "조향각\n65°", fontsize=9, color=INK2, ha="left")
    ax.text(T[0] + 0.2, 5.35, "천정 (보어사이트)\nd = 550 km\nFSPL  Tx 177.1 dB / Rx 173.8 dB",
            fontsize=9, color=AQ, ha="left", va="center", fontweight="bold", linespacing=1.4)
    mx, my = (T[0] + S2[0]) / 2 + 0.6, (T[1] + S2[1]) / 2 + 0.3
    ax.text(mx + 0.55, my - 0.95, f"최대 경사거리 d = {D_MAX:,.0f} km\nFSPL  Tx {L_TX:.1f} dB / Rx {L_RX:.1f} dB",
            fontsize=9, color=RX, rotation=EL, rotation_mode="anchor", ha="center", va="top",
            fontweight="bold", linespacing=1.4)
    ax.text(S2[0], S2[1] + 0.4, "설계 기준 (최악 조건)", fontsize=9, color=RX, ha="center", va="bottom")
    ax.text(0.2, 0.35, "※ 개념도 (축척 무시).  FSPL은 Tx 31 GHz, Rx 21.2 GHz 기준", fontsize=8, color=MUTED)
    ax.set_title("LEO 위성 링크 기하 구조 및 설계 기준 조건", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig1a_leo_geometry.png")


# ---------------------------------------------------------------- 1-b 16APSK 성상도
def fig1b():
    gamma = 3.15                                  # 16APSK 2/3 링 반경비 (DVB-S2)
    r1 = np.sqrt(16 / (4 + 12 * gamma ** 2)); r2 = gamma * r1   # 평균 전력 1로 정규화
    inner = [r1 * np.exp(1j * np.radians(45 + 90 * k)) for k in range(4)]
    outer = [r2 * np.exp(1j * np.radians(15 + 30 * k)) for k in range(12)]
    fig, ax = plt.subplots(figsize=(6.6, 5.6))
    th = np.linspace(0, 2 * np.pi, 300)
    for r, c in ((r1, RX), (r2, TX)):
        ax.plot(r * np.cos(th), r * np.sin(th), color=c, lw=0.9, ls="--", alpha=0.7)
    ax.plot([p.real for p in outer], [p.imag for p in outer], "o", ms=10, color=TX, mec="white", mew=1.5,
            label="외곽 링 12점 (반경 R₂)")
    ax.plot([p.real for p in inner], [p.imag for p in inner], "o", ms=10, color=RX, mec="white", mew=1.5,
            label="내부 링 4점 (반경 R₁)")
    ax.annotate("", xy=(r2 * np.cos(np.radians(-8)), r2 * np.sin(np.radians(-8))), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=TX, lw=1.0))
    ax.annotate("", xy=(r1 * np.cos(np.radians(-25)), r1 * np.sin(np.radians(-25))), xytext=(0, 0),
                arrowprops=dict(arrowstyle="-|>", color=RX, lw=1.0))
    ax.text(r2 * 0.62, -0.30, "R₂", color=TX, fontsize=10, fontweight="bold")
    ax.text(0.02, -0.2, "R₁", color=RX, fontsize=10, fontweight="bold")
    ax.axhline(0, color=MUTED, lw=0.7); ax.axvline(0, color=MUTED, lw=0.7)
    ax.set_aspect("equal"); ax.set_xlim(-1.75, 1.75); ax.set_ylim(-1.6, 1.75)
    ax.set_xlabel("I (동위상)"); ax.set_ylabel("Q (직교위상)")
    ax.legend(loc="upper center", ncol=2, frameon=False, fontsize=9, bbox_to_anchor=(0.5, 1.0))
    ax.text(1.72, -1.5, f"링 반경비 γ = R₂/R₁ = {gamma}\n(16APSK 2/3, DVB-S2)", ha="right", va="bottom",
            fontsize=8.8, color=INK2, bbox=dict(fc="white", ec="none", alpha=0.9))
    ax.set_title("16APSK 성상도 (4 + 12 APSK)", fontsize=12.5, fontweight="bold")
    save(fig, "fig1b_16apsk_constellation.png")


# ---------------------------------------------------------------- 1-c 링크 버짓 흐름
def fig1c():
    fig, ax = canvas(16.4, 6.6, (12.5, 5.0))
    xs = [2.5, 5.3, 8.1, 10.9, 13.7]
    w, h = 2.4, 2.25
    rows = [
        (3.75, "업링크\n(단말 → 위성)", TX, TX_L, [
            "기준 MODCOD\n16APSK 2/3, 20 Msps\n필요 Es/N0 10.0 dB",
            "필요 C/N0\n83.0 dBHz",
            "경로 및 위성 조건\nFSPL 183.3 dB\n부가 손실 5.0 dB\n위성 G/T 13 dB/K",
            "필요 EIRP\n29.7 dBW\n(요구치 30 dBW)",
            "채널 요구치\n최대 출력 +2.8 dBm\nOP1dB ≥ +9 dBm\nEVM ≤ 5 %"]),
        (0.55, "다운링크\n(위성 → 단말)", RX, RX_L, [
            "기준 MODCOD\n16APSK 2/3, 20 Msps\n필요 Es/N0 10.0 dB",
            "필요 C/N0\n83.0 dBHz",
            "경로 및 위성 조건\nFSPL 180.0 dB\n부가 손실 4.0 dB\n위성 EIRP 38 dBW",
            "필요 G/T\n0.4 dB/K\n(안테나 이득 27 dBi)",
            "채널 요구치\n시스템 NF ≤ 3.75 dB\nBFIC G ≥ 15 dB\nNF ≤ 3.1 dB"]),
    ]
    for y, label, c, cl, items in rows:
        box(ax, 0.1, y, 2.0, h, label, fc=c, ec=c, tc="white", bold=True, fs=10)
        for i, (x, t) in enumerate(zip(xs, items)):
            hl = i in (3, 4)
            box(ax, x, y, w, h, t, fc=cl if hl else "white", ec=c if hl else INK2,
                lw=1.6 if hl else 1.0, fs=8.8, bold=(i == 3))
            if i:
                arrow(ax, xs[i - 1] + w, y + h / 2, x, y + h / 2)
        arrow(ax, 2.1, y + h / 2, xs[0], y + h / 2)
    ax.text(8.2, 6.35, "C/N0 = EIRP - FSPL - L + G/T - k,   Es/N0 = C/N0 - 10·log Rs   (부가 손실 = 가스 + 강우 + 편파·지향)",
            ha="center", fontsize=9.2, color=INK2)
    ax.set_title("링크 버짓 기반 송수신 모듈 요구사항 도출 흐름 (16APSK 2/3)", fontsize=13, fontweight="bold", pad=2)
    save(fig, "fig1c_link_budget_flow.png")


# ---------------------------------------------------------------- 1-d 앙각별 Es/N0와 ACM
def fig1d():
    E = np.linspace(25, 90, 300)
    d = slant(E)
    th = 90 - E
    ul = 30.0 + scan_loss(65) - scan_loss(th) - fspl(31.0, d) - 5.0 + 13 + 228.6 - 73.0
    dl = 38.0 - fspl(21.2, d) - 4.0 + (0.4 + scan_loss(65) - scan_loss(th)) + 228.6 - 73.0
    mods = [("16APSK 2/3", 10.0), ("16APSK 3/4", 11.2), ("16APSK 4/5", 12.0), ("16APSK 5/6", 12.6)]
    fig, ax = plt.subplots(figsize=(8.4, 4.6))
    ax.plot(E, ul, color=TX, lw=2.2, label="업링크 (EIRP 30 dBW 설계)")
    ax.plot(E, dl, color=RX, lw=2.2, label="다운링크 (G/T 0.4 dB/K 설계)")
    for name, v in mods:
        ax.axhline(v, color=MUTED, lw=0.9, ls="--")
        ax.text(89.5, v + 0.12, name, ha="right", va="bottom", fontsize=8.5, color=INK2,
                bbox=dict(fc="white", ec="none", pad=0.5))
    ax.axvline(25, color=INK2, lw=0.9, ls=":")
    ax.annotate("설계 기준\n(앙각 25°)", xy=(25, 10.1), xytext=(29, 6.6), fontsize=8.8, color=INK2,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    e12 = E[np.argmax(dl >= 12.6)]
    ax.axvspan(e12, 90, color=GR_L, zorder=0)
    ax.text((e12 + 90) / 2, 22.6, "최상위 MODCOD 운용 영역\n(남는 여유 = 추가 강우 마진)", ha="center", va="top",
            fontsize=8.8, color=INK2)
    ax.set_xlim(25, 90); ax.set_ylim(5, 23)
    ax.set_xlabel("앙각 (°)"); ax.set_ylabel("가용 Es/N0 (dB)")
    ax.legend(loc="lower right", frameon=False, fontsize=9)
    ax.set_title("앙각에 따른 가용 Es/N0 및 16APSK ACM 운용", fontsize=12.5, fontweight="bold")
    fig.text(0.08, -0.03, "※ 설계 강우 마진(Tx 3 dB, Rx 2 dB) 포함 조건. 스캔 손실 cos^1.2 θ, 필요 Es/N0는 DVB-S2 값 + 구현 손실 1 dB",
             fontsize=8, color=MUTED)
    save(fig, "fig1d_acm_elevation.png")


# ---------------------------------------------------------------- 2-a Tx 출력 특성
def fig2a():
    G, OP1, PSAT = 28.0, 21.0, 24.0
    from scipy.optimize import brentq
    p = brentq(lambda p: 1 - (10 / p) * np.log10(10 ** (p / 10) - 1) - (PSAT - OP1), 0.8, 5)
    pin = np.linspace(-45, 0, 500)
    x = 10 ** ((pin + G - PSAT) / 20)
    pout = PSAT + 20 * np.log10(x / (1 + x ** (2 * p)) ** (1 / (2 * p)))
    fig, ax = plt.subplots(figsize=(8.0, 5.0))
    ax.plot(pin, pin + G, color=MUTED, ls="--", lw=1.1, label="선형 외삽 (단일 채널 이득 28 dB)")
    ax.plot(pin, pout, color=TX, lw=2.2, label="Stampede2731 채널 출력 (개념 곡선)")
    ax.axhline(OP1, color=TX, lw=1.0, ls=":"); ax.axhline(19.5, color=TX, lw=1.0, ls=":")
    ax.text(-44.5, OP1 + 0.4, "OP1dB typ +21 dBm", color=TX, fontsize=9, fontweight="bold")
    ax.text(-44.5, 19.5 - 1.6, "OP1dB min +19.5 dBm", color=TX, fontsize=9)
    ax.axhline(2.8, color=AQ, lw=1.4)
    ax.text(-44.5, 2.8 + 0.4, "채널 최대 출력 +2.8 dBm (테이퍼 중심, 기준)", color="#0f7a55", fontsize=9, fontweight="bold")
    ax.axhline(9.0, color=RX, lw=1.4, ls="--")
    ax.text(-44.5, 9.0 + 0.4, "요구 OP1dB ≥ +9 dBm (최대 출력 + 백오프 6 dB)", color=RX, fontsize=9, fontweight="bold")
    xb = -6.0
    ax.annotate("", xy=(xb, OP1), xytext=(xb, 2.8), arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=1.0, mutation_scale=9))
    ax.text(xb + 0.4, 15.2, "실제 백오프\n18.2 dB", fontsize=9, va="center")
    xu = -1.5
    ax.annotate("", xy=(xu, 8.8), xytext=(xu, 2.8), arrowprops=dict(arrowstyle="-|>", color=YE, lw=1.4, mutation_scale=9))
    ax.text(xu - 0.3, 5.6, "UPC\n+6 dB", fontsize=8.5, color="#b07800", ha="right", va="center", fontweight="bold")
    pin1 = OP1 + 1 - G
    ax.plot([pin1], [OP1], "o", color=TX, ms=6, zorder=5)
    ax.set_xlim(-45, 0); ax.set_ylim(-15, 28)
    ax.set_xlabel("채널 입력 전력 (dBm)"); ax.set_ylabel("채널 출력 전력 (dBm)")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax.set_title("송신 채널 출력 특성과 OP1dB 요구치 (Stampede2731)", fontsize=12.5, fontweight="bold")
    fig.text(0.07, -0.04, f"※ 데이터시트 typ (이득 28 dB, OP1dB 21 dBm, Psat 24 dBm) 기준 Rapp 모델 (p = {p:.2f}) 개념 곡선",
             fontsize=8, color=MUTED)
    save(fig, "fig2a_tx_op1db.png")


def friis(stages):
    F, G = 0.0, 1.0
    out = []
    for i, (g, nf) in enumerate(stages):
        Fi = 10 ** (nf / 10)
        F = Fi if i == 0 else F + (Fi - 1) / G
        G *= 10 ** (g / 10)
        out.append((10 * np.log10(F), 10 * np.log10(G)))
    return out


# ---------------------------------------------------------------- 2-b Rx 종속 NF
def fig2b():
    stages = [("방사소자–BFIC\n전송선로", -0.5, 0.5),
              ("Blueway1721\nRx 채널", 18.0, 2.0),
              ("Rx 결합망\n(128:1)", -2.0, 2.0),
              ("공통 LNA", 15.0, 2.5),
              ("하향변환단", 20.0, 10.0)]
    cum = friis([(g, nf) for _, g, nf in stages])
    fig, ax = canvas(17, 6.4, (13.0, 4.9))
    xs = [1.8, 4.85, 7.9, 10.95, 14.0]
    w, h, y = 2.65, 1.7, 3.5
    antenna(ax, 0.75, y + h / 2)
    arrow(ax, 0.75, y + h / 2, xs[0], y + h / 2)
    for i, ((name, g, nf), x) in enumerate(zip(stages, xs)):
        hl = i in (1, 3)
        ec = RX if i == 1 else (AQ if i == 3 else INK2)
        fc = RX_L if i == 1 else (AQ_L if i == 3 else "white")
        box(ax, x, y, w, h, name, fc=fc, ec=ec, lw=1.6 if hl else 1.0, fs=9.5, bold=hl)
        ax.text(x + w / 2, y + h + 0.2, f"G = {g:+.1f} dB,  NF = {nf:.1f} dB", ha="center", fontsize=8.6,
                color=ec if hl else INK2, fontweight="bold" if hl else "normal")
        if i:
            arrow(ax, xs[i - 1] + w, y + h / 2, x, y + h / 2)
        box(ax, x + 0.2, 1.15, w - 0.4, 1.45, f"누적 NF  {cum[i][0]:.2f} dB\n누적 이득  {cum[i][1]:+.1f} dB",
            fc=GR_L, ec=GR_L, fs=8.8)
        line(ax, [x + w / 2, x + w / 2], [y, 2.6], c=MUTED, lw=0.8, ls=":")
    ax.text(0.75, y + h / 2 - 0.35, "ANT", ha="center", fontsize=8.5, color=INK2)
    ax.text(12.3, 5.85, "결합망 출력단에 추가", ha="center", fontsize=8.6, color="#0f7a55", fontweight="bold")
    ax.text(8.5, 0.45, f"시스템 NF = {cum[-1][0]:.2f} dB (typ),  최악 2.98 dB  —  요구치 ≤ 3.75 dB,  G/T 1.6 ~ 2.3 dB/K",
            ha="center", fontsize=10, fontweight="bold", color=RX)
    ax.set_title("수신 체인 종속 잡음지수 (공통 LNA 적용, Friis)", fontsize=13, fontweight="bold", pad=2)
    save(fig, "fig2b_rx_nf_cascade.png")


# ---------------------------------------------------------------- 2-c BFIC 이득 vs 시스템 NF
def fig2c():
    g = np.linspace(10, 26, 200)
    line_ = (-0.5, 0.5); comb = (-2.0, 2.0); lna = (15, 2.5); dc = (20, 10.0)
    def sysnf(gg, nf, with_lna):
        st = [line_, (gg, nf), comb] + ([lna] if with_lna else []) + [dc]
        return friis(st)[-1][0]
    fig, ax = plt.subplots(figsize=(8.2, 4.8))
    ax.axvspan(15, 21, color=GR_L, zorder=0)
    ax.text(18, 2.25, "Blueway1721 이득 범위\n(min 15 / typ 18 / max 21 dB)", ha="center", va="bottom", fontsize=8.6, color=INK2)
    for with_lna, c, lab in [(False, RX, "공통 LNA 미적용"), (True, TX, "공통 LNA 적용")]:
        for nf, ls in [(2.0, "-"), (2.3, "--")]:
            ax.plot(g, [sysnf(x, nf, with_lna) for x in g], color=c, lw=2.0, ls=ls,
                    label=f"{lab}, BFIC NF {nf} dB ({'typ' if nf == 2.0 else 'max'})")
    ax.axhline(3.75, color=INK, lw=1.2, ls=":")
    ax.text(10.2, 3.80, "시스템 NF 요구치 3.75 dB", fontsize=9, fontweight="bold", va="bottom")
    p_bad = sysnf(15, 2.3, False); p_ok = sysnf(15, 2.3, True)
    ax.plot([15], [p_bad], "o", color=RX, ms=7, mec="white", mew=1.5, zorder=5)
    ax.annotate(f"{p_bad:.2f} dB (초과)", xy=(15, p_bad), xytext=(15.7, 4.3), fontsize=9, color=RX, fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=RX, lw=0.8))
    ax.plot([15], [p_ok], "o", color=TX, ms=7, mec="white", mew=1.5, zorder=5)
    ax.annotate(f"{p_ok:.2f} dB", xy=(15, p_ok), xytext=(11.0, 2.4), fontsize=9, color=TX, fontweight="bold",
                arrowprops=dict(arrowstyle="-", color=TX, lw=0.8))
    ax.set_xlim(10, 26); ax.set_ylim(2.2, 5.2)
    ax.set_xlabel("BFIC Rx 채널 이득 (dB)"); ax.set_ylabel("수신 시스템 NF (dB)")
    ax.legend(frameon=False, fontsize=8.4, loc="upper right")
    ax.set_title("BFIC 이득에 따른 수신 시스템 NF와 공통 LNA 효과", fontsize=12.5, fontweight="bold")
    save(fig, "fig2c_nf_vs_bfic_gain.png")


# ---------------------------------------------------------------- 3-a EIRP 워터폴
def fig3a():
    steps = [("채널 평균 출력", -0.2, "abs"), ("H/V 2채널\n합성", 3.0, "d"), ("배열 이득\n20·log 1,024", 60.2, "d"),
             ("소자 이득", 5.0, "d"), ("급전 손실", -2.0, "d"), ("스캔 손실\n(65°)", -4.5, "d"),
             ("부정합\n(VSWR 2:1)", -0.5, "d"), ("오차·온도\n마진", -1.0, "d"), ("EIRP", None, "tot")]
    fig, ax = plt.subplots(figsize=(10.5, 5.2))
    level = 0.0
    for i, (name, v, kind) in enumerate(steps):
        if kind == "abs":
            bottom, height, col = min(0, v), abs(v), YE; level = v; lab = f"{v:+.1f} dBm"
        elif kind == "tot":
            bottom, height, col = 0, level, TX; lab = f"{level:.1f} dBm\n(= {level - 30:.1f} dBW)"
        else:
            bottom = level if v >= 0 else level + v
            height = abs(v); col = AQ if v >= 0 else RX
            lab = f"{v:+.1f} dB"; level += v
        ax.bar(i, max(height, 0.6), bottom=bottom, color=col, width=0.62, zorder=3)
        ax.text(i, bottom + max(height, 0.6) + 1.2, lab, ha="center", va="bottom", fontsize=9, fontweight="bold")
        if 0 < i < len(steps) - 1:
            ax.plot([i - 0.69, i - 0.31], [bottom + (height if v < 0 else 0)] * 2, color=MUTED, lw=0.8, ls=":")
    ax.axhline(60, color=RX, lw=1.2, ls="--", zorder=2)
    ax.text(3.6, 55.8, "요구 EIRP 30 dBW (60 dBm)", color=RX, fontsize=9.5, fontweight="bold")
    ax.set_xticks(range(len(steps))); ax.set_xticklabels([s[0] for s in steps], fontsize=9)
    ax.set_ylim(-3, 80); ax.set_ylabel("전력 레벨 (dBm)")
    ax.grid(axis="x", visible=False)
    ax.set_title("송신 EIRP 버짓 (1,024소자, 65° 조향 최악 조건)", fontsize=12.5, fontweight="bold")
    fig.text(0.07, -0.04, "※ 원형편파: 소자당 H/V 2채널 합성(+3 dB). Taylor 테이퍼 적용 시 중심 채널은 +3 dB 높은 +2.8 dBm 필요. 소자 이득 5 dBi는 가정값",
             fontsize=8, color=MUTED)
    save(fig, "fig3a_eirp_budget.png")


# ---------------------------------------------------------------- 3-b 분배 구조 + 레벨
def fig3b():
    fig = plt.figure(figsize=(12, 8.4))
    ax = fig.add_axes([0.0, 0.37, 1.0, 0.61])
    ax.set_xlim(0, 16); ax.set_ylim(0, 7.2); ax.axis("off"); ax.set_aspect("equal")
    yc = 3.5
    box(ax, 0.1, yc - 0.55, 1.5, 1.1, "상향변환기\n출력", fc="white", ec=INK2, fs=8.8)
    ax.add_patch(Polygon([[1.95, yc - 0.42], [1.95, yc + 0.42], [2.65, yc]], closed=True, fc=TX_L, ec=TX, lw=1.2))
    ax.text(1.95, yc - 0.6, "구동증폭기\n(OP1dB ≥ +22 dBm)", ha="center", va="top", fontsize=8.3, color=TX)
    line(ax, [1.6, 1.95], [yc, yc]); line(ax, [2.65, 3.0], [yc, yc])
    ax.text(2.3, yc + 0.5, "+6.9 dBm", fontsize=8.3, color=TX, fontweight="bold", ha="center", va="bottom")

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
    ax.text(5.8, 7.0, "Wilkinson 분배기 이진 트리\n기판 8단 (1:256)", ha="center", va="top", fontsize=9.5, color=VI, fontweight="bold")
    ax.text(5.8, -0.05, "이론 분배손실 24.1 dB + 초과손실 1.2 ~ 2.0 dB", ha="center", va="bottom", fontsize=9, color=VI)
    lx, ly = leaves[0]
    bx, bw, bh, by = 9.0, 2.5, 2.9, 0.1
    line(ax, [lx, 8.6, 8.6, bx], [ly, ly, by + bh / 2, by + bh / 2], c=VI)
    box(ax, bx, by, bw, bh, "", fc=TX_L, ec=TX, lw=1.5)
    ax.text(bx + bw / 2, by + bh - 0.2, "Stampede2731", ha="center", va="top", fontsize=9.5, fontweight="bold", color=TX)
    ax.text(bx + bw / 2, by + 0.2, "칩 내부 분배\n8채널 증폭\n(전 채널 이득 22 dB)", ha="center", va="bottom", fontsize=8.3)
    yel = np.linspace(by + 0.45, by + bh - 0.45, 4)
    for yy in yel:
        for off, lab in ((0.11, "H"), (-0.11, "V")):
            line(ax, [bx + bw, 13.2], [yy + off, yy + off], c=TX, lw=0.9)
        ax.add_patch(Rectangle((13.2, yy - 0.25), 0.5, 0.5, fc=YE, ec=INK, lw=0.7))
    ax.text(12.5, by + bh + 0.08, "H / V", ha="center", fontsize=8, color=TX)
    ax.text(13.9, by + bh / 2, "방사소자 ×4\n(원형편파\n H/V 90°)", va="center", fontsize=8.6)
    ax.text(bx + bw / 2, by + bh + 0.5, "BFIC 256개 × 4소자 = 1,024소자\n(2,048채널)", ha="center", va="bottom",
            fontsize=9.3, fontweight="bold", color=TX)

    a2 = fig.add_axes([0.08, 0.05, 0.88, 0.26])
    pos = [0, 1, 2, 3]
    lev = [6.9, -19.2, 2.8, 2.8]
    a2.step(pos, lev, where="post", color=TX, lw=2, label="기준 (BFIC 이득 typ 22 dB)")
    a2.step(pos, [v + 6 for v in lev], where="post", color=YE, lw=1.4, ls="--", label="UPC 최대 (+6 dB)")
    a2.plot(pos[:3], lev[:3], "o", color=TX)
    labels = ["분배망 입력\n+6.9 dBm", "BFIC 빔 입력\n-19.2 dBm", "채널 최대 출력\n+2.8 dBm"]
    for x, v, t in zip(pos[:3], lev[:3], labels):
        a2.text(x + 0.05, v - 2.0, t, fontsize=8.8, va="top")
    a2.text(1.05, 2.0, "분배망 -26.1 dB", color=VI, fontsize=9)
    a2.text(2.05, -12.0, "BFIC 이득 +22 dB", color=TX, fontsize=9)
    a2.set_xlim(-0.2, 3.2); a2.set_ylim(-34, 22)
    a2.set_xticks([]); a2.set_ylabel("전력 (dBm)")
    a2.legend(frameon=False, fontsize=8.5, loc="upper right")
    a2.set_title("송신 경로 전력 레벨", fontsize=10.5, fontweight="bold", loc="left")
    fig.suptitle("송신 전력 분배 구조 및 구동 전력 레벨", fontsize=13, fontweight="bold", y=1.0)
    save(fig, "fig3b_power_distribution.png")


# ---------------------------------------------------------------- 4-a RF chain
def fig4a():
    fig, ax = canvas(16.4, 10.0, (12.8, 7.8))
    bh = 0.6
    # ---- Tx
    box(ax, 1.5, 5.25, 11.2, 4.45, "", fc="white", ec=TX, lw=1.5, ls="--")
    ax.text(1.65, 9.55, "Tx BFIC  Stampede2731 (27.5 ~ 31 GHz, 8채널 / 2빔)", fontsize=10, fontweight="bold", color=TX, va="top")
    box(ax, 0.0, 7.1 - 0.4, 1.2, 0.8, "빔 입력\nB0 / B1", fc=TX_L, ec=TX, fs=8.3, bold=True)
    box(ax, 1.75, 6.55, 1.25, 1.1, "공통\n감쇠기\n16 dB", fc=GR_L, fs=7.8)
    box(ax, 3.3, 5.75, 0.95, 2.75, "분배", fc=GR_L, fs=8.5)
    arrow(ax, 1.2, 7.1, 1.75, 7.1); arrow(ax, 3.0, 7.1, 3.3, 7.1)
    rows = [8.45, 7.6, 6.75, 5.9]
    blocks = [(4.6, 1.75, "감쇠기\n6-bit, 16 dB"), (6.7, 1.75, "위상천이기\n6-bit, 5.625°"), (8.8, 1.1, "PA")]
    for k, yy in enumerate(rows):
        prev = 4.25
        for x, w, t in blocks:
            arrow(ax, prev, yy, x, yy, lw=1)
            box(ax, x, yy - bh / 2, w, bh, t, fc=TX_L if t == "PA" else "white", ec=TX if t == "PA" else INK2, fs=7.6)
            prev = x + w
        line(ax, [prev, 13.15], [yy, yy], c=TX)
        ax.add_patch(Rectangle((13.15, yy - 0.2), 0.4, 0.4, fc=YE, ec=INK, lw=0.7))
        ax.text(10.35, yy + 0.08, f"소자 {k + 1}  H/V", fontsize=7.6, color=INK2, va="bottom")
    box(ax, 11.35, 5.55, 1.15, 3.2, "", fc=YE_L, ec=YE, fs=7.8, ls="--")
    ax.text(11.925, 8.85, "출력 정합 회로 (보드)", ha="center", va="bottom", fontsize=7.8, color="#b07800", fontweight="bold",
            bbox=dict(fc="white", ec="none", pad=1))
    ax.text(13.75, 7.15, "방사소자 ×4\n(H/V 2채널씩)", fontsize=8.6, va="center")
    cap = [(4.6 + 1.75 / 2, "진폭 테이퍼 · UPC"), (6.7 + 1.75 / 2, "빔 조향"), (8.8 + 0.55, "OP1dB 21 dBm")]
    for x, t in cap:
        ax.text(x, 5.35, t, ha="center", fontsize=7.8, color=TX)
    ax.text(11.9, 5.35, "출력 RL 5 dB 보완", ha="center", fontsize=7.8, color="#b07800")
    # ---- 제어
    box(ax, 1.5, 4.3, 11.2, 0.7, "디지털 제어부 :  SPI (100 MHz)  ·  빔 테이블 1,024 entry  ·  Beam_UPDATE 동기  ·  온도 / 전력 센서",
        fc=YE_L, ec=YE, fs=8.8, bold=True)
    for x in (5.5, 7.6):
        line(ax, [x, x], [5.0, 5.25], c=YE, ls="--"); line(ax, [x, x], [4.05, 4.3], c=YE, ls="--")
    # ---- Rx
    box(ax, 1.5, 0.05, 11.2, 4.0, "", fc="white", ec=RX, lw=1.5, ls="--")
    ax.text(1.65, 3.9, "Rx BFIC  Blueway1721 (17.7 ~ 21.2 GHz, 8채널 / 2빔)", fontsize=10, fontweight="bold", color=RX, va="top")
    rrows = [3.0, 2.2, 1.4, 0.6]
    rblocks = [(1.9, 1.3, "2단 LNA"), (3.55, 1.75, "위상천이기\n6-bit"), (5.65, 1.75, "감쇠기\n6-bit, 32 dB")]
    for k, yy in enumerate(rrows):
        ax.add_patch(Rectangle((0.35, yy - 0.2), 0.4, 0.4, fc=YE, ec=INK, lw=0.7))
        prev = 0.75
        for x, w, t in rblocks:
            arrow(ax, prev, yy, x, yy, lw=1)
            box(ax, x, yy - bh / 2, w, bh, t, fc=RX_L if "LNA" in t else "white", ec=RX if "LNA" in t else INK2, fs=7.6)
            prev = x + w
        arrow(ax, prev, yy, 7.75, yy, lw=1)
    ax.text(0.1, 3.45, "방사소자 ×4\n(H/V)", fontsize=8.3)
    box(ax, 7.75, 0.3, 0.95, 3.0, "결합", fc=GR_L, fs=8.5)
    box(ax, 9.0, 1.25, 1.25, 1.1, "공통\n감쇠기\n16 dB", fc=GR_L, fs=7.8)
    arrow(ax, 8.7, 1.8, 9.0, 1.8)
    box(ax, 13.2, 1.8 - 0.4, 1.4, 0.8, "빔 출력\nB0 / B1", fc=RX_L, ec=RX, fs=8.3, bold=True)
    arrow(ax, 10.25, 1.8, 13.2, 1.8)
    ax.text(11.45, 2.15, "→ 기판 128:1 결합망\n→ 공통 LNA", fontsize=8, color=RX, ha="center")
    ax.text(2.55, 0.12, "G 18 dB / NF 2.0 dB", fontsize=7.8, color=RX, ha="center")
    ax.set_title("BFIC 기반 다채널 송수신 RF Chain 구성 (칩당 4소자 × H/V = 8채널)", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig4a_bfic_rf_chain.png")


# ---------------------------------------------------------------- 4-b 타일 구조
def fig4b():
    fig, ax = canvas(16.5, 7.6, (12.5, 5.8))
    x0, x1 = 0.4, 8.4
    for y, h, fc in [(5.0, 0.55, "#f6f5f1"), (4.4, 0.6, TX_L), (3.8, 0.6, "#f6f5f1")]:
        ax.add_patch(Rectangle((x0, y), x1 - x0, h, fc=fc, ec=INK2, lw=0.9))
    px = np.linspace(x0 + 0.6, x1 - 1.4, 4)
    for x in px:
        ax.add_patch(Rectangle((x, 5.55), 0.8, 0.12, fc=YE, ec=INK, lw=0.6))
    for xb in (px[0] + 0.4, px[2] + 0.4):
        ax.add_patch(Rectangle((xb - 0.2, 3.25), 2.0, 0.55, fc=INK2, ec=INK, lw=0.8))
        ax.text(xb + 0.8, 3.52, "BFIC", color="white", ha="center", va="center", fontsize=8.5, fontweight="bold")
    for x in px:
        for off in (0.28, 0.52):
            line(ax, [x + off, x + off], [3.8, 5.55], c=RX, lw=1.2)
    ax.add_patch(Rectangle((x0, 3.05), x1 - x0, 0.2, fc="#c9c7c0", ec=INK2, lw=0.6))
    ax.add_patch(Rectangle((x0, 2.45), x1 - x0, 0.6, fc="#dcdad4", ec=INK2, lw=0.8))
    for x in np.linspace(x0 + 0.2, x1 - 0.3, 14):
        ax.add_patch(Rectangle((x, 1.45), 0.18, 1.0, fc="#dcdad4", ec=INK2, lw=0.6))
    labs = [(5.62, "방사소자 (H/V 이중 급전 패치)"), (5.27, "안테나 기판"), (4.7, "급전망 층 (스트립라인 · Wilkinson)"),
            (4.1, "제어 · 전원 배선 층"), (3.52, "BFIC (WLCSP 5.2 mm, 배면 실장)"), (3.15, "열 계면 물질 (TIM)"), (2.0, "방열판")]
    for y, t in labs:
        line(ax, [x1, x1 + 0.35], [y, y], c=MUTED, lw=0.7)
        ax.text(x1 + 0.45, y, t, va="center", fontsize=8.3)
    ax.text(px[1] + 1.2, 4.7, "H/V 수직 비아", fontsize=8.3, color=RX, ha="center", va="center", fontweight="bold",
            bbox=dict(fc="white", ec=RX, lw=0.6, pad=2))
    ax.text((x0 + x1) / 2, 0.95, "(a) 타일 단면 적층 구조", ha="center", fontsize=10.5, fontweight="bold")
    gx, gy, s = 12.1, 2.0, 1.05
    cols = [TX_L, AQ_L, YE_L, RX_L]
    for bi, (cx, cy) in enumerate([(0, 0), (2, 0), (0, 2), (2, 2)]):
        ax.add_patch(Rectangle((gx + cx * s - 0.02, gy + cy * s - 0.02), 2 * s, 2 * s, fc=cols[bi], ec=TX, lw=1.3, ls="--"))
        ax.add_patch(Rectangle((gx + (cx + 1) * s - 0.26, gy + (cy + 1) * s - 0.26), 0.52, 0.52, fc=INK2, ec=INK, lw=0.6))
    for i in range(4):
        for j in range(4):
            xx, yy = gx + i * s + 0.3, gy + j * s + 0.3
            ax.add_patch(Rectangle((xx, yy), 0.45, 0.45, fc=YE, ec=INK, lw=0.6))
    ax.annotate("", xy=(gx + 0.525 + s, gy + 4 * s + 0.25), xytext=(gx + 0.525, gy + 4 * s + 0.25),
                arrowprops=dict(arrowstyle="<|-|>", color=INK, lw=0.9, mutation_scale=8))
    ax.text(gx + 0.525 + s / 2, gy + 4 * s + 0.4, "d", ha="center", va="bottom", fontsize=9, fontweight="bold")
    ax.text(gx + 2 * s, gy - 0.35,
            "점선 영역 = BFIC 1개 (2 × 2 소자 × H/V = 8채널)\n회색 = BFIC 패키지 (5.2 × 5.2 mm)\nTx: d = 5.0 mm → 10 × 10 mm,  Rx: d = 7.4 mm → 14.8 × 14.8 mm",
            ha="center", va="top", fontsize=8.4, linespacing=1.4)
    ax.text(gx + 2 * s, 7.3, "(b) 상면 소자 및 BFIC 배치", ha="center", fontsize=10.5, fontweight="bold")
    ax.set_title("타일형 능동 위상배열 모듈 구조", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig4b_tile_structure.png")


# ---------------------------------------------------------------- 4-c 빔 제어 / 2빔 핸드오버
def fig4c():
    fig = plt.figure(figsize=(12.5, 6.6))
    ax = fig.add_axes([0.0, 0.47, 1.0, 0.5]); ax.set_xlim(0, 16); ax.set_ylim(0, 4.6); ax.axis("off")
    box(ax, 0.1, 1.5, 2.2, 1.6, "모뎀 / 제어부\n(위성 궤도 정보 →\n빔 상태 계산)", fc=YE_L, ec=YE, fs=8.5, bold=True)
    xs = [3.6, 6.6, 9.6, 13.2]
    for i, x in enumerate(xs):
        lab = ["BFIC #1", "BFIC #2", "BFIC #3", "BFIC #256"][i]
        box(ax, x, 1.4, 2.3, 1.8, "", fc=TX_L, ec=TX, lw=1.2)
        ax.text(x + 1.15, 2.95, lab, ha="center", va="top", fontsize=9, fontweight="bold", color=TX)
        box(ax, x + 0.2, 1.55, 1.9, 0.85, "빔 테이블\n1,024 entry", fc="white", ec=INK2, fs=7.8)
    ax.text(12.4, 2.3, "···", fontsize=16, ha="center", va="center", color=TX)
    for i in range(3):
        arrow(ax, xs[i] + 2.3, 2.75, xs[i + 1] if i < 2 else 11.95, 2.75, c=TX, lw=1)
    arrow(ax, 12.85, 2.75, xs[3], 2.75, c=TX, lw=1)
    arrow(ax, 2.3, 2.75, xs[0], 2.75, c=TX, lw=1.2)
    ax.text(2.95, 2.9, "SPI 체인\n100 MHz", fontsize=8, color=TX, ha="center", va="bottom")
    line(ax, [1.2, 1.2, 15.6], [1.5, 0.6, 0.6], c=RX, lw=1.4)
    for x in xs:
        arrow(ax, x + 1.15, 0.6, x + 1.15, 1.4, c=RX, lw=1.1)
    ax.text(8.4, 0.15, "Beam_UPDATE 동기 신호 → 전 칩 동시 적용 (사전 저장 빔 상태)", ha="center", fontsize=9, color=RX, fontweight="bold")
    ax.text(8.4, 4.25, "(a) 빔 제어 구조 :  빔 갱신 ≤ 0.4 s 주기,  SPI 직접 기입 시 전 칩 약 0.3 ms", ha="center",
            fontsize=10.5, fontweight="bold")

    a2 = fig.add_axes([0.1, 0.06, 0.86, 0.33])
    rowsy = {"Rx 빔 0": 2, "Rx 빔 1": 1, "Tx 빔": 0}
    a2.barh(2, 6.0, left=0, height=0.5, color=RX, label="위성 A 추적")
    a2.barh(1, 2.0, left=4.0, height=0.5, color=AQ, label="위성 B 사전 형성 · 동기 획득")
    a2.barh(1, 4.0, left=6.0, height=0.5, color=TX, label="위성 B 추적")
    a2.barh(2, 4.0, left=6.0, height=0.5, color=GR_L, ec=MUTED, hatch="///", lw=0.5, label="해제 / 차기 위성 대기")
    a2.barh(0, 6.0, left=0, height=0.5, color=RX); a2.barh(0, 4.0, left=6.0, height=0.5, color=TX)
    a2.axvline(6.0, color=INK, lw=1.2, ls="--")
    a2.text(6.08, 2.45, "핸드오버 시점 (빔 전환 수 ms 이내)", fontsize=8.8, va="bottom", fontweight="bold")
    a2.set_yticks(list(rowsy.values()), list(rowsy.keys()))
    a2.set_xticks([]); a2.set_xlim(0, 10); a2.set_ylim(-0.5, 3.0)
    a2.set_xlabel("시간"); a2.grid(False)
    a2.legend(frameon=False, fontsize=8.3, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    a2.set_title("(b) 수신 2빔을 이용한 무단절 핸드오버 (make-before-break)", fontsize=10.5, fontweight="bold")
    save(fig, "fig4c_beam_control_handover.png")


# ---------------------------------------------------------------- 5 측정 구성
def fig5():
    fig, ax = canvas(16, 12.4, (12.5, 9.6))
    rows = [
        (10.0, "(a) S-파라미터 측정", [("VNA\nPort 1", "white"), ("평가보드 (EVB)\nDUT", TX_L), ("VNA\nPort 2", "white")],
         "이득 · 평탄도 · VSWR\n위상/진폭 상태 스윕 → RMS 오차\n채널 간 격리도"),
        (6.9, "(b) 출력 특성 측정", [("신호\n발생기", "white"), ("구동\n증폭기", "white"), ("결합기 +\n입력 전력계", "white"),
                                 ("평가보드 (EVB)\nDUT (Tx)", TX_L), ("감쇠기", "white"), ("전력계 /\n스펙트럼 분석기", "white")],
         "입력 전력 스윕\n→ OP1dB, Psat\n이득 압축 특성"),
        (3.8, "(c) 변조 신호 EVM 측정", [("벡터 신호발생기\n16APSK 2/3\n20 Msps", "white"), ("평가보드 (EVB)\nDUT (Tx)", TX_L),
                                      ("감쇠기", "white"), ("벡터 신호분석기\n(VSA)", "white")],
         "출력 레벨별 EVM\n기준 +2.8 dBm\nUPC 최대 +8.8 dBm"),
        (0.8, "(d) 잡음지수 측정", [("잡음원\n(ENR 보정)", "white"), ("평가보드 (EVB)\nDUT (Rx)", RX_L), ("NF 분석기", "white")],
         "Y-factor 방식\n→ NF, 이득\n(또는 VNA cold-source)"),
    ]
    h = 1.5
    for y, title, blocks, meas in rows:
        ax.text(0.1, y + h + 0.35, title, fontsize=10.5, fontweight="bold")
        n = len(blocks)
        w = 1.55 if n > 4 else (2.1 if n == 4 else 2.3)
        gap = (11.4 - n * w) / (n - 1)
        prev = None
        for i, (t, fc) in enumerate(blocks):
            x = 0.2 + i * (w + gap)
            dut = "DUT" in t
            box(ax, x, y, w, h, t, fc=fc, ec=TX if fc == TX_L else (RX if fc == RX_L else INK2),
                lw=1.5 if dut else 1.0, fs=8.5, bold=dut)
            if prev is not None:
                arrow(ax, prev, y + h / 2, x, y + h / 2)
            prev = x + w
            if dut:
                box(ax, x + w / 2 - 0.75, y + h + 0.15, 1.5, 0.45, "제어 PC (SPI)", fc=YE_L, ec=YE, fs=7.8)
        box(ax, 12.2, y, 3.7, h, meas, fc=GR_L, ec=GR_L, fs=8.6)
        line(ax, [prev, 12.2], [y + h / 2, y + h / 2], c=MUTED, lw=0.8, ls=":")
    ax.text(0.1, 0.15, "※ 측정 주파수: 데이터시트 조건 (Tx 29.25 GHz, Rx 19.45 GHz, 25 °C) 및 대역 양 끝.  평가보드 손실은 디임베딩",
            fontsize=8.3, color=MUTED)
    ax.set_title("단일 채널 특성 측정 구성", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig5_test_setup.png")


# ---------------------------------------------------------------- 6 종합 흐름
def fig6():
    fig, ax = canvas(16.1, 6.8, (12.5, 5.3))
    items = [
        ("① 링크 버짓", "LEO 550 km\n최저 앙각 25°\n16APSK 2/3\n20 Msps", TX_L, TX),
        ("② 시스템 요구치", "EIRP 30 dBW\nG/T 0.4 dB/K\n시스템 NF ≤ 3.75 dB", TX_L, TX),
        ("③ 채널 요구치", "Tx OP1dB ≥ +9 dBm\nTx EVM ≤ 5 %\nRx G ≥ 15 dB\nRx NF ≤ 3.1 dB", TX_L, TX),
        ("④ 다채널 구조", "Tx 1,024소자 / BFIC 256\nRx 512소자 / BFIC 128\nH/V 원형편파 합성\n공통 LNA · 구동증폭기", AQ_L, AQ),
        ("⑤ 단일 채널 검증", "이득 · OP1dB · EVM\nNF · RMS 오차\nVSWR · 격리도", YE_L, YE),
        ("⑥ 차년도", "타일 모듈 제작\n채널 교정 · 열 검증\n변조 EVM · 방사 패턴", "white", MUTED),
    ]
    w, gap, y, h = 2.35, 0.3, 2.0, 3.1
    for i, (t, body, fc, ec) in enumerate(items):
        x = 0.1 + i * (w + gap)
        box(ax, x, y, w, h, "", fc=fc, ec=ec, lw=1.5, ls="--" if i == 5 else "-")
        ax.text(x + w / 2, y + h - 0.32, t, ha="center", va="top", fontsize=10, fontweight="bold")
        ax.text(x + w / 2, y + h / 2 - 0.3, body, ha="center", va="center", fontsize=8.5, linespacing=1.45)
        if i:
            arrow(ax, x - gap, y + h / 2, x, y + h / 2)
    groups = [(0, 2, "링크 버짓 설계", TX), (3, 3, "모듈 아키텍처", AQ), (4, 4, "단일 채널 연구", "#b07800")]
    for a, b, t, c in groups:
        xa, xb = 0.1 + a * (w + gap), 0.1 + b * (w + gap) + w
        line(ax, [xa, xa, xb, xb], [5.35, 5.55, 5.55, 5.35], c=c, lw=1.3)
        ax.text((xa + xb) / 2, 5.7, t, ha="center", fontsize=10, fontweight="bold", color=c)
    x5 = 0.1 + 4 * (w + gap) + w / 2
    x3 = 0.1 + 2 * (w + gap) + w / 2
    ax.annotate("", xy=(x3, y - 0.05), xytext=(x5, y - 0.05),
                arrowprops=dict(arrowstyle="-|>", color=RX, lw=1.3, mutation_scale=11, connectionstyle="arc3,rad=-0.35"))
    ax.text((x3 + x5) / 2, 0.55, "측정값 반영 → 버짓 재검증", ha="center", fontsize=9.5, color=RX, fontweight="bold")
    ax.set_title("모듈 아키텍처 / 버짓 설계 및 단일 채널 연구 흐름", fontsize=13, fontweight="bold", pad=4)
    save(fig, "fig6_summary_flow.png")


if __name__ == "__main__":
    for f in (fig1a, fig1b, fig1c, fig1d, fig2a, fig2b, fig2c, fig3a, fig3b, fig4a, fig4b, fig4c, fig5, fig6):
        f()
