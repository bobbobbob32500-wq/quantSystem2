/**
 * AI助手前端交互模块
 * 处理AI对话、快速问答、状态检测
 */

const AIAssistant = {
    _loading: false,

    /** 初始化AI助手 */
    init() {
        this._bindEvents();
        this._checkStatus();
    },

    /** 绑定事件 */
    _bindEvents() {
        const sendBtn = document.getElementById('aiSendButton');
        const input = document.getElementById('aiChatInput');
        const clearBtn = document.getElementById('aiClearButton');

        if (sendBtn) {
            sendBtn.addEventListener('click', () => this._sendMessage());
        }
        if (input) {
            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    this._sendMessage();
                }
            });
        }
        if (clearBtn) {
            clearBtn.addEventListener('click', () => this._clearChat());
        }

        // 快速问答按钮
        document.querySelectorAll('.ai-quick-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const key = btn.getAttribute('data-quick-key');
                this._quickAsk(key);
            });
        });
    },

    /** 检查AI服务状态 */
    async _checkStatus() {
        const indicator = document.getElementById('aiStatusIndicator');
        const statusText = document.getElementById('aiStatusText');
        try {
            const resp = await fetch('/api/ai/status');
            const data = await resp.json();
            if (data.available) {
                if (indicator) indicator.className = 'ai-status-indicator ai-status-online';
                if (statusText) statusText.textContent = `AI服务在线 | 模型: ${data.llm_status?.default_model || '未知'}`;
            } else {
                if (indicator) indicator.className = 'ai-status-indicator ai-status-offline';
                if (statusText) statusText.textContent = 'AI服务离线 - 请启动Ollama服务 (ollama serve)';
            }
        } catch {
            if (indicator) indicator.className = 'ai-status-indicator ai-status-offline';
            if (statusText) statusText.textContent = 'AI服务未连接';
        }
    },

    /** 发送消息 */
    async _sendMessage() {
        if (this._loading) return;
        const input = document.getElementById('aiChatInput');
        const message = (input?.value || '').trim();
        if (!message) return;

        // 显示用户消息
        this._appendMessage('user', message);
        input.value = '';

        // 显示加载状态
        this._appendMessage('assistant', '思考中...', true);
        this._loading = true;

        try {
            const resp = await fetch('/api/ai/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message }),
            });
            const data = await resp.json();
            // 移除加载消息
            this._removeLastMessage();
            if (data.success) {
                this._appendMessage('assistant', data.response);
            } else {
                this._appendMessage('system', `错误: ${data.message}`);
            }
        } catch (err) {
            this._removeLastMessage();
            this._appendMessage('system', `请求失败: ${err.message}`);
        } finally {
            this._loading = false;
        }
    },

    /** 快速问答 */
    async _quickAsk(key) {
        if (this._loading) return;
        this._appendMessage('user', `[快速问答] ${key}`);
        this._appendMessage('assistant', '思考中...', true);
        this._loading = true;

        try {
            const resp = await fetch('/api/ai/quick-ask', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ key }),
            });
            const data = await resp.json();
            this._removeLastMessage();
            if (data.success) {
                this._appendMessage('assistant', data.response);
            } else {
                this._appendMessage('system', `错误: ${data.message}`);
            }
        } catch (err) {
            this._removeLastMessage();
            this._appendMessage('system', `请求失败: ${err.message}`);
        } finally {
            this._loading = false;
        }
    },

    /** 清空对话 */
    async _clearChat() {
        const messages = document.getElementById('aiChatMessages');
        if (messages) {
            messages.innerHTML = `
                <div class="ai-message ai-message-system">
                    <div class="ai-message-content">对话已清空。请问有什么可以帮你的？</div>
                </div>`;
        }
        try {
            await fetch('/api/ai/clear-history', { method: 'POST' });
        } catch { /* ignore */ }
    },

    /** 添加消息 */
    _appendMessage(role, content, isLoading = false) {
        const container = document.getElementById('aiChatMessages');
        if (!container) return;

        const div = document.createElement('div');
        div.className = `ai-message ai-message-${role}`;
        if (isLoading) div.classList.add('ai-message-loading');

        const contentDiv = document.createElement('div');
        contentDiv.className = 'ai-message-content';
        contentDiv.textContent = content;
        // 简单的Markdown渲染（加粗、列表）
        if (!isLoading) {
            contentDiv.innerHTML = content
                .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
                .replace(/\n- /g, '<br>- ')
                .replace(/\n(\d+)\. /g, '<br>$1. ')
                .replace(/\n/g, '<br>');
        }

        div.appendChild(contentDiv);
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    },

    /** 移除最后一条消息 */
    _removeLastMessage() {
        const container = document.getElementById('aiChatMessages');
        if (container && container.lastChild) {
            container.removeChild(container.lastChild);
        }
    },
};

// 页面加载后初始化
document.addEventListener('DOMContentLoaded', () => {
    AIAssistant.init();
});
