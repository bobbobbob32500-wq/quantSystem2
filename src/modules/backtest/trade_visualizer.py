# -*- coding: utf-8 -*-
"""
交易详情可视化模块
支持分时图买卖点标注、悬停显示详情、交互式切换
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass

from src.core.logger import get_logger

logger = get_logger("trade_visualizer")


@dataclass
class TradePoint:
    """交易点数据结构"""
    symbol: str
    name: str
    time: datetime
    price: float
    shares: int
    trade_type: str  # 'buy' or 'sell'
    pnl_pct: float = 0.0
    pnl_amount: float = 0.0
    reason: str = ""
    signal_type: str = ""


class TradeVisualizer:
    """交易详情可视化器"""
    
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.has_plotly = self._check_plotly()
    
    def _check_plotly(self) -> bool:
        """检查Plotly是否可用"""
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            return True
        except ImportError:
            logger.warning("Plotly未安装，将使用基础HTML展示")
            return False
    
    def generate_intraday_chart(
        self,
        symbol: str,
        intraday_data: pd.DataFrame,
        trades: List = None,
        trade_points: List[TradePoint] = None,
        output_file: str = None,
        show_markers: bool = True,
        title: str = None
    ) -> str:
        """
        生成分时图并标注买卖点
        
        Args:
            symbol: 股票代码
            intraday_data: 分时数据DataFrame
            trades: 交易记录列表
            trade_points: 交易点列表（优先使用）
            output_file: 输出文件路径
            show_markers: 是否显示买卖点标注
            title: 图表标题
        
        Returns:
            生成的文件路径
        """
        if intraday_data.empty:
            logger.warning(f"无分时数据: {symbol}")
            return None
        
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = self.output_dir / f"intraday_{symbol.replace('.', '_')}_{timestamp}.html"
        else:
            output_file = Path(output_file)
        
        if trade_points is None and trades is not None:
            trade_points = self._convert_trades_to_points(trades, symbol)
        
        if self.has_plotly:
            html_content = self._generate_plotly_chart(
                symbol, intraday_data, trade_points, show_markers, title
            )
        else:
            html_content = self._generate_basic_html(
                symbol, intraday_data, trade_points, show_markers, title
            )
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"分时图已生成: {output_file}")
        return str(output_file)
    
    def generate_backtest_report(
        self,
        symbol: str,
        intraday_data: pd.DataFrame,
        trades: List,
        metrics=None,
        output_file: str = None
    ) -> str:
        """
        生成完整的回测报告，包含分时图和买卖点标注
        
        Args:
            symbol: 股票代码
            intraday_data: 分时数据
            trades: 交易记录
            metrics: 绩效指标
            output_file: 输出文件路径
        
        Returns:
            生成的文件路径
        """
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = self.output_dir / f"backtest_detail_{symbol.replace('.', '_')}_{timestamp}.html"
        else:
            output_file = Path(output_file)
        
        trade_points = self._convert_trades_to_points(trades, symbol)
        
        html_content = self._generate_full_report(
            symbol, intraday_data, trade_points, trades, metrics
        )
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"回测报告已生成: {output_file}")
        return str(output_file)
    
    def _convert_trades_to_points(self, trades: List, symbol: str) -> List[TradePoint]:
        """将交易记录转换为交易点"""
        points = []
        
        for trade in trades:
            if trade.symbol != symbol:
                continue
            
            points.append(TradePoint(
                symbol=trade.symbol,
                name=getattr(trade, 'name', ''),
                time=trade.entry_time,
                price=trade.entry_price,
                shares=trade.shares,
                trade_type='buy',
                signal_type=getattr(trade, 'signal_type', '')
            ))
            
            points.append(TradePoint(
                symbol=trade.symbol,
                name=getattr(trade, 'name', ''),
                time=trade.exit_time,
                price=trade.exit_price,
                shares=trade.shares,
                trade_type='sell',
                pnl_pct=trade.pnl_pct,
                pnl_amount=trade.pnl_amount,
                reason=trade.exit_reason
            ))
        
        return points
    
    def _generate_plotly_chart(
        self,
        symbol: str,
        intraday_data: pd.DataFrame,
        trade_points: List[TradePoint],
        show_markers: bool,
        title: str
    ) -> str:
        """使用Plotly生成交互式图表"""
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        
        if 'trade_time' in intraday_data.columns:
            intraday_data = intraday_data.sort_values('trade_time')
            times = intraday_data['trade_time']
        else:
            times = intraday_data.index
        
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.03,
            row_heights=[0.7, 0.3],
            subplot_titles=('分时价格', '成交量')
        )
        
        fig.add_trace(
            go.Scatter(
                x=times,
                y=intraday_data['close'],
                mode='lines',
                name='价格',
                line=dict(color='#2196F3', width=1.5),
                hovertemplate='<b>时间</b>: %{x}<br><b>价格</b>: %{y:.2f}<extra></extra>'
            ),
            row=1, col=1
        )
        
        if 'volume' in intraday_data.columns:
            colors = ['#4CAF50' if c >= o else '#f44336' 
                     for c, o in zip(intraday_data['close'], intraday_data['open'])]
            fig.add_trace(
                go.Bar(
                    x=times,
                    y=intraday_data['volume'],
                    name='成交量',
                    marker_color=colors,
                    opacity=0.7,
                    hovertemplate='<b>时间</b>: %{x}<br><b>成交量</b>: %{y:,.0f}<extra></extra>'
                ),
                row=2, col=1
            )
        
        if show_markers and trade_points:
            buy_points = [p for p in trade_points if p.trade_type == 'buy']
            sell_points = [p for p in trade_points if p.trade_type == 'sell']
            
            if buy_points:
                buy_times = [p.time for p in buy_points]
                buy_prices = [p.price for p in buy_points]
                buy_texts = [
                    f"<b>买入</b><br>"
                    f"时间: {p.time.strftime('%m-%d %H:%M')}<br>"
                    f"价格: {p.price:.2f}<br>"
                    f"数量: {p.shares}股<br>"
                    f"信号: {p.signal_type or '未知'}"
                    for p in buy_points
                ]
                
                fig.add_trace(
                    go.Scatter(
                        x=buy_times,
                        y=buy_prices,
                        mode='markers',
                        name='买入点',
                        marker=dict(
                            symbol='triangle-up',
                            size=15,
                            color='#4CAF50',
                            line=dict(color='white', width=2)
                        ),
                        hovertext=buy_texts,
                        hoverinfo='text',
                        customdata=['buy'] * len(buy_points)
                    ),
                    row=1, col=1
                )
            
            if sell_points:
                sell_times = [p.time for p in sell_points]
                sell_prices = [p.price for p in sell_points]
                sell_texts = [
                    f"<b>卖出</b><br>"
                    f"时间: {p.time.strftime('%m-%d %H:%M')}<br>"
                    f"价格: {p.price:.2f}<br>"
                    f"数量: {p.shares}股<br>"
                    f"收益: {p.pnl_pct*100:+.2f}%<br>"
                    f"原因: {p.reason or '未知'}"
                    for p in sell_points
                ]
                
                fig.add_trace(
                    go.Scatter(
                        x=sell_times,
                        y=sell_prices,
                        mode='markers',
                        name='卖出点',
                        marker=dict(
                            symbol='triangle-down',
                            size=15,
                            color='#f44336',
                            line=dict(color='white', width=2)
                        ),
                        hovertext=sell_texts,
                        hoverinfo='text',
                        customdata=['sell'] * len(sell_points)
                    ),
                    row=1, col=1
                )
        
        fig.update_layout(
            title=dict(
                text=title or f'{symbol} 分时图',
                font=dict(size=18)
            ),
            showlegend=True,
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            hovermode='closest',
            height=600,
            template='plotly_white',
            updatemenus=[
                dict(
                    type="buttons",
                    direction="left",
                    buttons=[
                        dict(
                            label="显示标注",
                            method="update",
                            args=[{"visible": True}]
                        ),
                        dict(
                            label="隐藏标注",
                            method="update",
                            args=[{"visible": [True, True, False, False]}]
                        )
                    ],
                    pad={"r": 10, "t": 10},
                    showactive=True,
                    x=0.11,
                    xanchor="left",
                    y=1.1,
                    yanchor="top"
                )
            ]
        )
        
        fig.update_xaxes(title_text="时间", row=2, col=1)
        fig.update_yaxes(title_text="价格", row=1, col=1)
        fig.update_yaxes(title_text="成交量", row=2, col=1)
        
        return fig.to_html(include_plotlyjs='cdn', full_html=True)
    
    def _generate_basic_html(
        self,
        symbol: str,
        intraday_data: pd.DataFrame,
        trade_points: List[TradePoint],
        show_markers: bool,
        title: str
    ) -> str:
        """生成基础HTML表格展示"""
        buy_points = [p for p in trade_points if p.trade_type == 'buy'] if trade_points else []
        sell_points = [p for p in trade_points if p.trade_type == 'sell'] if trade_points else []
        
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{symbol} 分时图</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background-color: #4CAF50; color: white; }}
        .buy {{ background-color: #e8f5e9; }}
        .sell {{ background-color: #ffebee; }}
        .positive {{ color: #4CAF50; }}
        .negative {{ color: #f44336; }}
    </style>
</head>
<body>
    <h1>{title or f'{symbol} 分时数据'}</h1>
    
    <h2>买入点 ({len(buy_points)}个)</h2>
    <table>
        <tr><th>时间</th><th>价格</th><th>数量</th><th>信号类型</th></tr>
        {self._generate_trade_table_rows(buy_points, 'buy')}
    </table>
    
    <h2>卖出点 ({len(sell_points)}个)</h2>
    <table>
        <tr><th>时间</th><th>价格</th><th>数量</th><th>收益率</th><th>原因</th></tr>
        {self._generate_trade_table_rows(sell_points, 'sell')}
    </table>
</body>
</html>
        """
    
    def _generate_trade_table_rows(self, points: List[TradePoint], trade_type: str) -> str:
        """生成交易表格行"""
        rows = ""
        for p in points:
            if trade_type == 'buy':
                rows += f"""
                <tr class="buy">
                    <td>{p.time.strftime('%m-%d %H:%M')}</td>
                    <td>{p.price:.2f}</td>
                    <td>{p.shares}</td>
                    <td>{p.signal_type or '-'}</td>
                </tr>
                """
            else:
                pnl_class = "positive" if p.pnl_pct >= 0 else "negative"
                rows += f"""
                <tr class="sell">
                    <td>{p.time.strftime('%m-%d %H:%M')}</td>
                    <td>{p.price:.2f}</td>
                    <td>{p.shares}</td>
                    <td class="{pnl_class}">{p.pnl_pct*100:+.2f}%</td>
                    <td>{p.reason or '-'}</td>
                </tr>
                """
        return rows
    
    def _generate_full_report(
        self,
        symbol: str,
        intraday_data: pd.DataFrame,
        trade_points: List[TradePoint],
        trades: List,
        metrics
    ) -> str:
        """生成完整报告"""
        buy_points = [p for p in trade_points if p.trade_type == 'buy'] if trade_points else []
        sell_points = [p for p in trade_points if p.trade_type == 'sell'] if trade_points else []
        
        symbol_trades = [t for t in trades if t.symbol == symbol] if trades else []
        
        total_pnl = sum(t.pnl_amount for t in symbol_trades)
        avg_pnl_pct = np.mean([t.pnl_pct for t in symbol_trades]) if symbol_trades else 0
        win_rate = len([t for t in symbol_trades if t.pnl_pct > 0]) / len(symbol_trades) if symbol_trades else 0
        
        chart_html = ""
        if self.has_plotly:
            chart_html = self._generate_plotly_chart(symbol, intraday_data, trade_points, True, None)
            chart_html = chart_html.split('<body>')[1].split('</body>')[0]
        
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{symbol} 回测详情报告</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        * {{ box-sizing: border-box; }}
        body {{ 
            font-family: 'Segoe UI', Arial, sans-serif; 
            margin: 0; 
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        h1 {{ 
            color: #333; 
            border-bottom: 3px solid #2196F3;
            padding-bottom: 10px;
        }}
        h2 {{ 
            color: #555;
            margin-top: 30px;
            border-left: 4px solid #2196F3;
            padding-left: 10px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .summary-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            text-align: center;
        }}
        .summary-card .label {{ font-size: 14px; opacity: 0.9; }}
        .summary-card .value {{ font-size: 24px; font-weight: bold; margin-top: 5px; }}
        .chart-container {{
            margin: 20px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
            overflow: hidden;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        th, td {{
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #ddd;
        }}
        th {{
            background-color: #2196F3;
            color: white;
            position: sticky;
            top: 0;
        }}
        tr:hover {{ background-color: #f5f5f5; }}
        .buy-row {{ background-color: #e8f5e9; }}
        .sell-row {{ background-color: #ffebee; }}
        .positive {{ color: #4CAF50; font-weight: bold; }}
        .negative {{ color: #f44336; font-weight: bold; }}
        .legend {{
            display: flex;
            gap: 20px;
            margin: 10px 0;
            padding: 10px;
            background-color: #f9f9f9;
            border-radius: 5px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .legend-marker {{
            width: 20px;
            height: 20px;
        }}
        .marker-buy {{
            width: 0;
            height: 0;
            border-left: 10px solid transparent;
            border-right: 10px solid transparent;
            border-bottom: 20px solid #4CAF50;
        }}
        .marker-sell {{
            width: 0;
            height: 0;
            border-left: 10px solid transparent;
            border-right: 10px solid transparent;
            border-top: 20px solid #f44336;
        }}
        .toggle-container {{
            margin: 15px 0;
        }}
        .toggle-btn {{
            padding: 10px 20px;
            margin-right: 10px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: all 0.3s;
        }}
        .toggle-btn.active {{
            background-color: #2196F3;
            color: white;
        }}
        .toggle-btn:not(.active) {{
            background-color: #ddd;
            color: #333;
        }}
        .toggle-btn:hover {{
            opacity: 0.8;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 {symbol} 回测详情报告</h1>
        <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>📈 交易概览</h2>
        <div class="summary-grid">
            <div class="summary-card">
                <div class="label">总交易次数</div>
                <div class="value">{len(symbol_trades)}</div>
            </div>
            <div class="summary-card">
                <div class="label">总收益</div>
                <div class="value">{total_pnl:,.2f}</div>
            </div>
            <div class="summary-card">
                <div class="label">平均收益率</div>
                <div class="value">{avg_pnl_pct*100:+.2f}%</div>
            </div>
            <div class="summary-card">
                <div class="label">胜率</div>
                <div class="value">{win_rate*100:.1f}%</div>
            </div>
        </div>
        
        <h2>📉 分时走势图</h2>
        <div class="legend">
            <div class="legend-item">
                <div class="marker-buy"></div>
                <span>买入点</span>
            </div>
            <div class="legend-item">
                <div class="marker-sell"></div>
                <span>卖出点</span>
            </div>
        </div>
        <div class="toggle-container">
            <button class="toggle-btn active" onclick="showAllMarkers()">显示标注</button>
            <button class="toggle-btn" onclick="hideMarkers()">隐藏标注</button>
        </div>
        <div class="chart-container" id="chart-container">
            {chart_html if self.has_plotly else '<p>请安装Plotly以查看交互式图表: pip install plotly</p>'}
        </div>
        
        <h2>📝 买入点详情 ({len(buy_points)}个)</h2>
        <table id="buy-table">
            <thead>
                <tr>
                    <th>序号</th>
                    <th>时间</th>
                    <th>价格</th>
                    <th>数量</th>
                    <th>金额</th>
                    <th>信号类型</th>
                </tr>
            </thead>
            <tbody>
                {self._generate_buy_table_rows(buy_points)}
            </tbody>
        </table>
        
        <h2>💰 卖出点详情 ({len(sell_points)}个)</h2>
        <table id="sell-table">
            <thead>
                <tr>
                    <th>序号</th>
                    <th>时间</th>
                    <th>价格</th>
                    <th>数量</th>
                    <th>收益率</th>
                    <th>收益金额</th>
                    <th>卖出原因</th>
                </tr>
            </thead>
            <tbody>
                {self._generate_sell_table_rows(sell_points)}
            </tbody>
        </table>
    </div>
    
    <script>
        function showAllMarkers() {{
            document.querySelectorAll('.toggle-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('#buy-table tbody tr, #sell-table tbody tr').forEach(row => {{
                row.style.display = '';
            }});
        }}
        
        function hideMarkers() {{
            document.querySelectorAll('.toggle-btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            document.querySelectorAll('#buy-table tbody tr, #sell-table tbody tr').forEach(row => {{
                row.style.display = 'none';
            }});
        }}
    </script>
</body>
</html>
        """
    
    def _generate_buy_table_rows(self, points: List[TradePoint]) -> str:
        """生成买入表格行"""
        rows = ""
        for i, p in enumerate(points, 1):
            amount = p.price * p.shares
            rows += f"""
                <tr class="buy-row">
                    <td>{i}</td>
                    <td>{p.time.strftime('%Y-%m-%d %H:%M')}</td>
                    <td>{p.price:.2f}</td>
                    <td>{p.shares}</td>
                    <td>{amount:,.2f}</td>
                    <td>{p.signal_type or '-'}</td>
                </tr>
            """
        return rows
    
    def _generate_sell_table_rows(self, points: List[TradePoint]) -> str:
        """生成卖出表格行"""
        rows = ""
        for i, p in enumerate(points, 1):
            pnl_class = "positive" if p.pnl_pct >= 0 else "negative"
            rows += f"""
                <tr class="sell-row">
                    <td>{i}</td>
                    <td>{p.time.strftime('%Y-%m-%d %H:%M')}</td>
                    <td>{p.price:.2f}</td>
                    <td>{p.shares}</td>
                    <td class="{pnl_class}">{p.pnl_pct*100:+.2f}%</td>
                    <td class="{pnl_class}">{p.pnl_amount:+,.2f}</td>
                    <td>{p.reason or '-'}</td>
                </tr>
            """
        return rows


def generate_multi_stock_report(
    symbols: List[str],
    intraday_data_dict: Dict[str, pd.DataFrame],
    trades: List,
    output_dir: str = "reports"
) -> str:
    """
    生成多股票回测报告
    
    Args:
        symbols: 股票代码列表
        intraday_data_dict: 分时数据字典 {symbol: DataFrame}
        trades: 交易记录列表
        output_dir: 输出目录
    
    Returns:
        报告文件路径
    """
    visualizer = TradeVisualizer(output_dir)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = Path(output_dir) / f"multi_stock_report_{timestamp}.html"
    
    html_parts = [f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>多股票回测报告</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 20px; background-color: #f5f5f5; }}
        .container {{ max-width: 1400px; margin: 0 auto; }}
        .stock-section {{ background-color: white; margin: 20px 0; padding: 20px; border-radius: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; text-align: center; }}
        h2 {{ color: #2196F3; border-bottom: 2px solid #2196F3; padding-bottom: 10px; }}
        .nav {{ position: sticky; top: 0; background-color: white; padding: 15px; margin-bottom: 20px; border-radius: 5px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
        .nav a {{ margin-right: 15px; text-decoration: none; color: #2196F3; font-weight: bold; }}
        .nav a:hover {{ text-decoration: underline; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 多股票回测报告</h1>
        <p style="text-align: center;">生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <div class="nav">
            <strong>快速导航：</strong>
    """]
    
    for symbol in symbols:
        html_parts.append(f'<a href="#{symbol}">{symbol}</a>')
    
    html_parts.append('</div>')
    
    for symbol in symbols:
        intraday_data = intraday_data_dict.get(symbol, pd.DataFrame())
        symbol_trades = [t for t in trades if t.symbol == symbol]
        
        trade_points = visualizer._convert_trades_to_points(symbol_trades, symbol)
        
        html_parts.append(f'<div class="stock-section" id="{symbol}">')
        html_parts.append(f'<h2>{symbol}</h2>')
        
        if not intraday_data.empty and visualizer.has_plotly:
            chart_html = visualizer._generate_plotly_chart(symbol, intraday_data, trade_points, True, None)
            chart_content = chart_html.split('<body>')[1].split('</body>')[0] if '<body>' in chart_html else chart_html
            html_parts.append(chart_content)
        
        if symbol_trades:
            html_parts.append('<table style="width:100%; margin-top:20px;">')
            html_parts.append('<tr><th>买入时间</th><th>买入价格</th><th>卖出时间</th><th>卖出价格</th><th>收益率</th><th>原因</th></tr>')
            for t in symbol_trades:
                pnl_class = "positive" if t.pnl_pct > 0 else "negative"
                html_parts.append(f'''
                    <tr>
                        <td>{t.entry_time.strftime('%m-%d %H:%M') if t.entry_time else '-'}</td>
                        <td>{t.entry_price:.2f}</td>
                        <td>{t.exit_time.strftime('%m-%d %H:%M') if t.exit_time else '-'}</td>
                        <td>{t.exit_price:.2f}</td>
                        <td class="{pnl_class}">{t.pnl_pct*100:+.2f}%</td>
                        <td>{t.exit_reason}</td>
                    </tr>
                ''')
            html_parts.append('</table>')
        else:
            html_parts.append('<p>无交易记录</p>')
        
        html_parts.append('</div>')
    
    html_parts.append('</div></body></html>')
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(html_parts))
    
    return str(output_file)
