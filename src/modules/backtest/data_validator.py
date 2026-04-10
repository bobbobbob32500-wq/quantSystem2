# -*- coding: utf-8 -*-
"""
数据验证模块
验证股票代码格式、数据完整性、时间跨度
"""

import re
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Set
from dataclasses import dataclass
from enum import Enum

from src.core.logger import get_logger
from src.modules.backtest.history_recommendation_db import HistoryRecommendationDB

logger = get_logger("data_validator")


class ValidationStatus(Enum):
    """验证状态"""
    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"
    PARTIAL = "partial"


@dataclass
class StockValidationResult:
    """股票验证结果"""
    symbol: str
    status: ValidationStatus
    errors: List[str] = None
    warnings: List[str] = None
    data_coverage: float = 0.0
    missing_dates: List[str] = None
    
    def __post_init__(self):
        if self.errors is None:
            self.errors = []
        if self.warnings is None:
            self.warnings = []
        if self.missing_dates is None:
            self.missing_dates = []


@dataclass
class DataValidationReport:
    """数据验证报告"""
    total_stocks: int
    valid_stocks: int
    invalid_stocks: int
    missing_data_stocks: int
    partial_data_stocks: int
    details: List[StockValidationResult]
    summary: Dict
    
    def print_report(self):
        """打印报告"""
        print("\n" + "=" * 70)
        print("数据验证报告")
        print("=" * 70)
        print(f"\n总股票数: {self.total_stocks}")
        print(f"  ✓ 完整有效: {self.valid_stocks}")
        print(f"  ✗ 格式无效: {self.invalid_stocks}")
        print(f"  ! 数据缺失: {self.missing_data_stocks}")
        print(f"  ~ 部分数据: {self.partial_data_stocks}")
        
        if self.invalid_stocks > 0:
            print("\n【格式无效的股票】")
            for detail in self.details:
                if detail.status == ValidationStatus.INVALID:
                    print(f"  {detail.symbol}: {', '.join(detail.errors)}")
        
        if self.missing_data_stocks > 0:
            print("\n【数据缺失的股票】")
            for detail in self.details:
                if detail.status == ValidationStatus.MISSING:
                    print(f"  {detail.symbol}")
        
        if self.partial_data_stocks > 0:
            print("\n【部分数据的股票】")
            for detail in self.details:
                if detail.status == ValidationStatus.PARTIAL:
                    print(f"  {detail.symbol}: 覆盖率 {detail.data_coverage*100:.1f}%")
                    if detail.missing_dates:
                        print(f"    缺失日期: {', '.join(detail.missing_dates[:5])}")
                        if len(detail.missing_dates) > 5:
                            print(f"    ... 共 {len(detail.missing_dates)} 天")
        
        print("=" * 70)


