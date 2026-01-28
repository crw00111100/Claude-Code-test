"""
Wind 热门概念指数动量因子分析
===============================
复现研报内容:
  1. 计算周度/月度动量因子
  2. Rank IC 检验
  3. 分位数组合检验 (10 组, 多空净值)
  4. Top 10% 动量策略 vs 中证全指

使用方法:
  方式1 - Wind API (需要已安装 WindPy 并登录 Wind 终端):
      python momentum_factor_analysis.py --source wind

  方式2 - CSV 文件:
      python momentum_factor_analysis.py --source csv \
          --price_file concept_prices.csv \
          --benchmark_file benchmark_price.csv
      CSV 格式说明:
        concept_prices.csv : index=日期(yyyy-mm-dd), columns=概念指数代码, values=收盘价
        benchmark_price.csv: index=日期(yyyy-mm-dd), 第一列=中证全指收盘价

  方式3 - 模拟数据 (仅用于验证代码逻辑):
      python momentum_factor_analysis.py --source demo
"""

import argparse
import warnings
from datetime import datetime

import matplotlib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

# ---------- 中文字体设置 ----------
matplotlib.rcParams["font.sans-serif"] = [
    "SimHei",
    "Microsoft YaHei",
    "WenQuanYi Micro Hei",
    "Arial Unicode MS",
    "DejaVu Sans",
]
matplotlib.rcParams["axes.unicode_minus"] = False


# ================================================================
#  Part 1: 数据加载
# ================================================================

def load_data_wind(start_date="2018-06-01", end_date="2025-08-29"):
    """
    从 Wind API 获取热门概念指数日频收盘价及中证全指基准价格。
    需要提前安装 WindPy 并在 Wind 终端中运行。
    start_date 比回测起始 (2019) 早半年, 用于计算初始动量。
    """
    from WindPy import w
    w.start()

    # --- 获取 Wind 概念指数成分列表 ---
    # sectorid 对应"Wind概念指数"板块, 可在Wind终端查看
    # 若 sectorid 不对, 也可用 w.wset("sectorconstituent",
    #     "date=2025-08-29;sectorid=a]按需调整") 获取
    result = w.wset(
        "sectorconstituent",
        f"date={end_date};sectorid=1000034137000000",
    )
    if result.ErrorCode != 0:
        # 备选: 通过板块名获取
        result = w.wset(
            "sectorconstituent",
            f"date={end_date};sector=Wind概念指数",
        )
    codes = result.Data[1]  # Wind 代码列表
    names = result.Data[2]  # 指数名称列表
    code_name_map = dict(zip(codes, names))
    print(f"[Wind] 获取到 {len(codes)} 个概念指数")

    # --- 获取日频收盘价 ---
    price_result = w.wsd(
        codes, "close", start_date, end_date, "Fill=Previous"
    )
    dates = [pd.Timestamp(d) for d in price_result.Times]
    prices = pd.DataFrame(price_result.Data, index=codes, columns=dates).T
    prices.index.name = "date"
    print(f"[Wind] 价格矩阵: {prices.shape[0]} 天 x {prices.shape[1]} 个指数")

    # --- 基准: 中证全指 (000985.CSI) ---
    bm = w.wsd("000985.CSI", "close", start_date, end_date, "Fill=Previous")
    benchmark = pd.Series(
        bm.Data[0],
        index=[pd.Timestamp(d) for d in bm.Times],
        name="benchmark",
    )
    w.close()
    return prices, benchmark, code_name_map


def load_data_csv(price_file, benchmark_file=None):
    """从 CSV 文件加载数据"""
    prices = pd.read_csv(price_file, index_col=0, parse_dates=True)
    prices.index.name = "date"
    benchmark = None
    if benchmark_file:
        bm = pd.read_csv(benchmark_file, index_col=0, parse_dates=True)
        benchmark = bm.iloc[:, 0]
        benchmark.name = "benchmark"
    print(f"[CSV] 价格矩阵: {prices.shape[0]} 天 x {prices.shape[1]} 个指数")
    return prices, benchmark, {}


