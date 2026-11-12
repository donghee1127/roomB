# -*- coding: utf-8 -*-
"""
연차보고서 그림 생성 스크립트
 - 송수신 모듈 구조 설계 및 기본 성능 기준 수립
 - BFIC: Sivers Stampede2731 (Tx, 27.5-31 GHz, 8ch = 4ch x 2pol)
         Sivers Blueway1721  (Rx, 17.7-21.2 GHz, 8ch, RF-SOI)

※ [가정] 표시 값은 데이터시트/과제 목표값으로 교체 필요 (아래 PARAMETERS 블록만 수정)
실행: python make_figures.py  ->  같은 폴더에 fig01~fig10 PNG 생성
"""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch

OUT = os.path.dirname(os.path.abspath(__file__))
plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "font.size": 10, "axes.edgecolor": "#8a8986", "axes.labelcolor": "#0b0b0b",
    "xtick.color": "#52514e", "ytick.color": "#52514e",
    "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False,
    "savefig.dpi": 220, "savefig.bbox": "tight", "figure.facecolor": "white",
})

# ---------------- palette ----------------
TX, RX, AQ, YE, VI = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#8a8986"
TX_L, RX_L, GR_L, AQ_L, YE_L = "#e3eefb", "#fde9e0", "#f1f0ec", "#ddf3ea", "#fdf1d6"

# ================= PARAMETERS =================
k_dB = -228.6                       # Boltzmann [dBW/K/Hz]
# --- LEO 궤도 기하 ---
R_E = 6371.0                        # 지구 반경 [km]
ALT_KM = 550.0                      # LEO 궤도 고도 [km] [가정]
EL_MIN = 25.0                       # 최소 운용 앙각 [deg] [가정]
_el = np.radians(EL_MIN)
SLANT_KM = np.sqrt((R_E + ALT_KM) ** 2 - (R_E * np.cos(_el)) ** 2) - R_E * np.sin(_el)  # 최소 앙각 경사거리 (최악)
# --- 상향 링크 (단말 Tx -> 위성) ---
UL = dict(f=29.75, sat_GT=8.0, atm=3.0, pol=0.5, Rs=50e6, EsN0=5.0, margin=3.0)
# --- 하향 링크 (위성 -> 단말 Rx) ---
DL = dict(f=19.70, sat_EIRP=40.0, atm=2.0, pol=0.5, Rs=100e6, EsN0=5.0, margin=3.0)
# --- 배열/소자 ---
GE = 5.0          # 소자 이득 [dBi] [가정]
L_SCAN = 3.0      # 스캔/기타 손실 [dB] [가정] - LEO 추적 시 저앙각 광각 스캔(±65°) 고려
TX_OP1DB = 14.0   # Stampede2731 채널당 OP1dB [dBm] [가정 - 데이터시트 값으로 교체]
TX_BO = 3.0       # 동작 back-off [dB] [가정]
RX_NF = 2.5       # Blueway1721 채널 NF (급전손실 포함) [dB] [가정]
T_ANT = 50.0      # 안테나 잡음온도 [K] [가정]
ELEM_PER_IC = 4   # 이중편파 소자 4개 / BFIC (8ch)
# ================================================


def fspl(f_ghz, d_km):
    return 92.45 + 20 * np.log10(f_ghz) + 20 * np.log10(d_km)


def save(fig, name):
    fig.savefig(os.path.join(OUT, name))
    plt.close(fig)
    print("saved", name)


# ---------- diagram helpers ----------
def box(ax, x, y, w, h, text, fc="white", ec=INK2, fs=9, bold=False, lw=1.0, tc=INK, ls="-"):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.12",
                       fc=fc, ec=ec, lw=lw, ls=ls)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs,
            color=tc, fontweight="bold" if bold else "normal", linespacing=1.35)
    return p


def arrow(ax, x1, y1, x2, y2, c=INK2, lw=1.2, ls="-", both=False):
    ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                arrowprops=dict(arrowstyle="<|-|>" if both else "-|>", color=c, lw=lw,
                                ls=ls, shrinkA=0, shrinkB=0, mutation_scale=11))


def canvas(w, h, figsize):
    fig, ax = plt.subplots(figsize=figsize)
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off"); ax.set_aspect("equal")
    return fig, ax


# ============ link budget computation ============
def uplink():
    p = UL
    L = fspl(p["f"], SLANT_KM)
    cn0 = p["EsN0"] + 10 * np.log10(p["Rs"]) + p["margin"]
    eirp = cn0 + L + p["atm"] + p["pol"] - p["sat_GT"] + k_dB
    return L, cn0, eirp


def downlink():
    p = DL
    L = fspl(p["f"], SLANT_KM)
    cn0 = p["EsN0"] + 10 * np.log10(p["Rs"]) + p["margin"]
    gt = cn0 - p["sat_EIRP"] + L + p["atm"] + p["pol"] + k_dB
    return L, cn0, gt


def tx_eirp(N, pch):     # dBW
    return pch + 20 * np.log10(N) + GE - L_SCAN - 30


def rx_gt(N, nf):
    G = 10 * np.log10(N) + GE - L_SCAN
    Tsys = T_ANT + 290 * (10 ** (nf / 10) - 1)
    return G - 10 * np.log10(Tsys)


