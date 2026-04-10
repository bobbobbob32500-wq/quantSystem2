#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原策略优化版(legacy_opt)2026年2月历史回测
分析策略在不同时间段的表现
"""

import sys
import os
import numpy as np
import pandas as pd
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from backtest_legacy_opt_final import LegacyOptBacktesterFinal

def main():
    """主函数"""
    print("开始原策略优化版(legacy_opt)2026年2月历史回测...")
    print("=" * 80)
    
    try:
        # 初始化回测器
        backtester = LegacyOptBacktesterFinal()
        
        # 运行2026年2月回测
        print("运行2026年2月回测...")
        results_feb = backtester.run_backtest(
            start_date="2026-02-01",
            end_date="2026-02-28"
        )
        
        if not results_feb['dates']:
            print("2026年2月回测没有产生任何交易记录")
            return
        
        # 分析结果
        analysis_feb = backtester.analyze_results(results_feb)
        
        # 生成报告
        report_feb = backtester.generate_report(results_feb, analysis_feb)
        
        # 保存报告到文件
        report_file = "reports/legacy_opt_2026_feb_report.txt"
        os.makedirs(os.path.dirname(report_file), exist_ok=True)
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report_feb)
        print(f"\n2026年2月报告已保存到: {report_file}")
        
        # 保存详细数据到CSV
        csv_file = "reports/legacy_opt_2026_feb_details.csv"
        import pandas as pd
        df = pd.DataFrame({
            'date': results_feb['dates'],
            'symbol': results_feb['recommendations'],
            'buy_price': results_feb['buy_prices'],
            'sell_price_t2': results_feb['sell_prices_t2'],
            'sell_price_t3': results_feb['sell_prices_t3'],
            'sell_price_t4': results_feb['sell_prices_t4'],
            'sell_price_t5': results_feb['sell_prices_t5'],
            'return_t2': results_feb['returns_t2'],
            'return_t3': results_feb['returns_t3'],
            'return_t4': results_feb['returns_t4'],
            'return_t5': results_feb['returns_t5'],
        })
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"2026年2月详细数据已保存到: {csv_file}")
        
        # 与2025年9-11月结果对比
        print("\n" + "=" * 80)
        print("时间段对比分析")
        print("=" * 80)
        
        # 读取2025年9-11月的结果
        try:
            df_2025 = pd.read_csv("reports/legacy_opt_final_backtest_details.csv")
            
            # 计算2025年9-11月的统计
            returns_2025_t2 = df_2025['return_t2'].dropna()
            returns_2025_t3 = df_2025['return_t3'].dropna()
            returns_2025_t4 = df_2025['return_t4'].dropna()
            returns_2025_t5 = df_2025['return_t5'].dropna()
            
            # 2026年2月数据
            df_2026 = pd.DataFrame({
                'date': results_feb['dates'],
                'symbol': results_feb['recommendations'],
                'buy_price': results_feb['buy_prices'],
                'return_t2': results_feb['returns_t2'],
                'return_t3': results_feb['returns_t3'],
                'return_t4': results_feb['returns_t4'],
                'return_t5': results_feb['returns_t5'],
            })
            
            returns_2026_t2 = df_2026['return_t2'].dropna()
            returns_2026_t3 = df_2026['return_t3'].dropna()
            returns_2026_t4 = df_2026['return_t4'].dropna()
            returns_2026_t5 = df_2026['return_t5'].dropna()
            
            print("\n时间段对比:")
            print("-" * 100)
            print("持有期 | 时间段       | 交易次数 | 胜率(%) | 平均收益(%) | 最大收益(%) | 最小收益(%) | 标准差(%)")
            print("-" * 100)
            
            for period in [2, 3, 4, 5]:
                # 2025年数据
                if len(returns_2025_t2) > 0:
                    returns_2025 = [returns_2025_t2, returns_2025_t3, returns_2025_t4, returns_2025_t5][period-2]
                    win_rate_2025 = (returns_2025 > 0).mean() * 100
                    avg_return_2025 = returns_2025.mean() * 100
                    max_return_2025 = returns_2025.max() * 100
                    min_return_2025 = returns_2025.min() * 100
                    std_return_2025 = returns_2025.std() * 100
                    
                    print(f"T+{period}   | 2025.09-11 | {len(returns_2025):8d} | {win_rate_2025:7.2f} | {avg_return_2025:10.2f} | {max_return_2025:10.2f} | {min_return_2025:10.2f} | {std_return_2025:9.2f}")
                
                # 2026年数据
                if len(returns_2026_t2) > 0:
                    returns_2026 = [returns_2026_t2, returns_2026_t3, returns_2026_t4, returns_2026_t5][period-2]
                    win_rate_2026 = (returns_2026 > 0).mean() * 100
                    avg_return_2026 = returns_2026.mean() * 100
                    max_return_2026 = returns_2026.max() * 100
                    min_return_2026 = returns_2026.min() * 100
                    std_return_2026 = returns_2026.std() * 100
                    
                    print(f"T+{period}   | 2026.02    | {len(returns_2026):8d} | {win_rate_2026:7.2f} | {avg_return_2026:10.2f} | {max_return_2026:10.2f} | {min_return_2026:10.2f} | {std_return_2026:9.2f}")
            
            # 总体对比分析
            print("\n" + "=" * 80)
            print("策略表现时间对比分析")
            print("=" * 80)
            
            # 计算总体表现
            all_returns_2025 = []
            for period in [2, 3, 4, 5]:
                returns = [returns_2025_t2, returns_2025_t3, returns_2025_t4, returns_2025_t5][period-2]
                all_returns_2025.extend(returns.tolist())
            
            all_returns_2026 = []
            for period in [2, 3, 4, 5]:
                returns = [returns_2026_t2, returns_2026_t3, returns_2026_t4, returns_2026_t5][period-2]
                all_returns_2026.extend(returns.tolist())
            
            if all_returns_2025 and all_returns_2026:
                avg_2025 = np.mean(all_returns_2025) * 100
                win_rate_2025 = (np.array(all_returns_2025) > 0).mean() * 100
                sharpe_2025 = (np.mean(all_returns_2025) / np.std(all_returns_2025) * np.sqrt(252)) if np.std(all_returns_2025) > 0 else 0
                
                avg_2026 = np.mean(all_returns_2026) * 100
                win_rate_2026 = (np.array(all_returns_2026) > 0).mean() * 100
                sharpe_2026 = (np.mean(all_returns_2026) / np.std(all_returns_2026) * np.sqrt(252)) if np.std(all_returns_2026) > 0 else 0
                
                print(f"\n2025年9-11月总体表现:")
                print(f"  平均收益: {avg_2025:.2f}%")
                print(f"  胜率: {win_rate_2025:.2f}%")
                print(f"  夏普比率: {sharpe_2025:.2f}")
                
                print(f"\n2026年2月总体表现:")
                print(f"  平均收益: {avg_2026:.2f}%")
                print(f"  胜率: {win_rate_2026:.2f}%")
                print(f"  夏普比率: {sharpe_2026:.2f}")
                
                print(f"\n表现变化:")
                print(f"  平均收益变化: {avg_2026 - avg_2025:+.2f}%")
                print(f"  胜率变化: {win_rate_2026 - win_rate_2025:+.2f}%")
                print(f"  夏普比率变化: {sharpe_2026 - sharpe_2025:+.2f}")
                
                # 策略稳定性分析
                if abs(avg_2026 - avg_2025) < 1.0 and abs(win_rate_2026 - win_rate_2025) < 5.0:
                    print(f"\n结论: 策略在不同时间段表现相对稳定")
                else:
                    print(f"\n结论: 策略在不同时间段表现有显著差异")
                    if avg_2026 > avg_2025:
                        print(f"      2026年2月表现优于2025年9-11月")
                    else:
                        print(f"      2026年2月表现差于2025年9-11月")
            
        except FileNotFoundError:
            print("警告: 未找到2025年9-11月的回测数据文件")
            print("只生成2026年2月的回测报告")
        
        # 打印2026年2月报告摘要
        print("\n" + "=" * 80)
        print("2026年2月回测结果摘要")
        print("=" * 80)
        print(f"总交易次数: {analysis_feb.get('total_trades', 0)}")
        print(f"涉及股票数: {analysis_feb.get('unique_stocks', 0)}")
        print(f"交易日数: {analysis_feb.get('trading_days', 0)}")
        
        for period in [2, 3, 4, 5]:
            trades = analysis_feb.get(f't{period}_total_trades', 0)
            if trades > 0:
                win_rate = analysis_feb.get(f't{period}_win_rate', 0)
                avg_return = analysis_feb.get(f't{period}_avg_return', 0)
                print(f"T+{period}: {trades}次交易, 胜率{win_rate:.1f}%, 平均收益{avg_return:.2f}%")
        
    except Exception as e:
        print(f"回测过程中出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()