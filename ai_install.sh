#!/bin/bash
# WHartTest AI 智能安装助手
# 纯 Bash 实现，无需 Python 环境

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# 全局变量
API_URL=""
API_KEY=""
MODEL_NAME=""
CONVERSATION_FILE="/tmp/ai_install_conversation_$$.json"
SYSTEM_PROMPT=""
ASSUME_YES=0
APPROVE_ALL=0
LOG_DIR="${AI_INSTALL_LOG_DIR:-data/logs}"
LOG_FILE=""
DEBUG_LOG="${AI_INSTALL_DEBUG:-0}"
MAX_TOKENS="${AI_INSTALL_MAX_TOKENS:-1024}"
TEMPERATURE="${AI_INSTALL_TEMPERATURE:-0.7}"
INCLUDE_TEMPERATURE="${AI_INSTALL_INCLUDE_TEMPERATURE:-1}"

# 清理函数
cleanup() {
    rm -f "$CONVERSATION_FILE"
}
trap cleanup EXIT

# 打印带颜色的消息
print_color() {
    local color=$1
    shift
    echo -e "${color}$@${NC}"
}

# 打印标题
print_header() {
    echo ""
    print_color "$CYAN" "=========================================="
    print_color "$BOLD$CYAN" "$1"
    print_color "$CYAN" "=========================================="
    echo ""
}

# 初始化日志文件（默认写入 data/logs）
init_log() {
    local ts
    ts=$(date '+%Y%m%d_%H%M%S' 2>/dev/null || echo "unknown_time")

    mkdir -p "$LOG_DIR" 2>/dev/null || true
    LOG_FILE="$LOG_DIR/ai_install_${ts}_$$.log"

    # 如果目标目录不可写，回退到 /tmp
    if ! ( : > "$LOG_FILE" ) 2>/dev/null; then
        LOG_DIR="/tmp"
        LOG_FILE="/tmp/ai_install_${ts}_$$.log"
        : > "$LOG_FILE" 2>/dev/null || true
    fi
}

log_line() {
    local level="$1"
    shift
    local ts
    ts=$(date '+%F %T' 2>/dev/null || echo "unknown_time")
    printf '[%s] [%s] %s\n' "$ts" "$level" "$(redact_secrets "$*")" >> "$LOG_FILE" 2>/dev/null || true
}

# 获取系统信息
get_system_info() {
    local os_type=$(uname -s)
    local os_version=$(uname -r)
    local arch=$(uname -m)
    
    echo "操作系统: $os_type $os_version"
    echo "架构: $arch"
    echo "工作目录: $(pwd)"
}

# 构建系统提示词
build_system_prompt() {
    local sys_info=$(get_system_info)
    
    SYSTEM_PROMPT="你是一个专业的项目安装助手。你正在帮助用户安装项目。

当前环境信息：
$sys_info


你的职责：
1. 理解用户的安装需求和环境
2. 提供清晰的安装步骤指导
3. 当需要执行命令时，使用特殊格式：【执行命令：命令内容】
4. 解释每个步骤的作用
5. 处理可能出现的错误

重要规则：
- 当你需要执行命令时，必须使用格式：【执行命令：命令内容】
- 一次只执行一个命令，等待结果后再继续
- **安全第一**：对于只读命令（如检查版本、查看文件），可以直接执行。
- **必须询问**：对于修改性操作（如安装软件、修改配置、下载文件），**必须先询问用户是否同意**，用户同意后才能执行。
- 另外：脚本本身也会对“可能修改系统/可能泄露敏感信息”的命令进行二次确认，避免误操作或把密钥输出回传给接口。
- 优先检测用户环境，推荐合适的安装方式
- 如果有 Docker，推荐 Docker 安装
- 如果没有 Docker，指导手动安装依赖
- 提供友好的中文指导
- **Docker 加速镜像**：如果用户在中国大陆且遇到 Docker 拉取镜像缓慢或失败的问题，请推荐配置以下加速器（daemon.json）：
  - https://docker.1ms.run
  - https://k-docker.asia
  - https://docker.1panel.live
  - https://dockerproxy.cn
  - https://docker.nastool.de
  - https://docker.agsv.top
  - https://docker.agsvpt.work
  - https://docker.m.daocloud.io
  - https://dockerhub.anzu.vip
  - https://docker.chenby.cn
  - https://docker.jijiai.cn

示例 1（只读操作）：
用户问：\"帮我检查环境\"
你回答：\"好的，让我检查一下 Docker 版本：
【执行命令：docker --version】\"

示例 2（修改操作）：
用户问：\"帮我安装 Docker\"
你回答：\"检测到您未安装 Docker。是否允许我为您安装 Docker？（这将执行安装脚本）\"
用户回答：\"可以\"
你回答：\"好的，正在安装 Docker...
【执行命令：curl -fsSL https://get.docker.com | sh】\"

现在，请开始与用户对话，了解他们的需求。"
}

