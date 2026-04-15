#!/bin/bash
# 云API部署脚本 - 适用于小型云服务器

set -e

echo "========================================"
echo "AI大模型云API部署脚本"
echo "适用于: 2vCPU / 4GB内存 / 无GPU"
echo "========================================"

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "错误: Python3未安装"
    exit 1
fi

echo ""
echo "服务器配置检查:"
echo "  CPU: $(nproc) 核"
echo "  内存: $(free -h | grep Mem | awk '{print $2}')"
echo "  存储: $(df -h / | tail -1 | awk '{print $4}') 可用"

# 选择云服务商
echo ""
echo "========================================"
echo "选择云API服务商"
echo "========================================"
echo "1. DeepSeek (推荐) - ¥0.001/1K tokens, 最便宜"
echo "2. 通义千问 - ¥0.002/1K tokens, 中文效果好"
echo "3. 智谱AI - ¥0.01/1K tokens, 性能优秀"
echo "4. 跳过（稍后手动配置）"
echo ""
read -p "请选择 [1-4]: " choice

case $choice in
    1)
        PROVIDER="deepseek"
        API_KEY_ENV="DEEPSEEK_API_KEY"
        echo ""
        echo "请访问 https://platform.deepseek.com/ 获取API Key"
        read -p "请输入DeepSeek API Key: " api_key
        ;;
    2)
        PROVIDER="qwen"
        API_KEY_ENV="QWEN_API_KEY"
        echo ""
        echo "请访问 https://dashscope.console.aliyun.com/ 获取API Key"
        read -p "请输入通义千问 API Key: " api_key
        ;;
    3)
        PROVIDER="zhipu"
        API_KEY_ENV="ZHIPU_API_KEY"
        echo ""
        echo "请访问 https://open.bigmodel.cn/ 获取API Key"
        read -p "请输入智谱AI API Key: " api_key
        ;;
    4)
        echo "已跳过，请手动配置 .env 文件"
        exit 0
        ;;
    *)
        echo "无效选择"
        exit 1
        ;;
esac

# 配置环境变量
echo ""
echo "========================================"
echo "配置API密钥"
echo "========================================"

# 检查.env文件
if [ ! -f ".env" ]; then
    touch .env
    echo "✓ 创建 .env 文件"
fi

# 添加API密钥
if grep -q "$API_KEY_ENV" .env; then
    # 更新现有配置
    sed -i "s/^$API_KEY_ENV=.*/$API_KEY_ENV=$api_key/" .env
    echo "✓ 更新 $API_KEY_ENV"
else
    # 添加新配置
    echo "$API_KEY_ENV=$api_key" >> .env
    echo "✓ 添加 $API_KEY_ENV"
fi

# 更新AI配置
echo ""
echo "========================================"
echo "配置AI模块"
echo "========================================"

# 备份原配置
if [ -f "config/ai_config.yaml" ]; then
    cp config/ai_config.yaml config/ai_config.yaml.bak
    echo "✓ 备份原配置"
fi

# 使用云API配置
cp config/ai_config.cloud_api.yaml config/ai_config.yaml

# 更新provider配置
sed -i "s/provider: .*/provider: \"$PROVIDER\"/" config/ai_config.yaml
echo "✓ 使用 $PROVIDER 云API"

# 安装依赖
echo ""
echo "========================================"
echo "安装依赖"
echo "========================================"

if [ -f "requirements.txt" ]; then
    pip3 install -r requirements.txt --upgrade
    echo "✓ 依赖安装完成"
fi

# 测试API连接
echo ""
echo "========================================"
echo "测试API连接"
echo "========================================"

python3 << EOF
import os
import requests

api_key = os.getenv("$API_KEY_ENV")
if not api_key:
    print("✗ API密钥未设置")
    exit(1)

try:
    if "$PROVIDER" == "deepseek":
        resp = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": "你好"}],
                "max_tokens": 50,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            print("✓ DeepSeek API连接成功")
        else:
            print(f"✗ API错误: {resp.status_code}")
    elif "$PROVIDER" == "qwen":
        print("✓ 通义千问配置完成（请手动测试）")
except Exception as e:
    print(f"✗ 连接失败: {e}")
EOF

# 完成
echo ""
echo "========================================"
echo "部署完成！"
echo "========================================"
echo ""
echo "配置信息:"
echo "  云服务商: $PROVIDER"
echo "  API密钥: 已配置"
echo "  配置文件: config/ai_config.yaml"
echo ""
echo "下一步："
echo "  1. 重启量化系统: python3 dashboard.py"
echo "  2. 启动AI管家: curl -X POST http://<服务器IP>:8501/api/butler/start"
echo "  3. 或通过Mobile API: curl -X POST http://<服务器IP>:8000/api/butler/start"
echo ""
echo "成本估算:"
echo "  每日约 ¥0.05-0.1"
echo "  每月约 ¥1.5-3"
echo ""
