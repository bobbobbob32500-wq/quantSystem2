# -*- coding: utf-8 -*-
"""
Qlib 因子适配器
将 Qlib 的 Alpha158 因子集成到现有因子分析框架
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime

try:
    import qlib
    from qlib.data.dataset import DatasetH
    from qlib.contrib.data.handler import Alpha158, Alpha360
    QLIB_AVAILABLE = True
except ImportError:
    QLIB_AVAILABLE = False

from src.core.logger import get_logger
from src.core.database import DatabaseManager
from src.core.config import ConfigManager

logger = get_logger("qlib_factor_adapter")


class QlibFactorAdapter:
    """Qlib 因子适配器 - 桥接 Qlib 与现有因子分析框架"""
    
    def __init__(self, config: ConfigManager = None, db: DatabaseManager = None):
        """
        初始化 Qlib 因子适配器
        
        Args:
            config: 配置管理器
            db: 数据库管理器
        """
        if not QLIB_AVAILABLE:
            raise ImportError(
                "Qlib 未安装，请执行以下命令：\n"
                "1. conda create -n qlib_env python=3.10\n"
                "2. conda activate qlib_env\n"
                "3. pip install pyqlib"
            )
        
        self.config = config or ConfigManager()
        self.db = db or DatabaseManager(self.config)
        
        # 初始化 Qlib（使用默认配置）
        try:
            qlib.init(provider_uri='~/.qlib/qlib_data/cn_data')
            logger.info("Qlib 初始化成功")
        except Exception as e:
            logger.warning(f"Qlib 初始化失败（可能需要先下载数据）: {e}")
        
        logger.info("Qlib 因子适配器初始化完成")
    
    def calculate_alpha158_factors(self, 
                                   stock_code: str,
                                   start_date: str,
                                   end_date: str) -> pd.DataFrame:
        """
        计算单只股票的 Alpha158 因子
        
        Args:
            stock_code: 股票代码（如 '000001.SZ'）
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
        
        Returns:
            因子值 DataFrame，列名为因子名，索引为日期
        """
        logger.info(f"计算 Alpha158 因子: {stock_code}, {start_date} ~ {end_date}")
        
        try:
            # 创建 Alpha158 数据处理器
            handler = Alpha158(
                instruments=stock_code,
                start_time=start_date,
                end_time=end_date
            )
            
            # 获取因子数据
            factor_data = handler.fetch()
            
            logger.info(f"成功计算 {len(factor_data.columns)} 个因子，{len(factor_data)} 个交易日")
            return factor_data
        
        except Exception as e:
            logger.error(f"计算 Alpha158 因子失败: {e}")
            return pd.DataFrame()
    
    def calculate_alpha360_factors(self,
                                   stock_code: str,
                                   start_date: str,
                                   end_date: str) -> pd.DataFrame:
        """
        计算单只股票的 Alpha360 因子（更丰富的因子集）
        
        Args:
            stock_code: 股票代码
            start_date: 开始日期（YYYY-MM-DD）
            end_date: 结束日期（YYYY-MM-DD）
        
        Returns:
            因子值 DataFrame
        """
        logger.info(f"计算 Alpha360 因子: {stock_code}, {start_date} ~ {end_date}")
        
        try:
            handler = Alpha360(
                instruments=stock_code,
                start_time=start_date,
                end_time=end_date
            )
            
            factor_data = handler.fetch()
            logger.info(f"成功计算 {len(factor_data.columns)} 个 Alpha360 因子")
            return factor_data
        
        except Exception as e:
            logger.error(f"计算 Alpha360 因子失败: {e}")
            return pd.DataFrame()
    
    def save_qlib_factors_to_db(self, 
                                factor_data: pd.DataFrame,
                                stock_code: str,
                                factor_prefix: str = 'qlib_alpha158_'):
        """
        将 Qlib 因子保存到数据库
        
        Args:
            factor_data: Qlib 因子数据
            stock_code: 股票代码
            factor_prefix: 因子名前缀
        """
        if factor_data.empty:
            logger.warning("因子数据为空，跳过保存")
            return
        
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        saved_count = 0
        
        try:
            # 遍历每个因子列
            for factor_name in factor_data.columns:
                full_factor_name = f"{factor_prefix}{factor_name}"
                
                # 遍历每个日期
                for date, value in factor_data[factor_name].items():
                    if pd.isna(value):
                        continue
                    
                    # 处理日期格式
                    if hasattr(date, 'strftime'):
                        trade_date = date.strftime('%Y%m%d')
                    else:
                        trade_date = str(date).replace('-', '')
                    
                    # 插入或更新因子值
                    cursor.execute("""
                        INSERT OR REPLACE INTO factor_values 
                        (ts_code, trade_date, factor_name, factor_value, update_time)
                        VALUES (?, ?, ?, ?, ?)
                    """, (
                        stock_code,
                        trade_date,
                        full_factor_name,
                        float(value),
                        datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    ))
                    saved_count += 1
            
            conn.commit()
            logger.info(f"已保存 {saved_count} 条因子数据到数据库（{len(factor_data.columns)} 个因子）")
        
        except Exception as e:
            logger.error(f"保存因子数据失败: {e}")
            conn.rollback()
        
        finally:
            cursor.close()
            conn.close()
    
    def batch_calculate_factors(self,
                                stock_codes: List[str],
                                start_date: str,
                                end_date: str,
                                factor_type: str = 'alpha158') -> Dict[str, pd.DataFrame]:
        """
        批量计算多只股票的 Qlib 因子
        
        Args:
            stock_codes: 股票代码列表
            start_date: 开始日期
            end_date: 结束日期
            factor_type: 因子类型（'alpha158' 或 'alpha360'）
        
        Returns:
            字典：股票代码 -> 因子数据
        """
        results = {}
        
        for i, stock_code in enumerate(stock_codes):
            logger.info(f"处理进度: {i+1}/{len(stock_codes)} - {stock_code}")
            
            try:
                if factor_type == 'alpha158':
                    factor_data = self.calculate_alpha158_factors(
                        stock_code, start_date, end_date
                    )
                else:
                    factor_data = self.calculate_alpha360_factors(
                        stock_code, start_date, end_date
                    )
                
                if not factor_data.empty:
                    results[stock_code] = factor_data
                    # 自动保存到数据库
                    self.save_qlib_factors_to_db(factor_data, stock_code)
            
            except Exception as e:
                logger.error(f"处理 {stock_code} 失败: {e}")
                continue
        
        logger.info(f"批量计算完成，成功处理 {len(results)}/{len(stock_codes)} 只股票")
        return results
    
    def get_factor_list(self, factor_prefix: str = 'qlib_alpha158_') -> List[str]:
        """
        获取数据库中已有的 Qlib 因子列表
        
        Args:
            factor_prefix: 因子名前缀
        
        Returns:
            因子名列表
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT DISTINCT factor_name 
                FROM factor_values 
                WHERE factor_name LIKE ?
                ORDER BY factor_name
            """, (f"{factor_prefix}%",))
            
            factor_names = [row[0] for row in cursor.fetchall()]
            return factor_names
        
        finally:
            cursor.close()
            conn.close()
    
    def get_factor_statistics(self, factor_name: str) -> Dict:
        """
        获取因子的基本统计信息
        
        Args:
            factor_name: 因子名
        
        Returns:
            统计信息字典
        """
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT 
                    COUNT(*) as count,
                    AVG(factor_value) as mean,
                    MIN(factor_value) as min,
                    MAX(factor_value) as max,
                    STDEV(factor_value) as std
                FROM factor_values
                WHERE factor_name = ?
            """, (factor_name,))
            
            row = cursor.fetchone()
            
            if row and row[0] > 0:
                return {
                    'count': row[0],
                    'mean': row[1],
                    'min': row[2],
                    'max': row[3],
                    'std': row[4]
                }
            
            return {}
        
        finally:
            cursor.close()
            conn.close()


