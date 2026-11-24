import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

CU, CU_E = "#d98c3a", "#8a5316"
MAT = {"DS-9000": ("#cfe3f5", "#3f78b0"), "DS-7409": ("#e3f0d6", "#5d8f3a")}
diel = [("DS-9000", 50)] * 2 + [("DS-7409", 60)] * 5 + [("DS-9000", 50)] * 2
cu_h = 14          # drawing height of copper (not to scale)
sc = 0.9           # dielectric drawing scale (um -> units)
x0, w = 0, 10

fig, ax = plt.subplots(figsize=(9, 8.2))
y = 0
layers = []        # build top-down
for i in range(10):
    layers.append(("cu", i + 1))
    if i < 9:
        layers.append(("d", i + 1))
heights = [cu_h if k == "cu" else diel[n - 1][1] * sc for k, n in layers]
y = sum(heights)
for (k, n), h in zip(layers, heights):
    y -= h
    if k == "cu":
        ax.add_patch(Rectangle((x0, y), w, h, fc=CU, ec=CU_E, lw=1))
        ax.text(x0 - 0.3, y + h / 2, f"L{n}", ha="right", va="center", fontsize=11, fontweight="bold", color=CU_E)
        ax.text(x0 + w / 2, y + h / 2, "Copper", ha="center", va="center", fontsize=8.5, color="white", fontweight="bold")
    else:
        m, t = diel[n - 1]
        fc, ec = MAT[m]
        ax.add_patch(Rectangle((x0, y), w, h, fc=fc, ec=ec, lw=1))
        ax.text(x0 + w / 2, y + h / 2, f"유전체 {n}층  |  {m}", ha="center", va="center", fontsize=10.5, color="#222")
        ax.text(x0 + w + 0.3, y + h / 2, f"{t} µm", ha="left", va="center", fontsize=10.5, color=ec, fontweight="bold")

tot = sum(heights)
ax.annotate("", xy=(x0 + w + 2.4, 0), xytext=(x0 + w + 2.4, tot), arrowprops=dict(arrowstyle="<->", color="#555"))
ax.text(x0 + w + 2.8, tot / 2, "유전체 합계\n500 µm\n(동박 제외)", ha="left", va="center", fontsize=9.5, color="#333", bbox=dict(fc="white", ec="none", pad=2))

from matplotlib.patches import Patch
ax.legend(handles=[Patch(fc=CU, ec=CU_E, label="Copper (L1 ~ L10)"),
                   Patch(fc=MAT["DS-9000"][0], ec=MAT["DS-9000"][1], label="DS-9000 (유전체 1·2·8·9층, 50 µm)"),
                   Patch(fc=MAT["DS-7409"][0], ec=MAT["DS-7409"][1], label="DS-7409 (유전체 3~7층, 60 µm)")],
          loc="upper center", bbox_to_anchor=(0.5, -0.01), ncol=1, frameon=False, fontsize=9.5)
ax.text(x0 + w / 2, tot + 8, "10층 PCB 스택업 단면 (Copper 기준)", ha="center", va="bottom", fontsize=13, fontweight="bold")
ax.text(x0 + w, -6, "※ 동박 두께는 도식용으로 과장 표시", ha="right", va="top", fontsize=8, color="#777")
ax.set_xlim(-1.5, 15.5); ax.set_ylim(-10, tot + 22)
ax.axis("off")
plt.savefig("fig_stackup_10L.png", dpi=220, bbox_inches="tight", facecolor="white")
