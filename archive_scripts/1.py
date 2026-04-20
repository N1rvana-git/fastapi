import numpy as np
import matplotlib.pyplot as plt


def generate_wiou_curve():
    # 1. 设置参数
    alpha = 1.9
    delta = 3.0

    # 2. 生成数据点 (beta 从 0 到 10)
    beta = np.linspace(0, 8, 500)

    # 3. 计算 r
    # r = beta / (delta * alpha^(beta - delta))
    r = beta / (delta * np.power(alpha, beta - delta))

    # 4. 绘图设置
    plt.figure(figsize=(8, 5), dpi=300)
    plt.style.use('seaborn-v0_8-paper')  # 使用学术风格

    # 画主曲线
    plt.plot(beta, r, color='#FF5722', linewidth=2.5, label='WIoU v3 Focusing Mechanism')

    # 5. 标注关键区域
    # 峰值位置：理论上在 delta 附近
    peak_beta = delta
    peak_r = peak_beta / (delta * np.power(alpha, peak_beta - delta))

    plt.scatter([peak_beta], [peak_r], color='red', zorder=5)
    plt.text(peak_beta, peak_r + 0.05, f'Focus Peak ($\\beta={delta}$)',
             ha='center', fontsize=10, fontweight='bold')

    # 简单样本区域 (左侧)
    plt.axvspan(0, 1.5, color='green', alpha=0.1)
    plt.text(0.75, 0.2, 'Simple Examples\n(Down-weighted)', ha='center', color='green', fontsize=9)

    # 极端样本区域 (右侧)
    plt.axvspan(5, 8, color='gray', alpha=0.1)
    plt.text(6.5, 0.2, 'Outliers/Abnormal\n(Suppressed)', ha='center', color='gray', fontsize=9)

    # 普通困难样本 (中间)
    plt.text(3.0, 0.4, 'Hard Examples\n(High Focus)', ha='center', color='#D84315', fontsize=9, fontweight='bold')

    # 6. 坐标轴修饰
    plt.title(r'WIoU v3 Dynamic Non-Monotonic Focusing Mechanism ($\alpha=1.9, \delta=3.0$)', fontsize=12, pad=15)
    plt.xlabel(r'Outlierness ($\beta$)', fontsize=11)
    plt.ylabel(r'Gradient Gain ($r$)', fontsize=11)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.xlim(0, 8)
    plt.ylim(0, 1.2)

    # 保存
    save_path = 'wiou_curve.png'
    plt.savefig(save_path, bbox_inches='tight')
    print(f"Chart saved to {save_path}")


if __name__ == "__main__":
    generate_wiou_curve()