# ---------------------------------------------------------------- Fig 1
def fig01():
    fig, ax = canvas(21.2, 9.6, (13.8, 6.3))
    cols = [
        ("① 시스템/서비스 요구", GR_L, [f"LEO 궤도: {ALT_KM:.0f} km, 앙각 ≥ {EL_MIN:.0f}°",
                                   "Tx 27.5–31 / Rx 17.7–21.2 GHz",
                                   "데이터율 · MODCOD (Es/N0)",
                                   "위성 추적 · 도플러 · 강우 마진"]),
        ("② 위성 링크 버짓", YE_L, ["상향: 위성 G/T, FSPL, 손실",
                                 "→ 단말 요구 EIRP [dBW]",
                                 "하향: 위성 EIRP, FSPL, 손실",
                                 "→ 단말 요구 G/T [dB/K]"]),
        ("③ 배열/모듈 요구", AQ_L, ["소자 수 N, 소자이득 Ge",
                                 "광각 스캔 손실 · 분배/결합 손실",
                                 "EIRP = Pch + 20logN + Ge - L",
                                 "G/T = G - 10log(Tsys)"]),
        ("④ 채널 RF 성능지표", TX_L, ["Tx: Pout/ch, OP1dB, Gain",
                                   "Rx: NF, Gain, IP1dB",
                                   "위상/이득 제어 분해능",
                                   "채널 간 편차 · 소모전력"]),
        ("⑤ BFIC · RF Chain 구성", RX_L, ["Tx: Stampede2731 (8ch)",
                                       "Rx: Blueway1721 (8ch)",
                                       "1:M 분배 / M:1 결합망",
                                       "U/D 컨버터 · LO · 제어(SPI)"]),
    ]
    w, gap, x0 = 3.8, 0.45, 0.3
    for i, (title, fc, items) in enumerate(cols):
        x = x0 + i * (w + gap)
        box(ax, x, 7.6, w, 1.1, title, fc=fc, fs=10.5, bold=True)
        box(ax, x, 2.6, w, 4.6, "", fc="white", ec=MUTED)
        for j, t in enumerate(items):
            ax.text(x + 0.15, 6.65 - j * 1.05, "• " + t, fontsize=8.2, va="center", color=INK)
        if i < 4:
            arrow(ax, x + w + 0.05, 4.9, x + w + gap - 0.05, 4.9, c=INK, lw=1.6)
    # verification loop
    box(ax, 6.5, 0.35, 7.0, 1.2, "⑥ 단일 채널 기초 검증\n(Gain · Pout/P1dB · NF 측정 → 버짓 갱신)",
        fc="#f6f5f2", ec=VI, fs=9.5, bold=True, tc=VI)
    xr = x0 + 4 * (w + gap) + w / 2
    arrow(ax, xr, 2.55, xr, 0.95, c=VI); arrow(ax, xr, 0.95, 13.55, 0.95, c=VI)
    xl = x0 + 1 * (w + gap) + w / 2
    ax.plot([6.45, xl], [0.95, 0.95], color=VI, lw=1.2)
    arrow(ax, xl, 0.95, xl, 2.55, c=VI)
    ax.text(xl + 0.15, 1.75, "버짓 재검토(Feedback)", fontsize=8.5, color=VI)
    ax.set_title("위성 링크 버짓 기반 송수신 모듈 성능 요구사항 도출 흐름", fontsize=13, fontweight="bold", pad=6)
    save(fig, "fig01_requirement_flow.png")


# ---------------------------------------------------------------- Fig 2
def fig02():
    Lu, cn0u, eirp = uplink()
    Ld, cn0d, gt = downlink()
    rows = [
        ("주파수", f"{UL['f']:.2f} GHz", f"{DL['f']:.2f} GHz"),
        ("궤도 / 최소 앙각", f"LEO {ALT_KM:.0f} km / {EL_MIN:.0f}°", f"LEO {ALT_KM:.0f} km / {EL_MIN:.0f}°"),
        ("최대 경사 거리", f"{SLANT_KM:,.0f} km", f"{SLANT_KM:,.0f} km"),
        ("자유공간 손실 (FSPL)", f"{Lu:.1f} dB", f"{Ld:.1f} dB"),
        ("대기/강우 손실", f"{UL['atm']:.1f} dB", f"{DL['atm']:.1f} dB"),
        ("편파/지향 손실", f"{UL['pol']:.1f} dB", f"{DL['pol']:.1f} dB"),
        ("위성 G/T  |  위성 EIRP", f"{UL['sat_GT']:.1f} dB/K", f"{DL['sat_EIRP']:.1f} dBW"),
        ("심볼율 Rs", f"{UL['Rs']/1e6:g} Msps", f"{DL['Rs']/1e6:g} Msps"),
        ("요구 Es/N0", f"{UL['EsN0']:.1f} dB", f"{DL['EsN0']:.1f} dB"),
        ("구현/링크 마진", f"{UL['margin']:.1f} dB", f"{DL['margin']:.1f} dB"),
        ("요구 C/N0", f"{cn0u:.1f} dBHz", f"{cn0d:.1f} dBHz"),
        ("볼츠만 상수 k", "-228.6 dBW/K/Hz", "-228.6 dBW/K/Hz"),
        ("단말 요구 성능", f"EIRP ≥ {eirp:.1f} dBW", f"G/T ≥ {gt:.1f} dB/K"),
    ]
    fig, ax = plt.subplots(figsize=(9, 5.4)); ax.axis("off")
    t = ax.table(cellText=[r[1:] for r in rows], rowLabels=[r[0] for r in rows],
                 colLabels=["상향 링크 (Tx, Stampede2731)", "하향 링크 (Rx, Blueway1721)"],
                 cellLoc="center", rowLoc="left", loc="center", colWidths=[0.36, 0.36])
    t.auto_set_font_size(False); t.set_fontsize(10); t.scale(1, 1.55)
    for (r, c), cell in t.get_celld().items():
        cell.set_edgecolor("#d6d5d0")
        if r == 0:
            cell.set_facecolor(TX_L if c == 0 else RX_L); cell.set_text_props(fontweight="bold")
        if r == len(rows):
            cell.set_facecolor(YE_L); cell.set_text_props(fontweight="bold")
    ax.set_title("위성 링크 버짓 및 단말 요구 성능 (C/N0 = EIRP - L + G/T - k)", fontsize=12.5, fontweight="bold")
    fig.text(0.5, 0.02, "※ 최소 앙각(최대 경사거리) 기준 최악조건. 궤도 고도, 위성 G/T·EIRP, 심볼율, Es/N0 등은 [가정] 값이며 대상 LEO 위성/서비스 사양으로 교체", ha="center",
             fontsize=8.5, color=INK2)
    save(fig, "fig02_link_budget_table.png")


