# -*- coding: utf-8 -*-
"""1차년도 연차보고서 결과 그림 (예시/가상 데이터).
DEMO_TAG=True 이면 각 그림 우하단에 '예시 데이터' 표기를 넣는다. 실측 데이터로 교체 후 False로."""
import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

DEMO_TAG = True
OUT = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(7)

plt.rcParams.update({
    "font.family": "Malgun Gothic", "axes.unicode_minus": False,
    "font.size": 10, "axes.titlesize": 11.5, "axes.titleweight": "bold",
    "axes.edgecolor": "#8a8984", "axes.linewidth": 0.8,
    "axes.grid": True, "grid.color": "#e4e3df", "grid.linewidth": 0.7,
    "axes.spines.top": False, "axes.spines.right": False,
    "xtick.color": "#52514e", "ytick.color": "#52514e",
    "axes.labelcolor": "#0b0b0b", "legend.frameon": False,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "lines.linewidth": 2.0, "axes.axisbelow": True,
})
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
LIM = "#d03b3b"      # 규격선
BAND = "#f0efec"     # 대역 음영
TXT2 = "#52514e"

def save(fig, name):
    if DEMO_TAG:
        fig.text(0.995, 0.005, "예시(가상) 데이터", ha="right", va="bottom",
                 fontsize=7.5, color="#b0afa9")
    fig.savefig(os.path.join(OUT, name), dpi=220, bbox_inches="tight")
    plt.close(fig)
    print("saved", name)

def bands(ax, label=True, y=None):
    for (a, b, t) in [(17.7, 21.2, "Rx 대역"), (27.5, 31.0, "Tx 대역")]:
        ax.axvspan(a, b, color=BAND, zorder=0)
        if label:
            yy = ax.get_ylim()[1] if y is None else y
            ax.text((a + b) / 2, yy, t, ha="center", va="top", fontsize=8.5, color=TXT2)

def limit(ax, y, text, xpos=None, va="bottom"):
    ax.axhline(y, color=LIM, lw=1.3, ls="--", zorder=3)
    x0, x1 = ax.get_xlim()
    x = x1 - 0.01*(x1 - x0) if xpos is None else xpos
    ax.text(x, y, text, color=LIM, fontsize=8.5, va="bottom", ha="right", zorder=4,
            bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none", alpha=0.85))

f = np.linspace(15, 35, 401)
RL_VSWR25 = -20 * np.log10(1.5 / 3.5)   # 7.36 dB

# ---------------------------------------------------------------- 1. 회로/PCB
# 1a 채널 간 진폭/위상 편차
amp_tx = [0.18, -0.12, -0.21, 0.15]; amp_rx = [0.10, -0.16, 0.08, -0.05]
ph_tx = [1.8, -2.4, 0.9, -1.1];      ph_rx = [-1.2, 2.1, -0.6, 0.4]
fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.6))
x = np.arange(4); w = 0.36
for ax, (dt, dr, yl, lim, unit) in zip(axs, [(amp_tx, amp_rx, "진폭 편차 (dB)", 0.5, "dB"),
                                            (ph_tx, ph_rx, "위상 편차 (°)", 5, "°")]):
    ax.bar(x - w/2 - 0.01, dt, w, color=C[0], label="Tx (29 GHz)")
    ax.bar(x + w/2 + 0.01, dr, w, color=C[1], label="Rx (19.5 GHz)")
    ax.axhline(0, color="#8a8984", lw=0.8)
    for s in (1, -1):
        ax.axhline(s * lim, color=LIM, lw=1.2, ls="--")
    ax.text(3.6, lim, f"설계 목표 ±{lim}{unit}", color=LIM, fontsize=8.5, ha="right", va="bottom")
    ax.set_xticks(x, [f"CH{i+1}" for i in x]); ax.set_ylabel(yl)
    ax.set_ylim(-lim * 1.4, lim * 1.4); ax.grid(axis="x", visible=False)
axs[0].set_title("채널 간 진폭 편차"); axs[1].set_title("채널 간 위상 편차")
axs[0].legend(loc="lower left", ncol=2, fontsize=8.5)
fig.tight_layout(); save(fig, "fig1a_channel_deviation.png")

