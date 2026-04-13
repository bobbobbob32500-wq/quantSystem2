# -*- coding: utf-8 -*-
"""
A股量化交易辅助系统 V1.0
主入口程序 - 集成所有功能模块
"""

import sys
import os
import json
import subprocess
from datetime import datetime

# 添加项目根目录到 Python 路径（main.py 位于仓库根目录时为一层 dirname）
def _strip_windows_long_path_prefix(path: str) -> str:
    if os.name != "nt":
        return path
    text = str(path or "")
    if text.startswith("\\\\?\\UNC\\"):
        return "\\\\" + text[8:]
    if text.startswith("\\\\?\\"):
        return text[4:]
    return text


_ROOT = _strip_windows_long_path_prefix(os.path.dirname(os.path.abspath(__file__)))
if os.name == "nt":
    _ROOT = os.path.normpath(_ROOT)
try:
    _cwd = _strip_windows_long_path_prefix(os.getcwd())
    if os.name == "nt":
        _cwd = os.path.normpath(_cwd)
    if _cwd and _cwd != os.getcwd() and os.path.isdir(_cwd):
        os.chdir(_cwd)
except Exception:
    pass
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from src.core.logger import setup_logger, get_logger
from src.core.config import ConfigManager
from src.core.database import DatabaseManager
from src.modules.terminal_dashboard import TerminalDashboard
from src.modules import (
    DataUpdater,
    PositionController,
    StockSelector,
    HoldAnalyzer,
    RiskController,
    MessagePusher,
    DailyReportGenerator,
    TradePlanGenerator,
    PostMarketWorker,
    TradeEvaluator,
    SignalFeedbackEvaluator,
    SecondaryLaunchMenu,
)
# 导入P0优化模块
try:
    from src.modules.factor_analysis import FactorAnalyzer, FactorICValidator, FactorCorrelationAnalyzer
    P0_MODULES_AVAILABLE = True
except ImportError as e:
    print(f"警告: P0优化模块导入失败: {e}")
    P0_MODULES_AVAILABLE = False

# 导入仓位控制引擎
try:
    from src.modules.position_controller import PositionController
    POSITION_CONTROLLER_AVAILABLE = True
except ImportError as e:
    print(f"警告: 仓位控制引擎导入失败: {e}")
    POSITION_CONTROLLER_AVAILABLE = False

# 导入回测菜单模块
try:
    from src.modules.backtest_menu import BacktestMenu
    BACKTEST_MENU_AVAILABLE = True
except ImportError as e:
    print(f"警告: 回测菜单模块导入失败: {e}")
    BACKTEST_MENU_AVAILABLE = False

# 导入突破选股模块（选强→等突破→跟强留强）
try:
    from src.modules.breakout_selector_menu import (
        breakout_selector_menu,
        wide_breakout_selector_menu as wide_breakout_menu_entry,
    )
    BREAKOUT_SELECTOR_AVAILABLE = True
except ImportError as e:
    print(f"警告: 突破选股模块导入失败: {e}")
    BREAKOUT_SELECTOR_AVAILABLE = False
    wide_breakout_menu_entry = None  # type: ignore[misc, assignment]


def print_banner():
    """打印系统横幅"""
    banner = """
    ================================================================
    |          A股量化交易辅助系统 V1.0                              |
    |          Quant Trading Assistant System                      |
    ================================================================
    |  功能模块:                                                    |
    |    - 数据更新    - 市场分析    - 每日选股                      |
    |    - 持仓分析    - 风控检测    - 实时监控                      |
    |    - 一键日报    - 交易计划    - 策略回测                      |
    |    - 突破选股    - 仓位控制    - 系统优化                       |
    ================================================================
    |  定位: 量化辅助决策工具，非全自动交易系统                      |
    |  入口: 本程序统一集成数据/选股/监控/看板自检，无需多脚本并行    |
    ================================================================
    """
    print(banner)


