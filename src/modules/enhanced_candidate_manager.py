"""
候选池管理模块 - 从 EnhancedHybridSystem 拆分
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


class CandidateManager:
    """候选池管理，负责盘后选股、候选池加载/持久化、信号展示。"""

    def __init__(self, hybrid_system):
        self._hs = hybrid_system

    def run_overnight_selection(self) -> List[Dict]:
        logger = self._hs.logger
        config = self._hs.config
        logger.info("执行盘后选股...")
        try:
            selection_result = self._hs.overnight_selector.run_selection(
                market_score=self._hs._get_market_environment().get("market_score", 50.0)
            )
            if not selection_result:
                logger.warning("盘后选股结果为空")
                return []
            core_pool = []
            reserve_pool = []
            for i, stock in enumerate(selection_result):
                score = float(stock.get("total_score", 0))
                candidate = {
                    "symbol": stock.get("ts_code", "").split(".")[0],
                    "name": stock.get("name", ""),
                    "score": score,
                    "level": stock.get("level", ""),
                    "industry": stock.get("industry", ""),
                    "pool_type": "core" if i < config["core_pool_size"] else "reserve",
                    "strategy_profile": self._hs._normalize_strategy_profile(
                        stock.get("strategy_profile", self._hs._resolve_candidate_strategy_profile(stock))
                    ),
                }
                if i < config["core_pool_size"]:
                    core_pool.append(candidate)
                elif i < config["core_pool_size"] + config["reserve_pool_size"]:
                    reserve_pool.append(candidate)
            self._hs.candidate_pool = core_pool + reserve_pool
            self._hs.candidate_date = datetime.now().strftime("%Y%m%d")
            logger.info(f"盘后选股完成: 共{len(self._hs.candidate_pool)}只")
            return self._hs.candidate_pool
        except Exception as e:
            logger.error(f"盘后选股异常: {e}")
            return []

    def load_candidate_pool(self) -> bool:
        logger = self._hs.logger
        data_dir = self._hs.config.get("data.directory", "data")
        candidate_path = Path(data_dir) / "cache" / "candidate_pool.json"
        if not candidate_path.is_file():
            logger.info("候选池文件不存在")
            return False
        try:
            with open(str(candidate_path), "r", encoding="utf-8") as f:
                raw = json.load(f)
            pool = raw if isinstance(raw, list) else raw.get("candidates", [])
            self._hs.candidate_pool = pool
            self._hs.candidate_date = raw.get("candidate_date", "")
            logger.info(f"从文件加载候选池: {len(pool)} 只")
            return True
        except Exception as e:
            logger.error(f"加载候选池失败: {e}")
            return False

    def _save_candidate_pool(self):
        logger = self._hs.logger
        if not self._hs.candidate_pool:
            return
        data_dir = self._hs.config.get("data.directory", "data")
        candidate_path = Path(data_dir) / "cache" / "candidate_pool.json"
        try:
            candidate_path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(candidate_path), "w", encoding="utf-8") as f:
                json.dump(
                    {"candidate_date": self._hs.candidate_date, "candidates": self._hs.candidate_pool},
                    f, ensure_ascii=False, indent=2,
                )
        except Exception as e:
            logger.error(f"保存候选池失败: {e}")

    def print_buy_signals(self, signals):
        if not signals:
            print("    无买入信号")
            return
        print(f"\n{'='*60}")
        print(f"  发现 {len(signals)} 条买入信号")
        print(f"{'='*60}")
        for sig in signals:
            symbol = sig.get("symbol", "N/A")
            name = sig.get("name", "N/A")
            score = sig.get("score", 0)
            reason = sig.get("reason", "")
            strategy = sig.get("strategy_profile", "")
            price = sig.get("price", 0)
            print(f"  {symbol} {name:8s} | 评分:{score:.1f} | 策略:{strategy} | {reason}")
            if price:
                print(f"    {'':>12s}参考价: {price:.2f}")