class StockCodeValidator:
    """股票代码验证器"""
    
    # A股代码规则
    PATTERNS = {
        'sh_main': re.compile(r'^6\d{5}\.SH$'),      # 沪市主板
        'sz_main': re.compile(r'^0\d{5}\.SZ$'),      # 深市主板
        'sz_sme': re.compile(r'^0\d{5}\.SZ$'),       # 中小板
        'sz_gem': re.compile(r'^3\d{5}\.SZ$'),       # 创业板
        'sh_star': re.compile(r'^68\d{5}\.SH$'),     # 科创板
        'bj': re.compile(r'^8\d{5}\.BJ$'),            # 北交所
    }
    
    @classmethod
    def validate(cls, symbol: str) -> Tuple[bool, List[str]]:
        """
        验证股票代码格式
        
        Args:
            symbol: 股票代码，如 "600519.SH"
        
        Returns:
            (是否有效, 错误信息列表)
        """
        errors = []
        
        if not symbol:
            errors.append("股票代码为空")
            return False, errors
        
        # 检查格式
        if '.' not in symbol:
            errors.append("格式错误，缺少市场后缀(如.SH/.SZ)")
            return False, errors
        
        code, market = symbol.split('.')
        
        # 检查代码长度
        if len(code) != 6:
            errors.append(f"代码长度错误: {len(code)}位，应为6位")
        
        # 检查是否为数字
        if not code.isdigit():
            errors.append("代码应全为数字")
        
        # 检查市场后缀
        if market not in ['SH', 'SZ', 'BJ']:
            errors.append(f"未知市场后缀: {market}")
        
        # 检查代码前缀
        if market == 'SH':
            if not (code.startswith('6') or code.startswith('68') or code.startswith('8')):
                errors.append("沪市代码应以6、68或8开头")
        elif market == 'SZ':
            if not (code.startswith('0') or code.startswith('3')):
                errors.append("深市代码应以0或3开头")
        elif market == 'BJ':
            if not code.startswith('8'):
                errors.append("北交所代码应以8开头")
        
        return len(errors) == 0, errors
    
    @classmethod
    def normalize(cls, symbol: str) -> str:
        """
        标准化股票代码
        
        Args:
            symbol: 原始代码，如 "600519" 或 "600519.SH"
        
        Returns:
            标准化代码，如 "600519.SH"
        """
        if not symbol:
            return ""
        
        symbol = symbol.strip().upper()
        
        # 已有后缀
        if '.' in symbol:
            return symbol
        
        # 根据前缀判断市场
        if symbol.startswith('6') or symbol.startswith('8'):
            return f"{symbol}.SH"
        elif symbol.startswith('0') or symbol.startswith('3'):
            return f"{symbol}.SZ"
        else:
            return symbol
    
    @classmethod
    def is_main_board(cls, symbol: str) -> bool:
        """判断是否为主板股票"""
        if not symbol:
            return False
        
        code = symbol.split('.')[0] if '.' in symbol else symbol
        
        # 沪市主板: 600, 601, 603, 605
        if symbol.endswith('.SH'):
            return code.startswith(('600', '601', '603', '605'))
        
        # 深市主板: 000, 001, 002, 003
        if symbol.endswith('.SZ'):
            return code.startswith(('000', '001', '002', '003'))
        
        return False