# 1b Tx-Rx 격리도 (레이아웃 개선 전/후)
iso_before = -19 - 2.5*np.sin((f-15)/3.1) - 0.08*(f-15) + rng.normal(0, 0.25, f.size)
iso_after = -29 - 3*np.sin((f-15)/2.6) - 0.12*(f-15) + rng.normal(0, 0.25, f.size)
fig, ax = plt.subplots(figsize=(7.2, 3.8))
ax.set_ylim(-45, -5); ax.set_xlim(15, 35)
bands(ax)
ax.plot(f, iso_before, color=C[1], label="초기 레이아웃")
ax.plot(f, iso_after, color=C[0], label="Tx/Rx 분리 배치 적용")
limit(ax, -15, "격리도 기준 15 dB")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("Tx–Rx 결합 |S| (dB)")
ax.set_title("Tx–Rx 포트 간 격리도 해석 결과")
ax.legend(loc="lower left")
fig.tight_layout(); save(fig, "fig1b_txrx_isolation.png")

# 1c 소재별 단위 길이당 삽입 손실
mats = [("소재 A (PTFE 계열, Df 0.0013)", 0.060, 0.004),
        ("소재 B (탄화수소 세라믹, Df 0.0037)", 0.065, 0.011),
        ("소재 C (저손실 FR-4, Df 0.008)", 0.070, 0.022)]
fig, ax = plt.subplots(figsize=(7.2, 3.8))
ax.set_xlim(15, 35); ax.set_ylim(0, 1.3)
bands(ax)
for i, (lab, a, b) in enumerate(mats):
    ax.plot(f, a*np.sqrt(f) + b*f, color=C[i], label=lab)
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("삽입 손실 (dB/cm)")
ax.set_title("PCB 소재별 50 Ω 마이크로스트립 단위 길이당 손실")
ax.legend(loc="upper left", fontsize=8.5, bbox_to_anchor=(0, 0.93))
fig.tight_layout(); save(fig, "fig1c_material_loss.png")

# 1d 안테나 기판 두께/유전율에 따른 이득
t = np.array([0.127, 0.203, 0.254, 0.305, 0.381, 0.508])
gains = {"Tx (29 GHz)": {"Dk 3.0": [5.2, 5.9, 6.2, 6.4, 6.4, 6.0], "Dk 3.5": [4.6, 5.3, 5.6, 5.8, 5.8, 5.4]},
         "Rx (19.5 GHz)": {"Dk 3.0": [4.4, 5.1, 5.5, 5.8, 6.1, 6.2], "Dk 3.5": [3.8, 4.6, 5.0, 5.3, 5.6, 5.7]}}
fig, axs = plt.subplots(1, 2, figsize=(9.5, 3.6), sharey=True)
for ax, (k, d) in zip(axs, gains.items()):
    for i, (lab, g) in enumerate(d.items()):
        ax.plot(t, g, color=C[i], marker="o", ms=6, mec="white", mew=1.5, label=lab)
    ax.set_xlim(0.1, 0.53); ax.set_ylim(3, 7)
    limit(ax, 4, "목표 4 dBi", va="top")
    ax.set_title(f"{k} 단일 소자 이득"); ax.set_xlabel("안테나 기판 두께 (mm)")
axs[0].set_ylabel("이득 (dBi)"); axs[0].legend(loc="lower right")
fig.tight_layout(); save(fig, "fig1d_antenna_gain_substrate.png")

# ---------------------------------------------------------------- 2. 트랜지션
# 2a 전송선로 종류별 삽입 손실
fig, ax = plt.subplots(figsize=(7.2, 3.8))
ax.set_xlim(15, 35); ax.set_ylim(0, 0.9)
bands(ax)
for i, (lab, a, b) in enumerate([("마이크로스트립", 0.060, 0.004), ("GCPW", 0.066, 0.005), ("스트립라인", 0.075, 0.006)]):
    ax.plot(f, a*np.sqrt(f) + b*f + 0.01*np.sin(f/1.7), color=C[i], label=lab)
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("삽입 손실 (dB/cm)")
ax.set_title("전송선로 구조별 단위 길이당 삽입 손실 (소재 A)")
ax.legend(loc="upper left", bbox_to_anchor=(0, 0.93))
fig.tight_layout(); save(fig, "fig2a_line_loss.png")