def test_qlib_integration():
    """测试 Qlib 集成"""
    print("=" * 60)
    print("Qlib 因子适配器测试")
    print("=" * 60)
    
    try:
        adapter = QlibFactorAdapter()
        
        # 测试计算 Alpha158 因子
        print("\n1. 测试计算 Alpha158 因子...")
        factor_data = adapter.calculate_alpha158_factors(
            stock_code='000001.SZ',
            start_date='2023-01-01',
            end_date='2023-12-31'
        )
        
        if not factor_data.empty:
            print(f"✅ 成功计算 {len(factor_data.columns)} 个因子")
            print(f"   时间范围: {factor_data.index[0]} ~ {factor_data.index[-1]}")
            print(f"   因子示例: {list(factor_data.columns[:5])}")
            
            # 测试保存到数据库
            print("\n2. 测试保存到数据库...")
            adapter.save_qlib_factors_to_db(factor_data, '000001.SZ')
            print("✅ 保存成功")
            
            # 测试获取因子列表
            print("\n3. 测试获取因子列表...")
            factor_list = adapter.get_factor_list()
            print(f"✅ 数据库中共有 {len(factor_list)} 个 Qlib 因子")
            
            # 测试获取因子统计
            if factor_list:
                print("\n4. 测试获取因子统计...")
                stats = adapter.get_factor_statistics(factor_list[0])
                print(f"✅ 因子 {factor_list[0]} 统计:")
                print(f"   数据量: {stats.get('count', 0)}")
                print(f"   均值: {stats.get('mean', 0):.4f}")
                print(f"   标准差: {stats.get('std', 0):.4f}")
        else:
            print("❌ 因子计算失败，可能需要先下载 Qlib 数据")
        
        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)
    
    except ImportError as e:
        print(f"❌ {e}")
    except Exception as e:
        print(f"❌ 测试失败: {e}")


if __name__ == '__main__':
    test_qlib_integration()
