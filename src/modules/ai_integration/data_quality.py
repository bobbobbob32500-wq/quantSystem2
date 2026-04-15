# -*- coding: utf-8 -*-
"""
数据质量监控
自动检测数据异常、数据缺失预警、数据质量报告
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from src.core.logger import get_logger

logger = get_logger("data_quality")


class DataQualityMonitor:
    """数据质量监控"""

    def __init__(self, config: Optional[Dict] = None):
        self._config = config or {}
        self._stale_threshold_days = self._config.get("stale_threshold_days", 5)
        self._quality_history: List[Dict] = []

    def check_data_quality(
        self,
        data_status: Dict[str, Any],
        expected_symbols: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """检查数据质量"""
        issues: List[Dict[str, Any]] = []

        # 完整性检查
        completeness = self._check_completeness(data_status, expected_symbols, issues)

        # 及时性检查
        timeliness = self._check_timeliness(data_status, issues)

        # 准确性检查
        accuracy = self._check_accuracy(data_status, issues)

        # 一致性检查
        consistency = self._check_consistency(data_status, issues)

        # 综合评分
        overall_score = completeness * 0.3 + timeliness * 0.3 + accuracy * 0.25 + consistency * 0.15

        report = {
            "overall_score": round(overall_score, 4),
            "completeness": round(completeness, 4),
            "timeliness": round(timeliness, 4),
            "accuracy": round(accuracy, 4),
            "consistency": round(consistency, 4),
            "issues": issues,
            "issue_count": len(issues),
            "critical_issues": len([i for i in issues if i.get("severity") == "critical"]),
            "checked_at": datetime.now().isoformat(),
        }

        self._quality_history.append(report)
        return report

    def _check_completeness(
        self,
        data_status: Dict,
        expected_symbols: Optional[List[str]],
        issues: List[Dict],
    ) -> float:
        """完整性检查"""
        available_symbols = set(data_status.get("available_symbols", []))
        missing_symbols = data_status.get("missing_symbols", [])

        if expected_symbols:
            missing = set(expected_symbols) - available_symbols
            if missing:
                issues.append({
                    "type": "completeness",
                    "severity": "high" if len(missing) > 5 else "medium",
                    "message": f"缺少 {len(missing)} 只股票数据: {', '.join(list(missing)[:5])}",
                })
            return len(available_symbols & set(expected_symbols)) / len(expected_symbols) if expected_symbols else 1.0

        if missing_symbols:
            issues.append({
                "type": "completeness",
                "severity": "medium",
                "message": f"有 {len(missing_symbols)} 只股票数据缺失",
            })
            return max(0, 1 - len(missing_symbols) / 100)

        return 1.0

    def _check_timeliness(self, data_status: Dict, issues: List[Dict]) -> float:
        """及时性检查"""
        last_update = data_status.get("last_update_time")
        if not last_update:
            issues.append({
                "type": "timeliness",
                "severity": "critical",
                "message": "无法获取数据更新时间",
            })
            return 0.0

        try:
            if isinstance(last_update, str):
                update_time = datetime.fromisoformat(last_update)
            else:
                update_time = last_update

            age_hours = (datetime.now() - update_time).total_seconds() / 3600

            if age_hours > self._stale_threshold_days * 24:
                issues.append({
                    "type": "timeliness",
                    "severity": "critical",
                    "message": f"数据已过期 {age_hours:.0f} 小时（阈值 {self._stale_threshold_days} 天）",
                })
                return 0.0
            elif age_hours > 24:
                issues.append({
                    "type": "timeliness",
                    "severity": "high",
                    "message": f"数据已 {age_hours:.0f} 小时未更新",
                })
                return 0.5
            elif age_hours > 4:
                issues.append({
                    "type": "timeliness",
                    "severity": "medium",
                    "message": f"数据 {age_hours:.1f} 小时前更新",
                })
                return 0.8

            return 1.0
        except Exception:
            return 0.5

    def _check_accuracy(self, data_status: Dict, issues: List[Dict]) -> float:
        """准确性检查"""
        anomalies = data_status.get("anomalies", [])
        if anomalies:
            for anomaly in anomalies[:5]:
                issues.append({
                    "type": "accuracy",
                    "severity": "high",
                    "message": f"数据异常: {anomaly}",
                })
            return max(0, 1 - len(anomalies) * 0.1)

        # 检查价格异常
        price_outliers = data_status.get("price_outliers", 0)
        if price_outliers > 0:
            issues.append({
                "type": "accuracy",
                "severity": "medium",
                "message": f"检测到 {price_outliers} 个价格异常值",
            })
            return max(0, 1 - price_outliers * 0.05)

        return 1.0

    def _check_consistency(self, data_status: Dict, issues: List[Dict]) -> float:
        """一致性检查"""
        inconsistencies = data_status.get("inconsistencies", [])
        if inconsistencies:
            for inc in inconsistencies[:3]:
                issues.append({
                    "type": "consistency",
                    "severity": "medium",
                    "message": f"数据不一致: {inc}",
                })
            return max(0, 1 - len(inconsistencies) * 0.1)
        return 1.0

    def check_specific_symbol(self, symbol: str, symbol_data: Dict) -> Dict[str, Any]:
        """检查单只股票数据质量"""
        issues = []

        close = symbol_data.get("close", 0)
        if close <= 0:
            issues.append({"type": "invalid_price", "message": f"{symbol} 价格无效: {close}"})

        volume = symbol_data.get("volume", 0)
        if volume < 0:
            issues.append({"type": "invalid_volume", "message": f"{symbol} 成交量异常: {volume}"})

        high = symbol_data.get("high", 0)
        low = symbol_data.get("low", 0)
        if high < low:
            issues.append({"type": "price_inconsistency", "message": f"{symbol} 最高价 < 最低价"})

        return {
            "symbol": symbol,
            "quality": "good" if not issues else "poor",
            "issues": issues,
        }

    def get_quality_trend(self, days: int = 7) -> List[Dict]:
        """获取数据质量趋势"""
        return self._quality_history[-days:]

    def get_summary(self) -> Dict[str, Any]:
        """获取质量摘要"""
        if not self._quality_history:
            return {"status": "no_data", "message": "尚未进行数据质量检查"}

        latest = self._quality_history[-1]
        return {
            "status": "good" if latest["overall_score"] > 0.8 else "warning" if latest["overall_score"] > 0.5 else "poor",
            "overall_score": latest["overall_score"],
            "issue_count": latest["issue_count"],
            "critical_issues": latest["critical_issues"],
            "last_checked": latest["checked_at"],
        }
