import pandas as pd
import numpy as np
from datetime import datetime

# 读取回测数据
backtest_daily = pd.read_csv('results/backtest_daily_20260331_020340.csv')

# 转换日期列
backtest_daily['rec_date'] = pd.to_datetime(backtest_daily['rec_date'], format='%Y%m%d')
backtest_daily['buy_date'] = pd.to_datetime(backtest_daily['buy_date'], format='%Y%m%d')
backtest_daily['sell_date'] = pd.to_datetime(backtest_daily['sell_date'], format='%Y%m%d')

# 计算持仓天数
backtest_daily['hold_days'] = (backtest_daily['sell_date'] - backtest_daily['buy_date']).dt.days

print('=' * 80)
print('参数敏感性与鲁棒性测试')
print('=' * 80)

# 1. 分析策略参数对收益的影响
print('\n1. 策略参数对收益的影响分析')
print('-' * 60)

# 按策略分组分析
strategy_groups = backtest_daily.groupby('strategy')
strategy_results = []

for strategy, group in strategy_groups:
    count = len(group)
    avg_return = group['net_return'].mean()
    std_return = group['net_return'].std()
    win_rate = (group['net_return'] > 0).sum() / count * 100
    avg_score = group['score'].mean()
    avg_hold_days = group['hold_days'].mean()
    
    strategy_results.append({
        '策略': strategy,
        '交易次数': count,
        '平均收益(%)': round(avg_return, 2),
        '收益波动(%)': round(std_return, 2),
        '胜率(%)': round(win_rate, 2),
        '平均评分': round(avg_score, 2),
        '平均持仓天数': round(avg_hold_days, 2)
    })

strategy_df = pd.DataFrame(strategy_results)
print(strategy_df.to_string(index=False))

# 2. 评分系统有效性分析
print('\n\n2. 评分系统有效性分析')
print('-' * 60)

# 创建评分区间
bins = [0, 60, 70, 80, 90, 100]
labels = ['<60', '60-70', '70-80', '80-90', '90-100']
backtest_daily['score_bin'] = pd.cut(backtest_daily['score'], bins=bins, labels=labels)

score_results = []
for label in labels:
    group = backtest_daily[backtest_daily['score_bin'] == label]
    if len(group) > 0:
        count = len(group)
        avg_return = group['net_return'].mean()
        std_return = group['net_return'].std()
        win_rate = (group['net_return'] > 0).sum() / count * 100
        avg_hold_days = group['hold_days'].mean()
        
        score_results.append({
            '评分区间': label,
            '交易次数': count,
            '平均收益(%)': round(avg_return, 2),
            '收益波动(%)': round(std_return, 2),
            '胜率(%)': round(win_rate, 2),
            '平均持仓天数': round(avg_hold_days, 2)
        })

score_df = pd.DataFrame(score_results)
print(score_df.to_string(index=False))

# 3. 持仓天数与收益关系
print('\n\n3. 持仓天数与收益关系分析')
print('-' * 60)

hold_results = []
for hold_days in sorted(backtest_daily['hold_days'].unique()):
    if hold_days <= 10:  # 只显示前10天
        group = backtest_daily[backtest_daily['hold_days'] == hold_days]
        if len(group) > 0:
            count = len(group)
            avg_return = group['net_return'].mean()
            std_return = group['net_return'].std()
            win_rate = (group['net_return'] > 0).sum() / count * 100
            
            hold_results.append({
                '持仓天数': hold_days,
                '交易次数': count,
                '平均收益(%)': round(avg_return, 2),
                '收益波动(%)': round(std_return, 2),
                '胜率(%)': round(win_rate, 2)
            })

hold_df = pd.DataFrame(hold_results)
print(hold_df.to_string(index=False))

# 4. 参数敏感性模拟
print('\n\n4. 参数敏感性分析')
print('-' * 60)

# 分析不同评分阈值的效果
score_thresholds = [60, 70, 80, 85, 90]
sensitivity_results = []

for threshold in score_thresholds:
    high_score_trades = backtest_daily[backtest_daily['score'] >= threshold]
    if len(high_score_trades) > 0:
        avg_return = high_score_trades['net_return'].mean()
        win_rate = (high_score_trades['net_return'] > 0).sum() / len(high_score_trades) * 100
        sensitivity_results.append({
            '评分阈值': threshold,
            '交易次数': len(high_score_trades),
            '平均收益(%)': round(avg_return, 2),
            '胜率(%)': round(win_rate, 2)
        })

sensitivity_df = pd.DataFrame(sensitivity_results)
print('评分阈值敏感性分析:')
print(sensitivity_df.to_string(index=False))

# 5. 鲁棒性测试 - 不同时间段表现
print('\n\n5. 策略鲁棒性测试（不同时间段）')
print('-' * 60)