# ---------------------------------------------------------------- Fig 3
def fig03():
    fig, axs = plt.subplots(1, 3, figsize=(14, 4.3))
    G, op1, psat = 20.0, TX_OP1DB, TX_OP1DB + 2.5
    pin = np.linspace(-30, 5, 400)
    lin = pin + G
    # Rapp model
    vin = 10 ** (lin / 20); vsat = 10 ** (psat / 20); p = 2.2
    pout = 20 * np.log10(vin / (1 + (vin / vsat) ** (2 * p)) ** (1 / (2 * p)))
    gain = pout - pin
    i1 = np.argmin(np.abs(gain - (G - 1)))
    ax = axs[0]
    ax.plot(pin, lin, ls="--", color=MUTED, lw=1.2, label="선형 외삽")
    ax.plot(pin, pout, color=TX, lw=2, label="Pout")
    ax.plot(pin[i1], pout[i1], "o", color=TX, ms=8, mec="white", mew=2)
    ax.annotate(f"OP1dB ≒ {pout[i1]:.1f} dBm", (pin[i1], pout[i1]), (pin[i1] - 17, pout[i1] + 3),
                fontsize=9, arrowprops=dict(arrowstyle="-", color=INK2))
    op = pout[i1] - TX_BO
    ax.axhline(op, color=AQ, lw=1.2, ls=":")
    ax.text(-29, op + 0.6, f"동작점 (back-off {TX_BO:g} dB)", fontsize=8.5, color=INK2)
    ax.set_ylim(-12, 22); ax.set_xlabel("입력 전력 Pin [dBm]"); ax.set_ylabel("출력 전력 Pout [dBm]")
    ax.set_title("(a) 채널 출력 특성과 P1dB", fontweight="bold"); ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    ax = axs[1]
    ax.plot(pin, gain, color=TX, lw=2)
    ax.axhline(G, color=MUTED, ls="--", lw=1); ax.axhline(G - 1, color=MUTED, ls=":", lw=1)
    ax.annotate("", (pin[i1] + 1, G - 1), (pin[i1] + 1, G), arrowprops=dict(arrowstyle="<|-|>", color=INK2))
    ax.text(pin[i1] + 1.8, G - 0.6, "1 dB", fontsize=9)
    ax.plot(pin[i1], gain[i1], "o", color=TX, ms=8, mec="white", mew=2)
    ax.text(pin[i1] - 1, G - 2.2, f"IP1dB ≒ {pin[i1]:.1f} dBm", fontsize=9, ha="right")
    ax.set_ylim(G - 6, G + 1.5); ax.set_xlabel("입력 전력 Pin [dBm]"); ax.set_ylabel("이득 [dB]")
    ax.set_title("(b) 이득 압축 (Gain compression)", fontweight="bold")
    # NF cascade
    ax = axs[2]
    stages = [("급전손실", -0.5, 0.5), ("LNA", 18, 2.0), ("위상변위기", -7, 7), ("VGA", 10, 6), ("후단", -10, 10)]
    f_tot, g_acc, contrib, labels = 0, 1, [], []
    for i, (n, g, nf) in enumerate(stages):
        F = 10 ** (nf / 10)
        c = (F - 1) / g_acc if i else F
        contrib.append(c); labels.append(n); g_acc *= 10 ** (g / 10)
    tot = sum(contrib)
    shares = np.array(contrib) / tot * 100
    ax.barh(labels[::-1], shares[::-1], color=RX, height=0.55)
    for y, s in enumerate(shares[::-1]):
        ax.text(s + 1, y, f"{s:.1f}%", va="center", fontsize=8.5)
    ax.set_xlim(0, 100); ax.set_xlabel("전체 잡음인자 F 기여도 [%]")
    ax.set_title(f"(c) Friis 식 NF 기여도 (총 NF ≒ {10*np.log10(tot):.2f} dB)", fontweight="bold")
    ax.grid(axis="y", visible=False)
    fig.suptitle("RF 성능지표 정의: P1dB · Gain · NF  (예시 파라미터, [가정])", fontsize=12.5, fontweight="bold", y=1.03)
    fig.tight_layout()
    save(fig, "fig03_rf_metrics.png")


