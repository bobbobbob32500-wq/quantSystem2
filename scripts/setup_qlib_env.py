# -*- coding: utf-8 -*-
"""
Qlib 环境设置脚本
用于快速创建和配置 Qlib 集成环境
"""

import subprocess
import sys
import os

def check_conda():
    """检查是否安装了 conda"""
    try:
        result = subprocess.run(['conda', '--version'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ 检测到 conda: {result.stdout.strip()}")
            return True
    except FileNotFoundError:
        pass
    
    print("❌ 未检测到 conda")
    return False


def create_conda_env():
    """创建 conda 虚拟环境"""
    env_name = "qlib_env"
    
    print(f"\n创建 conda 环境: {env_name} (Python 3.10)")
    
    # 检查环境是否已存在
    result = subprocess.run(['conda', 'env', 'list'], 
                          capture_output=True, text=True)
    
    if env_name in result.stdout:
        print(f"⚠️  环境 {env_name} 已存在")
        response = input("是否删除并重新创建？(y/n): ")
        if response.lower() == 'y':
            subprocess.run(['conda', 'env', 'remove', '-n', env_name, '-y'])
        else:
            print("跳过环境创建")
            return env_name
    
    # 创建新环境
    subprocess.run(['conda', 'create', '-n', env_name, 
                   'python=3.10', '-y'])
    
    print(f"✅ 环境 {env_name} 创建成功")
    return env_name


def install_dependencies(env_name):
    """安装依赖"""
    print("\n安装项目依赖...")
    
    # 安装基础依赖
    print("1. 安装 requirements.txt...")
    subprocess.run(['conda', 'run', '-n', env_name, 
                   'pip', 'install', '-r', 'requirements.txt'])
    
    # 安装 Qlib
    print("2. 安装 Qlib...")
    subprocess.run(['conda', 'run', '-n', env_name, 
                   'pip', 'install', 'pyqlib'])
    
    print("✅ 依赖安装完成")


def test_installation(env_name):
    """测试安装"""
    print("\n测试 Qlib 安装...")
    
    result = subprocess.run(
        ['conda', 'run', '-n', env_name, 'python', '-c', 
         'import qlib; print("Qlib 版本:", qlib.__version__)'],
        capture_output=True, text=True
    )
    
    if result.returncode == 0:
        print(f"✅ {result.stdout.strip()}")
        return True
    else:
        print(f"❌ 测试失败: {result.stderr}")
        return False


def print_activation_instructions(env_name):
    """打印激活指令"""
    print("\n" + "=" * 60)
    print("环境设置完成！")
    print("=" * 60)
    print(f"\n激活环境命令：")
    print(f"  conda activate {env_name}")
    print(f"\n运行测试：")
    print(f"  python src/modules/qlib_factor_adapter.py")
    print(f"\n下载 Qlib 数据：")
    print(f"  python -m qlib.run.get_data")
    print(f"\n运行 Qlib 基准策略：")
    print(f"  qrun benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml")
    print("=" * 60)


def main():
    """主函数"""
    print("=" * 60)
    print("Qlib 集成环境设置")
    print("=" * 60)
    
    # 检查 conda
    if not check_conda():
        print("\n请先安装 Anaconda 或 Miniconda:")
        print("https://docs.conda.io/en/latest/miniconda.html")
        return
    
    # 创建环境
    env_name = create_conda_env()
    
    # 安装依赖
    install_dependencies(env_name)
    
    # 测试安装
    if test_installation(env_name):
        print_activation_instructions(env_name)
    else:
        print("\n❌ 安装测试失败，请检查错误信息")


if __name__ == '__main__':
    main()
