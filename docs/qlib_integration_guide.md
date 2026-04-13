# Qlib 集成指南

## 为什么在本项目集成 Qlib？

### 优势
1. **代码复用**：直接利用现有的因子分析框架（FactorAnalyzer）
2. **数据共享**：TuShare/AKShare 数据无需重复获取
3. **模型对比**：Qlib 因子与现有因子可直接对比 IC 值
4. **统一管理**：单一项目，依赖和版本控制更简单

### 架构兼容性
- ✅ 因子分析模块：`src/modules/factor_analysis.py`
- ✅ 策略引擎：`src/core/strategy_engine.py`
- ✅ 回测框架：`src/modules/backtest/`
- ✅ 数据库：已有完整的因子存储表结构

## 集成步骤

### 第一步：创建 Python 3.10 虚拟环境

由于 Qlib 目前仅支持 Python 3.7-3.10，而你的主环境是 Python 3.14，需要创建独立虚拟环境：

```bash
# 方案A：使用 conda（推荐）
conda create -n qlib_env python=3.10
conda activate qlib_env

# 方案B：使用 venv（如果没有 conda）
# 先安装 Python 3.10，然后：
python3.10 -m venv .venv_qlib
# Windows 激活：
.venv_qlib\Scripts\activate
# Linux/Mac 激活：
source .venv_qlib/bin/activate
```

### 第二步：安装依赖

```bash
# 1. 安装项目基础依赖
pip install -r requirements.txt

# 2. 安装 Qlib
pip install pyqlib

# 3. 验证安装
python -c "import qlib; print('Qlib 安装成功')"
```

### 第三步：初始化 Qlib

```bash
# 下载 Qlib 内置数据（可选，用于测试）
python -m qlib.run.get_data

# 或使用你自己的数据源（推荐）
# 见下方"数据对接"章节
```

### 第四步：创建 Qlib 因子适配器

在项目中创建新模块：`src/modules/qlib_factor_adapter.py`

```python
# -*- coding: utf-8 -*-
"""
Qlib 因子适配器
将 Qlib 的 Alpha158 因子集成到现有因子分析框架
"""

import pandas as pd
import numpy as np
from typing import Dict, List
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
from src.modules.factor_analysis import FactorAnalyzer

logger = get_logger("qlib_factor_adapter")


class QlibFactorAdapter:
    """Qlib 因子适配器 - 桥接 Qlib 与现有因子分析框架"""
    
    def __init__(self, db: DatabaseManager = None):
        if not QLIB_AVAILABLE:
            raise ImportError("Qlib 未安装，请执行: pip install pyqlib")
        
        self.db = db or DatabaseManager()
        self.factor_analyzer = FactorAnalyzer(db=self.db)
        
        # 初始化 Qlib
        qlib.init(provider_uri='~/.qlib/qlib_data/cn_data')
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
        
        # 创建 Alpha158 数据处理器
        handler = Alpha158(
            instruments=stock_code,
            start_time=start_date,
            end_time=end_date
        )
        
        # 获取因子数据
        factor_data = handler.fetch()
        
        return factor_data
    
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
        conn = self.db._get_connection()
        cursor = conn.cursor()
        
        try:
            # 遍历每个因子列
            for factor_name in factor_data.columns:
                full_factor_name = f"{factor_prefix}{factor_name}"
                
                # 遍历每个日期
                for date, value in factor_data[factor_name].items():
                    if pd.isna(value):
                        continue
                    
                    trade_date = date.strftime('%Y%m%d')
                    
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
            
            conn.commit()
            logger.info(f"已保存 {len(factor_data.columns)} 个 Qlib 因子到数据库")
        
        finally:
            cursor.close()
            conn.close()
    
    def analyze_qlib_factors_ic(self,
                                factor_names: List[str],
                                period: int = 5) -> Dict[str, Dict]:
        """
        分析 Qlib 因子的 IC 值
        
        Args:
            factor_names: 因子名列表
            period: 预测周期
        
        Returns:
            各因子的 IC 统计结果
        """
        results = {}
        
        for factor_name in factor_names:
            logger.info(f"分析因子 IC: {factor_name}")
            
            # 使用现有的 FactorAnalyzer 计算 IC
            ic_df = self.factor_analyzer.calculate_stock_factor_ic(
                factor_name=factor_name,
                period=period
            )
            
            if not ic_df.empty:
                stats = self.factor_analyzer.calculate_ic_statistics(ic_df)
                results[factor_name] = stats
        
        return results
    
    def compare_with_existing_factors(self,
                                      qlib_factor_name: str,
                                      existing_factor_name: str) -> Dict:
        """
        对比 Qlib 因子与现有因子的表现
        
        Args:
            qlib_factor_name: Qlib 因子名
            existing_factor_name: 现有因子名
        
        Returns:
            对比结果
        """
        # 计算 Qlib 因子 IC
        qlib_ic = self.factor_analyzer.calculate_stock_factor_ic(qlib_factor_name)
        qlib_stats = self.factor_analyzer.calculate_ic_statistics(qlib_ic)
        
        # 计算现有因子 IC
        existing_ic = self.factor_analyzer.calculate_stock_factor_ic(existing_factor_name)
        existing_stats = self.factor_analyzer.calculate_ic_statistics(existing_ic)
        
        return {
            'qlib_factor': {
                'name': qlib_factor_name,
                'ic_mean': qlib_stats.get('ic_mean', 0),
                'ic_ir': qlib_stats.get('ic_ir', 0)
            },
            'existing_factor': {
                'name': existing_factor_name,
                'ic_mean': existing_stats.get('ic_mean', 0),
                'ic_ir': existing_stats.get('ic_ir', 0)
            },
            'improvement': {
                'ic_mean': qlib_stats.get('ic_mean', 0) - existing_stats.get('ic_mean', 0),
                'ic_ir': qlib_stats.get('ic_ir', 0) - existing_stats.get('ic_ir', 0)
            }
        }


def test_qlib_integration():
    """测试 Qlib 集成"""
    adapter = QlibFactorAdapter()
    
    # 测试计算 Alpha158 因子
    factor_data = adapter.calculate_alpha158_factors(
        stock_code='000001.SZ',
        start_date='2023-01-01',
        end_date='2023-12-31'
    )
    
    print(f"计算得到 {len(factor_data.columns)} 个因子")
    print(f"时间范围: {factor_data.index[0]} ~ {factor_data.index[-1]}")
    
    # 保存到数据库
    adapter.save_qlib_factors_to_db(factor_data, '000001.SZ')
    
    print("Qlib 集成测试完成")


if __name__ == '__main__':
    test_qlib_integration()
```