class DataValidator:
    """数据验证器"""
    
    def __init__(self, db: HistoryRecommendationDB = None):
        if db is None:
            db = HistoryRecommendationDB()
        self.db = db
    
    def validate_stock_list(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str,
        required_days: int = 7
    ) -> DataValidationReport:
        """
        验证股票列表
        
        Args:
            symbols: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            required_days: 需要的最少交易日天数
        
        Returns:
            验证报告
        """
        logger.info(f"开始验证 {len(symbols)} 只股票的数据...")
        
        details = []
        valid_count = 0
        invalid_count = 0
        missing_count = 0
        partial_count = 0
        
        for symbol in symbols:
            result = self._validate_single_stock(symbol, start_date, end_date, required_days)
            details.append(result)
            
            if result.status == ValidationStatus.VALID:
                valid_count += 1
            elif result.status == ValidationStatus.INVALID:
                invalid_count += 1
            elif result.status == ValidationStatus.MISSING:
                missing_count += 1
            elif result.status == ValidationStatus.PARTIAL:
                partial_count += 1
        
        report = DataValidationReport(
            total_stocks=len(symbols),
            valid_stocks=valid_count,
            invalid_stocks=invalid_count,
            missing_data_stocks=missing_count,
            partial_data_stocks=partial_count,
            details=details,
            summary={
                'valid_rate': valid_count / len(symbols) if symbols else 0,
                'start_date': start_date,
                'end_date': end_date,
                'required_days': required_days,
            }
        )
        
        logger.info(f"验证完成: 有效{valid_count}, 无效{invalid_count}, 缺失{missing_count}, 部分{partial_count}")
        
        return report
    
    def _validate_single_stock(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        required_days: int
    ) -> StockValidationResult:
        """验证单只股票"""
        # 1. 验证代码格式
        is_valid, errors = StockCodeValidator.validate(symbol)
        
        if not is_valid:
            return StockValidationResult(
                symbol=symbol,
                status=ValidationStatus.INVALID,
                errors=errors
            )
        
        # 2. 检查数据完整性
        df = self.db.get_intraday_data(symbol, start_date, end_date)
        
        if df.empty:
            return StockValidationResult(
                symbol=symbol,
                status=ValidationStatus.MISSING,
                errors=["无分时数据"]
            )
        
        # 3. 检查数据覆盖度
        df['date'] = df['trade_time'].dt.date
        unique_dates = df['date'].nunique()
        
        # 计算期望的交易日（简化处理，实际应排除节假日）
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
        expected_days = (end - start).days + 1
        
        coverage = unique_dates / expected_days if expected_days > 0 else 0
        
        # 找出缺失的日期
        actual_dates = set(df['date'].unique())
        missing_dates = []
        current = start
        while current <= end:
            if current not in actual_dates:
                missing_dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)
        
        # 4. 数据质量检查
        warnings = []
        
        # 检查是否有零值
        zero_prices = (df[['open', 'high', 'low', 'close']] == 0).any(axis=1).sum()
        if zero_prices > 0:
            warnings.append(f"存在{zero_prices}条零价格数据")
        
        # 检查是否有异常价格
        price_changes = df['close'].pct_change().abs()
        extreme_changes = (price_changes > 0.2).sum()
        if extreme_changes > 0:
            warnings.append(f"存在{extreme_changes}条异常价格变动(>20%)")
        
        # 判断状态
        if unique_dates >= required_days and coverage >= 0.9:
            status = ValidationStatus.VALID
        elif unique_days > 0:
            status = ValidationStatus.PARTIAL
        else:
            status = ValidationStatus.MISSING
        
        return StockValidationResult(
            symbol=symbol,
            status=status,
            errors=[],
            warnings=warnings,
            data_coverage=coverage,
            missing_dates=missing_dates
        )
    
    def get_missing_data_list(
        self,
        symbols: List[str],
        start_date: str,
        end_date: str
    ) -> List[Tuple[str, List[str]]]:
        """
        获取缺失数据的股票列表
        
        Returns:
            [(股票代码, 缺失日期列表), ...]
        """
        missing_list = []
        
        for symbol in symbols:
            result = self._validate_single_stock(symbol, start_date, end_date, 1)
            
            if result.status in [ValidationStatus.MISSING, ValidationStatus.PARTIAL]:
                if result.missing_dates:
                    missing_list.append((symbol, result.missing_dates))
                else:
                    missing_list.append((symbol, [f"{start_date}~{end_date}"]))
        
        return missing_list
    
    def validate_recommendations(
        self,
        start_date: str,
        end_date: str,
        required_days: int = 7
    ) -> DataValidationReport:
        """
        验证推荐记录的数据完整性
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            required_days: 每个股票需要的数据天数
        
        Returns:
            验证报告
        """
        logger.info(f"验证推荐记录数据: {start_date} ~ {end_date}")
        
        # 获取推荐记录
        recommendations = self.db.get_recommendations(start_date, end_date)
        
        if not recommendations:
            logger.warning("无推荐记录")
            return DataValidationReport(
                total_stocks=0,
                valid_stocks=0,
                invalid_stocks=0,
                missing_data_stocks=0,
                partial_data_stocks=0,
                details=[],
                summary={}
            )
        
        # 提取唯一股票代码
        symbols = list(set([r['symbol'] for r in recommendations]))
        
        logger.info(f"找到 {len(recommendations)} 条推荐记录，涉及 {len(symbols)} 只股票")
        
        # 计算每个推荐股票需要的数据范围
        # 推荐日 + 后续7个交易日
        validation_results = []
        
        for rec in recommendations:
            symbol = rec['symbol']
            rec_date = rec['recommendation_date']
            
            # 计算需要的数据范围
            rec_date_obj = datetime.strptime(rec_date, '%Y-%m-%d')
            data_start = rec_date_obj.strftime('%Y-%m-%d')
            data_end = (rec_date_obj + timedelta(days=required_days + 5)).strftime('%Y-%m-%d')
            
            # 验证该股票的数据
            result = self._validate_single_stock(symbol, data_start, data_end, required_days)
            validation_results.append(result)
        
        # 统计
        valid_count = sum(1 for r in validation_results if r.status == ValidationStatus.VALID)
        invalid_count = sum(1 for r in validation_results if r.status == ValidationStatus.INVALID)
        missing_count = sum(1 for r in validation_results if r.status == ValidationStatus.MISSING)
        partial_count = sum(1 for r in validation_results if r.status == ValidationStatus.PARTIAL)
        
        report = DataValidationReport(
            total_stocks=len(recommendations),
            valid_stocks=valid_count,
            invalid_stocks=invalid_count,
            missing_data_stocks=missing_count,
            partial_data_stocks=partial_count,
            details=validation_results,
            summary={
                'valid_rate': valid_count / len(recommendations) if recommendations else 0,
                'start_date': start_date,
                'end_date': end_date,
                'required_days': required_days,
            }
        )
        
        return report
