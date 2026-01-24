"""
GUI 登录窗口模块

提供 PySide6 图形界面登录功能，支持：
- 用户名/密码输入
- 服务器地址配置
- 登录验证
- 配置记忆
"""

import asyncio
import sys
from typing import Optional

from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import httpx
import tomli
import tomli_w
from pathlib import Path


class LoginWorker(QThread):
    """异步登录工作线程"""
    
    login_success = Signal(str, str)  # (access_token, refresh_token)
    login_failed = Signal(str)  # error_message
    
    def __init__(
        self,
        api_url: str,
        username: str,
        password: str,
        parent: Optional[QWidget] = None
    ):
        super().__init__(parent)
        self.api_url = api_url.rstrip('/')
        self.username = username
        self.password = password
    
    def run(self):
        """执行登录验证"""
        try:
            with httpx.Client(timeout=10) as client:
                resp = client.post(
                    f"{self.api_url}/api/token/",
                    json={"username": self.username, "password": self.password}
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    # 兼容不同的响应格式
                    if data.get('status') == 'success':
                        access = data['data']['access']
                        refresh = data['data'].get('refresh', '')
                    else:
                        access = data.get('access', '')
                        refresh = data.get('refresh', '')
                    
                    if access:
                        self.login_success.emit(access, refresh)
                    else:
                        self.login_failed.emit("登录响应格式错误")
                elif resp.status_code == 401:
                    self.login_failed.emit("用户名或密码错误")
                else:
                    self.login_failed.emit(f"服务器错误: {resp.status_code}")
                    
        except httpx.ConnectError:
            self.login_failed.emit("无法连接到服务器，请检查地址是否正确")
        except httpx.TimeoutException:
            self.login_failed.emit("连接超时，请检查网络")
        except Exception as e:
            self.login_failed.emit(f"登录失败: {str(e)}")


class LoginWindow(QDialog):
    """执行器登录窗口"""
    
    def __init__(self, config_path: str = "config.toml", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config_path = Path(config_path)
        self._config = self._load_config()
        
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._login_worker: Optional[LoginWorker] = None
        
        self._init_ui()
        self._load_saved_credentials()
    
    def _load_config(self) -> dict:
        """加载配置文件"""
        if self.config_path.exists():
            with open(self.config_path, 'rb') as f:
                return tomli.load(f)
        return {}
    
    def _save_config(self):
        """保存配置文件"""
        with open(self.config_path, 'wb') as f:
            tomli_w.dump(self._config, f)
    
    def _init_ui(self):
        """初始化界面"""
        self.setWindowTitle("WHartTest 执行器登录")
        self.setFixedSize(400, 280)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(30, 30, 30, 30)
        main_layout.setSpacing(15)
        
        # 标题
        title_label = QLabel("WHartTest 执行器")
        title_font = QFont()
        title_font.setPointSize(16)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(title_label)
        
        # 表单布局
        form_layout = QFormLayout()
        form_layout.setSpacing(10)
        
        # 服务器地址
        self.api_url_input = QLineEdit()
        self.api_url_input.setPlaceholderText("例如: http://localhost:8000")
        form_layout.addRow("服务器:", self.api_url_input)
        
        # 用户名
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("请输入用户名")
        form_layout.addRow("用户名:", self.username_input)
        
        # 密码
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("请输入密码")
        self.password_input.setEchoMode(QLineEdit.Password)
        form_layout.addRow("密码:", self.password_input)
        
        main_layout.addLayout(form_layout)
        
        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #666;")
        main_layout.addWidget(self.status_label)
        
        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        self.login_btn = QPushButton("登录")
        self.login_btn.setFixedHeight(35)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background-color: #1890ff;
                color: white;
                border: none;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #40a9ff;
            }
            QPushButton:pressed {
                background-color: #096dd9;
            }
            QPushButton:disabled {
                background-color: #d9d9d9;
            }
        """)
        self.login_btn.clicked.connect(self._on_login_clicked)
        
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setFixedHeight(35)
        self.cancel_btn.setFixedWidth(80)
        self.cancel_btn.clicked.connect(self.reject)
        
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.login_btn, 1)
        
        main_layout.addLayout(btn_layout)
        
        # 回车键登录
        self.password_input.returnPressed.connect(self._on_login_clicked)
    
    def _load_saved_credentials(self):
        """加载保存的凭证"""
        server = self._config.get('server', {})
        self.api_url_input.setText(server.get('api_url', 'http://localhost:8000'))
        self.username_input.setText(server.get('api_username', ''))
        self.password_input.setText(server.get('api_password', ''))
    
    def _on_login_clicked(self):
        """登录按钮点击处理"""
        api_url = self.api_url_input.text().strip()
        username = self.username_input.text().strip()
        password = self.password_input.text()
        
        if not api_url:
            self._show_error("请输入服务器地址")
            return
        if not username:
            self._show_error("请输入用户名")
            return
        if not password:
            self._show_error("请输入密码")
            return
        
        self._set_loading(True)
        self.status_label.setText("正在登录...")
        self.status_label.setStyleSheet("color: #1890ff;")
        
        # 启动登录工作线程
        self._login_worker = LoginWorker(api_url, username, password, self)
        self._login_worker.login_success.connect(self._on_login_success)
        self._login_worker.login_failed.connect(self._on_login_failed)
        self._login_worker.start()
    
    def _on_login_success(self, access_token: str, refresh_token: str):
        """登录成功处理"""
        self._access_token = access_token
        self._refresh_token = refresh_token
        
        # 更新配置
        if 'server' not in self._config:
            self._config['server'] = {}
        self._config['server']['api_url'] = self.api_url_input.text().strip()
        self._config['server']['api_username'] = self.username_input.text().strip()
        self._config['server']['api_password'] = self.password_input.text()
        self._save_config()
        
        self.status_label.setText("登录成功！")
        self.status_label.setStyleSheet("color: #52c41a;")
        
        self.accept()
    
    def _on_login_failed(self, error: str):
        """登录失败处理"""
        self._set_loading(False)
        self.status_label.setText(error)
        self.status_label.setStyleSheet("color: #ff4d4f;")
    
    def _set_loading(self, loading: bool):
        """设置加载状态"""
        self.login_btn.setEnabled(not loading)
        self.cancel_btn.setEnabled(not loading)
        self.api_url_input.setEnabled(not loading)
        self.username_input.setEnabled(not loading)
        self.password_input.setEnabled(not loading)
    
    def _show_error(self, message: str):
        """显示错误信息"""
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color: #ff4d4f;")
    
    @property
    def access_token(self) -> Optional[str]:
        """获取登录成功后的 access token"""
        return self._access_token
    
    @property
    def refresh_token(self) -> Optional[str]:
        """获取登录成功后的 refresh token"""
        return self._refresh_token
    
    @property
    def api_url(self) -> str:
        """获取服务器地址"""
        return self.api_url_input.text().strip()
    
    @property
    def username(self) -> str:
        """获取用户名"""
        return self.username_input.text().strip()
    
    @property
    def password(self) -> str:
        """获取密码"""
        return self.password_input.text()


def show_login_dialog(config_path: str = "config.toml") -> Optional[dict]:
    """
    显示登录对话框
    
    Returns:
        成功返回 {'access_token', 'api_url', 'username', 'password'}
        取消或失败返回 None
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    
    login_window = LoginWindow(config_path)
    result = login_window.exec()
    
    if result == QDialog.Accepted and login_window.access_token:
        return {
            'access_token': login_window.access_token,
            'refresh_token': login_window.refresh_token,
            'api_url': login_window.api_url,
            'username': login_window.username,
            'password': login_window.password,
        }
    return None


if __name__ == "__main__":
    # 独立测试
    result = show_login_dialog()
    if result:
        print(f"登录成功: {result['username']} @ {result['api_url']}")
        print(f"Token: {result['access_token'][:20]}...")
    else:
        print("登录取消或失败")