# 从环境变量或 .env 文件加载配置
load_config_from_env() {
    local env_file="${AI_INSTALL_ENV_FILE:-.env}"
    
    # 如果存在 .env 文件，先加载它
    if [ -f "$env_file" ]; then
        print_color "$CYAN" "📄 检测到 $env_file 文件，正在加载配置..."

        # 兼容 Windows/Git Bash：自动去掉 CRLF 的 \r，避免变量带回车导致 curl/grep 等异常
        local sanitized_env="/tmp/ai_install_env_$$.tmp"
        sed 's/\r$//' "$env_file" > "$sanitized_env"

        # 使用 source 加载（更可靠）
        set -a
        source "$sanitized_env"
        set +a
        rm -f "$sanitized_env"
    fi
    
    # 从环境变量读取配置
    if [ -n "$AI_API_URL" ]; then
        API_URL="$AI_API_URL"
        print_color "$GREEN" "✅ 从环境变量读取 API_URL: $API_URL"
    fi
    
    if [ -n "$AI_API_KEY" ]; then
        API_KEY="$AI_API_KEY"
        print_color "$GREEN" "✅ 从环境变量读取 API_KEY: ${API_KEY:0:10}..."
    fi
    
    if [ -n "$AI_MODEL" ]; then
        MODEL_NAME="$AI_MODEL"
        print_color "$GREEN" "✅ 从环境变量读取 MODEL: $MODEL_NAME"
    fi

    if [ -n "${AI_INSTALL_ASSUME_YES:-}" ]; then
        ASSUME_YES="$AI_INSTALL_ASSUME_YES"
        if [ "$ASSUME_YES" = "1" ]; then
            print_color "$YELLOW" "⚠️  已启用 AI_INSTALL_ASSUME_YES=1：将自动同意执行确认命令（不推荐）"
        fi
    fi
}

# 脱敏敏感信息（避免把密钥/令牌发给 AI）
redact_secrets() {
    local text="$1"
    printf '%s' "$text" | sed -E \
        -e 's/(AI_API_KEY=).*/\1***REDACTED***/g' \
        -e 's/(OPENAI_API_KEY=).*/\1***REDACTED***/g' \
        -e 's/(DEEPSEEK_API_KEY=).*/\1***REDACTED***/g' \
        -e 's/(DASHSCOPE_API_KEY=).*/\1***REDACTED***/g' \
        -e 's/(Authorization: Bearer )[A-Za-z0-9._-]+/\1***REDACTED***/g' \
        -e 's/(Bearer )[A-Za-z0-9._-]+/\1***REDACTED***/g' \
        -e 's/sk-[A-Za-z0-9]{10,}/sk-***REDACTED***/g'
}