def load_data_demo(
    n_concepts=200, start_date="2018-06-01", end_date="2025-08-29"
):
    """
    生成模拟数据, 仅用于验证代码逻辑。
    模拟 n_concepts 个概念指数的日频价格, 以及一个基准指数。
    """
    np.random.seed(42)
    dates = pd.bdate_range(start=start_date, end=end_date)
    n_days = len(dates)

    # 概念指数: 对数正态随机游走
    codes = [f"CI{str(i).zfill(4)}" for i in range(n_concepts)]
    log_returns = np.random.normal(0.0002, 0.025, size=(n_days, n_concepts))
    cum_log_ret = np.cumsum(log_returns, axis=0)
    prices = pd.DataFrame(
        1000 * np.exp(cum_log_ret), index=dates, columns=codes
    )
    prices.index.name = "date"

    # 基准指数
    bm_log_ret = np.random.normal(0.0003, 0.012, size=n_days)
    benchmark = pd.Series(
        1000 * np.exp(np.cumsum(bm_log_ret)), index=dates, name="benchmark"
    )
    print(f"[Demo] 模拟价格矩阵: {prices.shape[0]} 天 x {prices.shape[1]} 个指数")
    return prices, benchmark, {}


# ================================================================
#  Part 2: 动量因子计算
# ================================================================

def calc_momentum_factor(prices, freq="W"):
    """
    计算动量因子 (过去一期收益率) 及下一期收益率。

    Parameters
    ----------
    prices : DataFrame, 日频收盘价, index=日期, columns=指数代码
    freq   : str, 'W' 周度 / 'M' 月度 (使用月末)

    Returns
    -------
    factor   : DataFrame, 动量因子值 (= 本期收益率)
    fwd_ret  : DataFrame, 下一期收益率
    freq_prices : DataFrame, 重采样后的价格
    """
    # 重采样到目标频率, 取最后一个交易日的价格
    if freq == "M":
        freq_prices = prices.resample("ME").last()
    else:
        freq_prices = prices.resample("W-FRI").last()

    # 动量因子 = 本期收益率
    factor = freq_prices.pct_change()

    # 下一期收益率 (用于检验因子预测能力)
    fwd_ret = factor.shift(-1)

    return factor, fwd_ret, freq_prices


# ================================================================
#  Part 3: Rank IC 检验
# ================================================================

def calc_rank_ic_series(factor, fwd_return, min_obs=30):
    """
    计算 Rank IC 时间序列。

    RankIC_t = spearmanr(Rank(X_{t,m}), Rank(r_{t+1,m}))

    Parameters
    ----------
    factor     : DataFrame, 因子值
    fwd_return : DataFrame, 下一期收益率
    min_obs    : int, 单截面最少有效观测数

    Returns
    -------
    ic_series : Series, index=日期, values=Rank IC
    """
    common_dates = factor.index.intersection(fwd_return.index)
    ic_dict = {}

    for dt in common_dates:
        f = factor.loc[dt].dropna()
        r = fwd_return.loc[dt].dropna()
        common_cols = f.index.intersection(r.index)
        if len(common_cols) < min_obs:
            continue
        ic_val, _ = stats.spearmanr(f[common_cols], r[common_cols])
        ic_dict[dt] = ic_val

    return pd.Series(ic_dict, name="RankIC")


def report_ic(ic_series, label=""):
    """打印因子 IC 统计指标"""
    mean_ic = ic_series.mean()
    std_ic = ic_series.std()
    icir = mean_ic / std_ic if std_ic > 0 else 0
    pct_pos = (ic_series > 0).mean()

    print(f"\n===== {label} Rank IC 统计 =====")
    print(f"  Mean IC   : {mean_ic:.4f}  ({mean_ic*100:.2f}%)")
    print(f"  Std IC    : {std_ic:.4f}")
    print(f"  IC IR     : {icir:.4f}")
    print(f"  IC > 0 占比: {pct_pos:.2%}")
    print(f"  期数      : {len(ic_series)}")
    return {"mean_ic": mean_ic, "std_ic": std_ic, "icir": icir, "pct_pos": pct_pos}


# ================================================================
#  Part 4: 分位数组合检验
# ================================================================

