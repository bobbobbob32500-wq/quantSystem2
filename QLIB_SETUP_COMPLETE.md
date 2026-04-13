# Qlib 安装完成说明

## 安装成功！

Qlib 已成功安装在你的项目中，环境配置如下：

### 环境信息
- **Conda 环境**: `qlib_env`
- **Python 版本**: 3.10.20
- **Qlib 版本**: 0.9.7
- **安装位置**: `C:\Users\32519\miniconda3\envs\qlib_env`

### 已安装的核心模块
- [OK] Qlib 核心库
- [OK] DatasetH (数据集处理)
- [OK] Alpha158 (158个经典因子)
- [OK] Alpha360 (360个因子)
- [OK] LightGBM 模型支持
- [OK] 所有项目依赖

## 如何使用

### 1. 激活 Qlib 环境

在命令行中执行：
```bash
conda activate qlib_env
```

或者在 PowerShell 中：
```powershell
C:\Users\32519\miniconda3\Scripts\activate.bat qlib_env
```

### 2. 运行 Qlib 测试

```bash
python test_qlib_install.py
```

### 3. 使用 Qlib 因子适配器

```python
from src.modules.qlib_factor_adapter import QlibFactorAdapter

# 创建适配器
adapter = QlibFactorAdapter()

# 计算某只股票的 Alpha158 因子
factor_data = adapter.calculate_alpha158_factors(
    stock_code='000001.SZ',
    start_date='2023-01-01',
    end_date='2023-12-31'
)

# 保存到数据库
adapter.save_qlib_factors_to_db(factor_data, '000001.SZ')
```

### 4. 批量计算因子

```python
# 批量计算多只股票
stock_list = ['000001.SZ', '000002.SZ', '600000.SH']
results = adapter.batch_calculate_factors(
    stock_codes=stock_list,
    start_date='2023-01-01',
    end_date='2023-12-31'
)
```

### 5. 分析因子 IC 值

使用你现有的因子分析模块：

```python
from src.modules.factor_analysis import FactorAnalyzer

analyzer = FactorAnalyzer()

# 分析 Qlib 因子的 IC
ic_df = analyzer.calculate_stock_factor_ic(
    factor_name='qlib_alpha158_f0',
    period=5
)

# 获取统计指标
stats = analyzer.calculate_ic_statistics(ic_df)
print(f"IC均值: {stats['ic_mean']:.4f}")
print(f"ICIR: {stats['ic_ir']:.4f}")
```

## 项目文件说明

### 新增文件
1. **`src/modules/qlib_factor_adapter.py`** - Qlib 因子适配器
   - 计算 Alpha158/Alpha360 因子
   - 保存因子到数据库
   - 批量处理功能

2. **`docs/qlib_integration_guide.md`** - 完整集成指南
   - 详细使用说明
   - 示例代码
   - 常见问题

3. **`scripts/setup_qlib_env.py`** - 环境设置脚本（已执行）

4. **`test_qlib_install.py`** - 安装测试脚本

## 下一步建议

### 1. 下载 Qlib 数据（可选）
Qlib 已经初始化成功，但如果你需要使用 Qlib 内置的 A 股数据：
```bash
# 激活环境
conda activate qlib_env

# 下载数据（约 1-2GB，需要几分钟）
python -c "import qlib; from qlib.data import simple_dataset"
```

**注意**: 你的项目已有 TuShare/AKShare 数据源，可以直接使用现有数据，无需下载 Qlib 数据。

### 2. 测试因子计算
```bash
conda activate qlib_env
python src/modules/qlib_factor_adapter.py
```

### 3. 对比因子表现
将 Qlib 因子与你现有的因子对比 IC 值，筛选表现好的因子。

### 4. 纳入选股策略
将 IC 表现好的 Qlib 因子添加到你的选股策略中。

## 注意事项

### 1. 环境切换
- **Qlib 功能**: 必须在 `qlib_env` 环境中使用
- **其他功能**: 可以在主环境（Python 3.14）使用
- **切换命令**: `conda activate qlib_env` / `conda deactivate`

### 2. 依赖冲突
有一个已知的依赖冲突：
- `tushare` 需要 `websocket-client==0.57.0`
- `qlib` 安装了 `websocket-client==1.9.0`

这不影响 Qlib 的核心功能，但如果 TuShare 出现问题，可以：
```bash
conda activate qlib_env
pip install websocket-client==0.57.0
```

### 3. 数据格式
Qlib 对数据格式有特定要求，已通过适配器处理，无需手动转换。

## 验证安装

运行以下命令验证安装：
```bash
conda activate qlib_env
python test_qlib_install.py
```

预期输出：
```
[OK] Qlib 导入成功
[OK] Qlib 初始化成功
[OK] DatasetH 导入成功
[OK] Alpha158 导入成功
[OK] Qlib 安装验证完成
```

## 技术支持

- **Qlib 官方文档**: https://qlib.readthedocs.io/
- **项目集成指南**: `docs/qlib_integration_guide.md`
- **问题反馈**: 在项目中提 Issue

---

安装时间: 2026-04-12
安装状态: 成功