# 2b 비아 트랜지션 최적화 전/후 S11, S21
def s11_curve(f, depth, f0s, base):
    y = np.full_like(f, base)
    for f0 in f0s:
        y = -10*np.log10(10**(-y/10) + 10**(-(depth - 0)/10) * 0) if False else y
    return y
s11_before = -11 + 4.2*np.exp(-((f-30.5)/3.5)**2) + 0.12*(f-15) - 2.0 + rng.normal(0, 0.15, f.size)
s11_after = -24 + 5*np.cos((f-19.5)/1.6)*np.exp(-((f-24)/9)**2) + 0.18*(f-15) + rng.normal(0, 0.2, f.size)
s11_after = np.minimum(s11_after, -15.2 + 0.05*(f-15))
s21_before = -0.25 - 0.035*(f-15) - 0.6*np.exp(-((f-30.5)/3)**2)
s21_after = -0.15 - 0.018*(f-15)
fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
ax = axs[0]; ax.set_xlim(15, 35); ax.set_ylim(-40, 0)
bands(ax)
ax.plot(f, s11_before, color=C[1], label="초기 설계")
ax.plot(f, s11_after, color=C[0], label="최적화 설계")
limit(ax, -RL_VSWR25, "VSWR 2.5:1 (-7.4 dB)", va="top")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("S11 (dB)"); ax.set_title("비아 트랜지션 반사 특성")
ax.legend(loc="lower right")
ax = axs[1]; ax.set_xlim(15, 35); ax.set_ylim(-1.6, 0)
bands(ax)
ax.plot(f, s21_before, color=C[1], label="초기 설계")
ax.plot(f, s21_after, color=C[0], label="최적화 설계")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("S21 (dB)"); ax.set_title("비아 트랜지션 삽입 손실")
ax.legend(loc="lower left")
fig.tight_layout(); save(fig, "fig2b_via_transition.png")

# 2c 파라메트릭: 안티패드 직경 × 그라운드 비아 수
d = np.linspace(0.40, 0.90, 11)
fig, axs = plt.subplots(1, 2, figsize=(10, 3.8), sharey=True)
for ax, band_name, opt in [(axs[0], "Tx 대역 (27.5–31 GHz)", 0.62), (axs[1], "Rx 대역 (17.7–21.2 GHz)", 0.70)]:
    for i, (n, depth) in enumerate([(4, 13), (6, 18), (8, 21)]):
        y = -depth + 55*(d - opt)**2 + (0.0 if band_name.startswith("Rx") else 1.0)
        ax.plot(d, y, color=C[i], marker="o", ms=6, mec="white", mew=1.5, label=f"그라운드 비아 {n}개")
    limit(ax, -RL_VSWR25, "VSWR 2.5:1", va="top")
    ax.set_xlim(0.38, 0.92); ax.set_ylim(-25, 0)
    ax.set_xlabel("안티패드 직경 (mm)"); ax.set_title(f"대역 내 최대 S11 – {band_name}")
axs[0].set_ylabel("대역 내 최대 S11 (dB)"); axs[0].legend(loc="lower left", fontsize=8.5)
fig.tight_layout(); save(fig, "fig2c_parametric_antipad.png")