def quantile_portfolio_returns(factor, fwd_return, n_groups=10, min_obs=30):
    """
    按因子值从高到低将资产分为 n_groups 组,
    等权构建每组组合, 计算各组逐期收益率。

    Returns
    -------
    group_returns : DataFrame, index=日期, columns=Group1(Top)...Group10(Bottom)
    """
    common_dates = factor.index.intersection(fwd_return.index)
    records = []

    for dt in common_dates:
        f = factor.loc[dt].dropna()
        r = fwd_return.loc[dt].dropna()
        common_cols = f.index.intersection(r.index)
        if len(common_cols) < min_obs:
            continue

        f_sorted = f[common_cols].sort_values(ascending=False)
        r_aligned = r[common_cols]
        n = len(common_cols)
        group_size = n // n_groups
        row = {"date": dt}

        for g in range(n_groups):
            start = g * group_size
            end = start + group_size if g < n_groups - 1 else n
            members = f_sorted.index[start:end]
            row[f"G{g+1}"] = r_aligned[members].mean()

        records.append(row)

    group_ret = pd.DataFrame(records).set_index("date").sort_index()
    # 多空组合: Top(G1) - Bottom(G_last)
    group_ret["LS"] = group_ret["G1"] - group_ret[f"G{n_groups}"]
    return group_ret


def report_quantile(group_ret, label="", n_groups=10):
    """打印分位数组合的年化收益率和累计净值统计"""
    # 判断频率: 如果平均间隔小于10天, 视为周度
    avg_gap = (group_ret.index[-1] - group_ret.index[0]).days / len(group_ret)
    ann_factor = 52 if avg_gap < 10 else 12

    print(f"\n===== {label} 分位数组合统计 =====")
    cols = [f"G{g+1}" for g in range(n_groups)] + ["LS"]
    for col in cols:
        s = group_ret[col]
        cum = (1 + s).cumprod()
        total_ret = cum.iloc[-1] - 1
        ann_ret = (1 + total_ret) ** (ann_factor / len(s) * len(s) / ((group_ret.index[-1] - group_ret.index[0]).days / 365.25)) - 1
        # 更简洁的年化计算
        years = (group_ret.index[-1] - group_ret.index[0]).days / 365.25
        ann_ret = (cum.iloc[-1]) ** (1 / years) - 1 if years > 0 else 0
        ann_vol = s.std() * np.sqrt(ann_factor)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        tag = " <-- Top" if col == "G1" else (" <-- Bottom" if col == f"G{n_groups}" else (" <-- L-S" if col == "LS" else ""))
        print(f"  {col:>4s}: 年化收益={ann_ret:>8.2%}, 年化波动={ann_vol:>8.2%}, Sharpe={sharpe:>6.3f}{tag}")


# ================================================================
#  Part 5: Top 10% 动量策略
# ================================================================

def top_pct_strategy(factor, fwd_return, pct=0.1, min_obs=30):
    """
    每期选取动量因子排名前 pct 的概念指数, 等权构建组合。

    Returns
    -------
    strategy_ret : Series, 策略逐期收益率
    """
    common_dates = factor.index.intersection(fwd_return.index)
    strat_dict = {}

    for dt in common_dates:
        f = factor.loc[dt].dropna()
        r = fwd_return.loc[dt].dropna()
        common_cols = f.index.intersection(r.index)
        if len(common_cols) < min_obs:
            continue

        n_select = max(1, int(len(common_cols) * pct))
        top_codes = f[common_cols].nlargest(n_select).index
        strat_dict[dt] = r[top_codes].mean()

    return pd.Series(strat_dict, name="top_pct_strategy")


def equal_weight_benchmark_return(fwd_return, min_obs=30):
    """
    等权全样本组合 (用于对比), 或使用外部基准。
    """
    ret_dict = {}
    for dt in fwd_return.index:
        r = fwd_return.loc[dt].dropna()
        if len(r) < min_obs:
            continue
        ret_dict[dt] = r.mean()
    return pd.Series(ret_dict, name="equal_weight_all")


def calc_benchmark_period_return(benchmark_prices, freq="W"):
    """
    计算基准指数在对应频率下的收益率序列。
    """
    if freq == "M":
        bm_resampled = benchmark_prices.resample("ME").last()
    else:
        bm_resampled = benchmark_prices.resample("W-FRI").last()
    return bm_resampled.pct_change().dropna()