# 判断命令是否需要用户确认（修改性/敏感信息）
command_needs_confirmation() {
    local cmd="$1"
    cmd="$(echo "$cmd" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [ -z "$cmd" ] && return 1

    # 多条命令或复杂连接，保守起见需要确认
    if echo "$cmd" | grep -Eq '(^|[^\\])[;&]|&&|\|\|'; then
        return 0
    fi

    # 输出重定向/覆盖文件
    if echo "$cmd" | grep -Eq '(^|[^\\])>>?|(^|[^\\])2>>?|(^|[^\\])&>|(^|[^\\])\|[[:space:]]*tee([[:space:]]|$)'; then
        return 0
    fi

    # 可能泄露敏感信息的只读命令：执行后输出会被回传给 AI
    if echo "$cmd" | grep -Eq '(^|[[:space:]])(env|printenv)([[:space:]]|$)'; then
        return 0
    fi
    if echo "$cmd" | grep -Eq '(^|[[:space:]])cat[[:space:]]+(\.env|.*\.env)([[:space:]]|$)'; then
        return 0
    fi

    # 明确的修改性/安装类命令
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])(sudo|su)([[:space:]]|$)'; then
        return 0
    fi
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])(rm|mv|cp|mkdir|rmdir|chmod|chown|chgrp|ln|truncate|dd)([[:space:]]|$)'; then
        return 0
    fi
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])(apt|apt-get|yum|dnf|pacman|brew)([[:space:]]|$)'; then
        return 0
    fi
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])(pip|pip3|poetry|npm|pnpm|yarn)([[:space:]]|$)'; then
        return 0
    fi
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])(git)([[:space:]]+)(clone|checkout|switch|pull|push|reset|clean|rebase|merge|commit|tag)\b'; then
        return 0
    fi
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])docker([[:space:]]+)(run|build|pull|push|rm|rmi|volume|network)\b'; then
        return 0
    fi
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])docker([[:space:]]+)compose([[:space:]]+)(up|down|build|pull|push|rm)\b'; then
        return 0
    fi
    if echo "$cmd" | grep -Eiq '(^|[[:space:]])(systemctl|service)([[:space:]]|$)'; then
        return 0
    fi

    return 1
}

confirm_command() {
    local cmd="$1"

    if [ "${APPROVE_ALL:-0}" = "1" ] || [ "${ASSUME_YES:-0}" = "1" ]; then
        return 0
    fi

    if [ ! -t 0 ]; then
        print_color "$YELLOW" "⚠️  非交互模式：已跳过需要确认的命令：$cmd" >&2
        return 1
    fi

    echo "" >&2
    print_color "$YELLOW" "⚠️  该命令可能会修改系统或泄露敏感信息：" >&2
    print_color "$BOLD$YELLOW" "  $cmd" >&2
    local choice=""
    read -r -p "$(print_color $GREEN '是否允许执行？[y]允许 [n]拒绝 [a]本次全部允许 (默认 n): ')" choice || true

    case "$choice" in
        y|Y|yes|YES)
            return 0
            ;;
        a|A)
            APPROVE_ALL=1
            print_color "$YELLOW" "⚠️  已选择“本次全部允许”，后续将不再逐条确认（请谨慎）" >&2
            return 0
            ;;
        *)
            print_color "$CYAN" "已拒绝执行该命令。" >&2
            return 1
            ;;
    esac
}