# ---------------------------------------------------------------- 3. 스택업 검증
# 3a 비아 체인 DC 저항
coupons = np.arange(1, 13)
r = 2.6 + rng.normal(0, 0.12, coupons.size); r[8] = 2.95
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ax.bar(coupons, r, 0.6, color=C[0])
ax.axhline(r.mean(), color=TXT2, lw=1.0, ls=":")
ax.text(0.45, r.mean(), f"평균 {r.mean():.2f} mΩ", color=TXT2, fontsize=8.5, va="bottom", ha="left")
limit(ax, 4.0, "판정 기준 4.0 mΩ/via")
ax.set_xticks(coupons, [f"#{c}" for c in coupons]); ax.set_ylim(0, 4.6)
ax.set_xlabel("테스트 쿠폰 번호"); ax.set_ylabel("비아당 저항 (mΩ)")
ax.set_title("비아 체인 쿠폰 DC 저항 측정 (100 비아 체인, 층간 절연 > 100 MΩ 전 쿠폰 통과)")
ax.grid(axis="x", visible=False)
fig.tight_layout(); save(fig, "fig3a_via_chain_dc.png")

# 3b TDR 임피던스 프로파일
tt = np.linspace(0, 600, 1200)   # ps
z = 50 + 0.0*tt
z += 4.5*np.exp(-((tt-60)/18)**2)          # 커넥터 런치
z -= 6.0*np.exp(-((tt-330)/22)**2)         # 비아 (초기)
z_opt = 50 + 4.5*np.exp(-((tt-60)/18)**2) - 1.8*np.exp(-((tt-330)/22)**2)
z += 0.6*np.sin(tt/23); z_opt += 0.5*np.sin(tt/23)
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ax.axhspan(45, 55, color=BAND, zorder=0)
ax.text(590, 55, "50 Ω ±10%", ha="right", va="bottom", fontsize=8.5, color=TXT2)
ax.plot(tt, z, color=C[1], label="초기 비아 구조")
ax.plot(tt, z_opt, color=C[0], label="최적화 비아 구조")
for xx, lab in [(60, "커넥터 런치"), (180, "마이크로스트립"), (330, "층간 비아"), (440, "스트립라인")]:
    ax.text(xx, 59.5, lab, ha="center", fontsize=8.5, color=TXT2)
ax.set_xlim(0, 600); ax.set_ylim(40, 61)
ax.set_xlabel("시간 (ps)"); ax.set_ylabel("임피던스 (Ω)"); ax.set_title("TDR 임피던스 프로파일")
ax.legend(loc="lower left")
fig.tight_layout(); save(fig, "fig3b_tdr.png")

# 3c 공차 영향 (Monte Carlo 포락선)
nom = -20 + 4*np.cos((f-19.5)/1.8)*np.exp(-((f-25)/10)**2) + 0.15*(f-15)
runs = np.array([nom + rng.normal(0, 1.0) + 1.6*rng.normal(0, 1)*np.sin((f-15)/rng.uniform(2.5, 4)) for _ in range(200)])
fig, ax = plt.subplots(figsize=(7.2, 3.8))
ax.set_xlim(15, 35); ax.set_ylim(-35, 0)
bands(ax)
ax.fill_between(f, runs.min(0), runs.max(0), color="#b7d3f6", lw=0, label="공차 200회 해석 범위")
ax.plot(f, nom, color=C[0], label="공칭 설계")
limit(ax, -RL_VSWR25, "VSWR 2.5:1", va="top")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("S11 (dB)")
ax.set_title("적층·유전율·비아 가공 공차를 반영한 트랜지션 S11 분포")
ax.legend(loc="lower right")
fig.tight_layout(); save(fig, "fig3c_tolerance.png")

# 3d 측정 vs 해석 (트랜지션 쿠폰)
fm = f[::4]
s11_sim = s11_after; s21_sim = s21_after - 0.02*(f-15)
s11_meas = np.interp(fm, f, s11_sim) + 1.5 + rng.normal(0, 0.9, fm.size)
s21_meas = np.interp(fm, f, s21_sim) - 0.08 - 0.006*(fm-15) + rng.normal(0, 0.03, fm.size)
fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
ax = axs[0]; ax.set_xlim(15, 35); ax.set_ylim(-40, 0); bands(ax)
ax.plot(f, s11_sim, color=C[0], label="해석")
ax.plot(fm, s11_meas, color=C[1], lw=1.4, marker="o", ms=3.5, label="측정 (디임베딩 후)")
limit(ax, -RL_VSWR25, "VSWR 2.5:1", va="top")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("S11 (dB)"); ax.set_title("트랜지션 쿠폰 S11"); ax.legend(loc="lower right")
ax = axs[1]; ax.set_xlim(15, 35); ax.set_ylim(-1.5, 0); bands(ax)
ax.plot(f, s21_sim, color=C[0], label="해석")
ax.plot(fm, s21_meas, color=C[1], lw=1.4, marker="o", ms=3.5, label="측정 (디임베딩 후)")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("S21 (dB)"); ax.set_title("트랜지션 쿠폰 S21"); ax.legend(loc="lower left")
fig.tight_layout(); save(fig, "fig3d_meas_vs_sim.png")

