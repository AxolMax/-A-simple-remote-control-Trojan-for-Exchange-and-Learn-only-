import subprocess
import sys
import os

def install_package(package):
    """安装Python包"""
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package])
        print(f"✅ 成功安装: {package}")
        return True
    except subprocess.CalledProcessError:
        print(f"❌ 安装失败: {package}")
        return False

def main():
    print("🚀 开始安装远程控制程序依赖...")
    print("=" * 50)
    
    # 基础依赖
    base_requirements = [
        "flask",
        "requests",
        "pillow",
        "psutil"
    ]
    
    # Windows特定依赖
    windows_requirements = [
        "pywin32"
    ]
    
    # 可选依赖（用于高级功能）
    optional_requirements = [
        "cryptography",
        "opencv-python",
        "pyautogui"
    ]
    
    all_packages = base_requirements.copy()
    
    if sys.platform == "win32":
        all_packages.extend(windows_requirements)
    
    # 询问是否安装可选依赖
    print("可选依赖（用于高级功能）:")
    for package in optional_requirements:
        choice = input(f"是否安装 {package}? (y/n): ").lower().strip()
        if choice in ['y', 'yes']:
            all_packages.append(package)
    
    print(f"\n将要安装的包: {', '.join(all_packages)}")
    input("按Enter键开始安装...")
    
    success_count = 0
    for package in all_packages:
        if install_package(package):
            success_count += 1
    
    print("\n" + "=" * 50)
    print(f"安装完成: {success_count}/{len(all_packages)} 个包安装成功")
    
    if success_count == len(all_packages):
        print("🎉 所有依赖安装成功！")
    else:
        print("⚠️  部分依赖安装失败，某些功能可能无法使用")
    
    # 创建配置文件
    create_config_files()
    
    print("\n📝 接下来需要:")
    print("1. 修改 server.py 中的配置（如果需要）")
    print("2. 修改 client.py 中的 SERVER_URL")
    print("3. 先运行服务端: python server.py")
    print("4. 再运行客户端: python client.py")

def create_config_files():
    """创建配置文件"""
    config_content = """# 远程控制程序配置
# 服务端配置
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5000
MAX_CLIENTS = 50

# 安全配置
ENABLE_ENCRYPTION = false
AUTH_TOKEN = "your_secret_token_here"

# 性能配置
HEARTBEAT_INTERVAL = 10
MAX_UPLOAD_SIZE = 10485760  # 10MB
"""
    
    try:
        with open('config.py', 'w', encoding='utf-8') as f:
            f.write(config_content)
        print("✅ 配置文件创建成功: config.py")
    except Exception as e:
        print(f"❌ 创建配置文件失败: {e}")

if __name__ == '__main__':
    main()