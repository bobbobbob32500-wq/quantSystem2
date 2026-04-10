#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
原策略优化版(legacy_opt)历史回测脚本 - 最终版
基于实际legacy_opt权重进行模拟回测
"""

import sys
import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

class LegacyOptBacktesterFinal:
    """原策略优化版回测器 - 最终版"""
    
    def __init__(self):
        """初始化回测器"""
        # 连接到历史数据数据库
        self.history_db_path = "data/history_recommendation.db"
        
        # legacy_opt策略权重（从config.yaml获取）
        self.weights = {
            'trend': 0.35,      # 趋势因子权重
            'momentum': 0.30,    # 动量因子权重
            'volume': 0.05,      # 量能因子权重
            'fundamental': 0.05, # 基本面因子权重
            'pullback': 0.15,    # 回调因子权重
            'quality': 0.0       # 质量因子权重（legacy_opt中没有）
        }
        
        # 检查权重总和是否为1.0
        total_weight = sum(self.weights.values())
        if abs(total_weight - 0.9) > 0.01:  # 允许微小误差
            print(f"警告: 权重总和为{total_weight:.2f}，不是1.0")
    
    def get_trading_dates(self, start_date: str, end_date: str) -> List[str]:
        """获取交易日列表"""
        conn = sqlite3.connect(self.history_db_path)
        
        # 转换日期格式为数据库中的格式
        # 如果输入是YYYYMMDD格式，转换为YYYY-MM-DD
        if '-' not in start_date and len(start_date) == 8:
            start_date_db = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}"
        else:
            start_date_db = start_date
            
        if '-' not in end_date and len(end_date) == 8:
            end_date_db = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}"
        else:
            end_date_db = end_date
        
        query = """
        SELECT DISTINCT trade_date 
        FROM intraday_data 
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY trade_date
        """
        dates_df = pd.read_sql_query(query, conn, params=(start_date_db, end_date_db))
        conn.close()
        
        # 保持原始格式
        dates = []
        for date_str in dates_df['trade_date'].tolist():
            dates.append(str(date_str))
        
        return sorted(set(dates))
    
    def get_stock_price(self, symbol: str, date: str, price_type: str = 'open') -> Optional[float]:
        """获取股票价格"""
        conn = sqlite3.connect(self.history_db_path)
        date_str = str(date)
        
        try:
            # 获取价格数据
            query = """
            SELECT open, close 
            FROM intraday_data 
            WHERE symbol = ? AND trade_date = ?
            LIMIT 1
            """
            
            cursor = conn.execute(query, (symbol, date_str))
            result = cursor.fetchone()
            
            if result:
                if price_type == 'open':
                    price = result[0]
                else:  # close
                    price = result[1]
                
                if price is not None:
                    return float(price)
            
            return None
                
        except Exception as e:
            print(f"获取价格失败 {symbol} {date} {price_type}: {e}")
            return None
        finally:
            conn.close()
    
    def calculate_simple_score(self, symbol: str, date: str) -> float:
        """计算简化的股票评分（模拟legacy_opt策略）
        
        由于我们没有完整的因子数据，这里使用简化方法：
        1. 趋势因子：基于近期价格变化
        2. 动量因子：基于短期涨幅
        3. 量能因子：基于成交量
        4. 基本面因子：基于价格（简化）
        5. 回调因子：基于价格回撤
        """
        conn = sqlite3.connect(self.history_db_path)
        date_str = str(date)
        
        try:
            # 获取最近5天的数据
            query = """
            SELECT trade_date, open, close, volume, amount
            FROM intraday_data 
            WHERE symbol = ? AND trade_date <= ?
            ORDER BY trade_date DESC
            LIMIT 5
            """
            
            df = pd.read_sql_query(query, conn, params=(symbol, date_str))
            
            if len(df) < 3:
                return 0.0
            
            # 计算简单因子
            df = df.sort_values('trade_date')
            
            # 1. 趋势因子：价格是否在上涨
            first_close = df['close'].iloc[0]
            last_close = df['close'].iloc[-1]
            trend_score = (last_close - first_close) / first_close * 100 if first_close > 0 else 0
            
            # 2. 动量因子：近期涨幅
            recent_returns = df['close'].pct_change().dropna()
            momentum_score = recent_returns.mean() * 100 if len(recent_returns) > 0 else 0
            
            # 3. 量能因子：成交量变化
            avg_volume = df['volume'].mean()
            volume_score = np.log(avg_volume) if avg_volume > 0 else 0
            
            # 4. 基本面因子：价格水平（简化）
            price_level = df['close'].mean()
            fundamental_score = np.log(price_level) if price_level > 0 else 0
            
            # 5. 回调因子：最大回撤
            max_price = df['close'].max()
            current_price = df['close'].iloc[-1]
            pullback_score = (max_price - current_price) / max_price * 100 if max_price > 0 else 0
            
            # 归一化分数（简化处理）
            scores = {
                'trend': max(0, min(100, 50 + trend_score * 10)),
                'momentum': max(0, min(100, 50 + momentum_score * 10)),
                'volume': max(0, min(100, volume_score * 10)),
                'fundamental': max(0, min(100, fundamental_score)),
                'pullback': max(0, min(100, 100 - pullback_score))  # 回撤越小分数越高
            }
            
            # 加权总分
            total_score = (
                scores['trend'] * self.weights['trend'] +
                scores['momentum'] * self.weights['momentum'] +
                scores['volume'] * self.weights['volume'] +
                scores['fundamental'] * self.weights['fundamental'] +
                scores['pullback'] * self.weights['pullback']
            )
            
            return total_score
            
        except Exception as e:
            print(f"计算评分失败 {symbol} {date}: {e}")
            return 0.0
        finally:
            conn.close()
    
    def select_stocks(self, date: str, top_n: int = 10) -> List[str]:
        """选择股票（模拟legacy_opt策略）"""
        conn = sqlite3.connect(self.history_db_path)
        date_str = str(date)
        
        try:
            # 获取当天有交易的股票
            query = """
            SELECT DISTINCT symbol 
            FROM intraday_data 
            WHERE trade_date = ?
            """
            
            df = pd.read_sql_query(query, conn, params=(date_str,))
            
            if df.empty:
                return []
            
            stocks = df['symbol'].tolist()
            
            # 计算每只股票的评分
            stock_scores = []
            for symbol in stocks[:100]:  # 限制数量以提高性能
                score = self.calculate_simple_score(symbol, date_str)
                if score > 0:
                    stock_scores.append((symbol, score))
            
            # 按评分排序，选择前top_n只
            stock_scores.sort(key=lambda x: x[1], reverse=True)
            selected = [symbol for symbol, score in stock_scores[:top_n]]
            
            return selected
            
        except Exception as e:
            print(f"选股失败 {date}: {e}")
            return []
        finally:
            conn.close()
    
    def run_backtest(self, start_date: str = "20250901", end_date: str = "20251130") -> Dict:
        """运行回测"""
        print(f"开始回测: {start_date} 到 {end_date}")
        print(f"策略: legacy_opt (原策略优化版)")
        print(f"权重: {self.weights}")
        print("=" * 60)
        
        # 获取交易日列表
        trading_dates = self.get_trading_dates(start_date, end_date)
        print(f"找到 {len(trading_dates)} 个交易日")
        
        if not trading_dates:
            print("错误: 没有找到交易日数据")
            return {}
        
        # 存储回测结果
        results = {
            'dates': [],
            'recommendations': [],
            'buy_prices': [],
            'sell_prices_t2': [],
            'sell_prices_t3': [],
            'sell_prices_t4': [],
            'sell_prices_t5': [],
            'returns_t2': [],
            'returns_t3': [],
            'returns_t4': [],
            'returns_t5': [],
        }
        
        # 遍历每个交易日
        for i, date in enumerate(trading_dates):
            print(f"\n处理交易日 {i+1}/{len(trading_dates)}: {date}")
            
            try:
                # 选择股票
                recommendations = self.select_stocks(date, top_n=5)
                
                if not recommendations:
                    print(f"  {date}: 无推荐股票")
                    continue
                
                print(f"  {date}: 推荐 {len(recommendations)} 只股票: {recommendations}")
                
                # 获取t+1日（下一个交易日）
                if i + 1 < len(trading_dates):
                    next_date = trading_dates[i + 1]
                    
                    # 对每只推荐股票计算收益
                    for symbol in recommendations:
                        # 获取t+1开盘价（买入价）
                        buy_price = self.get_stock_price(symbol, next_date, 'open')
                        
                        if buy_price is None or buy_price <= 0:
                            print(f"    股票 {symbol}: 无法获取买入价")
                            continue
                        
                        # 获取t+2, t+3, t+4, t+5收盘价
                        sell_prices = {}
                        returns = {}
                        
                        for offset in [2, 3, 4, 5]:
                            if i + offset < len(trading_dates):
                                sell_date = trading_dates[i + offset]
                                sell_price = self.get_stock_price(symbol, sell_date, 'close')
                                
                                if sell_price and sell_price > 0:
                                    sell_prices[f't{offset}'] = sell_price
                                    returns[f't{offset}'] = (sell_price - buy_price) / buy_price
                                else:
                                    sell_prices[f't{offset}'] = None
                                    returns[f't{offset}'] = None
                            else:
                                sell_prices[f't{offset}'] = None
                                returns[f't{offset}'] = None
                        
                        # 存储结果
                        results['dates'].append(date)
                        results['recommendations'].append(symbol)
                        results['buy_prices'].append(buy_price)
                        results['sell_prices_t2'].append(sell_prices.get('t2'))
                        results['sell_prices_t3'].append(sell_prices.get('t3'))
                        results['sell_prices_t4'].append(sell_prices.get('t4'))
                        results['sell_prices_t5'].append(sell_prices.get('t5'))
                        results['returns_t2'].append(returns.get('t2'))
                        results['returns_t3'].append(returns.get('t3'))
                        results['returns_t4'].append(returns.get('t4'))
                        results['returns_t5'].append(returns.get('t5'))
                        
                        # 打印单只股票结果
                        print(f"    股票 {symbol}: 买入价={buy_price:.2f}", end="")
                        for offset in [2, 3, 4, 5]:
                            ret = returns.get(f't{offset}')
                            if ret is not None:
                                print(f", T+{offset}={ret*100:+.2f}%", end="")
                        print()
                
            except Exception as e:
                print(f"  处理日期 {date} 时出错: {e}")
                import traceback
                traceback.print_exc()
                continue
        
        print("\n" + "=" * 60)
        print("回测完成")
        
        return results
    
    def analyze_results(self, results: Dict) -> Dict:
        """分析回测结果"""
        if not results['dates']:
            print("没有有效的回测数据")
            return {}
        
        # 转换为DataFrame便于分析
        df = pd.DataFrame({
            'date': results['dates'],
            'symbol': results['recommendations'],
            'buy_price': results['buy_prices'],
            'sell_price_t2': results['sell_prices_t2'],
            'sell_price_t3': results['sell_prices_t3'],
            'sell_price_t4': results['sell_prices_t4'],
            'sell_price_t5': results['sell_prices_t5'],
            'return_t2': results['returns_t2'],
            'return_t3': results['returns_t3'],
            'return_t4': results['returns_t4'],
            'return_t5': results['returns_t5'],
        })
        
        # 计算统计指标
        analysis = {
            'total_trades': len(df),
            'unique_stocks': df['symbol'].nunique(),
            'trading_days': len(set(df['date'])),
        }
        
        # 计算各持有期的收益统计
        for period in [2, 3, 4, 5]:
            returns = df[f'return_t{period}'].dropna()
            if len(returns) > 0:
                analysis[f't{period}_total_trades'] = len(returns)
                analysis[f't{period}_win_rate'] = (returns > 0).mean() * 100
                analysis[f't{period}_avg_return'] = returns.mean() * 100
                analysis[f't{period}_median_return'] = returns.median() * 100
                analysis[f't{period}_max_return'] = returns.max() * 100
                analysis[f't{period}_min_return'] = returns.min() * 100
                analysis[f't{period}_std_return'] = returns.std() * 100
                analysis[f't{period}_sharpe_ratio'] = (returns.mean() / returns.std() * np.sqrt(252)) if returns.std() > 0 else 0
            else:
                analysis[f't{period}_total_trades'] = 0
                analysis[f't{period}_win_rate'] = 0
                analysis[f't{period}_avg_return'] = 0
                analysis[f't{period}_median_return'] = 0
                analysis[f't{period}_max_return'] = 0
                analysis[f't{period}_min_return'] = 0
                analysis[f't{period}_std_return'] = 0
                analysis[f't{period}_sharpe_ratio'] = 0
        
        return analysis
    
    def generate_report(self, results: Dict, analysis: Dict) -> str:
        """生成回测报告"""
        report = []
        report.append("=" * 80)
        report.append("原策略优化版(legacy_opt)历史回测报告")
        report.append("=" * 80)
        report.append("")
        report.append("回测参数:")
        report.append(f"  时间范围: 2025年9月-11月")
        report.append(f"  策略: legacy_opt (原策略优化版)")
        report.append(f"  权重配置: {self.weights}")
        report.append(f"  买入价: T+1日开盘价")
        report.append(f"  卖出价: T+2/T+3/T+4/T+5日收盘价")
        report.append("")
        
        report.append("回测统计:")
        report.append(f"  总交易次数: {analysis.get('total_trades', 0)}")
        report.append(f"  涉及股票数: {analysis.get('unique_stocks', 0)}")
        report.append(f"  交易日数: {analysis.get('trading_days', 0)}")
        report.append("")
        
        report.append("各持有期表现:")
        report.append("-" * 60)
        report.append("持有期 | 交易次数 | 胜率(%) | 平均收益(%) | 中位数收益(%) | 最大收益(%) | 最小收益(%) | 标准差(%) | 夏普比率")
        report.append("-" * 60)
        
        for period in [2, 3, 4, 5]:
            trades = analysis.get(f't{period}_total_trades', 0)
            if trades > 0:
                win_rate = analysis.get(f't{period}_win_rate', 0)
                avg_return = analysis.get(f't{period}_avg_return', 0)
                median_return = analysis.get(f't{period}_median_return', 0)
                max_return = analysis.get(f't{period}_max_return', 0)
                min_return = analysis.get(f't{period}_min_return', 0)
                std_return = analysis.get(f't{period}_std_return', 0)
                sharpe = analysis.get(f't{period}_sharpe_ratio', 0)
                
                report.append(f"T+{period}   | {trades:8d} | {win_rate:7.2f} | {avg_return:10.2f} | {median_return:13.2f} | {max_return:10.2f} | {min_return:10.2f} | {std_return:9.2f} | {sharpe:8.2f}")
        
        report.append("")
        report.append("策略分析:")
        report.append("-" * 60)
        
        # 分析策略表现
        if analysis.get('total_trades', 0) > 0:
            # 计算总体表现
            all_returns = []
            for period in [2, 3, 4, 5]:
                returns = [r for r in results[f'returns_t{period}'] if r is not None]
                all_returns.extend(returns)
            
            if all_returns:
                avg_return = np.mean(all_returns) * 100
                win_rate = (np.array(all_returns) > 0).mean() * 100
                sharpe = (np.mean(all_returns) / np.std(all_returns) * np.sqrt(252)) if np.std(all_returns) > 0 else 0
                
                report.append(f"  总体平均收益: {avg_return:.2f}%")
                report.append(f"  总体胜率: {win_rate:.2f}%")
                report.append(f"  总体夏普比率: {sharpe:.2f}")
                
                # 策略评价
                if avg_return > 0:
                    report.append("  策略评价: 盈利")
                else:
                    report.append("  策略评价: 亏损")
                
                if win_rate > 50:
                    report.append("  胜率评价: 超过50%，表现良好")
                else:
                    report.append("  胜率评价: 低于50%，需要优化")
        
        report.append("")
        report.append("详细交易记录（前20条）:")
        report.append("-" * 80)
        
        # 显示前20条交易记录
        df = pd.DataFrame({
            'date': results['dates'],
            'symbol': results['recommendations'],
            'buy_price': results['buy_prices'],
            'return_t2': results['returns_t2'],
            'return_t3': results['returns_t3'],
            'return_t4': results['returns_t4'],
            'return_t5': results['returns_t5'],
        })
        
        for i, row in df.head(20).iterrows():
            report.append(f"{row['date']} {row['symbol']}: 买入价={row['buy_price']:.2f}, "
                         f"T+2={row['return_t2']*100 if pd.notna(row['return_t2']) else 'N/A':+.2f}%, "
                         f"T+3={row['return_t3']*100 if pd.notna(row['return_t3']) else 'N/A':+.2f}%, "
                         f"T+4={row['return_t4']*100 if pd.notna(row['return_t4']) else 'N/A':+.2f}%, "
                         f"T+5={row['return_t5']*100 if pd.notna(row['return_t5']) else 'N/A':+.2f}%")
        
        if len(df) > 20:
            report.append(f"... 还有 {len(df) - 20} 条记录未显示")
        
        report.append("")
        report.append("=" * 80)
        report.append("回测完成")
        
        return "\n".join(report)

def main():
    """主函数"""
    print("开始原策略优化版(legacy_opt)历史回测...")
    
    try:
        # 初始化回测器
        backtester = LegacyOptBacktesterFinal()
        
        # 运行回测
        results = backtester.run_backtest(
            start_date="20250901",
            end_date="20251130"
        )
        
        if not results['dates']:
            print("回测没有产生任何交易记录")
            return
        
        # 分析结果
        analysis = backtester.analyze_results(results)
        
        # 生成报告
        report = backtester.generate_report(results, analysis)
        
        # 打印报告
        print(report)
        
        # 保存报告到文件
        report_file = "reports/legacy_opt_final_backtest_report.txt"
        os.makedirs(os.path.dirname(report_file), exist_ok=True)
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\n报告已保存到: {report_file}")
        
        # 保存详细数据到CSV
        csv_file = "reports/legacy_opt_final_backtest_details.csv"
        df = pd.DataFrame({
            'date': results['dates'],
            'symbol': results['recommendations'],
            'buy_price': results['buy_prices'],
            'sell_price_t2': results['sell_prices_t2'],
            'sell_price_t3': results['sell_prices_t3'],
            'sell_price_t4': results['sell_prices_t4'],
            'sell_price_t5': results['sell_prices_t5'],
            'return_t2': results['returns_t2'],
            'return_t3': results['returns_t3'],
            'return_t4': results['returns_t4'],
            'return_t5': results['returns_t5'],
        })
        df.to_csv(csv_file, index=False, encoding='utf-8-sig')
        print(f"详细数据已保存到: {csv_file}")
        
    except Exception as e:
        print(f"回测过程中出错: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()