# 按月份分析
backtest_daily['buy_month'] = backtest_daily['buy_date'].dt.month
month_results = []

for month in sorted(backtest_daily['buy_month'].unique()):
    month_trades = backtest_daily[backtest_daily['buy_month'] == month]
    if len(month_trades) > 0:
        count = len(month_trades)
        avg_return = month_trades['net_return'].mean()
        std_return = month_trades['net_return'].std()
        win_rate = (month_trades['net_return'] > 0).sum() / count * 100
        
        month_results.append({
            '月份': month,
            '交易次数': count,
            '平均收益(%)': round(avg_return, 2),
            '收益波动(%)': round(std_return, 2),
            '胜率(%)': round(win_rate, 2)
        })

month_df = pd.DataFrame(month_results)
print('月度表现分析:')
print(month_df.to_string(index=False))

# 计算月度表现稳定性
monthly_returns = month_df['平均收益(%)']
monthly_win_rates = month_df['胜率(%)']

print('\n月度收益稳定性:')
print('平均月度收益: ' + str(round(monthly_returns.mean(), 2)) + '%')
print('月度收益标准差: ' + str(round(monthly_returns.std(), 2)) + '%')
print('正收益月份比例: ' + str(round((monthly_returns > 0).sum() / len(monthly_returns) * 100, 1)) + '%')

print('\n月度胜率稳定性:')
print('平均月度胜率: ' + str(round(monthly_win_rates.mean(), 2)) + '%')
print('月度胜率标准差: ' + str(round(monthly_win_rates.std(), 2)) + '%')
print('胜率超过40%的月份比例: ' + str(round((monthly_win_rates > 40).sum() / len(monthly_win_rates) * 100, 1)) + '%')

# 6. 策略失效分析
print('\n\n6. 策略失效情况分析')
print('-' * 60)

# 识别亏损交易
loss_trades = backtest_daily[backtest_daily['net_return'] < 0]
if len(loss_trades) > 0:
    print('亏损交易总数: ' + str(len(loss_trades)) + ' (' + str(round(len(loss_trades)/len(backtest_daily)*100, 1)) + '%)')
    
    # 分析亏损交易特征
    loss_results = []
    for strategy, group in loss_trades.groupby('strategy'):
        count = len(group)
        avg_loss = group['net_return'].mean()
        max_loss = group['net_return'].min()
        avg_score = group['score'].mean()
        
        loss_results.append({
            '策略': strategy,
            '亏损次数': count,
            '平均亏损(%)': round(avg_loss, 2),
            '最大亏损(%)': round(max_loss, 2),
            '平均评分': round(avg_score, 2)
        })
    
    loss_df = pd.DataFrame(loss_results)
    print('\n各策略亏损情况:')
    print(loss_df.to_string(index=False))
    
    # 分析高评分但亏损的交易
    high_score_loss = loss_trades[loss_trades['score'] >= 80]
    if len(high_score_loss) > 0:
        print('\n高评分(≥80)但亏损的交易: ' + str(len(high_score_loss)) + '笔')
        print('平均评分: ' + str(round(high_score_loss['score'].mean(), 1)))
        print('平均亏损: ' + str(round(high_score_loss['net_return'].mean(), 2)) + '%')
        print('最大亏损: ' + str(round(high_score_loss['net_return'].min(), 2)) + '%')

# 7. 参数优化建议
print('\n\n7. 参数优化建议')
print('-' * 60)

print('基于参数敏感性分析，建议:')
print('1. 评分系统优化:')
if not sensitivity_df.empty:
    best_idx = sensitivity_df['平均收益(%)'].idxmax()
    best_threshold = sensitivity_df.loc[best_idx, '评分阈值']
    best_return = sensitivity_df.loc[best_idx, '平均收益(%)']
    print('   • 最佳评分阈值: ' + str(best_threshold) + ' (平均收益' + str(best_return) + '%)')
    print('   • 建议将评分阈值提高到' + str(best_threshold) + '以上')
else:
    print('   • 评分阈值敏感性分析数据不足')

print('\n2. 持仓周期优化:')
if not hold_df.empty:
    best_idx = hold_df['平均收益(%)'].idxmax()
    best_hold_days = hold_df.loc[best_idx, '持仓天数']
    best_return = hold_df.loc[best_idx, '平均收益(%)']
    print('   • 最佳持仓天数: ' + str(best_hold_days) + '天 (平均收益' + str(best_return) + '%)')
    print('   • 建议将最大持仓天数限制在' + str(best_hold_days) + '天以内')
else:
    print('   • 持仓天数分析数据不足')

