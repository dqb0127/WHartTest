"""与Brain Agent对话 - 对话式测试工具

用户可以:
1. 和Brain对话
2. Brain会生成执行计划
3. 用户可以提意见、调整
4. 用户确认后,Brain开始执行
"""

import requests
import time
import json
from typing import Optional

# 配置
BASE_URL = "http://localhost:8000"
USERNAME = "admin"
PASSWORD = "123456"


class BrainChatTester:
    def __init__(self):
        self.base_url = BASE_URL
        self.token = None
        self.session_id = None
        self.task_id = None
        self.project_id = None
    
    def login(self) -> bool:
        """登录"""
        print("="*60)
        print("  登录系统")
        print("="*60)
        
        url = f"{self.base_url}/api/token/"
        data = {"username": USERNAME, "password": PASSWORD}
        
        response = requests.post(url, json=data)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                self.token = result["data"]["access"]
                print(f"✅ 登录成功! (用户: {USERNAME})\n")
                return True
        
        print(f"❌ 登录失败: {response.text}")
        return False
    
    def select_project(self) -> bool:
        """选择项目(默认使用项目ID=1)"""
        self.project_id = 1
        print(f"✅ 使用默认项目 (ID: {self.project_id})\n")
        return True
    
    def create_chat_session(self) -> bool:
        """创建对话会话(使用第一条消息自动创建)"""
        # 不需要预先创建会话,聊天API会自动创建
        # 会话ID在第一次发送消息时生成
        print(f"✅ 准备开始对话\n")
        return True
    
    def chat_with_brain(self, user_message: str) -> Optional[str]:
        """发送消息给Brain"""
        url = f"{self.base_url}/api/lg/chat/"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }
        data = {
            "message": user_message,
            "session_id": self.session_id,  # 第一次为None,会自动创建
            "project_id": self.project_id    # 必需参数
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                data = result.get("data", {})
                
                # 保存session_id(第一次会返回)
                if not self.session_id and data.get("session_id"):
                    self.session_id = data["session_id"]
                    print(f"🔗 会话ID: {self.session_id}\n")
                
                # 获取Brain的回复
                brain_reply = data.get("llm_response", "") or data.get("ai_response", "")
                return brain_reply
        else:
            print(f"❌ API错误: {response.status_code}")
            print(f"   {response.text[:200]}")
        
        return None
    
    def check_for_execution_command(self, brain_reply: str) -> Optional[dict]:
        """检查Brain的回复是否包含执行指令"""
        if "{" in brain_reply and '"action"' in brain_reply:
            try:
                # 尝试解析JSON
                start = brain_reply.find("{")
                end = brain_reply.rfind("}") + 1
                json_str = brain_reply[start:end]
                command = json.loads(json_str)
                
                if command.get("action") == "execute_plan":
                    return command
            except:
                pass
        return None
    
    def create_task_from_command(self, command: dict) -> Optional[int]:
        """根据执行指令创建任务"""
        url = f"{self.base_url}/api/orchestrator/tasks/"
        headers = {"Authorization": f"Bearer {self.token}"}
        data = {
            "requirement": command.get("requirement", ""),
            "knowledge_base_ids": command.get("knowledge_base_ids", [])
        }
        
        response = requests.post(url, json=data, headers=headers)
        
        if response.status_code == 201:
            result = response.json()
            if result.get("status") == "success":
                self.task_id = result["data"]["id"]
                return self.task_id
        
        return None
    
    def monitor_task(self):
        """监控任务执行"""
        print("\n" + "="*60)
        print("  Brain正在执行任务...")
        print("="*60 + "\n")
        
        url = f"{self.base_url}/api/orchestrator/tasks/{self.task_id}/progress/"
        headers = {"Authorization": f"Bearer {self.token}"}
        
        last_step = -1
        while True:
            response = requests.get(url, headers=headers)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("status") == "success":
                    data = result["data"]
                    
                    status = data.get("status")
                    current_step = data.get("current_step", 0)
                    
                    if current_step != last_step and current_step > 0:
                        history = data.get("execution_history", [])
                        if history:
                            latest = history[-1]
                            print(f"🧠 步骤 {current_step}: {latest.get('agent')}")
                            print(f"   └─ {latest.get('结果', '')[:80]}\n")
                        last_step = current_step
                    
                    if status in ['completed', 'failed']:
                        print(f"✅ 任务{status}!\n")
                        return status
                    
                    time.sleep(2)
            else:
                time.sleep(2)
    
    def get_task_results(self):
        """获取任务结果"""
        url = f"{self.base_url}/api/orchestrator/tasks/{self.task_id}/"
        headers = {"Authorization": f"Bearer {self.token}"}
        
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            if result.get("status") == "success":
                data = result["data"]
                
                testcases = data.get('testcases', [])
                print(f"📋 生成了{len(testcases)}个测试用例:")
                for i, tc in enumerate(testcases, 1):
                    print(f"\n用例 {i}:")
                    print(json.dumps(tc, ensure_ascii=False, indent=2))
    
    def run_conversation(self):
        """运行对话"""
        print("\n" + "🤖 "*30)
        print("与 Brain Agent 对话")
        print("Brain 是智能编排系统的大脑,负责理解需求、制定计划并执行")
        print("🤖 "*30 + "\n")
        
        # 1. 登录
        if not self.login():
            return
        
        # 2. 选择项目
        if not self.select_project():
            return
        
        # 3. 准备对话会话
        if not self.create_chat_session():
            return
        
        print("💬 开始对话 (输入 'exit' 退出)\n")
        print("提示: 你可以这样说:")
        print("  - '我需要为登录功能生成测试用例'")
        print("  - '包括正常登录、错误密码、账号不存在等场景'")
        print("  - '可以,开始执行吧'\n")
        print("-"*60 + "\n")
        
        while True:
            # 用户输入
            user_input = input("你: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ['exit', 'quit', '退出']:
                print("\n👋 再见!")
                break
            
            # 发送给Brain
            print()  # 空行
            brain_reply = self.chat_with_brain(user_input)
            
            if brain_reply:
                print(f"🧠 Brain: {brain_reply}\n")
                
                # 检查是否有执行指令
                command = self.check_for_execution_command(brain_reply)
                
                if command:
                    print("🚀 Brain输出了执行指令!")
                    print(f"   需求: {command.get('requirement', '')}")
                    print(f"   计划步骤: {len(command.get('plan', {}).get('执行步骤', []))}个\n")
                    
                    # 创建任务
                    task_id = self.create_task_from_command(command)
                    
                    if task_id:
                        print(f"✅ 任务已创建 (ID: {task_id})")
                        
                        # 监控执行
                        status = self.monitor_task()
                        
                        if status == 'completed':
                            # 显示结果
                            self.get_task_results()
                        
                        print("\n" + "-"*60)
                        print("对话继续...\n")
            else:
                print("❌ Brain没有回复\n")


def main():
    """主函数"""
    chat = BrainChatTester()
    chat.run_conversation()


if __name__ == "__main__":
    main()