# -*- coding: utf-8 -*-
"""
技术指标可视化模块
提供技术指标的可视化展示功能
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from src.core.logger import get_logger

logger = get_logger("indicator_visualization")

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False


class IndicatorVisualizer:
    """技术指标可视化类"""
    
    def __init__(self, df: pd.DataFrame, figsize: Tuple[int, int] = (15, 10)):
        """
        初始化可视化器
        
        Args:
            df: 包含OHLCV和指标数据的DataFrame
            figsize: 图表大小
        """
        self.df = df.copy()
        self.figsize = figsize
        
        # 确保有日期索引
        if 'trade_date' in self.df.columns:
            self.df['trade_date'] = pd.to_datetime(self.df['trade_date'])
            self.df.set_index('trade_date', inplace=True)
    
    def plot_price_and_ma(
        self,
        ma_columns: List[str] = None,
        title: str = "价格与移动平均线",
        save_path: str = None
    ):
        """
        绘制价格和移动平均线
        
        Args:
            ma_columns: MA列名列表
            title: 图表标题
            save_path: 保存路径
        """
        if ma_columns is None:
            ma_columns = [col for col in self.df.columns if col.startswith('MA')]
        
        fig, ax = plt.subplots(figsize=self.figsize)
        
        # 绘制收盘价
        ax.plot(self.df.index, self.df['close'], label='收盘价', linewidth=2, color='black')
        
        # 绘制移动平均线
        colors = ['red', 'blue', 'green', 'orange', 'purple']
        for i, ma_col in enumerate(ma_columns):
            if ma_col in self.df.columns:
                color = colors[i % len(colors)]
                ax.plot(
                    self.df.index,
                    self.df[ma_col],
                    label=ma_col,
                    linewidth=1.5,
                    alpha=0.8,
                    color=color
                )
        
        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('价格', fontsize=12)
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, alpha=0.3)
        
        # 格式化x轴日期
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        plt.show()
    
    def plot_macd(
        self,
        title: str = "MACD指标",
        save_path: str = None
    ):
        """
        绘制MACD指标
        
        Args:
            title: 图表标题
            save_path: 保存路径
        """
        if 'MACD' not in self.df.columns:
            logger.warning("数据中不包含MACD指标")
            return
        
        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(self.figsize[0], self.figsize[1]),
            gridspec_kw={'height_ratios': [3, 1]}
        )
        
        # 上图: 价格
        ax1.plot(self.df.index, self.df['close'], label='收盘价', linewidth=2)
        ax1.set_title('价格走势', fontsize=14)
        ax1.set_ylabel('价格', fontsize=12)
        ax1.legend(loc='best')
        ax1.grid(True, alpha=0.3)
        
        # 下图: MACD
        ax2.plot(self.df.index, self.df['MACD'], label='MACD', color='red', linewidth=1.5)
        ax2.plot(self.df.index, self.df['MACD_SIGNAL'], label='Signal', color='blue', linewidth=1.5)
        
        # 绘制柱状图
        colors = ['red' if val >= 0 else 'green' for val in self.df['MACD_HIST']]
        ax2.bar(self.df.index, self.df['MACD_HIST'], label='Histogram', color=colors, alpha=0.6)
        
        ax2.axhline(y=0, color='black', linestyle='--', linewidth=0.8)
        ax2.set_title(title, fontsize=14)
        ax2.set_xlabel('日期', fontsize=12)
        ax2.set_ylabel('MACD', fontsize=12)
        ax2.legend(loc='best')
        ax2.grid(True, alpha=0.3)
        
        # 格式化x轴日期
        for ax in [ax1, ax2]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        plt.show()
    
    def plot_kdj(
        self,
        title: str = "KDJ指标",
        save_path: str = None
    ):
        """
        绘制KDJ指标
        
        Args:
            title: 图表标题
            save_path: 保存路径
        """
        if 'K' not in self.df.columns:
            logger.warning("数据中不包含KDJ指标")
            return
        
        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(self.figsize[0], self.figsize[1]),
            gridspec_kw={'height_ratios': [3, 1]}
        )
        
        # 上图: 价格
        ax1.plot(self.df.index, self.df['close'], label='收盘价', linewidth=2)
        ax1.set_title('价格走势', fontsize=14)
        ax1.set_ylabel('价格', fontsize=12)
        ax1.legend(loc='best')
        ax1.grid(True, alpha=0.3)
        
        # 下图: KDJ
        ax2.plot(self.df.index, self.df['K'], label='K', color='red', linewidth=1.5)
        ax2.plot(self.df.index, self.df['D'], label='D', color='blue', linewidth=1.5)
        ax2.plot(self.df.index, self.df['J'], label='J', color='green', linewidth=1.5)
        
        # 添加超买超卖线
        ax2.axhline(y=80, color='orange', linestyle='--', linewidth=1, label='超买线')
        ax2.axhline(y=20, color='purple', linestyle='--', linewidth=1, label='超卖线')
        
        ax2.set_title(title, fontsize=14)
        ax2.set_xlabel('日期', fontsize=12)
        ax2.set_ylabel('KDJ', fontsize=12)
        ax2.legend(loc='best')
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 100)
        
        # 格式化x轴日期
        for ax in [ax1, ax2]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        plt.show()
    
    def plot_rsi(
        self,
        title: str = "RSI指标",
        save_path: str = None
    ):
        """
        绘制RSI指标
        
        Args:
            title: 图表标题
            save_path: 保存路径
        """
        if 'RSI' not in self.df.columns:
            logger.warning("数据中不包含RSI指标")
            return
        
        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(self.figsize[0], self.figsize[1]),
            gridspec_kw={'height_ratios': [3, 1]}
        )
        
        # 上图: 价格
        ax1.plot(self.df.index, self.df['close'], label='收盘价', linewidth=2)
        ax1.set_title('价格走势', fontsize=14)
        ax1.set_ylabel('价格', fontsize=12)
        ax1.legend(loc='best')
        ax1.grid(True, alpha=0.3)
        
        # 下图: RSI
        ax2.plot(self.df.index, self.df['RSI'], label='RSI', color='purple', linewidth=1.5)
        
        # 添加超买超卖区域
        ax2.axhline(y=70, color='red', linestyle='--', linewidth=1, label='超买线')
        ax2.axhline(y=30, color='green', linestyle='--', linewidth=1, label='超卖线')
        ax2.fill_between(
            self.df.index,
            70, 100,
            alpha=0.2,
            color='red',
            label='超买区'
        )
        ax2.fill_between(
            self.df.index,
            0, 30,
            alpha=0.2,
            color='green',
            label='超卖区'
        )
        
        ax2.set_title(title, fontsize=14)
        ax2.set_xlabel('日期', fontsize=12)
        ax2.set_ylabel('RSI', fontsize=12)
        ax2.legend(loc='best')
        ax2.grid(True, alpha=0.3)
        ax2.set_ylim(0, 100)
        
        # 格式化x轴日期
        for ax in [ax1, ax2]:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        plt.show()
    
    def plot_boll(
        self,
        title: str = "布林带",
        save_path: str = None
    ):
        """
        绘制布林带
        
        Args:
            title: 图表标题
            save_path: 保存路径
        """
        if 'BOLL_UPPER' not in self.df.columns:
            logger.warning("数据中不包含布林带指标")
            return
        
        fig, ax = plt.subplots(figsize=self.figsize)
        
        # 绘制收盘价
        ax.plot(self.df.index, self.df['close'], label='收盘价', linewidth=2, color='black')
        
        # 绘制布林带
        ax.plot(self.df.index, self.df['BOLL_UPPER'], label='上轨', color='red', linewidth=1.5)
        ax.plot(self.df.index, self.df['BOLL_MID'], label='中轨', color='blue', linewidth=1.5)
        ax.plot(self.df.index, self.df['BOLL_LOWER'], label='下轨', color='green', linewidth=1.5)
        
        # 填充布林带区域
        ax.fill_between(
            self.df.index,
            self.df['BOLL_UPPER'],
            self.df['BOLL_LOWER'],
            alpha=0.2,
            color='gray',
            label='布林带区域'
        )
        
        ax.set_title(title, fontsize=16, fontweight='bold')
        ax.set_xlabel('日期', fontsize=12)
        ax.set_ylabel('价格', fontsize=12)
        ax.legend(loc='best', fontsize=10)
        ax.grid(True, alpha=0.3)
        
        # 格式化x轴日期
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        plt.show()
    
    def plot_all_indicators(
        self,
        title: str = "技术指标综合分析",
        save_path: str = None
    ):
        """
        绘制所有指标的综合图表
        
        Args:
            title: 图表标题
            save_path: 保存路径
        """
        # 确定需要绘制的子图数量
        n_plots = 1  # 价格图
        if 'MACD' in self.df.columns:
            n_plots += 1
        if 'K' in self.df.columns:
            n_plots += 1
        if 'RSI' in self.df.columns:
            n_plots += 1
        
        fig, axes = plt.subplots(
            n_plots, 1,
            figsize=(self.figsize[0], self.figsize[1] * n_plots / 2),
            constrained_layout=True
        )
        
        if n_plots == 1:
            axes = [axes]
        
        plot_idx = 0
        
        # 价格和MA
        ax = axes[plot_idx]
        ax.plot(self.df.index, self.df['close'], label='收盘价', linewidth=2, color='black')
        
        # 添加布林带
        if 'BOLL_UPPER' in self.df.columns:
            ax.plot(self.df.index, self.df['BOLL_UPPER'], label='布林上轨', color='red', linewidth=1, alpha=0.7)
            ax.plot(self.df.index, self.df['BOLL_MID'], label='布林中轨', color='blue', linewidth=1, alpha=0.7)
            ax.plot(self.df.index, self.df['BOLL_LOWER'], label='布林下轨', color='green', linewidth=1, alpha=0.7)
            ax.fill_between(
                self.df.index,
                self.df['BOLL_UPPER'],
                self.df['BOLL_LOWER'],
                alpha=0.1,
                color='gray'
            )
        
        # 添加MA
        ma_cols = [col for col in self.df.columns if col.startswith('MA')]
        colors = ['orange', 'purple', 'brown', 'pink']
        for i, ma_col in enumerate(ma_cols[:4]):
            color = colors[i % len(colors)]
            ax.plot(self.df.index, self.df[ma_col], label=ma_col, linewidth=1, alpha=0.7, color=color)
        
        ax.set_title('价格走势', fontsize=14, fontweight='bold')
        ax.set_ylabel('价格', fontsize=12)
        ax.legend(loc='best', fontsize=8)
        ax.grid(True, alpha=0.3)
        plot_idx += 1
        
        # MACD
        if 'MACD' in self.df.columns and plot_idx < n_plots:
            ax = axes[plot_idx]
            ax.plot(self.df.index, self.df['MACD'], label='MACD', color='red', linewidth=1.5)
            ax.plot(self.df.index, self.df['MACD_SIGNAL'], label='Signal', color='blue', linewidth=1.5)
            colors = ['red' if val >= 0 else 'green' for val in self.df['MACD_HIST']]
            ax.bar(self.df.index, self.df['MACD_HIST'], label='Histogram', color=colors, alpha=0.6)
            ax.axhline(y=0, color='black', linestyle='--', linewidth=0.8)
            ax.set_title('MACD指标', fontsize=14)
            ax.set_ylabel('MACD', fontsize=12)
            ax.legend(loc='best', fontsize=8)
            ax.grid(True, alpha=0.3)
            plot_idx += 1
        
        # KDJ
        if 'K' in self.df.columns and plot_idx < n_plots:
            ax = axes[plot_idx]
            ax.plot(self.df.index, self.df['K'], label='K', color='red', linewidth=1.5)
            ax.plot(self.df.index, self.df['D'], label='D', color='blue', linewidth=1.5)
            ax.plot(self.df.index, self.df['J'], label='J', color='green', linewidth=1.5)
            ax.axhline(y=80, color='orange', linestyle='--', linewidth=1)
            ax.axhline(y=20, color='purple', linestyle='--', linewidth=1)
            ax.set_title('KDJ指标', fontsize=14)
            ax.set_ylabel('KDJ', fontsize=12)
            ax.legend(loc='best', fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.set_ylim(0, 100)
            plot_idx += 1
        
        # RSI
        if 'RSI' in self.df.columns and plot_idx < n_plots:
            ax = axes[plot_idx]
            ax.plot(self.df.index, self.df['RSI'], label='RSI', color='purple', linewidth=1.5)
            ax.axhline(y=70, color='red', linestyle='--', linewidth=1)
            ax.axhline(y=30, color='green', linestyle='--', linewidth=1)
            ax.fill_between(self.df.index, 70, 100, alpha=0.2, color='red')
            ax.fill_between(self.df.index, 0, 30, alpha=0.2, color='green')
            ax.set_title('RSI指标', fontsize=14)
            ax.set_xlabel('日期', fontsize=12)
            ax.set_ylabel('RSI', fontsize=12)
            ax.legend(loc='best', fontsize=8)
            ax.grid(True, alpha=0.3)
            ax.set_ylim(0, 100)
        
        # 格式化所有x轴
        for ax in axes:
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        
        fig.suptitle(title, fontsize=16, fontweight='bold', y=1.02)
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            logger.info(f"图表已保存至: {save_path}")
        
        plt.show()


def create_indicator_report(
    df: pd.DataFrame,
    stock_code: str = '',
    save_dir: str = None
) -> Dict[str, str]:
    """
    创建技术指标分析报告
    
    Args:
        df: 包含OHLCV和指标数据的DataFrame
        stock_code: 股票代码
        save_dir: 保存目录
    
    Returns:
        保存的文件路径字典
    """
    visualizer = IndicatorVisualizer(df)
    saved_files = {}
    
    if save_dir:
        import os
        os.makedirs(save_dir, exist_ok=True)
        
        # 保存各类图表
        saved_files['price_ma'] = f"{save_dir}/{stock_code}_price_ma.png"
        visualizer.plot_price_and_ma(save_path=saved_files['price_ma'])
        
        if 'MACD' in df.columns:
            saved_files['macd'] = f"{save_dir}/{stock_code}_macd.png"
            visualizer.plot_macd(save_path=saved_files['macd'])
        
        if 'K' in df.columns:
            saved_files['kdj'] = f"{save_dir}/{stock_code}_kdj.png"
            visualizer.plot_kdj(save_path=saved_files['kdj'])
        
        if 'RSI' in df.columns:
            saved_files['rsi'] = f"{save_dir}/{stock_code}_rsi.png"
            visualizer.plot_rsi(save_path=saved_files['rsi'])
        
        if 'BOLL_UPPER' in df.columns:
            saved_files['boll'] = f"{save_dir}/{stock_code}_boll.png"
            visualizer.plot_boll(save_path=saved_files['boll'])
        
        saved_files['all'] = f"{save_dir}/{stock_code}_all_indicators.png"
        visualizer.plot_all_indicators(save_path=saved_files['all'])
        
        logger.info(f"技术指标报告已生成,共 {len(saved_files)} 个图表")
    
    return saved_files