# 获取可用模型列表
fetch_models() {
    print_color "$YELLOW" "\n🔍 正在获取可用模型列表..."
    
    local response=$(curl -s -w "\n%{http_code}" -X GET "$API_URL/models" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" 2>/dev/null)
    
    local http_code=$(echo "$response" | tail -n1)
    local body=$(echo "$response" | head -n -1)
    
    if [ "$http_code" = "200" ]; then
        # 提取模型 ID 列表（尝试多种 JSON 格式）
        local models=$(echo "$body" | grep -o '"id":"[^"]*"' | sed 's/"id":"//;s/"$//' | head -20)
        
        if [ -n "$models" ]; then
            print_color "$GREEN" "✅ 获取到以下可用模型：\n"
            
            # 显示模型列表并编号
            local index=1
            local model_array=()
            while IFS= read -r model; do
                if [ -n "$model" ]; then
                    print_color "$CYAN" "  [$index] $model"
                    model_array+=("$model")
                    ((index++))
                fi
            done <<< "$models"
            
            # 让用户选择
            echo ""
            read -p "$(print_color $GREEN '请选择模型编号 (或直接输入模型名称): ')" user_choice
            
            # 判断是数字还是模型名
            if [[ "$user_choice" =~ ^[0-9]+$ ]] && [ "$user_choice" -ge 1 ] && [ "$user_choice" -lt "$index" ]; then
                MODEL_NAME="${model_array[$((user_choice-1))]}"
                print_color "$GREEN" "✅ 已选择模型: $MODEL_NAME"
            elif [ -n "$user_choice" ]; then
                MODEL_NAME="$user_choice"
                print_color "$GREEN" "✅ 已设置模型: $MODEL_NAME"
            else
                print_color "$RED" "❌ 无效的选择"
                return 1
            fi
            
            return 0
        fi
    fi
    
    # 如果获取失败，提示用户手动输入
    print_color "$YELLOW" "⚠️  无法自动获取模型列表"
    echo ""
    print_color "$CYAN" "常用模型名称参考:"
    print_color "$BLUE" "  - OpenAI: gpt-4, gpt-4-turbo, gpt-3.5-turbo"
    print_color "$BLUE" "  - DeepSeek: deepseek-chat, deepseek-coder"
    print_color "$BLUE" "  - 通义千问: qwen-turbo, qwen-plus, qwen-max"
    print_color "$BLUE" "  - 硅基流动: Qwen/Qwen2.5-7B-Instruct"
    print_color "$BLUE" "  - Ollama: qwen2.5:7b, llama3.1:8b"
    echo ""
    
    while [ -z "$MODEL_NAME" ]; do
        read -p "$(print_color $GREEN '请手动输入模型名称: ')" MODEL_NAME
        if [ -z "$MODEL_NAME" ]; then
            print_color "$RED" "❌ 模型名称不能为空！"
        fi
    done
    
    return 0
}

# 配置 API
setup_api() {
    print_header "🤖 AI 智能安装助手"
    
    # 先尝试从环境变量加载配置
    load_config_from_env
    
    # 如果环境变量中已有完整配置（包括模型），直接使用
    if [ -n "$API_URL" ] && [ -n "$API_KEY" ] && [ -n "$MODEL_NAME" ]; then
        echo ""
        print_color "$GREEN" "✅ 使用环境变量配置："
        print_color "$CYAN" "  API_URL: $API_URL"
        print_color "$CYAN" "  API_KEY: ${API_KEY:0:10}..."
        print_color "$CYAN" "  MODEL: $MODEL_NAME"
        echo ""
        
        # 测试连接
        print_color "$YELLOW" "🔍 正在测试 API 连接..."
        if test_api_connection; then
            print_color "$GREEN" "✅ API 连接成功！\n"
            return 0
        else
            print_color "$RED" "❌ API 连接失败，将转为手动配置...\n"
            API_URL=""
            API_KEY=""
            MODEL_NAME=""
        fi
    fi
    
    print_color "$YELLOW" "请配置 AI API（支持 OpenAI 格式的所有接口）"
    echo ""
    print_color "$CYAN" "💡 提示：可以创建 .env 文件预设配置（AI_API_URL, AI_API_KEY, AI_MODEL）"
    echo ""
    print_color "$CYAN" "示例 API 地址:"
    print_color "$BLUE" "  - OpenAI: https://api.openai.com/v1"
    print_color "$BLUE" "  - DeepSeek: https://api.deepseek.com/v1"
    print_color "$BLUE" "  - 通义千问: https://dashscope.aliyuncs.com/compatible-mode/v1"
    print_color "$BLUE" "  - 硅基流动: https://api.siliconflow.cn/v1"
    print_color "$BLUE" "  - Ollama本地: http://localhost:11434/v1"
    echo ""
    
    # 获取 API URL（如果环境变量中没有）
    if [ -z "$API_URL" ]; then
        while [ -z "$API_URL" ]; do
            read -p "$(print_color $GREEN '请输入 API 地址: ')" API_URL
            if [ -z "$API_URL" ]; then
                print_color "$RED" "❌ API 地址不能为空！"
            fi
        done
    fi
    
    # 获取 API Key（如果环境变量中没有）
    if [ -z "$API_KEY" ]; then
        while [ -z "$API_KEY" ]; do
            read -p "$(print_color $GREEN '请输入 API Key: ')" API_KEY
            if [ -z "$API_KEY" ]; then
                print_color "$RED" "❌ API Key 不能为空！"
            fi
        done
    fi
    
    # 获取模型（如果环境变量中没有）
    if [ -z "$MODEL_NAME" ]; then
        if ! fetch_models; then
            API_URL=""
            API_KEY=""
            MODEL_NAME=""
            return 1
        fi
    fi
    
    # 测试连接
    print_color "$YELLOW" "\n🔍 正在测试 API 连接..."
    if test_api_connection; then
        print_color "$GREEN" "✅ API 连接成功！\n"
        return 0
    else
        print_color "$RED" "❌ API 连接失败，请检查配置！\n"
        API_URL=""
        API_KEY=""
        MODEL_NAME=""
        return 1
    fi
}

# 测试 API 连接
test_api_connection() {
    local payload="{\"model\":\"$MODEL_NAME\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"max_tokens\":10}"
    local payload_file="/tmp/ai_install_test_payload_$$.json"
    printf '%s' "$payload" > "$payload_file"

    local response=$(curl -sS --http1.1 -w "\n%{http_code}" -X POST "$API_URL/chat/completions" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -H "Expect:" \
        --data-binary @"$payload_file" 2>/dev/null)

    rm -f "$payload_file" 2>/dev/null || true
    
    local http_code=$(echo "$response" | tail -n1)
    
    if [ "$http_code" = "200" ]; then
        return 0
    else
        return 1
    fi
}

# 去除 ANSI 颜色代码
strip_ansi() {
    echo "$1" | sed 's/\x1b\[[0-9;]*m//g'
}

# JSON 转义函数
json_escape() {
    local string="$1"
    # 先去除 ANSI 颜色代码
    string=$(strip_ansi "$string")
    # 转义特殊字符
    string="${string//\\/\\\\}"  # 反斜杠
    string="${string//\"/\\\"}"  # 双引号
    string="${string//$'\n'/\\n}"  # 换行符
    string="${string//$'\r'/\\r}"  # 回车符
    string="${string//$'\t'/\\t}"  # 制表符
    echo "$string"
}

# 调用 AI API
call_ai() {
    local user_message="$1"
    local sanitized_user_message
    sanitized_user_message="$(redact_secrets "$user_message")"

    # 参数校验/兼容（部分 OpenAI 兼容接口对 temperature/max_tokens 很敏感）
    if ! [[ "$MAX_TOKENS" =~ ^[0-9]+$ ]]; then
        MAX_TOKENS=1024
    fi
    if ! [[ "$TEMPERATURE" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
        TEMPERATURE="0.7"
    fi
    
    # 构建消息数组
    local messages="[{\"role\":\"system\",\"content\":\"$(json_escape "$SYSTEM_PROMPT")\"}"
    
    # 读取历史对话
    if [ -f "$CONVERSATION_FILE" ]; then
        local history=$(cat "$CONVERSATION_FILE")
        if [ -n "$history" ]; then
            messages="$messages,$history"
        fi
    fi
    
    # 添加当前用户消息
    messages="$messages,{\"role\":\"user\",\"content\":\"$(json_escape "$sanitized_user_message")\"}]"

    local payload=""
    if [ "${INCLUDE_TEMPERATURE:-1}" = "1" ]; then
        payload="{
                \"model\": \"$MODEL_NAME\",
                \"messages\": $messages,
                \"temperature\": $TEMPERATURE,
                \"max_tokens\": $MAX_TOKENS
            }"
    else
        payload="{
                \"model\": \"$MODEL_NAME\",
                \"messages\": $messages,
                \"max_tokens\": $MAX_TOKENS
            }"
    fi

    local payload_file="/tmp/ai_install_payload_$$.json"
    printf '%s' "$payload" > "$payload_file"

    if [ -n "$LOG_FILE" ] && [ "$DEBUG_LOG" = "1" ]; then
        log_line "DEBUG" "AI request: url=$API_URL/chat/completions model=$MODEL_NAME payload=$(redact_secrets "$(cat "$payload_file")")"
    fi
    
    # 调用 API（Git Bash 兼容：避免把 JSON 当作命令行参数直接传给 curl.exe）
    local response=$(curl -sS --http1.1 -w "\n%{http_code}" -X POST "$API_URL/chat/completions" \
        -H "Authorization: Bearer $API_KEY" \
        -H "Content-Type: application/json" \
        -H "Expect:" \
        --data-binary @"$payload_file" 2>/dev/null)

    rm -f "$payload_file" 2>/dev/null || true

    local http_code
    http_code=$(echo "$response" | tail -n1)
    local body
    body=$(echo "$response" | head -n -1)

    if [ -n "$LOG_FILE" ] && [ "$DEBUG_LOG" = "1" ]; then
        log_line "DEBUG" "AI response: http_code=$http_code body=$(echo "$body" | tr '\n' ' ')"
    fi

    # 兼容回退：部分接口会对 temperature 或较大的 max_tokens 返回 400（但不给详细 message）
    if [ "$http_code" = "400" ]; then
        local fallback_payload="{
                \"model\": \"$MODEL_NAME\",
                \"messages\": $messages,
                \"max_tokens\": 512
            }"
        local fallback_payload_file="/tmp/ai_install_payload_fallback_$$.json"
        printf '%s' "$fallback_payload" > "$fallback_payload_file"
        if [ -n "$LOG_FILE" ] && [ "$DEBUG_LOG" = "1" ]; then
            log_line "DEBUG" "AI fallback request (no temperature, max_tokens=512): payload=$(redact_secrets "$(cat "$fallback_payload_file")")"
        fi

        local fallback_response
        fallback_response=$(curl -sS --http1.1 -w "\n%{http_code}" -X POST "$API_URL/chat/completions" \
            -H "Authorization: Bearer $API_KEY" \
            -H "Content-Type: application/json" \
            -H "Expect:" \
            --data-binary @"$fallback_payload_file" 2>/dev/null)
        rm -f "$fallback_payload_file" 2>/dev/null || true

        local fallback_code
        fallback_code=$(echo "$fallback_response" | tail -n1)
        local fallback_body
        fallback_body=$(echo "$fallback_response" | head -n -1)

        if [ -n "$LOG_FILE" ] && [ "$DEBUG_LOG" = "1" ]; then
            log_line "DEBUG" "AI fallback response: http_code=$fallback_code body=$(echo "$fallback_body" | tr '\n' ' ')"
        fi

        if [ "$fallback_code" = "200" ]; then
            http_code="$fallback_code"
            body="$fallback_body"
        fi
    fi

    if [ "$http_code" != "200" ]; then
        print_color "$RED" "❌ AI 调用失败"
        local error_msg=""
        # OpenAI 兼容格式常见：{"error":{"message":"..."}}
        error_msg=$(echo "$body" | grep -o '"message":"[^"]*"' | head -1 | sed 's/"message":"//;s/"$//')
        if [ -z "$error_msg" ]; then
            error_msg=$(echo "$body" | grep -o '"msg":"[^"]*"' | head -1 | sed 's/"msg":"//;s/"$//')
        fi
        if [ -z "$error_msg" ]; then
            error_msg=$(echo "$body" | grep -o '"error":"[^"]*"' | head -1 | sed 's/"error":"//;s/"$//')
        fi
        if [ -n "$error_msg" ]; then
            print_color "$YELLOW" "错误信息: $error_msg"
        else
            print_color "$YELLOW" "HTTP 状态码: $http_code"
        fi
        log_line "ERROR" "AI call failed: http_code=$http_code url=$API_URL/chat/completions model=$MODEL_NAME body=$(echo "$body" | tr '\n' ' ')"
        print_color "$CYAN" "日志已写入: $LOG_FILE"
        if [ "$DEBUG_LOG" != "1" ]; then
            print_color "$CYAN" "可用 AI_INSTALL_DEBUG=1 重新运行以记录请求 payload（已脱敏）"
        fi
        return 1
    fi
    
    # 提取 AI 回复
    local ai_message=$(echo "$body" | grep -o '"content":"[^"]*"' | head -1 | sed 's/"content":"//;s/"$//' | sed 's/\\n/\n/g;s/\\"/"/g')
    
    if [ -z "$ai_message" ]; then
        print_color "$RED" "❌ AI 调用失败"
        log_line "ERROR" "AI call returned empty content: body=$(echo "$body" | tr '\n' ' ')"
        print_color "$CYAN" "日志已写入: $LOG_FILE"
        return 1
    fi
    
    # 保存对话历史
    local user_json="{\"role\":\"user\",\"content\":\"$(json_escape "$sanitized_user_message")\"}"
    local assistant_json="{\"role\":\"assistant\",\"content\":\"$(json_escape "$ai_message")\"}"
    
    if [ -f "$CONVERSATION_FILE" ]; then
        echo ",$user_json,$assistant_json" >> "$CONVERSATION_FILE"
    else
        echo "$user_json,$assistant_json" > "$CONVERSATION_FILE"
    fi
    
    echo "$ai_message"
}