# 3e TRL 추출: 단위 길이 손실, 실효 유전율
loss_sim = 0.060*np.sqrt(f) + 0.004*f
loss_meas = loss_sim*1.12 + rng.normal(0, 0.008, f.size)
eeff_sim = 2.62 + 0.0015*(f-15)
eeff_meas = 2.68 + 0.002*(f-15) + rng.normal(0, 0.006, f.size)
fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
ax = axs[0]; ax.set_xlim(15, 35); ax.set_ylim(0, 0.8); bands(ax)
ax.plot(f, loss_sim, color=C[0], label="해석"); ax.plot(f, loss_meas, color=C[1], lw=1.4, label="TRL 추출 (측정)")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("손실 (dB/cm)"); ax.set_title("단위 길이당 삽입 손실"); ax.legend(loc="lower right")
ax = axs[1]; ax.set_xlim(15, 35); ax.set_ylim(2.5, 2.8); bands(ax)
ax.plot(f, eeff_sim, color=C[0], label="해석"); ax.plot(f, eeff_meas, color=C[1], lw=1.4, label="TRL 추출 (측정)")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("실효 유전율 εeff"); ax.set_title("실효 유전율"); ax.legend(loc="lower right")
fig.tight_layout(); save(fig, "fig3e_trl_extraction.png")

# 3f 인접 선로 결합 (격리도)
fig, ax = plt.subplots(figsize=(7.2, 3.8))
ax.set_xlim(15, 35); ax.set_ylim(-50, -5); bands(ax)
cpl = [("Tx 인접 채널 (S31)", -24 + 0.25*(f-15)), ("Rx 인접 채널 (S31)", -27 + 0.22*(f-15)),
       ("Tx–Rx 선로 (S41)", -36 + 0.15*(f-15))]
for i, (lab, y) in enumerate(cpl):
    ax.plot(f, y + 1.2*np.sin(f/1.3 + i) + rng.normal(0, 0.35, f.size), color=C[i], lw=1.6, label=lab)
limit(ax, -15, "격리도 기준 15 dB")
ax.set_xlabel("주파수 (GHz)"); ax.set_ylabel("결합 (dB)"); ax.set_title("결합 패턴 쿠폰 측정 결과")
ax.legend(loc="lower right", fontsize=8.5)
fig.tight_layout(); save(fig, "fig3f_coupling.png")

# ---------------------------------------------------------------- 4. SI/PI
# 4a SPI 클럭 파형 (종단 전/후)
tn = np.linspace(0, 60, 3000)  # ns, 25 MHz clock
def clk(tn, ov, damp, fr):
    period = 40; edge = 1.0
    y = np.zeros_like(tn)
    for e, lvl in [(5, 1), (25, 0), (45, 1)]:
        step = 1/(1 + np.exp(-(tn-e)/(edge/4)))
        ring = ov*np.exp(-(tn-e)/damp)*np.sin(2*np.pi*fr*(tn-e))*(tn > e)
        y = y + (step + ring)*(1 if lvl else -1)
    return 1.8*y
v_raw = clk(tn, 0.28, 2.2, 0.45); v_term = clk(tn, 0.05, 1.2, 0.45)
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ax.plot(tn, v_raw, color=C[1], lw=1.6, label="종단 미적용")
ax.plot(tn, v_term, color=C[0], label="직렬 종단 적용")
for yv, lab in [(1.8*0.7, "VIH (0.7·VDD)"), (1.8*0.3, "VIL (0.3·VDD)")]:
    ax.axhline(yv, color=TXT2, lw=0.9, ls=":"); ax.text(60, yv, lab + " ", ha="right", va="bottom", fontsize=8.5, color=TXT2)
