"""测试Orchestrator流式接口的脚本

使用方法:
    python orchestrator_integration/test_stream.py

需要:
    1. Django服务器正在运行
    2. 有效的JWT token
    3. 至少一个项目ID
"""
import requests
import json
import sys
import os

# 配置
BASE_URL = "http://localhost:8000"
API_ENDPOINT = f"{BASE_URL}/api/orchestrator/stream/"

def test_orchestrator_stream(token, project_id, requirement):
    """测试流式接口"""
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    
    payload = {
        "message": requirement,
        "project_id": project_id,
        # "session_id": "test_session_123",  # 可选
        # "prompt_id": 1,  # 可选：指定Brain提示词ID
    }
    
    print(f"🚀 发送请求到: {API_ENDPOINT}")
    print(f"📋 需求: {requirement}")
    print(f"📁 项目ID: {project_id}")
    print("=" * 80)
    
    try:
        response = requests.post(
            API_ENDPOINT,
            headers=headers,
            json=payload,
            stream=True,  # 关键：启用流式接收
            timeout=300  # 5分钟超时
        )
        
        if response.status_code != 200:
            print(f"❌ 错误: HTTP {response.status_code}")
            print(response.text)
            return
        
        print("✅ 连接成功，开始接收流式数据...\n")
        
        # 逐行读取SSE数据
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            
            # SSE格式: "data: {json}"
            if line.startswith("data: "):
                data_str = line[6:]  # 去掉 "data: " 前缀
                
                if data_str == "[DONE]":
                    print("\n✅ 流式传输完成")
                    break
                
                try:
                    data = json.loads(data_str)
                    event_type = data.get('type', 'unknown')
                    
                    # 根据事件类型格式化输出
                    if event_type == 'start':
                        print(f"🎬 开始执行")
                        print(f"   Session ID: {data.get('session_id')}")
                        print(f"   Project: {data.get('project_name')}")
                        print()
                    
                    elif event_type == 'brain_decision':
                        print(f"🧠 Brain决策 (步骤 {data.get('step')})")
                        print(f"   → 下一步: {data.get('next_agent')}")
                        print(f"   → 指令: {data.get('instruction')}")
                        print(f"   → 理由: {data.get('reason')}")
                        print()
                    
                    elif event_type == 'requirement_analysis':
                        print(f"📝 需求分析完成")
                        analysis = data.get('analysis', {})
                        if isinstance(analysis, dict):
                            for key, value in analysis.items():
                                print(f"   {key}: {value}")
                        print()
                    
                    elif event_type == 'knowledge_retrieval':
                        print(f"📚 知识检索完成")
                        print(f"   找到 {data.get('doc_count', 0)} 个相关文档")
                        docs = data.get('docs', [])
                        for i, doc in enumerate(docs, 1):
                            content = doc.get('content', '')[:100]
                            print(f"   文档{i}: {content}...")
                        print()
                    
                    elif event_type == 'testcase_generation':
                        print(f"✅ 测试用例生成完成")
                        print(f"   生成 {data.get('testcase_count', 0)} 个测试用例")
                        testcases = data.get('testcases', [])
                        for i, tc in enumerate(testcases, 1):
                            if isinstance(tc, dict):
                                print(f"   用例{i}: {tc.get('用例名称', tc.get('内容', 'N/A'))}")
                        print()
                    
                    elif event_type == 'agent_message':
                        agent = data.get('agent', 'Unknown')
                        content = data.get('content', '')
                        print(f"💬 {agent}: {content[:200]}")
                        if len(content) > 200:
                            print(f"   ... (共 {len(content)} 字符)")
                        print()
                    
                    elif event_type == 'final_summary':
                        print(f"📊 最终结果摘要")
                        print(f"   需求分析: {'✓' if data.get('requirement_analysis') else '✗'}")
                        print(f"   知识文档: {data.get('knowledge_doc_count', 0)} 个")
                        print(f"   测试用例: {data.get('testcase_count', 0)} 个")
                        print(f"   总步骤数: {data.get('total_steps', 0)}")
                        print()
                    
                    elif event_type == 'complete':
                        print("🎉 任务完成")
                        print()
                    
                    elif event_type == 'error':
                        print(f"❌ 错误: {data.get('message')}")
                        print()
                    
                    elif event_type == 'info':
                        print(f"ℹ️  {data.get('message')}")
                    
                    elif event_type == 'warning':
                        print(f"⚠️  {data.get('message')}")
                    
                    else:
                        # 其他类型的事件
                        print(f"📨 {event_type}: {data}")
                        print()
                
                except json.JSONDecodeError as e:
                    print(f"⚠️  无法解析JSON: {data_str[:100]}")
                    continue
        
        print("=" * 80)
        print("测试完成！")
        
    except requests.exceptions.RequestException as e:
        print(f"❌ 请求失败: {e}")
        return
    except KeyboardInterrupt:
        print("\n⚠️  用户中断")
        return


def main():
    """主函数"""
    print("=" * 80)
    print("Orchestrator流式接口测试工具")
    print("=" * 80)
    print()
    
    # 从环境变量或命令行参数获取配置
    token = os.environ.get('JWT_TOKEN') or input("请输入JWT Token: ").strip()
    if not token:
        print("❌ 需要JWT Token")
        sys.exit(1)
    
    project_id = os.environ.get('PROJECT_ID') or input("请输入项目ID: ").strip()
    if not project_id:
        print("❌ 需要项目ID")
        sys.exit(1)
    
    requirement = input("请输入需求描述 (直接回车使用默认): ").strip()
    if not requirement:
        requirement = "实现一个用户登录功能，包括账号密码验证、记住登录状态、登录失败提示等"
    
    print()
    test_orchestrator_stream(token, project_id, requirement)


if __name__ == "__main__":
    main()