### 第五步：数据对接

Qlib 需要特定格式的数据，创建转换脚本：`scripts/convert_data_to_qlib.py`

```python
# -*- coding: utf-8 -*-
"""
将 TuShare 数据转换为 Qlib 格式
"""

import pandas as pd
from src.core.database import DatabaseManager

def convert_to_qlib_format():
    """将数据库中的数据转换为 Qlib 格式"""
    db = DatabaseManager()
    
    # 获取股票日线数据
    conn = db._get_connection()
    df = pd.read_sql("""
        SELECT 
            ts_code as instrument,
            trade_date as datetime,
            open,
            high,
            low,
            close,
            vol as volume,
            amount
        FROM stock_daily
        ORDER BY ts_code, trade_date
    """, conn)
    conn.close()
    
    # 转换日期格式
    df['datetime'] = pd.to_datetime(df['datetime'])
    
    # 保存为 Qlib 格式（QLib 需要 parquet 或二进制格式）
    # 这里简化为 CSV，实际使用建议用 Qlib 的数据构建工具
    df.to_csv('data/qlib_format_data.csv', index=False)
    
    print(f"已转换 {len(df)} 条数据")


if __name__ == '__main__':
    convert_to_qlib_format()
```

## 使用示例

### 示例 1：计算并保存 Qlib 因子

```python
from src.modules.qlib_factor_adapter import QlibFactorAdapter

adapter = QlibFactorAdapter()

# 计算平安银行的 Alpha158 因子
factor_data = adapter.calculate_alpha158_factors(
    stock_code='000001.SZ',
    start_date='2023-01-01',
    end_date='2023-12-31'
)

# 保存到数据库
adapter.save_qlib_factors_to_db(factor_data, '000001.SZ')
```

### 示例 2：分析 Qlib 因子 IC

```python
# 分析前 10 个 Alpha158 因子的 IC
factor_names = [f'qlib_alpha158_f{ i}' for i in range(10)]
ic_results = adapter.analyze_qlib_factors_ic(factor_names, period=5)

# 打印结果
for factor_name, stats in ic_results.items():
    print(f"{factor_name}: IC均值={stats['ic_mean']:.4f}, ICIR={stats['ic_ir']:.4f}")
```

### 示例 3：对比因子表现

```python
# 对比 Qlib 的动量因子与你现有的动量因子
comparison = adapter.compare_with_existing_factors(
    qlib_factor_name='qlib_alpha158_f0',  # Qlib 的某个因子
    existing_factor_name='momentum_score'  # 你现有的动量因子
)

print(f"Qlib 因子 IC均值: {comparison['qlib_factor']['ic_mean']:.4f}")
print(f"现有因子 IC均值: {comparison['existing_factor']['ic_mean']:.4f}")
print(f"提升: {comparison['improvement']['ic_mean']:.4f}")
```

## 运行 Qlib 基准策略

```bash
# 运行 Qlib 内置的 LightGBM 策略（与你的模型对比）
qrun benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml

# 查看结果
# 结果会保存在 Qlib 的输出目录中
```

## 注意事项

1. **虚拟环境切换**
   - 使用 Qlib 功能前，确保激活 `qlib_env` 环境
   - 其他功能继续使用主环境（Python 3.14）

2. **数据格式**
   - Qlib 对数据格式有特定要求
   - 建议先用少量数据测试转换流程

3. **性能优化**
   - Alpha158 因子计算较慢，建议批量处理
   - 可使用 Qlib 的缓存机制加速

4. **依赖冲突**
   - 如果遇到依赖冲突，可尝试：
     ```bash
     pip install pyqlib --no-deps
     pip install qlib-run  # 单独安装运行时依赖
     ```

## 下一步

1. ✅ 创建虚拟环境并安装 Qlib
2. ✅ 运行测试脚本验证集成
3. ✅ 批量计算股票的 Alpha158 因子
4. ✅ 对比 Qlib 因子与现有因子的 IC 表现
5. ✅ 将表现好的 Qlib 因子纳入选股策略

## 常见问题

### Q: Qlib 数据下载慢怎么办？
A: 可以使用你现有的 TuShare/AKShare 数据，通过转换脚本转为 Qlib 格式。

### Q: Qlib 因子计算报错？
A: 检查数据格式是否符合 Qlib 要求，确保有足够的交易日数据（至少 60 天）。

### Q: 如何选择有用的 Qlib 因子？
A: 使用 `analyze_qlib_factors_ic()` 批量计算 IC，筛选 IC均值 > 0.03 且 ICIR > 0.5 的因子。