ax.set_xlim(0, 60); ax.set_ylim(-0.6, 2.5)
ax.set_xlabel("시간 (ns)"); ax.set_ylabel("전압 (V)"); ax.set_title("BFIC 입력단 SPI 클럭 파형 (25 MHz, 1.8 V)")
ax.legend(loc="lower right", ncol=2)
fig.tight_layout(); save(fig, "fig4a_spi_waveform.png")

# 4b PDN 임피던스
fp = np.logspace(4, 9.3, 500)  # Hz
lf = np.log10(fp)
def zcurve(base, bumps):
    y = base(lf)
    for c, h, wd in bumps:
        y = y + h*np.exp(-((lf - c)/wd)**2)
    return 10**y / 1e3
# 저주파: VRM 영역, 중간: 벌크/MLCC, 고주파: MLCC ESL-플레인 반공진
z_before = zcurve(lambda x: 1.35 + 0.25*np.tanh((x-6.6)/0.6), [(5.2, 0.25, 0.35), (8.0, 0.95, 0.22), (8.9, 0.35, 0.25)])
z_after = zcurve(lambda x: 1.10 + 0.12*np.tanh((x-6.6)/0.6), [(5.2, 0.12, 0.35), (8.2, 0.42, 0.22), (9.0, 0.20, 0.25)])
fig, ax = plt.subplots(figsize=(7.2, 3.8))
ax.loglog(fp, z_before*1e3, color=C[1], label="초기 디커플링 구성")
ax.loglog(fp, z_after*1e3, color=C[0], label="디커플링 최적화")
ax.axhline(60, color=LIM, lw=1.3, ls="--"); ax.text(1.2e4, 60, " 목표 임피던스 60 mΩ", color=LIM, fontsize=8.5, va="bottom")
ax.set_xlim(1e4, 2e9); ax.set_ylim(5, 1000)
ax.set_xlabel("주파수 (Hz)"); ax.set_ylabel("|Z| (mΩ)"); ax.set_title("Tx BFIC 전원 레일 PDN 임피던스")
ax.grid(True, which="both", lw=0.5); ax.legend(loc="upper left")
fig.tight_layout(); save(fig, "fig4b_pdn_impedance.png")

# 4c 송수신 전환 시 과도 전압
tu = np.linspace(-5, 45, 2000)  # us
def droop(tu, dv, tau, fr):
    return 1.2 - dv*np.exp(-np.clip(tu, 0, None)/tau)*np.cos(2*np.pi*fr*np.clip(tu, 0, None))*(tu > 0) \
           - 0.012*(tu > 0)
vb = droop(tu, 0.095, 6, 0.09); va_ = droop(tu, 0.035, 3, 0.09)
fig, ax = plt.subplots(figsize=(7.2, 3.6))
ax.axhspan(1.2*0.95, 1.2*1.05, color=BAND, zorder=0)
ax.text(44, 1.2*1.05, "허용 범위 ±5%", ha="right", va="bottom", fontsize=8.5, color=TXT2)
ax.axvline(0, color=TXT2, lw=0.9, ls=":"); ax.text(0.5, 1.29, "Tx 활성화", fontsize=8.5, color=TXT2)
ax.plot(tu, vb, color=C[1], label="초기 PDN")
ax.plot(tu, va_, color=C[0], label="최적화 PDN")
ax.set_xlim(-5, 45); ax.set_ylim(1.05, 1.3)
ax.set_xlabel("시간 (µs)"); ax.set_ylabel("BFIC 전원 전압 (V)"); ax.set_title("Rx→Tx 전환 시 전원 과도 응답 (1.2 V 레일)")
ax.legend(loc="lower right")
fig.tight_layout(); save(fig, "fig4c_transient.png")