print('\n3. 市场环境适应性:')
if not month_df.empty:
    best_idx = month_df['平均收益(%)'].idxmax()
    worst_idx = month_df['平均收益(%)'].idxmin()
    best_month = month_df.loc[best_idx, '月份']
    worst_month = month_df.loc[worst_idx, '月份']
    best_return = month_df.loc[best_idx, '平均收益(%)']
    worst_return = month_df.loc[worst_idx, '平均收益(%)']
    print('   • 表现最佳月份: ' + str(best_month) + '月 (平均收益' + str(best_return) + '%)')
    print('   • 表现最差月份: ' + str(worst_month) + '月 (平均收益' + str(worst_return) + '%)')
    print('   • 建议在' + str(worst_month) + '月降低仓位或暂停交易')
else:
    print('   • 月度分析数据不足')

print('\n4. 风险控制建议:')
if len(loss_trades) > 0:
    avg_loss = loss_trades['net_return'].mean()
    max_loss = loss_trades['net_return'].min()
    print('   • 平均亏损: ' + str(round(avg_loss, 2)) + '%')
    print('   • 最大亏损: ' + str(round(max_loss, 2)) + '%')
    print('   • 建议设置止损线在' + str(round(abs(max_loss)*0.7, 1)) + '%左右')
else:
    print('   • 无亏损交易数据')

print('\n5. 策略组合优化:')
if not strategy_df.empty:
    best_idx = strategy_df['平均收益(%)'].idxmax()
    worst_idx = strategy_df['平均收益(%)'].idxmin()
    best_strategy = strategy_df.loc[best_idx, '策略']
    worst_strategy = strategy_df.loc[worst_idx, '策略']
    best_return = strategy_df.loc[best_idx, '平均收益(%)']
    worst_return = strategy_df.loc[worst_idx, '平均收益(%)']
    print('   • 表现最佳策略: ' + best_strategy + ' (平均收益' + str(best_return) + '%)')
    print('   • 表现最差策略: ' + worst_strategy + ' (平均收益' + str(worst_return) + '%)')
    print('   • 建议增加' + best_strategy + '的权重，减少' + worst_strategy + '的权重')
else:
    print('   • 策略分析数据不足')

# 8. 鲁棒性评分
print('\n\n8. 策略鲁棒性评分')
print('-' * 60)

# 计算鲁棒性指标
robustness_metrics = {}

# 1) 时间稳定性
if not month_df.empty and monthly_returns.mean() != 0:
    time_stability = 1 - (monthly_returns.std() / abs(monthly_returns.mean()))
    robustness_metrics['时间稳定性'] = max(0, min(1, time_stability))
else:
    robustness_metrics['时间稳定性'] = 0.5

# 2) 评分有效性
if len(score_df) >= 2:
    high_score_win = score_df[score_df['评分区间'] == '90-100']['胜率(%)'].values[0] if '90-100' in score_df['评分区间'].values else 0
    low_score_win = score_df[score_df['评分区间'] == '<60']['胜率(%)'].values[0] if '<60' in score_df['评分区间'].values else 0
    score_effectiveness = (high_score_win - low_score_win) / 100
    robustness_metrics['评分有效性'] = max(0, min(1, score_effectiveness))
else:
    robustness_metrics['评分有效性'] = 0.5

# 3) 参数敏感性
if not sensitivity_df.empty and sensitivity_df['平均收益(%)'].mean() != 0:
    param_sensitivity_score = 1 - (sensitivity_df['平均收益(%)'].std() / abs(sensitivity_df['平均收益(%)'].mean()))
    robustness_metrics['参数稳定性'] = max(0, min(1, param_sensitivity_score))
else:
    robustness_metrics['参数稳定性'] = 0.5

# 4) 市场适应性
if not month_df.empty:
    market_adaptability = (month_df['胜率(%)'] > 40).sum() / len(month_df)
    robustness_metrics['市场适应性'] = market_adaptability
else:
    robustness_metrics['市场适应性'] = 0.5

# 5) 风险控制
if len(backtest_daily) > 0:
    risk_control = 1 - (len(loss_trades) / len(backtest_daily))
    robustness_metrics['风险控制'] = risk_control
else:
    robustness_metrics['风险控制'] = 0.5

print('鲁棒性指标评分 (0-1, 越高越好):')
for metric, score in robustness_metrics.items():
    print('  ' + metric + ': ' + str(round(score, 3)))

overall_robustness = np.mean(list(robustness_metrics.values()))
print('\n综合鲁棒性评分: ' + str(round(overall_robustness, 3)))

if overall_robustness >= 0.7:
    print('✓ 策略鲁棒性良好')
elif overall_robustness >= 0.5:
    print('⚠ 策略鲁棒性一般，需要优化')
else:
    print('✗ 策略鲁棒性较差，需要大幅改进')