def report_strategy(strategy_ret, benchmark_ret, label=""):
    """
    报告策略 vs 基准的表现:
    年化收益、年化超额、信息比率、最大回撤等。
    """
    # 对齐日期
    common = strategy_ret.index.intersection(benchmark_ret.index)
    strat = strategy_ret.loc[common]
    bench = benchmark_ret.loc[common]
    excess = strat - bench

    # 累计净值
    strat_nav = (1 + strat).cumprod()
    bench_nav = (1 + bench).cumprod()
    excess_nav = (1 + excess).cumprod()

    years = (common[-1] - common[0]).days / 365.25

    ann_strat = strat_nav.iloc[-1] ** (1 / years) - 1 if years > 0 else 0
    ann_bench = bench_nav.iloc[-1] ** (1 / years) - 1 if years > 0 else 0
    ann_excess = excess_nav.iloc[-1] ** (1 / years) - 1 if years > 0 else 0

    avg_gap = (common[-1] - common[0]).days / len(common)
    ann_factor = 52 if avg_gap < 10 else 12
    excess_vol = excess.std() * np.sqrt(ann_factor)
    ir = ann_excess / excess_vol if excess_vol > 0 else 0

    # 最大回撤
    def max_drawdown(nav):
        peak = nav.cummax()
        dd = (nav - peak) / peak
        return dd.min()

    mdd_strat = max_drawdown(strat_nav)
    mdd_excess = max_drawdown(excess_nav)

    print(f"\n===== {label} Top 10% 策略表现 =====")
    print(f"  回测区间       : {common[0].strftime('%Y-%m-%d')} ~ {common[-1].strftime('%Y-%m-%d')}")
    print(f"  策略年化收益    : {ann_strat:.2%}")
    print(f"  基准年化收益    : {ann_bench:.2%}")
    print(f"  年化超额收益    : {ann_excess:.2%}")
    print(f"  超额波动率      : {excess_vol:.2%}")
    print(f"  信息比率 (IR)   : {ir:.4f}")
    print(f"  策略最大回撤    : {mdd_strat:.2%}")
    print(f"  超额最大回撤    : {mdd_excess:.2%}")

    return {
        "strat_nav": strat_nav,
        "bench_nav": bench_nav,
        "excess_nav": excess_nav,
        "ann_excess": ann_excess,
    }


# ================================================================
#  Part 6: 可视化
# ================================================================

def plot_ic_series(ic_weekly, ic_monthly, save_path="ic_series.png"):
    """绘制 IC 时间序列柱状图"""
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=False)

    for ax, ic, title in zip(
        axes,
        [ic_weekly, ic_monthly],
        ["周度动量因子 Rank IC", "月度动量因子 Rank IC"],
    ):
        colors = ["#d62728" if v >= 0 else "#2ca02c" for v in ic.values]
        ax.bar(ic.index, ic.values, width=5 if "周" in title else 15, color=colors, alpha=0.7)
        ax.axhline(0, color="black", linewidth=0.5)
        ax.axhline(ic.mean(), color="blue", linestyle="--", linewidth=1,
                    label=f"Mean IC = {ic.mean():.4f}")
        ax.set_title(title, fontsize=13)
        ax.set_ylabel("Rank IC")
        ax.legend(fontsize=10)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()
    print(f"[图表已保存] {save_path}")