# ---------------------------------------------------------------- Fig 4
def fig04():
    _, _, eirp_req = uplink(); _, _, gt_req = downlink()
    N = np.logspace(np.log10(16), np.log10(4096), 300)
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.6))
    ax = axs[0]
    pchs = [(TX_OP1DB - TX_BO - 3, VI), (TX_OP1DB - TX_BO, TX), (TX_OP1DB - TX_BO + 3, AQ)]
    for pc, c in pchs:
        ax.plot(N, tx_eirp(N, pc), color=c, lw=2, label=f"Pch = {pc:g} dBm")
    ax.axhline(eirp_req, color=RX, lw=1.4, ls="--")
    ax.text(18, eirp_req + 0.8, f"요구 EIRP {eirp_req:.1f} dBW", color=INK, fontsize=9)
    ax.set_xscale("log"); ax.set_xticks([16, 64, 256, 1024, 4096]); ax.set_xticklabels(["16", "64", "256", "1024", "4096"])
    ax.set_xlabel("Tx 배열 소자 수 N"); ax.set_ylabel("EIRP [dBW]")
    ax.set_title("(a) 송신: EIRP = Pch + 20·log N + Ge - L", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    ax = axs[1]
    for nf, c in [(RX_NF - 1, AQ), (RX_NF, RX), (RX_NF + 1, VI)]:
        ax.plot(N, rx_gt(N, nf), color=c, lw=2, label=f"NF = {nf:g} dB")
    ax.axhline(gt_req, color=TX, lw=1.4, ls="--")
    ax.text(18, gt_req + 0.6, f"요구 G/T {gt_req:.1f} dB/K", color=INK, fontsize=9)
    ax.set_xscale("log"); ax.set_xticks([16, 64, 256, 1024, 4096]); ax.set_xticklabels(["16", "64", "256", "1024", "4096"])
    ax.set_xlabel("Rx 배열 소자 수 N"); ax.set_ylabel("G/T [dB/K]")
    ax.set_title(f"(b) 수신: G/T = 10·log N + Ge - L - 10·log Tsys (Ta={T_ANT:g} K)", fontweight="bold")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.suptitle("시스템 요구 EIRP / G/T 기준 배열 규모 및 채널 성능 트레이드오프", fontsize=12.5, fontweight="bold", y=1.02)
    fig.tight_layout()
    save(fig, "fig04_eirp_gt_vs_N.png")


# ---------------------------------------------------------------- Fig 5
def fig05():
    # (a) 분배 구조 트리 + (b) 레벨 다이어그램
    fig = plt.figure(figsize=(14, 5.6))
    ax = fig.add_axes([0.0, 0.0, 0.55, 1.0]); ax.set_xlim(0, 14); ax.set_ylim(0, 10); ax.axis("off")
    box(ax, 0.2, 4.4, 1.7, 1.2, "U/C 출력\n(RF in)", fc=GR_L, fs=8.5)
    box(ax, 2.4, 4.4, 1.5, 1.2, "구동\n증폭기", fc=TX_L, fs=8.5)
    arrow(ax, 1.9, 5.0, 2.4, 5.0); arrow(ax, 3.9, 5.0, 4.4, 5.0)
    # binary tree 1:16 drawn as 1:2 -> 1:4 -> ... showing 4 levels compressed
    ys_lvl = [[5.0], [7.4, 2.6], [8.6, 6.2, 3.8, 1.4]]
    xs = [4.6, 6.2, 7.8]
    for li in range(2):
        for j, y in enumerate(ys_lvl[li]):
            ax.add_patch(plt.Circle((xs[li], y), 0.22, fc="white", ec=TX, lw=1.4))
            for yc in ys_lvl[li + 1][2 * j:2 * j + 2]:
                ax.plot([xs[li] + 0.22, xs[li + 1] - 0.22], [y, yc], color=TX, lw=1.2)
    for y in ys_lvl[2]:
        ax.text(7.95, y, "···", fontsize=12, va="center", color=TX)
        box(ax, 8.6, y - 0.5, 2.3, 1.0, "Stampede2731\n(1:8 내부 분배)", fc=TX_L, ec=TX, fs=7.5)
        for k in range(4):
            yy = y - 0.36 + k * 0.24
            ax.plot([10.9, 11.9], [yy, yy], color=TX, lw=0.8)
            ax.add_patch(plt.Rectangle((11.9, yy - 0.08), 0.18, 0.16, fc=TX, ec="none"))
    ax.text(5.4, 9.6, "Wilkinson 1:M 분배망\n(log₂M 단, 단당 3 dB + 삽입손실)", ha="center", fontsize=8.5, color=INK2)
    ax.text(12.1, 9.6, "이중편파\n소자 4개/IC", ha="center", fontsize=8.5, color=INK2)
    ax.text(7, 0.2, "(a) BFIC 기반 송신 전력 분배 구조 (Rx는 역방향 M:1 결합)", ha="center", fontsize=10, fontweight="bold")
    # (b) level diagram
    ax2 = fig.add_axes([0.62, 0.14, 0.37, 0.76])
    M, L_stage = 16, 0.8
    stages = [("U/C 출력", 0), ("구동증폭", 12), (f"1:{M} 분배\n({int(np.log2(M))}단)", -(10 * np.log10(M) + np.log2(M) * L_stage)),
              ("BFIC\n1:8 분배", -(10 * np.log10(8) + 1)), ("위상변위", -7), ("VGA", 11), ("DA", 12), ("PA", 10), ("출력/급전", -1)]
    lvl = np.cumsum([s[1] for s in stages])
    x = np.arange(len(stages))
    ax2.step(x, lvl, where="mid", color=TX, lw=2)
    ax2.plot(x, lvl, "o", color=TX, ms=7, mec="white", mew=1.5)
    for xi, v in zip(x, lvl):
        ax2.text(xi, v + 1.3, f"{v:.1f}", ha="center", fontsize=8)
    ax2.axhline(TX_OP1DB, color=RX, ls="--", lw=1.2)
    ax2.text(2.6, TX_OP1DB + 1, f"채널 OP1dB {TX_OP1DB:g} dBm [가정]", fontsize=8.5)
    ax2.set_xticks(x); ax2.set_xticklabels([s[0] for s in stages], fontsize=8)
    ax2.set_ylabel("신호 레벨 [dBm]"); ax2.set_ylim(-25, 22)
    ax2.set_title(f"(b) 송신 경로 전력 레벨 다이어그램 (M={M}, 채널 기준)", fontsize=10, fontweight="bold")
    save(fig, "fig05_power_distribution.png")


# ---------------------------------------------------------------- Fig 6
def fig06():
    fig, ax = canvas(26, 15, (15, 8.7))
    # ---- Tx (top)
    ax.text(6.4, 14.3, "송신부 (Tx, 27.5–31 GHz)", fontsize=11.5, fontweight="bold", color=TX)
    box(ax, 0.3, 11.0, 2.4, 1.6, "모뎀\nIF/L-band", fc=GR_L, fs=9)
    box(ax, 3.4, 11.0, 2.6, 1.6, "상향 변환기\n(Mixer+Filter)", fc=TX_L, fs=9)
    box(ax, 6.7, 11.0, 2.2, 1.6, "구동 증폭기\n/ BPF", fc=TX_L, fs=9)
    box(ax, 9.6, 10.2, 2.4, 3.2, "1:M\nWilkinson\n분배망", fc="white", ec=TX, fs=9)
    arrow(ax, 2.7, 11.8, 3.4, 11.8); arrow(ax, 6.0, 11.8, 6.7, 11.8); arrow(ax, 8.9, 11.8, 9.6, 11.8)
    for i, y in enumerate([12.8, 10.3]):
        box(ax, 13.0, y - 0.1, 5.4, 1.5, "", fc=TX_L, ec=TX)
        ax.text(15.7, y + 1.15, f"Stampede2731 #{['1','M'][i]}  (8ch: 4H + 4V)", ha="center", fontsize=8.5, fontweight="bold")
        for k, t in enumerate(["PS 6bit", "VGA", "PA"]):
            box(ax, 13.3 + k * 1.65, y + 0.05, 1.45, 0.75, t, fc="white", ec=TX, fs=7.5)
        arrow(ax, 12.0, y + 0.45, 13.0, y + 0.45, c=TX)
        for kk in range(4):
            yy = y + 0.05 + kk * 0.3
            ax.plot([18.4, 20.3], [yy, yy], color=TX, lw=0.9)
    ax.plot([15.7]*3, [12.05, 12.25, 12.45], "o", color=TX, ms=2.5)
    # ---- Rx (bottom)
    ax.text(6.4, 7.5, "수신부 (Rx, 17.7–21.2 GHz)", fontsize=11.5, fontweight="bold", color=RX)
    box(ax, 0.3, 4.3, 2.4, 1.6, "모뎀\nIF/L-band", fc=GR_L, fs=9)
    box(ax, 3.4, 4.3, 2.6, 1.6, "하향 변환기\n(Mixer+Filter)", fc=RX_L, fs=9)
    box(ax, 6.7, 4.3, 2.2, 1.6, "LNA\n/ BPF", fc=RX_L, fs=9)
    box(ax, 9.6, 3.5, 2.4, 3.2, "M:1\nWilkinson\n결합망", fc="white", ec=RX, fs=9)
    arrow(ax, 3.4, 5.1, 2.7, 5.1); arrow(ax, 6.7, 5.1, 6.0, 5.1); arrow(ax, 9.6, 5.1, 8.9, 5.1)
    for i, y in enumerate([6.1, 3.6]):
        box(ax, 13.0, y - 0.1, 5.4, 1.5, "", fc=RX_L, ec=RX)
        ax.text(15.7, y + 1.15, f"Blueway1721 #{['1','M'][i]}  (8ch)", ha="center", fontsize=8.5, fontweight="bold")
        for k, t in enumerate(["VGA", "PS", "LNA"]):
            box(ax, 13.3 + k * 1.65, y + 0.05, 1.45, 0.75, t, fc="white", ec=RX, fs=7.5)
        arrow(ax, 13.0, y + 0.45, 12.0, y + 0.45, c=RX)
        for kk in range(4):
            yy = y + 0.05 + kk * 0.3
            ax.plot([18.4, 20.3], [yy, yy], color=RX, lw=0.9)
    ax.plot([15.7]*3, [5.35, 5.55, 5.75], "o", color=RX, ms=2.5)
    # antennas
    for y0, c, lab in [(10.2, TX, "Tx 배열 안테나\n(이중편파 패치,\nN = 4·M 소자)"), (3.5, RX, "Rx 배열 안테나\n(이중편파 패치,\nN = 4·M 소자)")]:
        box(ax, 20.3, y0, 2.9, 3.2, "", fc="white", ec=c)
        for r in range(4):
            for q in range(4):
                ax.add_patch(plt.Rectangle((20.6 + q * 0.62, y0 + 0.3 + r * 0.72), 0.4, 0.4, fc=c, ec="none", alpha=0.85))
        ax.text(24.7, y0 + 1.6, lab, ha="center", va="center", fontsize=8.5)
    # LO + control
    box(ax, 3.4, 8.0, 2.6, 1.3, "LO 합성기\n(PLL)", fc=YE_L, fs=9)
    arrow(ax, 4.7, 9.3, 4.7, 11.0, c="#b07a00"); arrow(ax, 4.7, 8.0, 4.7, 5.9, c="#b07a00")
    box(ax, 9.6, 8.0, 10.3, 1.3, "제어부 (MCU/FPGA): SPI · 빔 테이블 로드 · TX/RX 전환 · 온도/전류 모니터링", fc=AQ_L, fs=8.8)
    arrow(ax, 15.7, 9.3, 15.7, 10.3, c=AQ); arrow(ax, 15.7, 8.0, 15.7, 7.6, c=AQ)
    box(ax, 0.3, 0.4, 25.4, 1.6, "전원부: BFIC 공급전압 · PA/LNA 바이어스 · 시퀀싱    |    열관리: 히트싱크/히트스프레더 (Tx 채널당 소모전력 기준 설계)",
        fc="#f6f5f2", ec=MUTED, fs=9)
    ax.set_title("BFIC 기반 다채널 송수신 모듈 구조 (Sivers Stampede2731 / Blueway1721)", fontsize=13, fontweight="bold")
    save(fig, "fig06_module_architecture.png")


# ---------------------------------------------------------------- Fig 7
def fig07():
    fig, ax = canvas(24, 10, (14, 5.9))
    # Tx single channel
    ax.text(0.3, 9.3, "(a) 송신 단일 채널 RF Chain  —  Stampede2731 1 채널", fontsize=11, fontweight="bold", color=TX)
    chain = [("RF 입력\n(BFIC 공통)", GR_L), ("1:8\n분배기", "white"), ("위상변위기\n6-bit, 360°", TX_L),
             ("VGA\n(이득 제어)", TX_L), ("구동증폭\n(DA)", TX_L), ("전력증폭\n(PA)", TX_L), ("급전선\n/안테나", GR_L)]
    w, gap = 2.6, 0.75
    for i, (t, fc) in enumerate(chain):
        x = 0.3 + i * (w + gap)
        box(ax, x, 6.3, w, 1.8, t, fc=fc, ec=TX, fs=9)
        if i: arrow(ax, x - gap, 7.2, x, 7.2, c=TX)
    ax.text(12, 5.7, "측정 지표: 소신호 Gain · Gain 평탄도 · OP1dB/Psat · 위상/이득 제어 정확도 · 소모전류", ha="center",
            fontsize=9, color=INK2)
    # Rx
    ax.text(0.3, 4.5, "(b) 수신 단일 채널 RF Chain  —  Blueway1721 1 채널", fontsize=11, fontweight="bold", color=RX)
    chain = [("안테나\n/급전선", GR_L), ("LNA", RX_L), ("위상변위기", RX_L), ("VGA\n(이득 제어)", RX_L),
             ("8:1\n결합기", "white"), ("RF 출력\n(BFIC 공통)", GR_L)]
    w2 = (23.4 - 5 * gap) / 6
    for i, (t, fc) in enumerate(chain):
        x = 0.3 + i * (w2 + gap)
        box(ax, x, 1.5, w2, 1.8, t, fc=fc, ec=RX, fs=9)
        if i: arrow(ax, x - gap, 2.4, x, 2.4, c=RX)
    ax.text(12, 0.85, "측정 지표: NF · 소신호 Gain · IP1dB · 위상/이득 제어 정확도 · 소모전류", ha="center",
            fontsize=9, color=INK2)
    ax.text(23.7, 0.15, "※ BFIC 내부 블록 구성은 개념도이며 상세 구조는 데이터시트 기준", ha="right", fontsize=8, color=MUTED)
    save(fig, "fig07_single_channel_chain.png")


# ---------------------------------------------------------------- Fig 8
def fig08():
    fig, axs = plt.subplots(1, 3, figsize=(15, 4.4))
    # Rx cascade
    st = [("급전손실", -0.5, 0.5), ("LNA", 18, 2.0), ("위상변위", -7, 7), ("VGA", 10, 6)]
    names, gc, nfc = ["입력"], [0], [0]
    F, g = 1, 1
    for i, (n, gdb, nf) in enumerate(st):
        Fi = 10 ** (nf / 10); F = F + (Fi - 1) / g; g *= 10 ** (gdb / 10)
        names.append(n); gc.append(10 * np.log10(g)); nfc.append(10 * np.log10(F))
    x = np.arange(len(names))
    ax = axs[1]
    ax.plot(x, gc, "-o", color=RX, lw=2, ms=7, mec="white", mew=1.5)
    for xi, v in zip(x, gc): ax.text(xi, v + 1.2, f"{v:.1f}", ha="center", fontsize=8.5)
    ax.set_xticks(x); ax.set_xticklabels(names); ax.set_ylabel("누적 이득 [dB]"); ax.set_ylim(-5, 26)
    ax.set_title("(b) 수신 채널 누적 이득", fontweight="bold")
    ax = axs[2]
    ax.plot(x, nfc, "-o", color=RX, lw=2, ms=7, mec="white", mew=1.5)
    for xi, v in zip(x, nfc): ax.text(xi, v + 0.12, f"{v:.2f}", ha="center", fontsize=8.5)
    ax.set_xticks(x); ax.set_xticklabels(names); ax.set_ylabel("누적 NF [dB]"); ax.set_ylim(0, 3.6)
    ax.set_title("(c) 수신 채널 누적 NF (Friis)", fontweight="bold")
    # Tx lineup with stage P1dB
    ax = axs[0]
    st = [("BFIC 내부\n분배 후", -13.3, None), ("위상변위", -7, None), ("VGA", 11, 5), ("DA", 12, 9), ("PA", 10, TX_OP1DB + 1), ("출력", -1, None)]
    lvl = np.cumsum([s[1] for s in st])
    x = np.arange(len(st))
    ax.plot(x, lvl, "-o", color=TX, lw=2, ms=7, mec="white", mew=1.5, label="신호 레벨")
    p1 = [(i, s[2]) for i, s in enumerate(st) if s[2] is not None]
    ax.plot([a for a, _ in p1], [b for _, b in p1], "s", color=VI, ms=8, mec="white", mew=1.5, label="단별 OP1dB")
    for i, b in p1:
        ax.annotate("", (i, b), (i, lvl[i]), arrowprops=dict(arrowstyle="<|-|>", color=MUTED, lw=0.9))
        ax.text(i + 0.12, (b + lvl[i]) / 2, f"{b - lvl[i]:.1f} dB", fontsize=8, color=INK2)
    for xi, v in zip(x, lvl): ax.text(xi - 0.12, v + 0.4, f"{v:.1f}", ha="right", va="bottom", fontsize=8.5)
    ax.set_xticks(x); ax.set_xticklabels([s[0] for s in st], fontsize=8.5)
    ax.set_ylabel("레벨 [dBm]"); ax.set_ylim(-25, 20); ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    ax.set_title("(a) 송신 채널 레벨/백오프 라인업", fontweight="bold")
    fig.suptitle("단일 채널 Gain · 출력 · NF 버짓 분석  (단별 값 [가정])", fontsize=12.5, fontweight="bold", y=1.03)
    fig.tight_layout()
    save(fig, "fig08_single_channel_lineup.png")


# ---------------------------------------------------------------- Fig 9
def fig09():
    fig, ax = canvas(24, 11, (14, 6.4))
    ax.text(0.3, 10.4, "(a) 송신 채널 Gain / Pout · P1dB 측정", fontsize=11, fontweight="bold", color=TX)
    box(ax, 0.3, 7.2, 3.2, 1.8, "신호발생기 /\nVNA Port1\n(27.5–31 GHz)", fc=GR_L, fs=8.5)
    box(ax, 4.4, 7.2, 2.4, 1.8, "가변\n감쇠기", fc="white", fs=8.5)
    box(ax, 7.7, 6.8, 4.4, 2.6, "DUT: Stampede2731 EVB\n(단일 채널 ON,\n나머지 채널 OFF/종단)", fc=TX_L, ec=TX, fs=8.5)
    box(ax, 13.0, 7.2, 2.6, 1.8, "고정 감쇠기\n/ 커플러", fc="white", fs=8.5)
    box(ax, 16.5, 7.2, 3.2, 1.8, "파워미터 /\nSA / VNA Port2", fc=GR_L, fs=8.5)
    for a, b in [(3.5, 4.4), (6.8, 7.7), (12.1, 13.0), (15.6, 16.5)]:
        arrow(ax, a, 8.1, b, 8.1)
    ax.text(10, 10.0, "보정: 케이블·감쇠기 손실 de-embedding", ha="center", fontsize=8.5, color=INK2)
    # Rx
    ax.text(0.3, 5.3, "(b) 수신 채널 NF / Gain 측정 (Y-factor)", fontsize=11, fontweight="bold", color=RX)
    box(ax, 0.3, 2.2, 3.2, 1.8, "잡음원\n(ENR 보정,\n18–26.5 GHz)", fc=GR_L, fs=8.5)
    box(ax, 7.7, 1.8, 4.4, 2.6, "DUT: Blueway1721 EVB\n(단일 채널 ON,\n나머지 채널 OFF)", fc=RX_L, ec=RX, fs=8.5)
    box(ax, 16.5, 2.2, 3.2, 1.8, "NF 분석기 /\nSA (NF 옵션)", fc=GR_L, fs=8.5)
    arrow(ax, 3.5, 3.1, 7.7, 3.1); arrow(ax, 12.1, 3.1, 16.5, 3.1)
    ax.text(14.3, 3.4, "(필요 시 프리앰프)", ha="center", fontsize=8, color=INK2)
    # common
    box(ax, 20.6, 4.2, 3.1, 3.0, "제어 PC\n(GUI / 스크립트)\n· 채널 선택\n· 위상/이득 설정", fc=AQ_L, ec=AQ, fs=8.3)
    box(ax, 20.6, 0.6, 3.1, 2.6, "DC 전원\n(전압/전류\n모니터링)", fc=YE_L, ec="#b07a00", fs=8.5)
    arrow(ax, 20.6, 6.2, 9.9, 6.8, c=AQ, ls="--"); arrow(ax, 20.6, 5.2, 12.1, 3.9, c=AQ, ls="--")
    ax.text(16.4, 6.15, "USB-SPI", fontsize=8.5, color=AQ, rotation=-14)
    arrow(ax, 20.6, 1.9, 12.1, 2.2, c="#b07a00", ls=":")
    ax.set_title("단일 채널 기초 검증 측정 구성", fontsize=13, fontweight="bold")
    save(fig, "fig09_test_setup.png")


# ---------------------------------------------------------------- Fig 10
def fig10():
    rng = np.random.default_rng(3)
    fig, axs = plt.subplots(2, 2, figsize=(12.5, 8))
    ft = np.linspace(27.5, 31, 36); fr = np.linspace(17.7, 21.2, 36)
    g = 20 + 1.2 * np.cos((ft - 29.2) / 1.6) - 0.6 + rng.normal(0, 0.12, ft.size)
    ax = axs[0, 0]; ax.plot(ft, g, color=TX, lw=2)
    ax.axhline(18, color=RX, ls="--", lw=1.2); ax.text(27.6, 18.2, "목표 Gain ≥ 18 dB [가정]", fontsize=8.5)
    ax.set_xlabel("주파수 [GHz]"); ax.set_ylabel("Gain [dB]"); ax.set_ylim(15, 23)
    ax.set_title("(a) 송신 채널 소신호 Gain", fontweight="bold")
    p1 = TX_OP1DB + 0.4 * np.cos((ft - 29) / 1.2) - 0.2 + rng.normal(0, 0.1, ft.size)
    ax = axs[0, 1]; ax.plot(ft, p1, color=TX, lw=2)
    ax.axhline(TX_OP1DB - 1, color=RX, ls="--", lw=1.2); ax.text(27.6, TX_OP1DB - 0.8, f"목표 OP1dB ≥ {TX_OP1DB-1:g} dBm [가정]", fontsize=8.5)
    ax.set_xlabel("주파수 [GHz]"); ax.set_ylabel("OP1dB [dBm]"); ax.set_ylim(TX_OP1DB - 4, TX_OP1DB + 3)
    ax.set_title("(b) 송신 채널 출력 P1dB", fontweight="bold")
    nf = RX_NF + 0.25 * ((fr - 19.4) / 1.75) ** 2 + rng.normal(0, 0.05, fr.size)
    ax = axs[1, 0]; ax.plot(fr, nf, color=RX, lw=2)
    ax.axhline(RX_NF + 0.5, color=TX, ls="--", lw=1.2); ax.text(17.8, RX_NF + 0.56, f"목표 NF ≤ {RX_NF+0.5:g} dB [가정]", fontsize=8.5)
    ax.set_xlabel("주파수 [GHz]"); ax.set_ylabel("NF [dB]"); ax.set_ylim(1.5, 4.5)
    ax.set_title("(c) 수신 채널 잡음지수", fontweight="bold")
    gr = 21 - 0.8 * ((fr - 19.2) / 1.75) ** 2 + rng.normal(0, 0.1, fr.size)
    ax = axs[1, 1]; ax.plot(fr, gr, color=RX, lw=2)
    ax.axhline(18, color=TX, ls="--", lw=1.2); ax.text(17.8, 18.2, "목표 Gain ≥ 18 dB [가정]", fontsize=8.5)
    ax.set_xlabel("주파수 [GHz]"); ax.set_ylabel("Gain [dB]"); ax.set_ylim(15, 23)
    ax.set_title("(d) 수신 채널 소신호 Gain", fontweight="bold")
    for a in axs.flat:
        a.text(0.98, 0.04, "예시 데이터 – 측정값으로 교체", transform=a.transAxes, ha="right", fontsize=8, color=MUTED)
    fig.suptitle("단일 채널 Gain · 출력 · NF 특성 (결과 그래프 템플릿)", fontsize=12.5, fontweight="bold")
    fig.tight_layout()
    save(fig, "fig10_single_channel_results_template.png")


if __name__ == "__main__":
    for f in [fig01, fig02, fig03, fig04, fig05, fig06, fig07, fig08, fig09, fig10]:
        f()
    Lu, cn0u, e = uplink(); Ld, cn0d, gt = downlink()
    print(f"UL: FSPL={Lu:.1f} C/N0={cn0u:.1f} EIRP_req={e:.1f} dBW | DL: FSPL={Ld:.1f} C/N0={cn0d:.1f} G/T_req={gt:.1f}")