# 执行命令
execute_command() {
    local command="$1"
    
    # 使用紫色背景和白色文字显示命令，使其更醒目
    echo "" >&2
    echo -e "\033[45;37m ⚡ 执行系统命令 \033[0m \033[1;35m$command\033[0m" >&2
    echo -e "\033[0;90m----------------------------------------\033[0m" >&2
    
    # 执行命令并捕获输出（同时显示在终端）
    local output
    local exit_code
    local temp_log="/tmp/ai_install_cmd_output_$$.log"
    local errexit_was_set=0
    local pipefail_was_set=0

    case "$-" in
        *e*) errexit_was_set=1 ;;
    esac
    if set -o | grep -q '^pipefail[[:space:]]*on$'; then
        pipefail_was_set=1
    fi
    
    # 使用 tee 实时显示输出并保存到临时文件
    # set -o pipefail 确保管道中任何命令失败都返回失败
    set +e
    set -o pipefail
    eval "$command" 2>&1 | tee "$temp_log" >&2
    exit_code=${PIPESTATUS[0]}
    (( pipefail_was_set )) || set +o pipefail
    (( errexit_was_set )) && set -e
    
    # 读取捕获的输出
    output=$(cat "$temp_log")
    rm -f "$temp_log"
    
    echo -e "\033[0;90m----------------------------------------\033[0m" >&2
    if [ $exit_code -eq 0 ]; then
        print_color "$GREEN" "✅ 执行成功" >&2
    else
        print_color "$RED" "❌ 执行失败 (返回码: $exit_code)" >&2
    fi
    echo "" >&2
    
    # 将结果反馈给 AI（去除 ANSI 颜色代码，防止 JSON 错误）
    local clean_output=$(strip_ansi "$output")
    clean_output=$(redact_secrets "$clean_output")
    local status
    if [ $exit_code -eq 0 ]; then
        status="成功"
    else
        status="失败"
    fi
    local feedback=$'命令执行'"$status"$'。\n输出:\n'"$clean_output"
    
    # 这里的 echo 是为了让调用者（process_ai_response）捕获反馈，而不是打印到屏幕
    # 因为 process_ai_response 会调用 call_ai，需要这个反馈作为输入
    printf '%s' "$feedback"
}