def plot_quantile_nav(group_ret_weekly, group_ret_monthly, n_groups=10,
                      save_path="quantile_nav.png"):
    """绘制分位数组合累计净值"""
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))

    for idx, (gret, label) in enumerate([
        (group_ret_weekly, "周度"),
        (group_ret_monthly, "月度"),
    ]):
        # 左图: 各组净值
        ax = axes[idx, 0]
        for g in range(n_groups):
            col = f"G{g+1}"
            nav = (1 + gret[col]).cumprod()
            alpha = 1.0 if g == 0 or g == n_groups - 1 else 0.4
            lw = 2 if g == 0 or g == n_groups - 1 else 0.8
            label_g = f"G{g+1} (Top)" if g == 0 else (f"G{g+1} (Bottom)" if g == n_groups - 1 else f"G{g+1}")
            ax.plot(nav.index, nav.values, alpha=alpha, linewidth=lw, label=label_g)
        ax.set_title(f"{label}动量 - 分位数组合净值", fontsize=12)
        ax.set_ylabel("累计净值")
        ax.legend(fontsize=7, ncol=2, loc="upper left")
        ax.grid(True, alpha=0.3)

        # 右图: 多空净值
        ax2 = axes[idx, 1]
        ls_nav = (1 + gret["LS"]).cumprod()
        ax2.plot(ls_nav.index, ls_nav.values, color="#d62728", linewidth=1.5)
        ax2.axhline(1.0, color="gray", linestyle="--", linewidth=0.5)
        ax2.set_title(f"{label}动量 - 多空 (L-S) 净值", fontsize=12)
        ax2.set_ylabel("累计净值")
        ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()
    print(f"[图表已保存] {save_path}")


def plot_strategy_nav(results_weekly, results_monthly,
                      save_path="strategy_nav.png"):
    """绘制 Top 10% 策略净值及超额净值"""
    fig, axes = plt.subplots(2, 2, figsize=(16, 10))

    for idx, (res, label) in enumerate([
        (results_weekly, "周度"),
        (results_monthly, "月度"),
    ]):
        # 左: 策略 vs 基准
        ax = axes[idx, 0]
        ax.plot(res["strat_nav"].index, res["strat_nav"].values,
                label="Top 10% 策略", linewidth=1.5)
        ax.plot(res["bench_nav"].index, res["bench_nav"].values,
                label="中证全指", linewidth=1.5, alpha=0.8)
        ax.set_title(f"{label}动量 Top 10% 策略 vs 中证全指", fontsize=12)
        ax.set_ylabel("累计净值")
        ax.legend(fontsize=10)
        ax.grid(True, alpha=0.3)

        # 右: 超额净值
        ax2 = axes[idx, 1]
        ax2.plot(res["excess_nav"].index, res["excess_nav"].values,
                 color="#d62728", linewidth=1.5)
        ax2.axhline(1.0, color="gray", linestyle="--", linewidth=0.5)
        ax2.set_title(f"{label}动量 - 超额净值", fontsize=12)
        ax2.set_ylabel("超额累计净值")
        ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    plt.savefig(save_path, dpi=150, bbox_inches="tight")
    plt.show()
    print(f"[图表已保存] {save_path}")


# ================================================================
#  Part 7: 主流程
# ================================================================