# 4d IR drop 분포 맵
nx, ny = 120, 80
X, Y = np.meshgrid(np.linspace(0, 30, nx), np.linspace(0, 20, ny))
src = (2, 10)
loads = [(20, 6, 1.0), (20, 14, 0.45)]   # Tx BFIC, Rx BFIC (상대 전류)
rs = np.hypot(X - src[0], Y - src[1]) + 0.8
drop = 0.0
for (lx, ly, wgt) in loads:
    rr = np.hypot(X - lx, Y - ly) + 0.8
    drop = drop + wgt*np.log(rs/0.8)/(1 + 0.12*rr)
drop = drop/drop.max()*14.5  # mV
fig, ax = plt.subplots(figsize=(7.2, 4.2))
from matplotlib.colors import LinearSegmentedColormap
cmap = LinearSegmentedColormap.from_list("seq", ["#f4f8fd", "#86b6ef", "#2a78d6", "#104281"])
im = ax.imshow(drop, origin="lower", extent=[0, 30, 0, 20], cmap=cmap, aspect="equal")
ax.plot(*src, marker="s", ms=9, color="white", mec="#0b0b0b"); ax.text(src[0] + 1, src[1], "전원 입력", fontsize=8.5, va="center")
for (lx, ly, _), lab in zip(loads, ["Tx BFIC", "Rx BFIC"]):
    ax.plot(lx, ly, marker="s", ms=10, color="white", mec="#0b0b0b")
    ax.text(lx, ly - 1.7, lab, ha="center", fontsize=8.5, color="white", fontweight="bold")
ax.grid(False)
cb = fig.colorbar(im, ax=ax, shrink=0.85); cb.set_label("IR drop (mV)")
ax.set_xlabel("x (mm)"); ax.set_ylabel("y (mm)")
ax.set_title("전원 플레인 IR drop 분포 (최대 14.5 mV, 1.2 V 대비 1.2%)")
fig.tight_layout(); save(fig, "fig4d_ir_drop_map.png")

# 4e 확장 시 SI/PI 변화
n = np.array([2, 4, 8, 16, 32, 64])
fig, axs = plt.subplots(1, 2, figsize=(10, 3.8))
ax = axs[0]
ax.plot(n, 18 - 3.1*np.log2(n), color=C[1], marker="o", ms=6, mec="white", mew=1.5, label="직접 분기 (버퍼 없음)")
ax.plot(n, 17 - 0.6*np.log2(n), color=C[0], marker="o", ms=6, mec="white", mew=1.5, label="그룹별 버퍼 분배")
ax.axhline(0, color=LIM, lw=1.3, ls="--"); ax.text(1.85, 0.3, "타이밍 마진 0 ns", color=LIM, fontsize=8.5, va="bottom")
ax.set_xscale("log", base=2); ax.set_xticks(n, [str(v) for v in n])
ax.set_ylim(-3, 25); ax.set_xlabel("SPI 버스 연결 BFIC 수"); ax.set_ylabel("셋업 타이밍 마진 (ns)")
ax.set_title("BFIC 수 증가에 따른 제어 신호 타이밍 마진"); ax.legend(loc="upper right", fontsize=8.5)
ax = axs[1]
ax.plot(n, 9*np.sqrt(n), color=C[1], marker="o", ms=6, mec="white", mew=1.5, label="단일 전원 공급")
ax.plot(n, 9*np.sqrt(np.minimum(n, 8)) + 0.8*np.sqrt(n), color=C[0], marker="o", ms=6, mec="white", mew=1.5, label="그룹별 분할 공급")
ax.axhline(60, color=LIM, lw=1.3, ls="--"); ax.text(2, 60, " 허용 전원 잡음 60 mV (±5%)", color=LIM, fontsize=8.5, va="bottom")
ax.set_xscale("log", base=2); ax.set_xticks(n, [str(v) for v in n])
ax.set_ylim(0, 100); ax.set_xlabel("동시 스위칭 BFIC 수"); ax.set_ylabel("전원 잡음 피크 (mV)")
ax.set_title("동시 스위칭 잡음 (SSN) 변화"); ax.legend(loc="upper left", fontsize=8.5)
fig.tight_layout(); save(fig, "fig4e_scaling.png")
