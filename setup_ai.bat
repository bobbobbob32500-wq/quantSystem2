@echo off
chcp 65001 >nul
echo ============================================
echo   AI集成 - Ollama安装和模型下载脚本
echo   适用于: quantSystem2 量化交易辅助系统
echo ============================================
echo.

:: 检查Ollama是否已安装
where ollama >nul 2>&1
if %errorlevel% equ 0 (
    echo [OK] Ollama已安装
    ollama --version
) else (
    echo [!] Ollama未安装
    echo.
    echo 请按以下步骤安装Ollama:
    echo   1. 访问 https://ollama.com/download
    echo   2. 下载Windows版本
    echo   3. 运行安装程序
    echo   4. 安装完成后重新运行此脚本
    echo.
    echo 或者使用winget安装:
    echo   winget install Ollama.Ollama
    echo.
    pause
    exit /b 1
)

echo.
echo [1/3] 启动Ollama服务...
start "" /B ollama serve >nul 2>&1
timeout /t 3 /nobreak >nul

echo.
echo [2/3] 下载Qwen2.5 7B模型 (中文主力模型)...
echo 注意: 模型约4.7GB，下载可能需要一些时间
ollama pull qwen2.5:7b

echo.
echo [3/3] 下载Mistral 7B模型 (代码生成模型)...
echo 注意: 模型约4.1GB，下载可能需要一些时间
ollama pull mistral:7b

echo.
echo ============================================
echo   安装完成！
echo.
echo   已安装模型:
ollama list

echo.
echo   使用方法:
echo   1. 启动Ollama服务: ollama serve
echo   2. 启动量化系统看板: python dashboard.py
echo   3. 在看板中点击"AI助手"开始使用
echo.
echo   API接口:
echo   - POST /api/ai/chat          - AI对话
echo   - POST /api/ai/quick-ask     - 快速问答
echo   - POST /api/ai/explain-selection - 选股解释
echo   - POST /api/ai/analyze-signal    - 信号分析
echo   - POST /api/ai/analyze-news      - 新闻分析
echo   - POST /api/ai/generate-code     - 代码生成
echo   - GET  /api/ai/status        - AI服务状态
echo ============================================
pause
