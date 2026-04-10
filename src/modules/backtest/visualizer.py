# -*- coding: utf-8 -*-
"""
回测结果可视化模块
生成图表展示关键指标，包含分时图买卖点标注
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from src.core.logger import get_logger

logger = get_logger("backtest_visualizer")


class BacktestVisualizer:
    """回测结果可视化器"""
    
    def __init__(self, output_dir: str = "reports"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates
            self.plt = plt
            self.mdates = mdates
            self.plt.rcParams['font.sans-serif'] = [
                'Microsoft YaHei',
                'SimHei',
                'Noto Sans CJK SC',
                'WenQuanYi Micro Hei',
                'Arial Unicode MS',
                'DejaVu Sans',
            ]
            self.plt.rcParams['axes.unicode_minus'] = False
            self.has_matplotlib = True
        except ImportError:
            logger.warning("matplotlib未安装，将只生成HTML报告")
            self.has_matplotlib = False
        
        try:
            import plotly.graph_objects as go
            from plotly.subplots import make_subplots
            self.has_plotly = True
        except ImportError:
            logger.warning("Plotly未安装，将使用基础HTML展示")
            self.has_plotly = False
    
    def generate_report(
        self,
        metrics,
        trades: List,
        equity_curve: List[Dict],
        output_file: str = None,
        intraday_data_dict: Dict[str, pd.DataFrame] = None,
        stock_names: Dict[str, str] = None
    ) -> str:
        """
        生成可视化报告
        
        Args:
            metrics: 绩效指标
            trades: 交易记录
            equity_curve: 资金曲线
            output_file: 输出文件路径
            intraday_data_dict: 分时数据字典 {symbol: DataFrame}
            stock_names: 股票名称字典 {symbol: name}
        
        Returns:
            报告文件路径
        """
        if output_file is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_file = self.output_dir / f"backtest_report_{timestamp}.html"
        else:
            output_file = Path(output_file)
        
        if stock_names is None:
            stock_names = {}
        
        if intraday_data_dict is None:
            intraday_data_dict = {}
        
        html_content = self._generate_html_report(
            metrics, trades, equity_curve, intraday_data_dict, stock_names
        )
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"报告已生成: {output_file}")
        
        if self.has_matplotlib:
            self._generate_charts(metrics, trades, equity_curve, output_file.stem)
        
        return str(output_file)
    
    def _generate_html_report(
        self,
        metrics,
        trades: List,
        equity_curve: List[Dict],
        intraday_data_dict: Dict[str, pd.DataFrame],
        stock_names: Dict[str, str]
    ) -> str:
        """生成HTML报告"""
        
        monthly_returns = self._calculate_monthly_returns(equity_curve)
        
        traded_symbols = list(set(t.symbol for t in trades)) if trades else []
        
        intraday_charts_html = ""
        if self.has_plotly and intraday_data_dict:
            intraday_charts_html = self._generate_intraday_charts(
                trades, intraday_data_dict, stock_names
            )
        
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>回测绩效报告</title>
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
            box-shadow: 0 0 10px rgba(0,0,0,0.1);
            border-radius: 10px;
        }}
        h1 {{
            color: #333;
            border-bottom: 3px solid #2196F3;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #555;
            border-bottom: 2px solid #ddd;
            padding-bottom: 5px;
            margin-top: 30px;
        }}
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }}
        .metric-card {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            text-align: center;
        }}
        .metric-label {{
            font-size: 14px;
            opacity: 0.9;
            margin-bottom: 5px;
        }}
        .metric-value {{
            font-size: 24px;
            font-weight: bold;
        }}
        .positive {{
            color: #4CAF50;
        }}
        .negative {{
            color: #f44336;
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
        tr:hover {{
            background-color: #f5f5f5;
        }}
        .chart-container {{
            margin: 20px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
            overflow: hidden;
        }}
        .stock-section {{
            margin: 30px 0;
            padding: 20px;
            background-color: #fafafa;
            border-radius: 10px;
            border-left: 4px solid #2196F3;
        }}
        .stock-title {{
            font-size: 18px;
            font-weight: bold;
            color: #333;
            margin-bottom: 15px;
        }}
        .legend {{
            display: flex;
            gap: 20px;
            margin: 10px 0;
            padding: 10px;
            background-color: #f0f0f0;
            border-radius: 5px;
        }}
        .legend-item {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}
        .marker-buy {{
            width: 0;
            height: 0;
            border-left: 8px solid transparent;
            border-right: 8px solid transparent;
            border-bottom: 16px solid #4CAF50;
        }}
        .marker-sell {{
            width: 0;
            height: 0;
            border-left: 8px solid transparent;
            border-right: 8px solid transparent;
            border-top: 16px solid #f44336;
        }}
        .nav {{
            position: sticky;
            top: 0;
            background-color: white;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            z-index: 100;
        }}
        .nav a {{
            margin-right: 15px;
            text-decoration: none;
            color: #2196F3;
            font-weight: bold;
        }}
        .nav a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 回测绩效报告</h1>
        <p>生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
        
        <h2>📈 核心指标</h2>
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-label">总收益率</div>
                <div class="metric-value">{metrics.total_return*100:+.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">年化收益率</div>
                <div class="metric-value">{metrics.annualized_return*100:+.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">最大回撤</div>
                <div class="metric-value">{metrics.max_drawdown*100:.2f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">夏普比率</div>
                <div class="metric-value">{metrics.sharpe_ratio:.3f}</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">胜率</div>
                <div class="metric-value">{metrics.win_rate*100:.1f}%</div>
            </div>
            <div class="metric-card">
                <div class="metric-label">盈亏比</div>
                <div class="metric-value">{metrics.profit_loss_ratio:.2f}</div>
            </div>
        </div>
        
        <h2>📋 详细指标</h2>
        <table>
            <tr><th>指标</th><th>数值</th></tr>
            <tr><td>总交易次数</td><td>{metrics.total_trades}</td></tr>
            <tr><td>盈利次数</td><td class="positive">{metrics.win_trades}</td></tr>
            <tr><td>亏损次数</td><td class="negative">{metrics.loss_trades}</td></tr>
            <tr><td>平均盈利</td><td class="positive">{metrics.avg_win*100:+.2f}%</td></tr>
            <tr><td>平均亏损</td><td class="negative">{metrics.avg_loss*100:+.2f}%</td></tr>
            <tr><td>波动率(年化)</td><td>{metrics.volatility*100:.2f}%</td></tr>
            <tr><td>Sortino比率</td><td>{metrics.sortino_ratio:.3f}</td></tr>
            <tr><td>Calmar比率</td><td>{metrics.calmar_ratio:.3f}</td></tr>
            <tr><td>平均持仓天数</td><td>{metrics.avg_holding_days:.1f}</td></tr>
        </table>
        
        <h2>📊 月度收益分布</h2>
        <table>
            <tr><th>月份</th><th>起始资金</th><th>结束资金</th><th>月收益率</th></tr>
        """
        
        for _, row in monthly_returns.iterrows():
            return_class = "positive" if row['monthly_return'] > 0 else "negative"
            html += f"""
            <tr>
                <td>{row['month']}</td>
                <td>{row['start_equity']:,.2f}</td>
                <td>{row['end_equity']:,.2f}</td>
                <td class="{return_class}">{row['monthly_return']*100:+.2f}%</td>
            </tr>
            """
        
        html += """
        </table>
        """
        
        if intraday_charts_html:
            html += f"""
        <h2>📉 分时图买卖点标注</h2>
        <div class="legend">
            <div class="legend-item"><div class="marker-buy"></div><span>买入点（绿色）</span></div>
            <div class="legend-item"><div class="marker-sell"></div><span>卖出点（红色）</span></div>
        </div>
        <div class="nav">
            <strong>快速导航：</strong>
            """
            for symbol in traded_symbols:
                name = stock_names.get(symbol, '')
                display_name = f"{symbol} {name}" if name else symbol
                html += f'<a href="#chart_{symbol}">{display_name}</a>'
            
            html += "</div>" + intraday_charts_html
        
        html += """
        
        <h2>📝 交易明细</h2>
        <table>
            <tr>
                <th>股票代码</th>
                <th>股票名称</th>
                <th>买入时间</th>
                <th>买入价格</th>
                <th>卖出时间</th>
                <th>卖出价格</th>
                <th>收益率</th>
                <th>卖出原因</th>
            </tr>
        """
        
        for trade in trades[:100]:
            entry_time = trade.entry_time.strftime('%m-%d %H:%M') if trade.entry_time else ''
            exit_time = trade.exit_time.strftime('%m-%d %H:%M') if trade.exit_time else ''
            return_class = "positive" if trade.pnl_pct > 0 else "negative"
            stock_name = stock_names.get(trade.symbol, getattr(trade, 'name', ''))
            
            html += f"""
            <tr>
                <td>{trade.symbol}</td>
                <td>{stock_name}</td>
                <td>{entry_time}</td>
                <td>{trade.entry_price:.2f}</td>
                <td>{exit_time}</td>
                <td>{trade.exit_price:.2f}</td>
                <td class="{return_class}">{trade.pnl_pct*100:+.2f}%</td>
                <td>{trade.exit_reason}</td>
            </tr>
            """
        
        if len(trades) > 100:
            html += f"<tr><td colspan='8' style='text-align:center;'>... 共 {len(trades)} 条记录</td></tr>"
        
        html += """
        </table>
    </div>
</body>
</html>
        """
        
        return html
    
    def _generate_intraday_charts(
        self,
        trades: List,
        intraday_data_dict: Dict[str, pd.DataFrame],
        stock_names: Dict[str, str]
    ) -> str:
        """生成所有股票的分时图"""
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        
        if not trades:
            return ""
        
        traded_symbols = list(set(t.symbol for t in trades))
        html_parts = []
        
        for symbol in traded_symbols:
            intraday_data = intraday_data_dict.get(symbol)
            if intraday_data is None or intraday_data.empty:
                continue
            
            symbol_trades = [t for t in trades if t.symbol == symbol]
            stock_name = stock_names.get(symbol, '')
            display_title = f"{symbol} {stock_name}" if stock_name else symbol
            
            buy_points = []
            sell_points = []
            
            for t in symbol_trades:
                if t.entry_time:
                    buy_points.append({
                        'time': t.entry_time,
                        'price': t.entry_price,
                        'shares': t.shares,
                        'signal': getattr(t, 'signal_type', '')
                    })
                if t.exit_time:
                    sell_points.append({
                        'time': t.exit_time,
                        'price': t.exit_price,
                        'shares': t.shares,
                        'pnl_pct': t.pnl_pct,
                        'reason': t.exit_reason
                    })
            
            chart_html = self._create_single_intraday_chart(
                symbol, intraday_data, buy_points, sell_points, display_title
            )
            
            html_parts.append(f'''
            <div class="stock-section" id="chart_{symbol}">
                <div class="stock-title">{display_title}</div>
                {chart_html}
            </div>
            ''')
        
        return '\n'.join(html_parts)
    
    def _create_single_intraday_chart(
        self,
        symbol: str,
        intraday_data: pd.DataFrame,
        buy_points: List[Dict],
        sell_points: List[Dict],
        title: str
    ) -> str:
        """创建单只股票的分时图"""
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
                     for c, o in zip(intraday_data['close'], intraday_data.get('open', intraday_data['close']))]
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
        
        if buy_points:
            buy_times = [p['time'] for p in buy_points]
            buy_prices = [p['price'] for p in buy_points]
            buy_texts = [
                f"<b>买入</b><br>"
                f"时间: {p['time'].strftime('%m-%d %H:%M')}<br>"
                f"价格: {p['price']:.2f}<br>"
                f"数量: {p['shares']}股<br>"
                f"信号: {p['signal'] or '未知'}"
                for p in buy_points
            ]
            
            fig.add_trace(
                go.Scatter(
                    x=buy_times,
                    y=buy_prices,
                    mode='markers+text',
                    name='买入点',
                    marker=dict(
                        symbol='triangle-up',
                        size=15,
                        color='#4CAF50',
                        line=dict(color='white', width=2)
                    ),
                    text=[f"{p['price']:.2f}" for p in buy_points],
                    textposition='bottom center',
                    textfont=dict(size=10, color='#4CAF50'),
                    hovertext=buy_texts,
                    hoverinfo='text'
                ),
                row=1, col=1
            )
        
        if sell_points:
            sell_times = [p['time'] for p in sell_points]
            sell_prices = [p['price'] for p in sell_points]
            sell_texts = [
                f"<b>卖出</b><br>"
                f"时间: {p['time'].strftime('%m-%d %H:%M')}<br>"
                f"价格: {p['price']:.2f}<br>"
                f"数量: {p['shares']}股<br>"
                f"收益: {p['pnl_pct']*100:+.2f}%<br>"
                f"原因: {p['reason'] or '未知'}"
                for p in sell_points
            ]
            
            fig.add_trace(
                go.Scatter(
                    x=sell_times,
                    y=sell_prices,
                    mode='markers+text',
                    name='卖出点',
                    marker=dict(
                        symbol='triangle-down',
                        size=15,
                        color='#f44336',
                        line=dict(color='white', width=2)
                    ),
                    text=[f"{p['price']:.2f}" for p in sell_points],
                    textposition='top center',
                    textfont=dict(size=10, color='#f44336'),
                    hovertext=sell_texts,
                    hoverinfo='text'
                ),
                row=1, col=1
            )
        
        fig.update_layout(
            title=dict(text=title, font=dict(size=16)),
            showlegend=True,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode='closest',
            height=500,
            margin=dict(l=50, r=50, t=60, b=50),
            template='plotly_white'
        )
        
        fig.update_xaxes(title_text="时间", row=2, col=1)
        fig.update_yaxes(title_text="价格", row=1, col=1)
        fig.update_yaxes(title_text="成交量", row=2, col=1)
        
        return fig.to_html(include_plotlyjs=False, full_html=False)
    
    def _generate_charts(
        self,
        metrics,
        trades: List,
        equity_curve: List[Dict],
        report_name: str
    ):
        """生成图表"""
        if not self.has_matplotlib:
            return
        
        try:
            self._plot_equity_curve(equity_curve, report_name)
            self._plot_return_distribution(trades, report_name)
            self._plot_monthly_returns(equity_curve, report_name)
        except Exception as e:
            logger.warning(f"生成图表失败: {e}")
    
    def _plot_equity_curve(self, equity_curve: List[Dict], report_name: str):
        """绘制资金曲线"""
        if not equity_curve:
            return
        
        df = pd.DataFrame(equity_curve)
        df['date'] = pd.to_datetime(df['date'])
        
        fig, (ax1, ax2) = self.plt.subplots(2, 1, figsize=(12, 8))
        
        ax1.plot(df['date'], df['equity'], linewidth=2, color='#2196F3')
        ax1.set_title('资金曲线', fontsize=14, fontweight='bold')
        ax1.set_xlabel('日期')
        ax1.set_ylabel('资金')
        ax1.grid(True, alpha=0.3)
        
        peak = df['equity'].expanding().max()
        drawdown = (df['equity'] - peak) / peak
        ax2.fill_between(df['date'], drawdown, 0, color='red', alpha=0.3)
        ax2.plot(df['date'], drawdown, color='red', linewidth=1)
        ax2.set_title('回撤曲线', fontsize=14, fontweight='bold')
        ax2.set_xlabel('日期')
        ax2.set_ylabel('回撤比例')
        ax2.grid(True, alpha=0.3)
        
        self.plt.tight_layout()
        self.plt.savefig(self.output_dir / f"{report_name}_equity.png", dpi=150)
        self.plt.close()
    
    def _plot_return_distribution(self, trades: List, report_name: str):
        """绘制收益分布"""
        if not trades:
            return
        
        returns = [t.pnl_pct * 100 for t in trades]
        
        fig, ax = self.plt.subplots(figsize=(10, 6))
        
        ax.hist(returns, bins=20, edgecolor='black', alpha=0.7, color='#4CAF50')
        ax.axvline(x=0, color='red', linestyle='--', linewidth=2)
        ax.set_title('收益分布', fontsize=14, fontweight='bold')
        ax.set_xlabel('收益率 (%)')
        ax.set_ylabel('频次')
        ax.grid(True, alpha=0.3)
        
        self.plt.tight_layout()
        self.plt.savefig(self.output_dir / f"{report_name}_returns.png", dpi=150)
        self.plt.close()
    
    def _plot_monthly_returns(self, equity_curve: List[Dict], report_name: str):
        """绘制月度收益"""
        monthly_returns = self._calculate_monthly_returns(equity_curve)
        
        if monthly_returns.empty:
            return
        
        fig, ax = self.plt.subplots(figsize=(12, 6))
        
        colors = ['#4CAF50' if r > 0 else '#f44336' for r in monthly_returns['monthly_return']]
        ax.bar(range(len(monthly_returns)), monthly_returns['monthly_return'] * 100, color=colors)
        ax.axhline(y=0, color='black', linestyle='-', linewidth=0.5)
        ax.set_title('月度收益', fontsize=14, fontweight='bold')
        ax.set_xlabel('月份')
        ax.set_ylabel('收益率 (%)')
        ax.set_xticks(range(len(monthly_returns)))
        ax.set_xticklabels([str(m) for m in monthly_returns['month']], rotation=45)
        ax.grid(True, alpha=0.3, axis='y')
        
        self.plt.tight_layout()
        self.plt.savefig(self.output_dir / f"{report_name}_monthly.png", dpi=150)
        self.plt.close()
    
    def _calculate_monthly_returns(self, equity_curve: List[Dict]) -> pd.DataFrame:
        """计算月度收益"""
        if not equity_curve:
            return pd.DataFrame()
        
        df = pd.DataFrame(equity_curve)
        df['date'] = pd.to_datetime(df['date'])
        df['month'] = df['date'].dt.to_period('M')
        
        monthly = df.groupby('month').agg({
            'equity': ['first', 'last']
        }).reset_index()
        
        monthly.columns = ['month', 'start_equity', 'end_equity']
        monthly['monthly_return'] = (monthly['end_equity'] - monthly['start_equity']) / monthly['start_equity']
        
        return monthly
