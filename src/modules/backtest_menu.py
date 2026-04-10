# -*- coding: utf-8 -*-
"""
回测菜单模块
整合事件驱动回测功能到主菜单
"""

import sys
import os
import runpy
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from src.core.logger import get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB
from src.modules.backtest.event_backtest_engine import EventDrivenBacktest, BacktestConfig
from src.modules.backtest.performance_analyzer import PerformanceAnalyzer
from src.modules.backtest.visualizer import BacktestVisualizer
from src.modules.backtest.trade_visualizer import TradeVisualizer, generate_multi_stock_report
from src.modules.backtest.data_validator import StockCodeValidator, DataValidator
from src.modules.backtest.backtest_data_manager import BacktestDataManager

logger = get_logger("backtest_menu")


class BacktestMenu:
    """回测菜单类"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        self.config = config or ConfigManager()
        self.db = db or DatabaseManager(self.config)
        self.history_db = HistoryRecommendationDB()
        self.data_validator = DataValidator(self.history_db)
        self.data_manager = BacktestDataManager(db=self.history_db, config=self.config)
    
    def show_menu(self):
        """显示回测主菜单"""
        while True:
            print("\n" + "=" * 70)
            print("                         策略回测系统")
            print("=" * 70)
            print("    |  1. 运行回测          |  2. 数据管理              |")
            print("    |  3. 参数配置          |  4. 查看历史回测          |")
            print("    |  5. 数据状态检查      |  6. 帮助说明              |")
            print("    |  0. 返回主菜单        |                           |")
            print("=" * 70)
            
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                self.run_backtest_menu()
            elif choice == "2":
                self.data_management_menu()
            elif choice == "3":
                self.config_menu()
            elif choice == "4":
                self.view_history_menu()
            elif choice == "5":
                self.check_data_status()
            elif choice == "6":
                self.show_help()
            elif choice == "0":
                break
            else:
                print("    无效选择，请重试")
    
    def run_backtest_menu(self):
        """运行回测菜单"""
        print("\n" + "-" * 70)
        print("                         运行回测")
        print("-" * 70)
        
        # 选择回测模式
        print("\n    请选择回测模式:")
        print("    |  1. 基于推荐记录回测（使用已有选股结果）")
        print("    |  2. 自定义股票回测")
        print("    |  3. 突破选股策略历史回测（盘前选股+突破量能确认）")
        print("    |  0. 返回")
        
        mode = input("    请选择: ").strip()
        
        if mode == "1":
            self._run_recommendation_backtest()
        elif mode == "2":
            self._run_custom_backtest()
        elif mode == "3":
            self._run_breakout_strategy_backtest()
        elif mode == "0":
            return

    def _run_breakout_strategy_backtest(self):
        """调用 scripts/run_breakout_backtest.py，与命令行直接运行结果一致。"""
        root = Path(__file__).resolve().parents[2]
        script = root / "scripts" / "run_breakout_backtest.py"
        if not script.is_file():
            print(f"\n    [错误] 未找到脚本: {script}")
            return
        print("\n    【突破选股策略历史回测】")
        print("    使用本地 stock_daily 全量数据，耗时取决于数据量，请稍候…")
        confirm = input("    确认运行? (y/n): ").strip().lower()
        if confirm != "y":
            print("    已取消")
            return
        old_cwd = os.getcwd()
        try:
            os.chdir(str(root))
            runpy.run_path(str(script), run_name="__main__")
        except Exception as exc:
            logger.exception("突破选股历史回测失败")
            print(f"\n    运行失败: {exc}")
        finally:
            os.chdir(old_cwd)
    
    def _run_recommendation_backtest(self):
        """基于推荐记录的回测"""
        print("\n    【基于推荐记录回测】")
        print("    使用已有选股结果进行回测")
        
        # 获取推荐记录统计
        stats = self.history_db.get_statistics()
        print(f"\n    数据库统计:")
        print(f"      推荐记录: {stats.get('total_recommendations', 0)}条")
        print(f"      分时数据: {stats.get('total_intraday_records', 0):,}条")
        print(f"      股票数量: {stats.get('symbols_with_data', 0)}只")
        
        if stats.get('total_recommendations', 0) == 0:
            print("\n    [警告] 无推荐记录，请先运行选股功能")
            return
        
        # 输入回测参数
        print("\n    请输入回测参数:")
        
        # 日期范围
        date_range = input("    日期范围（格式：2026-03-01,2026-03-25，留空自动）: ").strip()
        if date_range:
            try:
                start_date, end_date = date_range.split(',')
                start_date = start_date.strip()
                end_date = end_date.strip()
            except:
                print("    日期格式错误，使用自动检测")
                start_date = None
                end_date = None
        else:
            start_date = None
            end_date = None
        
        # 资金参数
        capital_input = input("    初始资金（默认100000）: ").strip()
        capital = float(capital_input) if capital_input else 100000
        
        position_input = input("    单只仓位比例（默认0.2）: ").strip()
        position_size = float(position_input) if position_input else 0.2
        
        max_pos_input = input("    最大持仓数量（默认5）: ").strip()
        max_positions = int(max_pos_input) if max_pos_input else 5
        
        # 创建回测配置
        config = BacktestConfig(
            initial_capital=capital,
            position_size=position_size,
            max_positions=max_positions,
            stop_loss_pct=-0.03,
            take_profit_pct=0.05
        )
        
        print(f"\n    回测配置:")
        print(f"      初始资金: {capital:,.0f}")
        print(f"      单只仓位: {position_size*100:.0f}%")
        print(f"      最大持仓: {max_positions}只")
        print(f"      止损比例: -3%")
        print(f"      止盈比例: +5%")
        
        # 确认运行
        confirm = input("\n    确认运行回测?(y/n): ").strip().lower()
        if confirm != 'y':
            print("    已取消")
            return
        
        # 运行回测
        print("\n    正在运行回测...")
        
        try:
            backtest = EventDrivenBacktest(db=self.history_db, config=config)
            
            # 如果没有指定日期，自动检测
            if not start_date or not end_date:
                recommendations = self.history_db.get_recommendations()
                if recommendations:
                    dates = [r['recommendation_date'] for r in recommendations if r.get('recommendation_date')]
                    if dates:
                        dates.sort()
                        start_date = dates[0]
                        end_date = dates[-1]
            
            results = backtest.run(
                start_date=start_date,
                end_date=end_date,
                show_progress=True
            )
            
            # 显示结果
            backtest.print_results()
            
            # 绩效分析
            print("\n    正在进行绩效分析...")
            analyzer = PerformanceAnalyzer(risk_free_rate=0.03)
            metrics = analyzer.analyze(
                trades=backtest.trades,
                equity_curve=backtest.equity_curve,
                initial_capital=capital
            )
            analyzer.print_report(metrics)
            
            # 询问是否保存结果
            save_choice = input("\n    是否保存回测结果?(y/n): ").strip().lower()
            if save_choice == 'y':
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_dir = "reports"
                os.makedirs(output_dir, exist_ok=True)
                
                # 保存交易记录
                trades_file = f"{output_dir}/trades_{timestamp}.csv"
                backtest.save_results(trades_file)
                
                # 获取分时数据和股票名称
                intraday_data_dict = {}
                stock_names = {}
                
                traded_symbols = list(set(t.symbol for t in backtest.trades))
                for symbol in traded_symbols:
                    df = self.history_db.get_intraday_data(symbol)
                    if not df.empty:
                        intraday_data_dict[symbol] = df
                    
                    name = self._get_stock_name(symbol)
                    if name:
                        stock_names[symbol] = name
                
                # 生成可视化报告（包含分时图）
                visualizer = BacktestVisualizer(output_dir=output_dir)
                report_file = visualizer.generate_report(
                    metrics=metrics,
                    trades=backtest.trades,
                    equity_curve=backtest.equity_curve,
                    output_file=f"{output_dir}/backtest_report_{timestamp}.html",
                    intraday_data_dict=intraday_data_dict,
                    stock_names=stock_names
                )
                
                print(f"\n    结果已保存:")
                print(f"      交易记录: {trades_file}")
                print(f"      分析报告: {report_file}")
                print(f"      包含分时图: {len(intraday_data_dict)}只股票")
            
        except Exception as e:
            print(f"\n    [错误] 回测失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_custom_backtest(self):
        """自定义股票回测"""
        print("\n    【自定义股票回测】")
        print("    手动输入股票代码进行回测")
        
        # 输入股票代码
        symbols_input = input("    股票代码（多个用逗号分隔，如600519.SH,000858.SZ）: ").strip()
        if not symbols_input:
            print("    未输入股票代码")
            return
        
        symbols = [s.strip() for s in symbols_input.split(',')]
        
        # 验证股票代码
        valid_symbols = []
        for symbol in symbols:
            is_valid, errors = StockCodeValidator.validate(symbol)
            if is_valid:
                valid_symbols.append(symbol)
            else:
                print(f"    [警告] {symbol}: {', '.join(errors)}")
        
        if not valid_symbols:
            print("    无有效股票代码")
            return
        
        print(f"\n    有效股票: {', '.join(valid_symbols)}")
        
        # 输入日期范围
        start_date = input("    开始日期（YYYY-MM-DD）: ").strip()
        end_date = input("    结束日期（YYYY-MM-DD）: ").strip()
        
        if not start_date or not end_date:
            print("    日期不能为空")
            return
        
        # 检查数据
        print("\n    检查数据完整性...")
        for symbol in valid_symbols:
            df = self.history_db.get_intraday_data(symbol, start_date, end_date)
            if df.empty:
                print(f"    [警告] {symbol}: 无分时数据")
            else:
                print(f"    [OK] {symbol}: {len(df)}条数据")
        
        # 继续回测流程...
        print("\n    自定义回测功能开发中，请使用推荐记录回测")
    
    def _get_stock_name(self, symbol: str) -> str:
        """获取股票名称"""
        try:
            conn = self.history_db.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM recommendations WHERE symbol = ? LIMIT 1",
                (symbol,)
            )
            result = cursor.fetchone()
            if result and result[0]:
                return result[0]
        except Exception as e:
            logger.debug(f"获取股票名称失败 {symbol}: {e}")
        return ""
    
    def _generate_detailed_charts(self, trades: List, output_dir: str, timestamp: str):
        """生成带买卖点标注的详细分时图"""
        print("\n    【生成分时图买卖点标注】")
        
        if not trades:
            print("    无交易记录")
            return
        
        trade_visualizer = TradeVisualizer(output_dir=output_dir)
        
        traded_symbols = list(set(t.symbol for t in trades))
        print(f"    涉及股票: {len(traded_symbols)}只")
        
        intraday_data_dict = {}
        for symbol in traded_symbols:
            df = self.history_db.get_intraday_data(symbol)
            if not df.empty:
                intraday_data_dict[symbol] = df
                print(f"      {symbol}: {len(df)}条分时数据")
        
        if not intraday_data_dict:
            print("    无分时数据")
            return
        
        multi_report = generate_multi_stock_report(
            symbols=traded_symbols,
            intraday_data_dict=intraday_data_dict,
            trades=trades,
            output_dir=output_dir
        )
        
        print(f"\n    分时图报告已生成: {multi_report}")
        
        print("\n    提示: 报告包含以下功能:")
        print("      - 分时图上精确标注买卖点位置")
        print("      - 买入点显示为绿色向上三角形")
        print("      - 卖出点显示为红色向下三角形")
        print("      - 鼠标悬停显示详细交易信息")
        print("      - 支持显示/隐藏标注切换")
    
    def data_management_menu(self):
        """数据管理菜单"""
        while True:
            print("\n" + "-" * 70)
            print("                         数据管理")
            print("-" * 70)
            print("    |  1. 查看数据统计      |  2. 检查数据完整性      |")
            print("    |  3. 下载分时数据      |  4. 清理缓存            |")
            print("    |  5. 修复股票代码      |  0. 返回                |")
            print("-" * 70)
            
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                self._show_data_statistics()
            elif choice == "2":
                self._check_data_completeness()
            elif choice == "3":
                self._download_intraday_data()
            elif choice == "4":
                self._clear_cache()
            elif choice == "5":
                self._fix_stock_symbols()
            elif choice == "0":
                break
    
    def _show_data_statistics(self):
        """显示数据统计"""
        print("\n    【数据统计】")
        
        stats = self.history_db.get_statistics()
        
        print(f"\n    推荐记录:")
        print(f"      总数: {stats.get('total_recommendations', 0)}条")
        print(f"      活跃: {stats.get('active_recommendations', 0)}条")
        
        print(f"\n    分时数据:")
        print(f"      总数: {stats.get('total_intraday_records', 0):,}条")
        print(f"      股票数: {stats.get('symbols_with_data', 0)}只")
        
        # 显示日期范围
        recommendations = self.history_db.get_recommendations()
        if recommendations:
            dates = [r['recommendation_date'] for r in recommendations if r.get('recommendation_date')]
            if dates:
                dates.sort()
                print(f"\n    推荐日期范围:")
                print(f"      最早: {dates[0]}")
                print(f"      最晚: {dates[-1]}")
    
    def _check_data_completeness(self):
        """检查数据完整性"""
        print("\n    【数据完整性检查】")
        
        recommendations = self.history_db.get_recommendations()
        
        if not recommendations:
            print("    无推荐记录")
            return
        
        print(f"    检查 {len(recommendations)} 条推荐记录...")
        
        complete = 0
        partial = 0
        missing = 0
        
        for rec in recommendations[:20]:  # 检查前20条
            symbol = rec['symbol']
            rec_date = rec['recommendation_date']
            
            # 检查分时数据
            df = self.history_db.get_intraday_data(symbol)
            
            if df.empty:
                missing += 1
                status = "缺失"
            elif len(df) < 500:
                partial += 1
                status = f"部分({len(df)}条)"
            else:
                complete += 1
                status = "完整"
            
            print(f"      {symbol} ({rec_date}): {status}")
        
        print(f"\n    统计:")
        print(f"      完整: {complete}")
        print(f"      部分: {partial}")
        print(f"      缺失: {missing}")
    
    def _download_intraday_data(self):
        """下载分时数据"""
        print("\n    【下载分时数据】")
        print("    此功能需要配置Tushare Token")
        
        token = self.config.get('data_source.tushare_token')
        if not token:
            print("    [错误] 未配置Tushare Token")
            print("    请在.env文件中配置: TUSHARE_TOKEN=your_token")
            return
        
        print("    功能开发中...")
    
    def _clear_cache(self):
        """清理缓存"""
        print("\n    【清理缓存】")
        
        from src.modules.backtest.backtest_data_manager import DataCache
        cache = DataCache()
        cache.clear_expired(max_age_days=0)
        
        print("    缓存已清理")
    
    def _fix_stock_symbols(self):
        """修复股票代码"""
        print("\n    【修复股票代码】")
        
        import sqlite3
        
        conn = sqlite3.connect(self.history_db.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT DISTINCT symbol FROM recommendations")
        symbols = [row[0] for row in cursor.fetchall()]
        
        fixed_count = 0
        for symbol in symbols:
            if '.' not in symbol:
                if symbol.startswith('6') or symbol.startswith('8'):
                    new_symbol = f"{symbol}.SH"
                elif symbol.startswith('0') or symbol.startswith('3'):
                    new_symbol = f"{symbol}.SZ"
                else:
                    continue
                
                cursor.execute("UPDATE recommendations SET symbol = ? WHERE symbol = ?", (new_symbol, symbol))
                cursor.execute("UPDATE intraday_data SET symbol = ? WHERE symbol = ?", (new_symbol, symbol))
                fixed_count += 1
                print(f"      {symbol} -> {new_symbol}")
        
        conn.commit()
        conn.close()
        
        print(f"\n    修复完成，共修复 {fixed_count} 个代码")
    
    def config_menu(self):
        """参数配置菜单"""
        while True:
            print("\n" + "-" * 70)
            print("                         参数配置")
            print("-" * 70)
            print("    |  1. 回测参数          |  2. 策略参数            |")
            print("    |  3. 交易成本          |  4. 恢复默认            |")
            print("    |  0. 返回              |                         |")
            print("-" * 70)
            
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                self._config_backtest_params()
            elif choice == "2":
                self._config_strategy_params()
            elif choice == "3":
                self._config_transaction_cost()
            elif choice == "4":
                self._reset_config()
            elif choice == "0":
                break
    
    def _config_backtest_params(self):
        """配置回测参数"""
        print("\n    【回测参数配置】")
        
        print("    当前配置:")
        print(f"      初始资金: 100000")
        print(f"      单只仓位: 20%")
        print(f"      最大持仓: 5只")
        print(f"      止损比例: -3%")
        print(f"      止盈比例: +5%")
        
        print("\n    请输入新值（留空保持不变）:")
        
        capital = input("    初始资金: ").strip()
        position = input("    单只仓位比例(如0.2): ").strip()
        max_pos = input("    最大持仓数量: ").strip()
        stop_loss = input("    止损比例(如-0.03): ").strip()
        take_profit = input("    止盈比例(如0.05): ").strip()
        
        print("\n    配置已更新（本次有效）")
    
    def _config_strategy_params(self):
        """配置策略参数"""
        print("\n    【策略参数配置】")
        print("    功能开发中...")
    
    def _config_transaction_cost(self):
        """配置交易成本"""
        print("\n    【交易成本配置】")
        print("    当前配置:")
        print("      佣金: 万三")
        print("      印花税: 千一（卖出）")
        print("      滑点: 千一")
        print("\n    功能开发中...")
    
    def _reset_config(self):
        """恢复默认配置"""
        print("\n    【恢复默认配置】")
        confirm = input("    确认恢复默认配置?(y/n): ").strip().lower()
        if confirm == 'y':
            print("    已恢复默认配置")
    
    def view_history_menu(self):
        """查看历史回测"""
        print("\n    【历史回测记录】")
        
        # 查找报告文件
        report_dir = "reports"
        if not os.path.exists(report_dir):
            print("    无历史记录")
            return
        
        reports = [f for f in os.listdir(report_dir) if f.startswith("backtest_report_") and f.endswith(".html")]
        
        if not reports:
            print("    无历史记录")
            return
        
        print(f"\n    找到 {len(reports)} 份报告:")
        for i, report in enumerate(reports[:10], 1):
            print(f"      {i}. {report}")
        
        if len(reports) > 10:
            print(f"      ... 共 {len(reports)} 份")
    
    def check_data_status(self):
        """检查数据状态"""
        print("\n" + "=" * 70)
        print("                         数据状态检查")
        print("=" * 70)
        
        import sqlite3
        
        db_path = self.history_db.db_path
        
        if not os.path.exists(db_path):
            print("    [错误] 数据库文件不存在")
            return
        
        # 文件大小
        size_mb = os.path.getsize(db_path) / (1024 * 1024)
        print(f"\n    数据库文件: {db_path}")
        print(f"    文件大小: {size_mb:.2f} MB")
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 推荐记录
        cursor.execute("SELECT COUNT(*) FROM recommendations")
        rec_count = cursor.fetchone()[0]
        print(f"\n    推荐记录: {rec_count}条")
        
        # 分时数据
        cursor.execute("SELECT COUNT(*) FROM intraday_data")
        data_count = cursor.fetchone()[0]
        print(f"    分时数据: {data_count:,}条")
        
        # 股票数量
        cursor.execute("SELECT COUNT(DISTINCT symbol) FROM recommendations")
        symbol_count = cursor.fetchone()[0]
        print(f"    股票数量: {symbol_count}只")
        
        # 日期范围
        cursor.execute("SELECT MIN(recommendation_date), MAX(recommendation_date) FROM recommendations")
        min_date, max_date = cursor.fetchone()
        print(f"    日期范围: {min_date} ~ {max_date}")
        
        # 股票代码验证
        cursor.execute("SELECT DISTINCT symbol FROM recommendations")
        symbols = [row[0] for row in cursor.fetchall()]
        
        invalid_count = 0
        for symbol in symbols:
            is_valid, _ = StockCodeValidator.validate(symbol)
            if not is_valid:
                invalid_count += 1
        
        if invalid_count > 0:
            print(f"\n    [警告] 发现 {invalid_count} 个无效股票代码")
        else:
            print(f"\n    [OK] 所有股票代码格式正确")
        
        conn.close()
        
        print("=" * 70)
    
    def show_help(self):
        """显示帮助说明"""
        print("\n" + "=" * 70)
        print("                         帮助说明")
        print("=" * 70)
        print("""
    【回测系统说明】

    1. 运行回测
       - 基于推荐记录：使用已有选股结果进行回测
       - 自定义回测：手动输入股票代码进行回测
       - 突破选股历史回测：盘前选强 + 次日突破与量能确认（见选项3）

    2. 数据管理
       - 查看数据统计：显示推荐记录和分时数据数量
       - 检查数据完整性：验证每只股票的数据覆盖情况
       - 下载分时数据：补充缺失的分时数据
       - 修复股票代码：为缺少后缀的代码添加.SH/.SZ

    3. 参数配置
       - 回测参数：初始资金、仓位比例、止损止盈等
       - 策略参数：买卖信号相关参数
       - 交易成本：佣金、印花税、滑点等

    4. 数据状态检查
       - 检查数据库文件状态
       - 验证股票代码格式
       - 显示数据覆盖情况

    【回测流程】

    1. 确保已有推荐记录（运行选股功能）
    2. 确保已下载分时数据
    3. 配置回测参数
    4. 运行回测
    5. 查看结果并保存

    【注意事项】

    - 回测结果仅供参考，不构成投资建议
    - 历史表现不代表未来收益
    - 请结合实际情况调整参数

    【快捷键】

    - 输入 0 返回上级菜单
    - 输入 q 退出系统
        """)
        print("=" * 70)