# 处理 AI 响应
process_ai_response() {
    local response="$1"
    
    # 处理 AI 响应
    # 1. 去除 <think>...</think> 内容
    local clean_response="$response"
    if command -v perl &> /dev/null; then
        clean_response=$(echo "$clean_response" | perl -0777 -pe 's/<think>.*?<\/think>//gs')
    else
        clean_response=$(echo "$clean_response" | sed '/<think>/,/<\/think>/d')
    fi

    # 提取【执行命令：xxx】格式的命令（支持多条；兼容不带结尾 】 的单行输出）
    local commands=""
    if command -v perl &> /dev/null; then
        commands=$(printf '%s' "$clean_response" | perl -0777 -ne '
            while(/【执行命令：(.*?)】/sg){
                my $c=$1; $c =~ s/^\s+|\s+$//g;
                print "$c\n" if length($c);
            }
            if($. == 1 && !/【执行命令：/s){ exit 0 }
            if(!/】/s){
                while(/【执行命令：([^\n】]*)/g){
                    my $c=$1; $c =~ s/^\s+|\s+$//g;
                    print "$c\n" if length($c);
                }
            }
        ')
    else
        commands=$(printf '%s\n' "$clean_response" | sed -n \
            -e 's/.*【执行命令：\([^】]*\)】.*/\1/p' \
            -e 's/.*【执行命令：\([^】]*\)$/\1/p')
    fi
    
    # 2. 提取纯文本响应（保留命令标记并高亮）
    # 方案：将【执行命令：xxx】替换为 [准备执行: xxx] 并高亮
    local display_response=$(echo "$clean_response" | sed "s/【执行命令：/$(echo -e "\033[1;33m[准备执行: ")/g" | sed "s/】/$(echo -e "]\033[0m")/g")
    
    # 去除多余的空行
    display_response=$(echo "$display_response" | sed '/^$/d')
    
    if [ -n "$display_response" ]; then
        print_color "$BLUE" "\n🤖 AI: $display_response\n"
    fi
    
    # 如果有命令，逐个执行
    if [ -n "$commands" ]; then
        local all_results=""
        
        # 设置 IFS 为换行符，以便逐行读取命令
        local IFS=$'\n'
        for cmd in $commands; do
            local result=""
            if command_needs_confirmation "$cmd"; then
                if confirm_command "$cmd"; then
                    result=$(execute_command "$cmd")
                else
                    result=$'已跳过：用户未同意执行该命令。'
                fi
            else
                result=$(execute_command "$cmd")
            fi
            
            # 收集结果
            all_results="${all_results}命令 '$cmd' 执行结果：\n$result\n"
        done
        unset IFS
        
        # 将所有命令的执行结果反馈给 AI
        if [ -n "$all_results" ]; then
            local next_response=""
            if next_response=$(call_ai "$all_results"); then
                process_ai_response "$next_response"
            fi
        fi
    fi
}

# 主对话循环
chat_loop() {
    print_header "💬 开始对话（输入 'quit' 或 'exit' 退出）"
    
    # 初始问候
    print_color "$YELLOW" "正在初始化 AI 助手..."
    local initial_response=""
    if initial_response=$(call_ai "你好！我想安装 WHartTest 项目，请帮我检查环境并指导安装。"); then
        process_ai_response "$initial_response"
    fi
    
    while true; do
        echo ""
        read -p "$(print_color $GREEN '你: ')" user_input
        
        # 检查退出命令
        if [[ "$user_input" =~ ^(quit|exit|退出|q)$ ]]; then
            print_color "$CYAN" "\n👋 再见！"
            break
        fi
        
        # 跳过空输入
        if [ -z "$user_input" ]; then
            continue
        fi
        
        # 调用 AI
        local ai_response=""
        if ai_response=$(call_ai "$user_input"); then
            process_ai_response "$ai_response"
        fi
    done
}

# 主函数
main() {
    init_log
    log_line "INFO" "ai_install started (cwd=$(pwd))"

    # 检查 curl 是否安装
    if ! command -v curl &> /dev/null; then
        print_color "$RED" "❌ 未找到 curl 命令，请先安装 curl"
        echo "Ubuntu/Debian: sudo apt-get install curl"
        echo "CentOS/RHEL: sudo yum install curl"
        echo "macOS: brew install curl"
        exit 1
    fi
    
    # 构建系统提示词
    build_system_prompt
    
    # 配置 API
    while ! setup_api; do
        read -p "$(print_color $YELLOW '是否重新配置？(y/n): ')" retry
        if [ "$retry" != "y" ]; then
            print_color "$CYAN" "👋 退出程序"
            exit 0
        fi
    done
    log_line "INFO" "config: api_url=$API_URL model=$MODEL_NAME max_tokens=$MAX_TOKENS temperature=$TEMPERATURE include_temperature=$INCLUDE_TEMPERATURE log_file=$LOG_FILE"
    
    # 开始对话
    chat_loop
}

# 运行主函数（被 source 时不自动执行）
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main
fi
