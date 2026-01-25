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
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
        """初始化界面 - 左右分栏设计"""
        self.setWindowTitle("WHartTest 执行器登录")
        self.setFixedSize(900, 560)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.setStyleSheet("background-color: #f0f2f5;")

        # 主布局 - 水平分栏
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ========== 左侧品牌区域 ==========
        left_panel = QFrame()
        left_panel.setFixedWidth(400)
        left_panel.setStyleSheet("""
            QFrame {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
                    stop:0 #1E88E5, stop:0.5 #1565C0, stop:1 #0D47A1);
                border-radius: 0;
            }
        """)

        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(40, 40, 40, 40)
        left_layout.setSpacing(0)

        left_layout.addStretch(2)

        # 左侧 Logo
        left_logo = QLabel()
        left_logo.setFixedSize(80, 80)
        left_logo.setStyleSheet("""
            background: rgba(255, 255, 255, 0.15);
            border-radius: 20px;
            border: none;
        """)
        logo_pixmap = self._create_logo()
        left_logo.setPixmap(logo_pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        left_logo.setAlignment(Qt.AlignCenter)

        logo_container = QHBoxLayout()
        logo_container.addStretch()
        logo_container.addWidget(left_logo)
        logo_container.addStretch()
        left_layout.addLayout(logo_container)
        left_layout.addSpacing(24)

        # 左侧标题
        left_title = QLabel("WHartTest")
        left_title.setStyleSheet("""
            font-size: 32px;
            font-weight: bold;
            color: white;
            background: transparent;
        """)
        left_title.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(left_title)
        left_layout.addSpacing(8)

        # 左侧副标题
        left_subtitle = QLabel("小麦智测自动化平台")
        left_subtitle.setStyleSheet("""
            font-size: 16px;
            color: rgba(255, 255, 255, 0.85);
            background: transparent;
        """)
        left_subtitle.setAlignment(Qt.AlignCenter)
        left_layout.addWidget(left_subtitle)
        left_layout.addSpacing(40)

        # 功能特性列表 - 2列网格布局（使用简写标识，完全兼容）
        features = [
            ("AI", "智能生成"),
            ("DB", "RAG 知识库"),
            ("MCP", "工具调用"),
            ("SK", "Skills 技能库"),
            ("PW", "自动化执行"),
            ("LG", "LangGraph"),
        ]

        features_grid = QGridLayout()
        features_grid.setSpacing(12)
        features_grid.setHorizontalSpacing(16)

        for idx, (icon, text) in enumerate(features):
            row = idx // 2
            col = idx % 2

            feature_widget = QFrame()
            feature_widget.setStyleSheet("""
                QFrame {
                    background: rgba(255, 255, 255, 0.08);
                    border-radius: 10px;
                }
            """)
            feature_widget.setFixedHeight(46)
            feature_widget.setMinimumWidth(145)

            feature_layout = QHBoxLayout(feature_widget)
            feature_layout.setContentsMargins(10, 8, 10, 8)
            feature_layout.setSpacing(8)

            icon_label = QLabel(icon)
            icon_label.setStyleSheet("""
                font-size: 10px;
                font-weight: bold;
                color: rgba(255, 255, 255, 0.95);
                background: rgba(255, 255, 255, 0.18);
                border-radius: 4px;
            """)
            icon_label.setMinimumWidth(32)
            icon_label.setFixedHeight(22)
            icon_label.setAlignment(Qt.AlignCenter)

            text_label = QLabel(text)
            text_label.setStyleSheet("""
                font-size: 12px;
                color: rgba(255, 255, 255, 0.95);
                background: transparent;
            """)

            feature_layout.addWidget(icon_label)
            feature_layout.addWidget(text_label, 1)

            features_grid.addWidget(feature_widget, row, col)

        left_layout.addLayout(features_grid)
        left_layout.addStretch(3)

        main_layout.addWidget(left_panel)

        # ========== 右侧登录表单区域 ==========
        right_panel = QFrame()
        right_panel.setStyleSheet("""
            QFrame {
                background-color: #f8fafc;
            }
        """)

        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(50, 40, 50, 40)
        right_layout.setSpacing(0)

        right_layout.addStretch(1)

        # 表单卡片
        form_card = QFrame()
        form_card.setStyleSheet("""
            QFrame {
                background-color: white;
                border-radius: 16px;
            }
        """)
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(80)
        shadow.setColor(QColor(0, 0, 0, 100))
        shadow.setOffset(0, 16)
        form_card.setGraphicsEffect(shadow)

        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(40, 36, 40, 36)
        form_layout.setSpacing(0)

        # 表单标题
        form_title = QLabel("执行器登录")
        form_title.setStyleSheet("""
            font-size: 24px;
            font-weight: bold;
            color: #1a1a1a;
            background: transparent;
        """)
        form_title.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(form_title)
        form_layout.addSpacing(6)

        form_subtitle = QLabel("请输入您的账号信息")
        form_subtitle.setStyleSheet("""
            font-size: 14px;
            color: #666;
            background: transparent;
        """)
        form_subtitle.setAlignment(Qt.AlignCenter)
        form_layout.addWidget(form_subtitle)
        form_layout.addSpacing(28)

        # 输入框样式 - 无图标，简洁设计
        input_style = """
            QLineEdit {
                border: 1px solid #e0e0e0;
                border-radius: 10px;
                padding: 14px 16px;
                font-size: 15px;
                background-color: #fafafa;
                color: #333;
            }
            QLineEdit:focus {
                border-color: #1976D2;
                background-color: white;
            }
            QLineEdit::placeholder {
                color: #bbb;
            }
        """

        # 服务器地址
        self.api_url_input = QLineEdit()
        self.api_url_input.setPlaceholderText("服务器地址")
        self.api_url_input.setFixedHeight(50)
        self.api_url_input.setStyleSheet(input_style)
        form_layout.addWidget(self.api_url_input)
        form_layout.addSpacing(14)

        # 用户名
        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("请输入用户名")
        self.username_input.setFixedHeight(50)
        self.username_input.setStyleSheet(input_style)
        form_layout.addWidget(self.username_input)
        form_layout.addSpacing(14)

        # 密码样式 - 右侧预留切换按钮空间
        password_style = """
            QLineEdit {
                border: 1px solid #e0e0e0;
                border-radius: 10px;
                padding: 14px 44px 14px 16px;
                font-size: 15px;
                background-color: #fafafa;
                color: #333;
            }
            QLineEdit:focus {
                border-color: #1976D2;
                background-color: white;
            }
            QLineEdit::placeholder {
                color: #bbb;
            }
        """
        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("请输入密码")
        self.password_input.setFixedHeight(50)
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.setStyleSheet(password_style)
        self._add_password_toggle(self.password_input)
        form_layout.addWidget(self.password_input)
        form_layout.addSpacing(16)

        # 状态标签
        self.status_label = QLabel("")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #666; background: transparent; font-size: 13px;")
        self.status_label.setFixedHeight(16)
        form_layout.addWidget(self.status_label)
        form_layout.addSpacing(8)

        # 登录按钮
        self.login_btn = QPushButton("登录")
        self.login_btn.setFixedHeight(50)
        self.login_btn.setCursor(Qt.PointingHandCursor)
        self.login_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1E88E5, stop:1 #1565C0);
                color: white;
                border: none;
                border-radius: 10px;
                font-size: 16px;
                font-weight: 500;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #42A5F5, stop:1 #1E88E5);
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1565C0, stop:1 #0D47A1);
            }
            QPushButton:disabled {
                background: #ccc;
            }
        """)
        self.login_btn.clicked.connect(self._on_login_clicked)
        form_layout.addWidget(self.login_btn)

        right_layout.addWidget(form_card)
        right_layout.addStretch(1)

        # 隐藏取消按钮（兼容性）
        self.cancel_btn = QPushButton()
        self.cancel_btn.hide()

        main_layout.addWidget(right_panel)

        # 回车键登录
        self.password_input.returnPressed.connect(self._on_login_clicked)

    def _create_logo(self) -> QPixmap:
        """创建 Logo - 尝试加载图片，失败则使用默认绘制"""
        # 尝试加载项目 logo 图片
        logo_paths = [
            Path(__file__).parent.parent / "data" / "WHartTest.png",
            Path(__file__).parent.parent.parent / "WHartTest_Vue" / "public" / "WHartTest.png",
            Path(__file__).parent.parent / "WHartTest.png",
        ]
        
        for logo_path in logo_paths:
            if logo_path.exists():
                pixmap = QPixmap(str(logo_path))
                if not pixmap.isNull():
                    return pixmap.scaled(56, 56, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        
        # 如果找不到图片，使用默认绘制
        pixmap = QPixmap(56, 56)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)

        # 绘制箭头形状
        from PySide6.QtGui import QPainterPath, QBrush

        path = QPainterPath()
        path.moveTo(8, 14)
        path.lineTo(30, 28)
        path.lineTo(8, 42)
        path.lineTo(18, 28)
        path.closeSubpath()
        painter.setBrush(QBrush(QColor("#0096c7")))
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)

        path2 = QPainterPath()
        path2.moveTo(24, 14)
        path2.lineTo(46, 28)
        path2.lineTo(24, 42)
        path2.lineTo(34, 28)
        path2.closeSubpath()
        painter.setBrush(QBrush(QColor("#48cae4")))
        painter.drawPath(path2)

        painter.end()
        return pixmap

    def _add_password_toggle(self, line_edit: QLineEdit):
        """添加密码显示/隐藏切换"""
        toggle_btn = QPushButton("o", line_edit)
        toggle_btn.setStyleSheet("""
            QPushButton {
                background: transparent;
                border: none;
                font-size: 14px;
                color: #999;
            }
            QPushButton:hover {
                color: #666;
            }
        """)
        toggle_btn.setFixedSize(24, 24)
        toggle_btn.setCursor(Qt.PointingHandCursor)
        toggle_btn.move(line_edit.width() - 38, 11)

        def update_position():
            toggle_btn.move(line_edit.width() - 38, 11)

        line_edit.resizeEvent = lambda e: update_position()

        def toggle_visibility():
            if line_edit.echoMode() == QLineEdit.Password:
                line_edit.setEchoMode(QLineEdit.Normal)
                toggle_btn.setText(".")  # 显示状态 - 密码可见
            else:
                line_edit.setEchoMode(QLineEdit.Password)
                toggle_btn.setText("o")  # 隐藏状态 - 密码隐藏

        toggle_btn.clicked.connect(toggle_visibility)
    
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
