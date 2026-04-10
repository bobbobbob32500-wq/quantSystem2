"""
实时行情数据获取模块（爬虫版）

支持两种数据源：
1. 新浪财经（sina）- 支持多只股票
2. 东方财富（dc）- 单只股票

注意：这是爬虫接口，数据来自网络，不进入tushare服务器
"""

import tushare as ts
import pandas as pd
from typing import List, Dict, Optional
import time
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class RealtimeQuoteFetcher:
    """实时行情获取器"""
    
    def __init__(self, token: Optional[str] = None):
        """
        初始化
        
        Args:
            token: Tushare token（可选，实时接口0积分开放）
        """
        if token:
            ts.set_token(token)
        
        self.pro = ts.pro_api()
        self._quota_limited_until_ts = 0.0

    @staticmethod
    def _is_quota_error(message: str) -> bool:
        text = str(message or "")
        return (
            "每天最多访问该接口" in text
            or "每分钟最多访问该接口" in text
            or ("积分" in text and "接口" in text)
        )
    
    def get_realtime_quotes_sina(self, codes: List[str]) -> pd.DataFrame:
        """
        使用新浪数据源获取实时行情（支持多只股票）
        
        Args:
            codes: 股票代码列表，如 ['000001', '600000']
                   一次最多50只股票
        
        Returns:
            实时行情数据
        """
        try:
            if time.time() < self._quota_limited_until_ts:
                logger.warning("实时行情接口额度受限，冷却中，跳过本轮请求")
                return pd.DataFrame()
            all_data = []
            
            # 逐个获取（避免旧版接口bug）
            for code in codes:
                try:
                    df = ts.get_realtime_quotes(code)
                    if df is not None and not df.empty:
                        all_data.append(df)
                    time.sleep(0.1)  # 避免请求过快
                except Exception as e:
                    logger.warning(f"获取{code}行情失败: {e}")
                    continue
            
            if all_data:
                # 合并数据
                df = pd.concat(all_data, ignore_index=True)
                # 格式化数据
                df = self._format_sina_data(df)
                logger.info(f"成功获取{len(df)}只股票实时行情")
                return df
            else:
                logger.warning("获取实时行情数据为空")
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"获取实时行情失败: {e}")
            return pd.DataFrame()
    
    def get_realtime_quote_single(self, code: str, src: str = 'sina') -> Dict:
        """
        获取单只股票实时行情
        
        Args:
            code: 股票代码，如 '000001'
            src: 数据源 'sina' 或 'dc'
        
        Returns:
            格式化的行情数据字典
        """
        try:
            if src == 'sina':
                df = ts.get_realtime_quotes(code)
            else:
                # 东方财富数据源
                ts_code = self._convert_code(code)
                df = self.pro.realtime_quote(ts_code=ts_code, src='dc')
            
            if df is not None and not df.empty:
                return self._format_single_quote(df.iloc[0])
            else:
                return {}
                
        except Exception as e:
            logger.error(f"获取{code}实时行情失败: {e}")
            return {}
    
    def get_realtime_quotes_batch(self, codes: List[str], batch_size: int = 50) -> pd.DataFrame:
        """
        批量获取实时行情（自动分批）
        
        Args:
            codes: 股票代码列表
            batch_size: 每批数量（新浪最多50）
        
        Returns:
            合并后的行情数据
        """
        all_data = []
        
        # 分批处理
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i+batch_size]
            
            logger.info(f"正在获取第{i//batch_size + 1}批数据 ({len(batch)}只股票)")
            
            df = self.get_realtime_quotes_sina(batch)
            if not df.empty:
                all_data.append(df)
            
            # 避免请求过快
            if i + batch_size < len(codes):
                time.sleep(0.5)
        
        if all_data:
            return pd.concat(all_data, ignore_index=True)
        else:
            return pd.DataFrame()
    
    def _format_sina_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """格式化新浪数据"""
        # 确保有code列
        if 'code' not in df.columns:
            logger.error("数据缺少code列")
            return pd.DataFrame()
        
        # 重命名字段
        column_map = {
            'code': 'symbol',
            'name': 'name',
            'open': 'open',
            'pre_close': 'pre_close',
            'price': 'price',
            'high': 'high',
            'low': 'low',
            'bid': 'bid',
            'ask': 'ask',
            'volume': 'volume',
            'amount': 'amount',
            'date': 'date',
            'time': 'time'
        }
        
        # 选择需要的列
        available_cols = [col for col in column_map.keys() if col in df.columns]
        df = df[available_cols].copy()
        
        # 重命名
        df = df.rename(columns={k: v for k, v in column_map.items() if k in available_cols})
        
        # 添加时间戳
        if 'date' in df.columns and 'time' in df.columns:
            df['datetime'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str))
        
        # 计算涨跌幅
        if 'price' in df.columns and 'pre_close' in df.columns:
            df['pct_change'] = (df['price'].astype(float) - df['pre_close'].astype(float)) / df['pre_close'].astype(float) * 100
        
        return df
    
    def _format_single_quote(self, row) -> Dict:
        """格式化单只股票行情"""
        return {
            'symbol': row.get('code', row.get('symbol', '')),
            'name': row.get('name', ''),
            'price': float(row.get('price', 0)),
            'open': float(row.get('open', 0)),
            'high': float(row.get('high', 0)),
            'low': float(row.get('low', 0)),
            'pre_close': float(row.get('pre_close', 0)),
            'volume': float(row.get('volume', 0)),
            'amount': float(row.get('amount', 0)),
            'pct_change': float(row.get('pct_change', 0)),
            'time': str(row.get('time', '')),
            'date': str(row.get('date', ''))
        }
    
    def _convert_code(self, code: str) -> str:
        """转换股票代码格式"""
        if code.startswith('6'):
            return f"{code}.SH"
        else:
            return f"{code}.SZ"
    
    def monitor_realtime(self, codes: List[str], interval: int = 5, callback=None):
        """
        实时监控股票行情
        
        Args:
            codes: 股票代码列表
            interval: 刷新间隔（秒）
            callback: 回调函数，处理行情数据
        """
        logger.info(f"开始实时监控 {len(codes)} 只股票，刷新间隔 {interval} 秒")
        
        try:
            while True:
                # 获取实时行情
                df = self.get_realtime_quotes_sina(codes)
                
                if not df.empty:
                    # 调用回调函数
                    if callback:
                        callback(df)
                    else:
                        # 默认打印
                        self._print_quotes(df)
                
                # 等待
                time.sleep(interval)
                
        except KeyboardInterrupt:
            logger.info("停止实时监控")
    
    def _print_quotes(self, df: pd.DataFrame):
        """打印行情数据"""
        print(f"\n实时行情 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*80)
        
        for _, row in df.iterrows():
            pct = row.get('pct_change', 0)
            pct_str = f"+{pct:.2f}%" if pct > 0 else f"{pct:.2f}%"
            
            print(f"{row['symbol']} {row['name']}")
            print(f"  价格: {row['price']:.2f}  涨跌: {pct_str}")
            print(f"  最高: {row['high']:.2f}  最低: {row['low']:.2f}")
            print(f"  成交量: {row['volume']:.0f}手")
            print("-"*80)


# 使用示例
if __name__ == '__main__':
    # 创建获取器
    fetcher = RealtimeQuoteFetcher()
    
    # 示例1：获取多只股票实时行情
    print("示例1：获取多只股票实时行情")
    print("="*80)
    codes = ['000001', '000002', '600000', '600036']
    df = fetcher.get_realtime_quotes_sina(codes)
    print(df[['symbol', 'name', 'price', 'pct_change', 'volume']])
    
    # 示例2：获取单只股票详细行情
    print("\n示例2：获取单只股票详细行情")
    print("="*80)
    quote = fetcher.get_realtime_quote_single('000001')
    for key, value in quote.items():
        print(f"{key}: {value}")
    
    # 示例3：批量获取（超过50只自动分批）
    print("\n示例3：批量获取")
    print("="*80)
    many_codes = ['000001', '000002', '000004', '000005', '000006',
                  '000007', '000008', '000009', '000010', '000011']
    df_batch = fetcher.get_realtime_quotes_batch(many_codes)
    print(f"获取到{len(df_batch)}只股票数据")