class QuantSystem:
    """量化系统主类"""
    
    def __init__(self):
        """初始化系统"""
        # 初始化日志
        self.logger = setup_logger("quant_system")
        self.logger.info("系统启动")
        
        # 初始化配置
        self.config = ConfigManager()
        self.logger.info("配置加载完成")
        
        # 初始化数据库
        self.db = DatabaseManager(self.config)
        self.logger.info("数据库初始化完成")
        
        # 初始化所有模块
        self._init_modules()
        
        self.logger.info("系统初始化完成")
    
    def _init_modules(self):
        """初始化所有业务模块"""
        self.data_updater = DataUpdater(self.config, self.db)
        self.position_controller = PositionController(self.config, self.db)
        self.stock_selector = StockSelector(self.config, self.db)
        self.hold_analyzer = HoldAnalyzer(self.config, self.db)
        self.risk_controller = RiskController(self.config, self.db)
        self.message_pusher = MessagePusher(self.config)
        self.daily_report = DailyReportGenerator(self.config, self.db)
        self.trade_plan = TradePlanGenerator(self.config, self.db)
        self.post_market = PostMarketWorker(self.config, self.db)
        self.trade_evaluator = TradeEvaluator(self.config, self.db)
        self.signal_feedback_evaluator = SignalFeedbackEvaluator(self.config, self.db)
        self.secondary_launch_menu_handler = SecondaryLaunchMenu(self.config, self.db)
        self.terminal_dashboard = TerminalDashboard(
            self.config,
            self.db,
            self.position_controller,
        )
        
        # 初始化P0优化模块
        if P0_MODULES_AVAILABLE:
            try:
                self.factor_analyzer = FactorAnalyzer(self.config, self.db)
                self.factor_validator = FactorICValidator(self.factor_analyzer)
                self.logger.info("P0优化模块初始化完成")
            except Exception as e:
                self.logger.warning(f"P0优化模块初始化失败: {e}")
                self.factor_analyzer = None
                self.factor_validator = None
        else:
            self.factor_analyzer = None
            self.factor_validator = None
            self.realistic_backtester = None
        
        self.logger.info("所有模块初始化完成")

    def _get_enhanced_weight_profile(self) -> str:
        """获取当前增强权重档位（已弃用，仅保留向后兼容）。"""
        return "legacy"

    @staticmethod
    def _enhanced_weight_profile_label(profile: str) -> str:
        """增强权重档位友好显示（已弃用）。"""
        return "legacy"

    def _strategy_profile_label(self, profile: str) -> str:
        """策略档位友好显示。"""
        return "基准原策略（legacy / 5因子）"

    def _get_strategy_profile(self) -> str:
        """获取当前策略档位（固定为 legacy）。"""
        return "legacy"

    def _apply_strategy_profile(self, profile: str, save: bool = True):
        """
        应用选股策略档位（Alpha158 IC加权模型）。
        """
        self.config.set("stock_selection.strategy_profile", "alpha158", save=save)
        selector = StockSelector(self.config, self.db)
        self.stock_selector = selector
        if hasattr(self.daily_report, "stock_selector"):
            self.daily_report.stock_selector = selector
        if hasattr(self.trade_plan, "stock_selector"):
            self.trade_plan.stock_selector = selector
        self.logger.info("选股策略已切换为: Alpha158 IC加权")

    def render_home_dashboard(self):
        """渲染终端首页仪表盘。"""
        try:
            print(self.terminal_dashboard.render_home())
        except Exception as e:
            print("\n    ==================== 首页仪表盘 ====================")
            print(f"    首页渲染失败: {e}")
            print("    ==================================================")

    def print_grouped_main_menu(self):
        """打印新的分组主菜单。"""
        menu = """
    ======================== 主导航 ========================
    |  1. 快捷操作          |  2. 交易执行              |
    |  3. 研究与策略        |  4. 系统运维              |
    |  5. 刷新首页          |  0. 退出系统              |
    ========================================================
        """
        print(menu)

    def quick_actions_menu(self):
        """快捷操作菜单。"""
        while True:
            print("\n    ==================== 快捷操作 ====================")
            print("    |  1. Alpha158选股      |  2. 突破选股(写候选池)  |")
            print("    |  3. 宽进突破选股      |  4. 一键日报            |")
            print("    |  5. 风控检测          |  6. 交易计划            |")
            print("    |  7. 盘后作业          |  8. 二次启动自检        |")
            print("    |  9. 二次启动近日报表  |  0. 返回首页            |")
            print("    ==================================================")
            choice = input("    请选择: ").strip()

            if choice == "1":
                self.run_primary_selection()
            elif choice == "2":
                self.run_breakout_selection_today()
            elif choice == "3":
                self.run_wide_breakout_selection_today()
            elif choice == "4":
                self.daily_report_menu()
            elif choice == "5":
                self.risk_check_menu()
            elif choice == "6":
                self.trade_plan_menu()
            elif choice == "7":
                self.post_market_menu()
            elif choice == "8":
                self.secondary_launch_menu_handler.run_persistence_self_check()
            elif choice == "9":
                self.secondary_launch_menu_handler.run_recent_tracking_report()
            elif choice == "0":
                return
            else:
                print("    无效选择，请重新输入")

    def trading_execution_menu(self):
        """交易执行菜单。"""
        while True:
            print("\n    ==================== 交易执行 ====================")
            print("    |  1. 今日选股入口      |  2. 二次启动策略入口    |")
            print("    |  3. 市场与仓位        |  4. 持仓管理            |")
            print("    |  5. 风控检测          |  6. 实时监控            |")
            print("    |  0. 返回首页                                    |")
            print("    ==================================================")
            choice = input("    请选择: ").strip()

            if choice == "1":
                self.stock_selection_menu()
            elif choice == "2":
                self.secondary_launch_menu()
            elif choice == "3":
                self.market_position_menu()
            elif choice == "4":
                self.hold_management_menu()
            elif choice == "5":
                self.risk_check_menu()
            elif choice == "6":
                self.monitor_menu()
            elif choice == "0":
                return
            else:
                print("    无效选择，请重新输入")

    def research_strategy_menu(self):
        """研究与策略菜单。"""
        while True:
            print("\n    ==================== 研究与策略 ====================")
            print("    |  1. 策略回测          |  2. 效果评测            |")
            print("    |  3. 二次启动策略      |  4. P0优化功能          |")
            print("    |  5. 自动优化管理      |  6. 突破选股策略 ★      |")
            print("    |  7. 宽进突破策略 ★    |  0. 返回首页            |")
            print("    ==================================================")
            choice = input("    请选择: ").strip()

            if choice == "1":
                self.backtest_menu()
            elif choice == "2":
                self.evaluator_menu()
            elif choice == "3":
                self.secondary_launch_menu()
            elif choice == "4":
                self.p0_optimization_menu()
            elif choice == "5":
                self.auto_optimization_menu()
            elif choice == "6":
                self.breakout_selector_menu()
            elif choice == "7":
                self.wide_breakout_selector_menu()
            elif choice == "0":
                return
            else:
                print("    无效选择，请重新输入")

    def breakout_selector_menu(self):
        """突破选股策略菜单入口（选强→等突破→跟强留强）"""
        if not BREAKOUT_SELECTOR_AVAILABLE:
            print("    突破选股模块不可用，请检查依赖")
            return
        try:
            breakout_selector_menu(config=self.config, db=self.db)
        except Exception as e:
            print(f"    突破选股模块异常: {e}")
            self.logger.exception("突破选股模块异常")

    def wide_breakout_selector_menu(self):
        """宽进突破策略菜单（宽选股 + 最严买点，独立候选池 wide_breakout）"""
        if not BREAKOUT_SELECTOR_AVAILABLE or wide_breakout_menu_entry is None:
            print("    宽进突破选股模块不可用，请检查依赖")
            return
        try:
            wide_breakout_menu_entry(config=self.config, db=self.db)
        except Exception as e:
            print(f"    宽进突破选股模块异常: {e}")
            self.logger.exception("宽进突破选股模块异常")

    def system_ops_menu(self):
        """系统运维菜单。"""
        while True:
            print("\n    ==================== 系统运维 ====================")
            print("    |  1. 数据管理          |  2. 系统状态            |")
            print("    |  3. 启动自动推送      |  4. 市场分析明细        |")
            print("    |  5. Web 可视化看板 ★ |  6. 核心功能自检        |")
            print("    |  0. 返回首页                                    |")
            print("    ==================================================")
            choice = input("    请选择: ").strip()

            if choice == "1":
                self.data_management_menu()
            elif choice == "2":
                self.system_status_menu()
            elif choice == "3":
                self.auto_push_menu()
            elif choice == "4":
                self.market_analysis_menu()
            elif choice == "5":
                self.web_dashboard_menu()
            elif choice == "6":
                self.run_core_function_self_check()
            elif choice == "0":
                return
            else:
                print("    无效选择，请重新输入")

    def web_dashboard_menu(self):
        """Web 看板：统一从菜单启动，无需单独执行 dashboard.py / start_dashboard.bat。"""
        from src.modules.dashboard_launcher import (
            launch_dashboard_blocking,
            launch_dashboard_in_new_console,
        )

        while True:
            print("\n    ================== Web 可视化看板 ==================")
            print("    |  1. 新窗口启动（推荐，不阻塞本终端）            |")
            print("    |  2. 当前窗口启动（阻塞，关闭看板后返回菜单）    |")
            print("    |  0. 返回上级                                    |")
            print("    ==================================================")
            choice = input("    请选择: ").strip()
            if choice == "1":
                ok, msg = launch_dashboard_in_new_console()
                print(f"\n    {msg}" if ok else f"\n    启动失败: {msg}")
            elif choice == "2":
                print("\n    正在启动看板（本窗口将阻塞，按 Ctrl+C 停止）...")
                try:
                    launch_dashboard_blocking()
                except KeyboardInterrupt:
                    print("\n    看板已停止")
            elif choice == "0":
                return
            else:
                print("    无效选择，请重新输入")

    def run_core_function_self_check(self):
        """调用 tools/core_function_self_check.py 执行 pytest 并可选落盘报告。"""
        script = os.path.join(_ROOT, "tools", "core_function_self_check.py")
        if not os.path.isfile(script):
            print(f"    未找到自检脚本: {script}")
            return
        write = input("\n    是否将结果写入 data/reports 报告文件? (y/n): ").strip().lower()
        args = [sys.executable, script]
        if write == "y":
            args.append("--write-report")
        print("\n    正在执行核心功能自检，请稍候...\n")
        try:
            subprocess.run(args, cwd=_ROOT, check=False)
        except Exception as e:
            print(f"    自检调用失败: {e}")

    def market_position_menu(self):
        """统一市场与仓位相关入口。"""
        while True:
            print("\n    ==================== 市场与仓位 ====================")
            print("    |  1. 市场概览          |  2. 仓位控制详版        |")
            print("    |  0. 返回上级                                    |")
            print("    ==================================================")
            choice = input("    请选择: ").strip()

            if choice == "1":
                self.market_analysis_menu()
            elif choice == "2":
                self.position_control_menu()
            elif choice == "0":
                return
            else:
                print("    无效选择，请重新输入")
    
    def data_management_menu(self):
        """数据管理菜单"""
        while True:
            print("\n    ==================== 数据管理 ====================")
            print("    |  1. 全量数据更新        |  2. 更新日线数据      |")
            print("    |  3. 更新股票基础信息    |  4. 更新指数数据      |")
            print("    |  5. 数据校验            |  0. 返回主菜单        |")
            print("    ==================================================")
            
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                print("\n    正在执行全量数据更新...")
                result = self.data_updater.run_full_update()
                print(f"    结果: {result['status']}")
                print(f"    股票基础: {result['stock_basic_count']}条")
                print(f"    日线数据: {result['daily_data_count']}条")
                print(f"    指数数据: {result['index_data_count']}条")
                # 显示数据最新日期
                latest_date = self.db.get_latest_trade_date("stock_daily")
                if latest_date:
                    # 格式化日期显示
                    if len(latest_date) == 8:
                        formatted_date = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"
                    else:
                        formatted_date = latest_date
                    print(f"    数据最新日期: {formatted_date}")
            
            elif choice == "2":
                date = input("    日期(YYYY-MM-DD，默认今天): ").strip() or None
                count = self.data_updater.update_daily_data(date)
                print(f"    更新完成: {count}条")
                # 显示数据最新日期
                latest_date = self.db.get_latest_trade_date("stock_daily")
                if latest_date:
                    if len(latest_date) == 8:
                        formatted_date = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"
                    else:
                        formatted_date = latest_date
                    print(f"    数据最新日期: {formatted_date}")
            
            elif choice == "3":
                count = self.data_updater.update_stock_basic()
                print(f"    更新完成: {count}条")
            
            elif choice == "4":
                code = input("    指数代码(默认000001.SH): ").strip() or "000001.SH"
                count = self.data_updater.update_index_data(code)
                print(f"    更新完成: {count}条")
                # 显示该指数数据最新日期
                sql = "SELECT MAX(trade_date) as latest FROM stock_daily WHERE ts_code = ?"
                result = self.db.query_one(sql, (code,))
                if result and result['latest']:
                    latest_date = result['latest']
                    if len(str(latest_date)) == 8:
                        formatted_date = f"{str(latest_date)[:4]}-{str(latest_date)[4:6]}-{str(latest_date)[6:]}"
                    else:
                        formatted_date = str(latest_date)
                    print(f"    数据最新日期: {formatted_date}")
            
            elif choice == "5":
                result = self.data_updater.verify_data()
                print(f"    校验结果: {'通过' if result['is_valid'] else '未通过'}")
                if result['issues']:
                    for issue in result['issues']:
                        print(f"      - {issue}")
                # 显示数据最新日期
                latest_date = self.db.get_latest_trade_date("stock_daily")
                if latest_date:
                    if len(latest_date) == 8:
                        formatted_date = f"{latest_date[:4]}-{latest_date[4:6]}-{latest_date[6:]}"
                    else:
                        formatted_date = latest_date
                    print(f"    数据最新日期: {formatted_date}")
            
            elif choice == "0":
                break
    
    def market_analysis_menu(self):
        """市场分析菜单"""
        print("\n    正在执行市场分析...")
        try:
            result = self.position_controller.analyze_market()
            print(f"\n    ==================== 市场分析结果 ====================")
            print(f"    市场状态: {result['market_regime']}")
            print(f"    目标仓位: {result['target_position']*100:.0f}%")
            print(f"    仓位等级: {result['position_level']}")
            print(f"    策略建议: {result['strategy_suggestion']}")
            print(f"    趋势状态: {result['trend_state']} (强度: {result['trend_strength']:.2f})")
            print(f"    资金状态: {result['money_state']} (强度: {result['money_strength']:.2f})")
            print(f"    情绪状态: {result['sentiment_state']} (强度: {result['sentiment_strength']:.2f})")
            print(f"    风险状态: {result['risk_state']} (强度: {result['risk_strength']:.2f})")
            print("    ======================================================")

            # 询问是否推送
            push_choice = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
            if push_choice == 'y':
                from src.modules.auto_push_manager import AutoPushManager
                auto_push = AutoPushManager(self.config, self.db)
                auto_push.last_market_score = result['target_position']  # 避免重复计算
                auto_push.last_market_regime = result['market_regime']
                if auto_push.push_market_analysis(force=True):
                    print("    已推送")
                else:
                    print("    推送失败")
        except Exception as e:
            print(f"    分析失败: {e}")

    def _push_primary_selection(self, results, selection_end_date: str | None = None):
        """推送原策略选股结果。"""
        selection_end_date = selection_end_date or self.db.get_latest_trade_date("stock_daily")
        if not selection_end_date:
            selection_end_date = datetime.now().strftime("%Y%m%d")

        selection_meta = {
            "selection_end_date": selection_end_date,
            "tradeability_thresholds": self.stock_selector.get_tradeability_thresholds(
                end_date=selection_end_date
            ),
        }
        if getattr(self.stock_selector, "use_dynamic_industry_strength", False):
            selection_meta["industry_snapshot"] = self.stock_selector.get_dynamic_industry_strength(
                end_date=selection_end_date,
                top_n=3,
            )

        market_analysis = {}
        try:
            market_analysis = self.position_controller.analyze_market(
                end_date=selection_end_date
            )
        except Exception:
            market_analysis = {}

        payload = {
            "report_date": datetime.now().strftime("%Y-%m-%d"),
            "report_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy_label": "Alpha158 IC加权动量策略",
            "market_analysis": market_analysis,
            "stock_selection": results,
            "stock_selection_meta": selection_meta,
        }

        if self.message_pusher.push_pre_market_selection(payload):
            print("    已推送")
        else:
            print("    推送失败")

    def run_primary_selection(self, end_date: str | None = None):
        """运行主选股（当前为 StockSelector：Alpha158 IC加权）。"""
        print("\n    正在执行 Alpha158 动量策略选股...")
        try:
            results = self.stock_selector.run_selection(end_date=end_date)
            sync_count = 0
            print(f"\n    ==================== 选股结果 ====================")
            print("    使用策略: Alpha158 IC加权动量策略")
            print(f"    共筛选出 {len(results)} 只股票:")
            print(f"    已同步到候选池缓存 {sync_count} 只")
            print("    --------------------------------------------------")
            for i, stock in enumerate(results[:10], 1):
                print(f"    {i}. {stock['ts_code']} {stock['name']}")
                print(f"       得分: {stock['total_score']}分 ({stock['level']})")
                if stock.get("alpha158_raw") is not None:
                    print(f"       Alpha158复合(z后加权): {float(stock['alpha158_raw']):.4f}")
                print(f"       行业: {stock.get('industry', '未知')}")
            print("    ==================================================")

            sync_count = self._sync_primary_selection_to_candidate_pool(
                selections=results,
                trade_date=end_date,
            )
            print(f"    已同步到候选池缓存: {sync_count} 只")
            if results:
                push_choice = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
                if push_choice == 'y':
                    self._push_primary_selection(results, selection_end_date=end_date)
        except Exception as e:
            print(f"    选股失败: {e}")

    def _resolve_selection_trade_date(self, trade_date: str | None = None) -> str:
        raw = str(trade_date or "").strip().replace("-", "").replace("/", "")
        if len(raw) == 8 and raw.isdigit():
            return raw
        latest = self.db.get_latest_trade_date("stock_daily")
        if latest:
            return str(latest)
        return datetime.now().strftime("%Y%m%d")

    def _sync_primary_selection_to_candidate_pool(
        self,
        selections: list[dict],
        trade_date: str | None = None,
    ) -> int:
        cache_file = os.path.join("data", "cache", "candidate_pool.json")
        os.makedirs(os.path.dirname(cache_file), exist_ok=True)
        resolved_trade_date = self._resolve_selection_trade_date(trade_date)

        previous_candidates: list[dict] = []
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    payload_old = json.load(f) or {}
                raw = payload_old.get("candidates")
                if isinstance(raw, list):
                    previous_candidates = [row for row in raw if isinstance(row, dict)]
            except Exception as exc:
                self.logger.warning(f"读取候选池缓存失败，将覆盖写入: {exc}")

        merged_candidates = [
            row
            for row in previous_candidates
            if str(row.get("strategy_profile", "")).lower() != "legacy"
        ]

        legacy_candidates: list[dict] = []
        for row in selections or []:
            ts_code = str(row.get("ts_code") or "").strip().upper()
            symbol = ts_code.split(".", 1)[0] if ts_code else str(row.get("symbol") or "").strip()
            if not symbol:
                continue
            try:
                score = float(row.get("total_score", row.get("score", 0)) or 0)
            except (TypeError, ValueError):
                score = 0.0
            legacy_candidates.append(
                {
                    "symbol": symbol,
                    "ts_code": ts_code or symbol,
                    "name": str(row.get("name") or ""),
                    "score": score,
                    "level": str(row.get("recommendation_level") or row.get("level") or "原策略候选"),
                    "industry": str(row.get("industry") or ""),
                    "pool_type": "core",
                    "strategy_profile": "legacy",
                    "strategy_name": str(row.get("strategy_name") or "legacy"),
                    "source": "console_primary_selection",
                    "trade_date": resolved_trade_date,
                    "recommendation_reason": row.get("recommendation_reason"),
                }
            )

        merged_candidates.extend(legacy_candidates)
        merged_candidates = sorted(
            merged_candidates,
            key=lambda x: float(x.get("score", 0) or 0),
            reverse=True,
        )[:30]

        payload = {
            "date": resolved_trade_date,
            "created_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "strategy_profile": "mixed",
            "candidates": merged_candidates,
        }
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return len(legacy_candidates)

    def run_primary_selection_today(self):
        """一键运行原策略今日选股。"""
        self.run_primary_selection(end_date=None)

    def run_breakout_selection_today(self, end_date: str | None = None):
        """
        突破策略选股，并写入 data/cache/candidate_pool.json，
        使首页指挥台与看板「候选池」能展示突破观察池。
        """
        if not BREAKOUT_SELECTOR_AVAILABLE:
            print("    突破选股模块不可用，请检查 src.modules.breakout_selector_menu")
            return
        print("\n    正在执行突破选股（选强→等突破）...")
        try:
            from src.modules.breakout_strategy import build_breakout_strategy_from_config
            from src.modules.breakout_selector_menu import (
                offer_breakout_wechat_push,
                print_breakout_watch_list,
                sync_breakout_watchlist_to_system_cache,
            )

            strategy = build_breakout_strategy_from_config(self.db, self.config)
            items = strategy.run(end_date=end_date)
            print(f"\n    ==================== 选股结果 ====================")
            print("    使用策略: 突破观察池（盘前选强，盘中待突破确认）")
            print_breakout_watch_list(items)
            wd = items[0].watch_date if items else strategy._resolve_end_date(end_date)
            sync_breakout_watchlist_to_system_cache(items, wd)
            offer_breakout_wechat_push(self.config, self.db, items, wd)
            print("    ==================================================")
        except Exception as e:
            print(f"    突破选股失败: {e}")
            self.logger.exception("突破选股失败")

    def run_wide_breakout_selection_today(self, end_date: str | None = None):
        """宽进突破策略选股，写入候选池 strategy_profile=wide_breakout。"""
        if not BREAKOUT_SELECTOR_AVAILABLE:
            print("    突破选股模块不可用，请检查 src.modules.breakout_selector_menu")
            return
        print("\n    正在执行宽进突破选股（宽选股 + 最严买点）...")
        try:
            from src.modules.breakout_strategy import build_wide_breakout_strategy_from_config
            from src.modules.breakout_selector_menu import (
                offer_breakout_wechat_push,
                print_breakout_watch_list,
                sync_breakout_watchlist_to_system_cache,
            )

            strategy = build_wide_breakout_strategy_from_config(self.db, self.config)
            items = strategy.run(end_date=end_date)
            print(f"\n    ==================== 选股结果 ====================")
            print("    使用策略: 宽进突破观察池（preset wide_pool_strict_entry_v2）")
            print_breakout_watch_list(items)
            wd = items[0].watch_date if items else strategy._resolve_end_date(end_date)
            sync_breakout_watchlist_to_system_cache(
                items,
                wd,
                strategy_profile="wide_breakout",
                strategy_name="wide_breakout_watchlist",
                level_label="宽进突破观察池",
                source="wide_breakout_strategy",
            )
            offer_breakout_wechat_push(
                self.config,
                self.db,
                items,
                wd,
                pool_level_label="宽进突破观察池",
                strategy_label="宽进突破策略（观察池）",
            )
            print("    ==================================================")
        except Exception as e:
            print(f"    宽进突破选股失败: {e}")
            self.logger.exception("宽进突破选股失败")

    def run_secondary_selection_today(self):
        """一键运行二次启动策略今日选股。"""
        print("\n    正在执行二次启动策略今日选股...")
        try:
            results = self.secondary_launch_menu_handler.get_daily_selection()
            self.secondary_launch_menu_handler.persist_daily_selection(selections=results)
            trade_date = self._resolve_selection_trade_date(None)
            sync_count = self.secondary_launch_menu_handler.sync_to_candidate_pool(
                trade_date=trade_date,
                selections=results,
            )
            print(f"\n    ==================== 选股结果 ====================")
            print(f"    使用策略: {self.secondary_launch_menu_handler.get_strategy_label()}")
            print(f"    共筛选出 {len(results)} 只股票:")
            print("    --------------------------------------------------")
            for i, stock in enumerate(results[:10], 1):
                print(f"    {i}. {stock['ts_code']} {stock['name']}")
                print(f"       排名: {stock.get('rank', i)} | RS20: {float(stock.get('rs20', 0.0)):.3f}")
                print(f"       回撤: {float(stock.get('drawdown_from_peak', 0.0)):.2%}")
            print("    ==================================================")

            if results:
                push_choice = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
                if push_choice == 'y':
                    selection_end_date = self.db.get_latest_trade_date("stock_daily")
                    market_analysis = {}
                    try:
                        market_analysis = self.position_controller.analyze_market(
                            end_date=selection_end_date
                        )
                    except Exception:
                        market_analysis = {}
                    payload = self.secondary_launch_menu_handler.build_push_payload(
                        trade_date=selection_end_date,
                        market_analysis=market_analysis,
                    )
                    if self.message_pusher.push_pre_market_selection(payload):
                        print("    已推送")
                    else:
                        print("    推送失败")
        except Exception as e:
            print(f"    二次启动策略选股失败: {e}")
    
    def stock_selection_menu(self):
        """选股菜单（Alpha158 / 突破 / 宽进突破）"""
        print("\n    ==================== 每日选股 ====================")
        print("    |  1. Alpha158动量策略    |  2. 突破选股★写入候选池 |")
        print("    |  3. 宽进突破选股★写入候选池  |  0. 返回            |")
        print("    ==================================================")

        choice = input(
            "    请选择(1 Alpha158/2突破/3宽进突破/0返回，回车默认1): "
        ).strip()

        if choice in {"", "1"}:
            print("    已选择: Alpha158动量策略（IC加权）")
            self.run_primary_selection()
            return
        if choice == "2":
            print("    已选择: 突破选股（选强→等突破，结果写入候选池）")
            self.run_breakout_selection_today()
            return
        if choice == "3":
            print("    已选择: 宽进突破选股（结果写入候选池）")
            self.run_wide_breakout_selection_today()
            return
        if choice == "0":
            print("    已返回")
            return
        print(f"    无效输入({choice})，请重试")
    
    def hold_management_menu(self):
        """持仓管理菜单"""
        while True:
            print("\n    ==================== 持仓管理 ====================")
            print("    |  1. 查看持仓          |  2. 添加持仓          |")
            print("    |  3. 更新持仓          |  4. 删除持仓          |")
            print("    |  5. 持仓分析          |  0. 返回主菜单        |")
            print("    ==================================================")
            
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                holds = self.hold_analyzer.get_hold_list()
                print(f"\n    当前持仓: {len(holds)}只")
                for h in holds:
                    print(f"      {h['ts_code']} {h['name']}: {h['hold_price']}元 x {h['hold_num']}股")
            
            elif choice == "2":
                code = input("    股票代码(如603098): ").strip()
                
                # 自动添加交易所后缀
                def format_stock_code(code_str):
                    """智能补全股票代码后缀"""
                    code_str = code_str.strip()
                    
                    # 如果已经包含后缀，直接返回
                    if '.' in code_str:
                        return code_str
                    
                    # 如果是6位数字，自动添加后缀
                    if code_str.isdigit() and len(code_str) == 6:
                        if code_str.startswith('6'):
                            return f'{code_str}.SH'
                        elif code_str.startswith('0') or code_str.startswith('3'):
                            return f'{code_str}.SZ'
                    
                    # 其他情况直接返回
                    return code_str
                
                code = format_stock_code(code)
                
                # 自动获取股票名称
                name = None
                
                # 方法1：从数据库获取
                sql = "SELECT name, industry FROM stock_basic WHERE ts_code = ?"
                result = self.db.query_one(sql, (code,))
                if result:
                    name = result['name']
                    industry = result.get('industry', '')
                    print(f"    股票名称: {name} ({industry})")
                else:
                    # 方法2：从实时行情获取
                    try:
                        from src.modules.realtime_quote import RealtimeQuote
                        quote = RealtimeQuote()
                        quote_data = quote.get_quote(code)
                        if quote_data and quote_data.get('name'):
                            name = quote_data['name']
                            print(f"    股票名称: {name}")
                    except:
                        pass
                
                if not name:
                    name = input("    未找到股票，请手动输入名称: ").strip()
                
                price = float(input("    持仓成本: ").strip())
                num = int(input("    持仓数量: ").strip())
                tp = input("    止盈价(可选): ").strip()
                ts = input("    止损价(可选): ").strip()
                
                self.hold_analyzer.add_hold(
                    code, name, price, num,
                    float(tp) if tp else None,
                    float(ts) if ts else None
                )
                print("    添加成功")
            
            elif choice == "3":
                hold_id = int(input("    持仓ID: ").strip())
                print("    可更新字段: hold_price, hold_num, target_profit, target_stop, status")
                field = input("    字段名: ").strip()
                value = input("    新值: ").strip()
                
                if field in ['hold_price', 'target_profit', 'target_stop']:
                    value = float(value)
                elif field == 'hold_num':
                    value = int(value)
                
                self.hold_analyzer.update_hold(hold_id, **{field: value})
                print("    更新成功")
            
            elif choice == "4":
                # 先显示持仓列表，方便用户选择
                holds = self.hold_analyzer.get_hold_list()
                if not holds:
                    print("    当前无持仓")
                    continue
                
                print("\n    当前持仓:")
                for h in holds:
                    print(f"      ID={h['id']} {h['ts_code']} {h['name']}: {h['hold_price']}元 x {h['hold_num']}股")
                
                hold_id = input("\n    请输入要删除的持仓ID: ").strip()
                if not hold_id:
                    print("    取消删除")
                    continue
                
                try:
                    hold_id = int(hold_id)
                    # 确认删除
                    confirm = input(f"    确认删除ID={hold_id}的持仓?(y/n): ").strip().lower()
                    if confirm == 'y':
                        result = self.hold_analyzer.delete_hold(hold_id)
                        if result:
                            print("    删除成功")
                        else:
                            print("    删除失败，请检查ID是否正确")
                    else:
                        print("    取消删除")
                except ValueError:
                    print("    请输入有效的数字ID")
            
            elif choice == "5":
                result = self.hold_analyzer.run_analysis()
                print(f"\n    {result['summary']}")
                for h in result['holds']:
                    print(f"      {h['ts_code']} {h['name']}: {h['profit']}% ({h['risk_level']})")
            
            elif choice == "0":
                break
    
    def risk_check_menu(self):
        """风控检测菜单"""
        print("\n    正在执行风控检测...")
        holds = self.hold_analyzer.get_hold_list()
        
        if not holds:
            print("    当前无持仓")
            return
        
        # 获取市场评分
        try:
            market_result = self.position_controller.analyze_market()
            # 将目标仓位转换为市场评分（0-100）
            market_score = market_result['target_position'] * 100
        except:
            market_score = 50.0
        
        result = self.risk_controller.run_risk_check(holds, market_score)
        
        print(f"\n    ==================== 风控检测结果 ====================")
        print(f"    检测持仓: {result['check_count']}只")
        print(f"    触发信号: {result['signal_count']}个")
        
        if result['signals']:
            print("    --------------------------------------------------")
            for s in result['signals']:
                print(f"    [{s['severity']}] {s['ts_code']} {s['name']}")
                print(f"      {s['signal_type']}: {s['suggestion']}")
        print("    ======================================================")
        
        # 询问是否推送
        if result['signals']:
            push_choice = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
            if push_choice == 'y':
                success = True
                for signal in result['signals']:
                    if not self.message_pusher.push_risk_signal(signal):
                        success = False
                print("    已推送" if success else "    推送失败")
    
    def monitor_menu(self):
        """实时监控菜单"""
        print("\n    ==================== 实时监控 ====================")
        print("    |  提示: 实时监控功能已升级为融合选股系统          |")
        print("    |================================================|")
        print("    |  1. 盘后选股(加入候选池)  |  2. 启动实时监控      |")
        print("    |  3. 查看候选池           |  4. 清空候选池        |")
        print("    |  5. 单次买点检测         |  6. 盘中买点路由自检  |")
        print("    |  0. 返回主菜单                                    |")
        print("    ==================================================")
        
        while True:
            choice = input("\n    请选择: ").strip()
            
            if choice == "1":
                # 盘后选股
                print("\n    执行盘后选股...")
                try:
                    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
                    system = EnhancedHybridSystem()
                    candidates = system.run_overnight_selection()
                    print(f"    选出{len(candidates)}只候选股")
                except Exception as e:
                    print(f"    选股失败: {e}")
            
            elif choice == "2":
                # 启动实时监控
                print("\n    启动实时监控...")
                try:
                    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
                    system = EnhancedHybridSystem()
                    if system.load_candidate_pool():
                        # 设置轮询间隔
                        interval = input("    轮询间隔(秒,默认10): ").strip()
                        interval = int(interval) if interval.isdigit() else 10
                        
                        print(f"\n    启动实时监控，轮询间隔{interval}秒...")
                        system.start_realtime_monitor(interval_seconds=interval)
                    else:
                        print("    请先执行盘后选股")
                except KeyboardInterrupt:
                    print("\n    监控已停止")
                except Exception as e:
                    print(f"    监控失败: {e}")
            
            elif choice == "3":
                # 查看候选池
                try:
                    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
                    system = EnhancedHybridSystem()
                    if system.load_candidate_pool():
                        print(f"\n    候选池({len(system.candidate_pool)}只):")
                        for i, c in enumerate(system.candidate_pool, 1):
                            pool_type = "核心池" if c['pool_type'] == 'core' else "备选池"
                            print(f"    {i}. {c['symbol']} - {c['name']} [{pool_type}] 评分:{c['score']:.1f}")
                    else:
                        print("    候选池为空")
                except Exception as e:
                    print(f"    查看失败: {e}")
            
            elif choice == "4":
                # 清空候选池
                import os
                cache_file = "data/cache/candidate_pool.json"
                if os.path.exists(cache_file):
                    os.remove(cache_file)
                    print("    候选池已清空")
                else:
                    print("    候选池已为空")
            
            elif choice == "5":
                # 单次买点检测
                print("\n    执行单次买点检测...")
                try:
                    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
                    system = EnhancedHybridSystem()
                    if system.load_candidate_pool():
                        signals = system.monitor_candidates()
                        system.print_buy_signals(signals)
                    else:
                        print("    请先执行盘后选股")
                except Exception as e:
                    print(f"    检测失败: {e}")

            elif choice == "6":
                # 各策略盘中买点路由冒烟（不依赖候选池是否有票）
                print("\n    执行盘中买点路由自检...")
                try:
                    from src.modules.enhanced_hybrid_system import EnhancedHybridSystem
                    from src.modules.enhanced_monitor_runtime import print_intraday_buy_router_healthcheck_report

                    system = EnhancedHybridSystem()
                    rows = system.run_intraday_buy_router_healthcheck()
                    print_intraday_buy_router_healthcheck_report(rows)
                except Exception as e:
                    print(f"    自检失败: {e}")
                    self.logger.exception("盘中买点路由自检失败")
            
            elif choice == "0":
                break
            
            else:
                print("    无效选择")
    
    def daily_report_menu(self):
        """一键日报菜单"""
        print("\n    正在生成综合日报...")
        result = self.daily_report.generate_report(skip_data_update=True)
        
        print(self.daily_report.format_report(result))
        
        push = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
        if push == 'y':
            markdown = self.daily_report.format_markdown_report(result)
            self.message_pusher.push_markdown(markdown)
            print("    已推送")
    
    def trade_plan_menu(self):
        """交易计划菜单"""
        print("\n    正在生成14:50交易计划...")
        result = self.trade_plan.generate_plan()
        
        print(self.trade_plan.format_plan(result))
        
        push = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
        if push == 'y':
            markdown = self.trade_plan.format_markdown_plan(result)
            self.message_pusher.push_markdown(markdown)
            print("    已推送")
    
    def backtest_menu(self):
        """策略回测菜单"""
        if BACKTEST_MENU_AVAILABLE:
            backtest = BacktestMenu(self.config, self.db)
            backtest.show_menu()
        else:
            print("\n    [错误] 回测模块未正确加载")
            print("    请检查 src/modules/backtest_menu.py 是否存在")
    
    def evaluator_menu(self):
        """效果评测菜单"""
        print("\n    ==================== 效果评测 ====================")
        print("    |  1. 交易效果评测(旧)     |  2. 信号闭环评测(新)   |")
        print("    |  0. 返回主菜单                                     |")
        print("    ==================================================")
        choice = input("    请选择: ").strip()

        if choice == "1":
            print("\n    正在执行交易效果评测...")
            result = self.trade_evaluator.run_evaluation()
            print(self.trade_evaluator.generate_report(result))

            suggestions = self.trade_evaluator.get_optimization_suggestions(result)
            if suggestions:
                print("\n    ==================== 优化建议 ====================")
                for i, s in enumerate(suggestions, 1):
                    print(f"    {i}. {s}")
            return

        if choice == "2":
            print("\n    正在执行信号收益闭环评测...")
            start_input = input("    开始日期(YYYYMMDD，回车默认近90天): ").strip()
            end_input = input("    结束日期(YYYYMMDD，回车默认最新交易日): ").strip()
            top_n_input = input("    每日TopN(回车默认10): ").strip()
            top_n = int(top_n_input) if top_n_input.isdigit() else None

            result = self.signal_feedback_evaluator.run_feedback(
                start_date=start_input or None,
                end_date=end_input or None,
                top_n_per_day=top_n,
            )

            print("\n    ==================== 闭环评测结果 ====================")
            print(f"    运行ID: {result.get('run_id', '')}")
            print(f"    评估区间: {result.get('start_date', '')} ~ {result.get('end_date', '')}")
            print(f"    明细样本: {result.get('detail_count', 0)}")
            print(f"    汇总条目: {result.get('summary_count', 0)}")
            print(f"    报告(MD): {result.get('files', {}).get('markdown', '')}")
            print(f"    报告(JSON): {result.get('files', {}).get('json', '')}")
            csv_path = result.get("files", {}).get("csv", "")
            if csv_path:
                print(f"    明细(CSV): {csv_path}")

            stats = result.get("stats", []) or []
            if stats:
                print("    --------------------------------------------------")
                for item in stats:
                    print(
                        "    "
                        f"[{item.get('source_type')}/{item.get('direction')}] "
                        f"T+{item.get('horizon')} "
                        f"样本{item.get('sample_count')} "
                        f"胜率{float(item.get('win_rate', 0)):.2%} "
                        f"均值{float(item.get('mean_net_return', 0)):.2%}"
                    )
            print("    ==================================================")
            return

        if choice == "0":
            return

        print("    无效选择")
    
    def post_market_menu(self):
        """盘后作业菜单"""
        print("\n    正在执行盘后作业...")
        result = self.post_market.run_all_tasks()
        
        print(self.post_market.format_report(result))
        
        # 询问是否推送
        push_choice = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
        if push_choice == 'y':
            from src.modules.auto_push_manager import AutoPushManager
            auto_push = AutoPushManager(self.config, self.db)
            if auto_push.push_post_market_summary():
                print("    已推送")
            else:
                print("    推送失败")
    
    def system_status_menu(self):
        """系统状态菜单"""
        print("\n    ==================== 系统状态 ====================")
        print(f"    数据库路径: {self.db.db_path}")
        print(f"    股票基础: {self.db.get_table_count('stock_basic')}条")
        print(f"    日线数据: {self.db.get_table_count('stock_daily')}条")
        print(f"    持仓记录: {self.db.get_table_count('hold_stock')}条")
        print(f"    信号历史: {self.db.get_table_count('signal_history')}条")
        print(f"    交易日志: {self.db.get_table_count('trade_log')}条")
        
        latest = self.db.get_latest_trade_date("stock_daily")
        print(f"    最新数据: {latest or '无数据'}")
        
        print("\n    ==================== 配置信息 ====================")
        print(f"    推送启用: {self.config.get('push.enabled')}")
        print(f"    监控启用: {self.config.get('monitor.enabled')}")
        print(f"    监控间隔: {self.config.get('monitor.interval_minutes')}分钟")
        print("    ==================================================")
    
    def auto_push_menu(self):
        """启动自动推送"""
        from src.modules.task_scheduler import QuantTaskManager
        
        print("\n    ==================== 自动推送 ====================")
        print("    启动自动推送服务...")
        print("    将按以下时间自动推送消息到企业微信:")
        print("    - 盘前 08:30: 市场分析 + 盘前选股计划")
        print("    - 盘中每30分钟: 市场分析（异常时）")
        print("    - 盘中每30分钟: 风控检测（有信号时）")
        print("    - 尾盘 14:50: 交易计划")
        print("    - 盘后 17:30: 盘后总结")
        print("    ==================================================")
        
        # 创建任务管理器
        print("    - 盘后 18:10: 信号闭环反馈摘要")
        task_manager = QuantTaskManager(self.config, self.db)
        task_manager.setup_auto_push_tasks()
        task_manager.start()
        
        print("\n    自动推送服务已启动！")
        print("    按 Ctrl+C 停止服务...")
        
        try:
            import time
            while True:
                time.sleep(60)
                # 显示任务状态
                jobs = task_manager.get_task_list()
                print(f"\n    [{time.strftime('%H:%M:%S')}] 运行中，共{len(jobs)}个任务")
        except KeyboardInterrupt:
            print("\n    正在停止服务...")
            task_manager.stop()
            print("    服务已停止")
    
    def p0_optimization_menu(self):
        """P0优化功能菜单"""
        if not P0_MODULES_AVAILABLE or self.factor_analyzer is None:
            print("\n    ==================== P0优化功能 ====================")
            print("    ⚠️  P0优化模块未安装或初始化失败")
            print("    请检查以下内容:")
            print("    1. src/modules/factor_analysis.py 是否存在")
            print("    2. src/modules/realistic_backtest.py 是否存在")
            print("    3. 依赖包是否完整（pandas, numpy, scipy）")
            print("    ==================================================")
            return
        
        while True:
            print("\n    ==================== P0优化功能 ⭐ ====================")
            print("    |  1. 因子IC分析        |  2. 因子有效性验证      |")
            print("    |  3. 因子相关性分析    |  4. 真实回测对比        |")
            print("    |  5. 生成优化报告      |  0. 返回主菜单        |")
            print("    =======================================================")
            
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                self._run_factor_ic_analysis()
            elif choice == "2":
                self._run_factor_validation()
            elif choice == "3":
                self._run_factor_correlation_analysis()
            elif choice == "4":
                self._run_backtest_comparison()
            elif choice == "5":
                self._generate_optimization_report()
            elif choice == "0":
                break
            else:
                print("    无效选择，请重新输入")
    
    def position_control_menu(self):
        """仓位控制菜单"""
        if not POSITION_CONTROLLER_AVAILABLE:
            print("\n    ==================== 仓位控制 ====================")
            print("    ⚠️  仓位控制引擎未安装或初始化失败")
            print("    请检查以下内容:")
            print("    1. src/modules/position_controller.py 是否存在")
            print("    2. 依赖包是否完整（pandas, numpy）")
            print("    ==================================================")
            return
        
        while True:
            print("\n    ==================== 仓位控制 (NEW) ====================")
            print("    |  1. 市场状态分析      |  2. 仓位建议            |")
            print("    |  3. 查看详细分析      |  0. 返回主菜单        |")
            print("    =======================================================")
            
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                self._run_market_regime_analysis()
            elif choice == "2":
                self._run_position_suggestion()
            elif choice == "3":
                self._run_detailed_analysis()
            elif choice == "0":
                break
            else:
                print("    无效选择，请重新输入")
    
    def _run_market_regime_analysis(self):
        """运行市场状态分析"""
        print("\n    ==================== 市场状态分析 ====================")
        print("    正在分析市场状态...")
        
        try:
            controller = PositionController(self.config, self.db)
            result = controller.analyze_market()
            
            print(f"\n    市场状态: {result['market_regime']}")
            print(f"    目标仓位: {result['target_position']*100:.0f}%")
            print(f"    仓位等级: {result['position_level']}")
            print(f"    策略建议: {result['strategy_suggestion']}")
            print(f"    分析时间: {result['analyze_time']}")
            
            # 显示市场状态说明
            print(f"\n    市场状态说明:")
            if result['market_regime'] == 'BULL':
                print("      [强势市场] 趋势向上，资金流入，情绪良好")
            elif result['market_regime'] == 'NEUTRAL':
                print("      [震荡市场] 趋势不明，资金中性，情绪一般")
            else:
                print("      [弱势市场] 趋势向下，资金流出，情绪很差")
            
        except Exception as e:
            print(f"    ❌ 分析失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_position_suggestion(self):
        """运行仓位建议"""
        print("\n    ==================== 仓位建议 ====================")
        print("    正在分析并生成仓位建议...")
        
        try:
            controller = PositionController(self.config, self.db)
            result = controller.analyze_market()
            
            position = result['target_position']
            
            print(f"\n    当前市场状态: {result['market_regime']}")
            print(f"    推荐仓位: {position*100:.0f}%")
            
            # 仓位建议详情
            print(f"\n    仓位建议详情:")
            if position >= 0.7:
                print("      [高仓位] 70%-100%")
                print("      - 激进策略：积极选股，允许追高")
                print("      - 使用动量策略，加大交易频率")
                print("      - 注意：风险较高，需严格控制止损")
            elif position >= 0.3:
                print("      [中仓位] 30%-60%")
                print("      - 均衡策略：低吸为主，控制频率")
                print("      - 使用回调策略，降低交易频率")
                print("      - 注意：平衡收益与风险")
            else:
                print("      [低仓位] 0%-20%")
                print("      - 防守策略：减少选股，降低仓位")
                print("      - 以防守为主，减少交易")
                print("      - 注意：市场风险高，建议空仓观望")
            
            print(f"\n    策略建议: {result['strategy_suggestion']}")
            
            # 关键机制提示
            print(f"\n    关键机制:")
            if result['risk_state'] == 'HIGH':
                print("      [风险一票否决] 已触发！风险高，仓位强制降低")
            if result['sentiment_state'] == 'OVERHEATED':
                print("      [情绪过热降仓] 已触发！情绪过热，仓位降低20%")
            elif result['sentiment_state'] == 'COLD':
                print("      [情绪过冷降仓] 已触发！情绪过冷，仓位降低10%")
            
        except Exception as e:
            print(f"    ❌ 分析失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_detailed_analysis(self):
        """运行详细分析"""
        print("\n    ==================== 详细分析 ====================")
        print("    正在进行详细分析...")
        
        try:
            controller = PositionController(self.config, self.db)
            result = controller.analyze_market()
            
            print(f"\n    市场状态: {result['market_regime']}")
            print(f"    目标仓位: {result['target_position']*100:.0f}%")
            print(f"    仓位等级: {result['position_level']}")
            print(f"    策略建议: {result['strategy_suggestion']}")
            
            print(f"\n    {'='*80}")
            print("    模块状态")
            print(f"    {'='*80}")
            print(f"    趋势状态: {result['trend_state']:8s} (强度: {result['trend_strength']:.2f})")
            print(f"    资金状态: {result['money_state']:8s} (强度: {result['money_strength']:.2f})")
            print(f"    情绪状态: {result['sentiment_state']:12s} (强度: {result['sentiment_strength']:.2f})")
            print(f"    风险状态: {result['risk_state']:8s} (强度: {result['risk_strength']:.2f})")
            
            print(f"\n    {'='*80}")
            print("    关键机制")
            print(f"    {'='*80}")
            
            # 风险一票否决
            if result['risk_state'] == 'HIGH':
                print("    [OK] 风险一票否决: 已触发")
            else:
                print("    [OK] 风险一票否决: 未触发")
            
            # 情绪过热降仓
            if result['sentiment_state'] == 'OVERHEATED':
                print("    [OK] 情绪过热降仓: 已触发（仓位降低20%）")
            elif result['sentiment_state'] == 'COLD':
                print("    [OK] 情绪过冷降仓: 已触发（仓位降低10%）")
            else:
                print("    [OK] 情绪调整: 未触发")
            
            print(f"\n    {'='*80}")
            print("    决策逻辑")
            print(f"    {'='*80}")
            
            # 市场状态判定
            if result['market_regime'] == 'BULL':
                print("    强势市场条件:")
                print(f"      - 趋势: {result['trend_state']}")
                print(f"      - 资金: {result['money_state']}")
                print(f"      - 情绪: {result['sentiment_state']}")
                print(f"      - 风险: {result['risk_state']}")
            elif result['market_regime'] == 'BEAR':
                print("    弱势市场条件:")
                print(f"      - 风险高 OR 资金流出 OR 趋势向下")
            else:
                print("    震荡市场条件:")
                print(f"      - 趋势/资金/情绪不一致")
            
            # 询问是否推送
            push_choice = input("\n    是否推送到企业微信?(y/n): ").strip().lower()
            if push_choice == 'y':
                content = f"""## 仓位控制分析报告

**分析时间**: {result['analyze_time']}

### 市场状态
- 市场状态: {result['market_regime']}
- 目标仓位: {result['target_position']*100:.0f}%
- 仓位等级: {result['position_level']}
- 策略建议: {result['strategy_suggestion']}

### 模块状态
- 趋势状态: {result['trend_state']} (强度: {result['trend_strength']:.2f})
- 资金状态: {result['money_state']} (强度: {result['money_strength']:.2f})
- 情绪状态: {result['sentiment_state']} (强度: {result['sentiment_strength']:.2f})
- 风险状态: {result['risk_state']} (强度: {result['risk_strength']:.2f})

### 关键机制
- 风险一票否决: {'已触发' if result['risk_state'] == 'HIGH' else '未触发'}
- 情绪调整: {'已触发' if result['sentiment_state'] in ['OVERHEATED', 'COLD'] else '未触发'}
"""
                if self.message_pusher.push_markdown(content):
                    print("    已推送")
                else:
                    print("    推送失败")
            
        except Exception as e:
            print(f"    ❌ 分析失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_factor_ic_analysis(self):
        """运行因子IC分析"""
        print("\n    ==================== 因子IC分析 ====================")
        print("    正在分析因子IC...")
        
        factor_names = ['trend_score', 'momentum_score', 'volume_score', 'pullback_score']
        
        try:
            ic_results = self.factor_analyzer.calculate_all_factors_ic(factor_names)
            
            if ic_results.empty:
                print("    ⚠️  未计算出IC值，可能原因:")
                print("    1. factor_values表中没有数据")
                print("    2. 需要先运行选股功能以收集因子值")
                print("    3. 数据时间范围不足")
                return
            
            print("\n    因子IC统计:")
            print("    " + "-" * 60)
            ic_results_str = ic_results.to_string(index=False)
            for line in ic_results_str.split('\n'):
                print(f"    {line}")
            print("    " + "-" * 60)
            
            print("\n    说明:")
            print("    - IC均值: 信息系数均值，绝对值越大因子越有效")
            print("    - IC_IR: 信息比率，IC均值/IC标准差")
            print("    - IC>0比例: IC为正的比例，>0.55为有效")
            print("    - t统计量: 显著性检验，|t|>2为显著")
            
        except Exception as e:
            print(f"    ❌ 分析失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_factor_validation(self):
        """运行因子有效性验证"""
        print("\n    ==================== 因子有效性验证 ====================")
        print("    正在验证因子有效性...")
        
        factor_names = ['trend_score', 'momentum_score', 'volume_score', 'pullback_score']
        
        try:
            validation_results = self.factor_validator.validate_all_factors(factor_names)
            
            if validation_results.empty:
                print("    ⚠️  未完成验证，请先运行因子IC分析")
                return
            
            print("\n    验证结果:")
            print("    " + "-" * 70)
            validation_str = validation_results.to_string(index=False)
            for line in validation_str.split('\n'):
                print(f"    {line}")
            print("    " + "-" * 70)
            
            # 统计有效因子
            effective_count = len(validation_results[validation_results['is_effective']])
            ineffective_count = len(validation_results[~validation_results['is_effective']])
            
            print(f"\n    有效因子: {effective_count}个")
            print(f"    无效因子: {ineffective_count}个")
            
            if ineffective_count > 0:
                print("\n    建议删除的因子:")
                for _, row in validation_results[~validation_results['is_effective']].iterrows():
                    print(f"      - {row['factor_name']}: {row['recommendation']}")
            
        except Exception as e:
            print(f"    ❌ 验证失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_factor_correlation_analysis(self):
        """运行因子相关性分析"""
        print("\n    ==================== 因子相关性分析 ====================")
        print("    正在分析因子相关性...")
        
        from src.modules.factor_analysis import FactorCorrelationAnalyzer
        
        factor_names = ['trend_score', 'momentum_score', 'volume_score', 'pullback_score']
        
        try:
            correlation_analyzer = FactorCorrelationAnalyzer(self.db)
            correlation_matrix = correlation_analyzer.calculate_factor_correlation_matrix(factor_names)
            
            if correlation_matrix.empty:
                print("    ⚠️  未计算出相关性矩阵，请先运行选股功能")
                return
            
            print("\n    因子相关性矩阵:")
            print("    " + "-" * 50)
            corr_str = correlation_matrix.to_string()
            for line in corr_str.split('\n'):
                print(f"    {line}")
            print("    " + "-" * 50)
            
            # 识别冗余因子
            redundant_pairs = correlation_analyzer.identify_redundant_factors(correlation_matrix, threshold=0.7)
            
            if redundant_pairs:
                print(f"\n    ⚠️  发现 {len(redundant_pairs)} 对冗余因子（相关系数 > 0.7）:")
                for f1, f2, corr in redundant_pairs:
                    print(f"      {f1} <-> {f2}: {corr:.3f}")
                print("\n    建议: 保留IC更高的因子，删除冗余因子")
            else:
                print("\n    ✓ 未发现冗余因子")
            
        except Exception as e:
            print(f"    ❌ 分析失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _run_backtest_comparison(self):
        """运行回测对比测试"""
        print("\n    ==================== 真实回测对比 ====================")
        print("    正在对比新旧回测引擎...")
        
        test_stocks = ['000001.SZ', '000002.SZ', '600000.SH']
        
        try:
            print(f"\n    测试股票: {', '.join(test_stocks)}")
            print("    回测期间: 2023-01-01 ~ 2023-12-31")
            
            results = []
            for ts_code in test_stocks:
                print(f"\n    测试 {ts_code}...")
                
                # 旧回测引擎
                try:
                    old_result = self.backtester.run_backtest(ts_code, '2023-01-01', '2023-12-31')
                    if 'error' in old_result:
                        print(f"      旧回测失败: {old_result['error']}")
                        continue
                except Exception as e:
                    print(f"      旧回测失败: {e}")
                    continue
                
                # 新回测引擎
                try:
                    from src.modules.realistic_backtest import simple_ma_strategy
                    new_result = self.realistic_backtester.run_backtest_realistic(
                        ts_code, '2023-01-01', '2023-12-31',
                        lambda df: simple_ma_strategy(df, fast=5, slow=20)
                    )
                    if 'error' in new_result:
                        print(f"      新回测失败: {new_result['error']}")
                        continue
                except Exception as e:
                    print(f"      新回测失败: {e}")
                    continue
                
                # 对比
                return_diff = new_result['total_return'] - old_result['total_return']
                
                print(f"      旧回测: 收益率{old_result['total_return']:.2f}%, 回撤{old_result['max_drawdown']:.2f}%")
                print(f"      新回测: 收益率{new_result['total_return']:.2f}%, 回撤{new_result['max_drawdown']:.2f}%, 失败{new_result['failed_trades']}次")
                print(f"      收益率差异: {return_diff:+.2f}%")
                
                results.append({
                    'ts_code': ts_code,
                    'old_return': old_result['total_return'],
                    'new_return': new_result['total_return'],
                    'return_diff': return_diff,
                    'failed_trades': new_result['failed_trades'],
                    'avg_slippage': new_result['avg_slippage']
                })
            
            if results:
                print("\n    ==================== 汇总统计 ====================")
                avg_return_diff = pd.Series([r['return_diff'] for r in results]).mean()
                avg_failed_trades = pd.Series([r['failed_trades'] for r in results]).mean()
                avg_slippage = pd.Series([r['avg_slippage'] for r in results]).mean()
                
                print(f"    平均收益率差异: {avg_return_diff:+.2f}%")
                print(f"    平均失败交易: {avg_failed_trades:.1f}次/股")
                print(f"    平均滑点: {avg_slippage:.3f}%")
                
                if avg_return_diff < -2:
                    print("\n    ⚠️  真实回测收益率显著下降，说明旧回测过于乐观")
                else:
                    print("\n    ✓ 收益率差异在合理范围内")
                
        except Exception as e:
            print(f"    ❌ 对比失败: {e}")
            import traceback
            traceback.print_exc()
    
    def _generate_optimization_report(self):
        """生成优化报告"""
        print("\n    ==================== 生成优化报告 ====================")
        print("    正在生成P0优化报告...")
        
        try:
            from src.modules.factor_analysis import generate_factor_analysis_report
            
            factor_names = ['trend_score', 'momentum_score', 'volume_score', 'pullback_score']
            
            # 确保报告目录存在
            import os
            report_dir = 'data/reports'
            os.makedirs(report_dir, exist_ok=True)
            
            report_path = os.path.join(report_dir, 'p0_optimization_report.txt')
            
            report = generate_factor_analysis_report(
                self.factor_analyzer,
                self.factor_validator,
                factor_names,
                output_path=report_path
            )
            
            print("\n    报告已生成!")
            print(f"    路径: {report_path}")
            print("\n    报告摘要:")
            print("    " + "-" * 60)
            print(report[:500])
            if len(report) > 500:
                print("    ...")
            print("    " + "-" * 60)
            
        except Exception as e:
            print(f"    ❌ 生成报告失败: {e}")
            import traceback
            traceback.print_exc()
    
    def run(self):
        """运行主循环"""
        while True:
            self.render_home_dashboard()
            self.print_grouped_main_menu()
            choice = input("    请选择: ").strip()
            
            if choice == "1":
                self.quick_actions_menu()
            elif choice == "2":
                self.trading_execution_menu()
            elif choice == "3":
                self.research_strategy_menu()
            elif choice == "4":
                self.system_ops_menu()
            elif choice == "5":
                continue
            elif choice == "0":
                print("\n    感谢使用，再见！")
                self.logger.info("系统退出")
                break
            else:
                print("    无效选择，请重新输入")
    
    def auto_optimization_menu(self):
        """自动优化管理菜单"""
        print("\n    ==================== 自动优化管理 (NEW) ====================")
        print("    |  1. 查看自动优化状态  |  2. 启动自动优化        |")
        print("    |  3. 停止自动优化      |  4. 强制重优化          |")
        print("    |  5. 查看优化统计      |  0. 返回主菜单          |")
        print("    ============================================================")
        
        while True:
            choice = input("\n    请选择: ").strip()
            
            if choice == "1":
                self._show_auto_optimization_status()
            elif choice == "2":
                self._start_auto_optimization()
            elif choice == "3":
                self._stop_auto_optimization()
            elif choice == "4":
                self._force_reoptimize()
            elif choice == "5":
                self._show_optimization_statistics()
            elif choice == "0":
                break
            else:
                print("    无效选择，请重新输入")
    
    def _show_auto_optimization_status(self):
        """显示自动优化状态"""
        print("\n    ==================== 自动优化状态 ====================")
        print("    自动优化系统已集成到以下模块:")
        print("    - 盘中买卖点分析 (enhanced_hybrid_system.py)")
        print("    - 盘前选股 (stock_selector.py)")
        print("    - 风控检测 (risk_controller.py)")
        print("\n    功能:")
        print("    - 在线学习: 实时更新Pattern")
        print("    - 定时重优化: 每30分钟后台重优化")
        print("    - 事件驱动: 连续亏损/回撤突破触发")
        print("    - 平滑切换: 策略无缝切换")
        print("    ======================================================")
    
    def _start_auto_optimization(self):
        """启动自动优化"""
        print("\n    正在启动自动优化...")
        print("    提示: 自动优化已在盘中监控中自动启动")
        print("    使用方法:")
        print("    1. 选择菜单6(实时监控)")
        print("    2. 执行盘后选股")
        print("    3. 启动实时监控")
        print("    自动优化将自动运行")
    
    def _stop_auto_optimization(self):
        """停止自动优化"""
        print("\n    正在停止自动优化...")
        print("    提示: 自动优化将在停止实时监控时自动停止")
    
    def _force_reoptimize(self):
        """强制重优化"""
        print("\n    正在执行强制重优化...")
        print("    提示: 强制重优化将在检测到关键事件时自动触发")
        print("    触发条件:")
        print("    - 连续亏损 >= 3次")
        print("    - 回撤突破 >= 15%")
        print("    - 市场状态突变")
    
    def _show_optimization_statistics(self):
        """显示优化统计"""
        print("\n    ==================== 优化统计 ====================")
        print("    自动优化系统统计信息:")
        print("    - 在线学习: 持续运行")
        print("    - 定时重优化: 每30分钟")
        print("    - 事件驱动: 实时监控")
        print("    - 策略切换: 平滑过渡")
        print("\n    详细统计请在实时监控中查看")
        print("    ==================================================")

    def secondary_launch_menu(self):
        """强势回调缩量二次启动策略菜单"""
        self.secondary_launch_menu_handler.show_menu()


def main():
    """主函数"""
    try:
        system = QuantSystem()
        system.run()
        return 0
    except Exception as e:
        print(f"\n    系统错误: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