def run_analysis(prices, benchmark, code_name_map, bt_start="2019-01-01"):
    """
    执行完整分析流程:
    1. 计算周度/月度动量因子
    2. Rank IC 检验
    3. 分位数组合检验
    4. Top 10% 策略 vs 基准
    """
    bt_start = pd.Timestamp(bt_start)

    # ---------- 1. 计算动量因子 ----------
    print("\n" + "=" * 60)
    print(" 计算动量因子")
    print("=" * 60)

    factor_w, fwd_w, fp_w = calc_momentum_factor(prices, freq="W")
    factor_m, fwd_m, fp_m = calc_momentum_factor(prices, freq="M")

    # 截取回测区间
    factor_w = factor_w.loc[factor_w.index >= bt_start]
    fwd_w = fwd_w.loc[fwd_w.index >= bt_start]
    factor_m = factor_m.loc[factor_m.index >= bt_start]
    fwd_m = fwd_m.loc[fwd_m.index >= bt_start]

    print(f"  周度因子: {factor_w.shape[0]} 期, {factor_w.shape[1]} 个指数")
    print(f"  月度因子: {factor_m.shape[0]} 期, {factor_m.shape[1]} 个指数")

    # ---------- 2. Rank IC ----------
    print("\n" + "=" * 60)
    print(" Rank IC 检验")
    print("=" * 60)

    ic_w = calc_rank_ic_series(factor_w, fwd_w)
    ic_m = calc_rank_ic_series(factor_m, fwd_m)

    stats_w = report_ic(ic_w, label="周度动量")
    stats_m = report_ic(ic_m, label="月度动量")

    # ---------- 3. 分位数组合 ----------
    print("\n" + "=" * 60)
    print(" 分位数组合检验 (10 组)")
    print("=" * 60)

    gret_w = quantile_portfolio_returns(factor_w, fwd_w, n_groups=10)
    gret_m = quantile_portfolio_returns(factor_m, fwd_m, n_groups=10)

    report_quantile(gret_w, label="周度动量", n_groups=10)
    report_quantile(gret_m, label="月度动量", n_groups=10)

    # ---------- 4. Top 10% 策略 vs 基准 ----------
    print("\n" + "=" * 60)
    print(" Top 10% 动量策略 vs 中证全指")
    print("=" * 60)

    strat_w = top_pct_strategy(factor_w, fwd_w, pct=0.1)
    strat_m = top_pct_strategy(factor_m, fwd_m, pct=0.1)

    # 基准收益率
    if benchmark is not None:
        bm_w = calc_benchmark_period_return(benchmark, freq="W")
        bm_m = calc_benchmark_period_return(benchmark, freq="M")
    else:
        # 无外部基准时, 使用全样本等权
        print("  [提示] 未提供基准数据, 使用全样本等权组合作为基准")
        bm_w = equal_weight_benchmark_return(fwd_w)
        bm_m = equal_weight_benchmark_return(fwd_m)

    res_w = report_strategy(strat_w, bm_w, label="周度动量")
    res_m = report_strategy(strat_m, bm_m, label="月度动量")

    # ---------- 5. 可视化 ----------
    print("\n" + "=" * 60)
    print(" 生成图表")
    print("=" * 60)

    try:
        plot_ic_series(ic_w, ic_m)
        plot_quantile_nav(gret_w, gret_m)
        plot_strategy_nav(res_w, res_m)
    except Exception as e:
        print(f"  [警告] 绘图失败 (可能无图形界面): {e}")
        print("  提示: 图表已保存为 PNG 文件, 可在本地查看。")

    # ---------- 汇总 ----------
    print("\n" + "=" * 60)
    print(" 结果汇总")
    print("=" * 60)
    print(f"  周度动量 Mean IC: {stats_w['mean_ic']*100:.2f}%  (研报参考值: 2.38%)")
    print(f"  月度动量 Mean IC: {stats_m['mean_ic']*100:.2f}%  (研报参考值: 1.35%)")
    print(f"  周度 Top10% 年化超额: {res_w['ann_excess']:.2%}  (研报参考值: 1.05%)")
    print(f"  月度 Top10% 年化超额: {res_m['ann_excess']:.2%}  (研报参考值: 1.12%)")


# ================================================================
#  命令行入口
# ================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Wind 热门概念指数动量因子分析"
    )
    parser.add_argument(
        "--source",
        type=str,
        default="demo",
        choices=["wind", "csv", "demo"],
        help="数据来源: wind / csv / demo",
    )
    parser.add_argument("--price_file", type=str, default=None, help="概念指数收盘价 CSV 路径")
    parser.add_argument("--benchmark_file", type=str, default=None, help="基准收盘价 CSV 路径")
    parser.add_argument("--start", type=str, default="2019-01-01", help="回测起始日期 (默认 2019-01-01)")
    parser.add_argument("--end", type=str, default="2025-08-29", help="回测截止日期 (默认 2025-08-29)")
    args = parser.parse_args()

    print("=" * 60)
    print(" Wind 热门概念指数动量因子分析")
    print("=" * 60)

    if args.source == "wind":
        # 获取数据时多取半年, 用于计算初始动量
        data_start = (pd.Timestamp(args.start) - pd.DateOffset(months=6)).strftime("%Y-%m-%d")
        prices, benchmark, name_map = load_data_wind(data_start, args.end)
    elif args.source == "csv":
        if not args.price_file:
            raise ValueError("CSV 模式需要 --price_file 参数")
        prices, benchmark, name_map = load_data_csv(args.price_file, args.benchmark_file)
    else:
        data_start = (pd.Timestamp(args.start) - pd.DateOffset(months=6)).strftime("%Y-%m-%d")
        prices, benchmark, name_map = load_data_demo(
            n_concepts=200, start_date=data_start, end_date=args.end
        )

    run_analysis(prices, benchmark, name_map, bt_start=args.start)


if __name__ == "__main__":
    main()
