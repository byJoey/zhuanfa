#!/bin/bash

# 端口转发工具管理脚本
# 作者: Joey
# 版本: 1.0

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 配置变量
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="t.py"
SERVICE_NAME="port-forwarder"
LOG_FILE="port_forwarder.log"
PID_FILE="/tmp/port_forwarder.pid"
BACKUP_DIR="backups"

# 检查是否为root用户
check_root() {
    if [[ $EUID -eq 0 ]]; then
        echo -e "${RED}错误: 请不要以root用户运行此脚本${NC}"
        exit 1
    fi
}

# 显示标题
show_header() {
    clear
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}    专业端口转发工具管理脚本${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo
}

# 显示菜单
show_menu() {
    echo -e "${YELLOW}请选择操作:${NC}"
    echo -e "${GREEN}1)${NC} 安装依赖"
    echo -e "${GREEN}2)${NC} 启动服务"
    echo -e "${GREEN}3)${NC} 停止服务"
    echo -e "${GREEN}4)${NC} 重启服务"
    echo -e "${GREEN}5)${NC} 查看状态"
    echo -e "${GREEN}6)${NC} 查看日志"
    echo -e "${GREEN}7)${NC} 查看配置"
    echo -e "${GREEN}8)${NC} 备份数据"
    echo -e "${GREEN}9)${NC} 恢复数据"
    echo -e "${GREEN}10)${NC} 清理数据"
    echo -e "${GREEN}11)${NC} 设置开机自启"
    echo -e "${GREEN}12)${NC} 取消开机自启"
            echo -e "${GREEN}13)${NC} 测试持久化功能"
        echo -e "${GREEN}14)${NC} 测试智能保存"
        echo -e "${GREEN}15)${NC} 下载最新版本"
        echo -e "${GREEN}16)${NC} 测试下载功能"
        echo -e "${GREEN}17)${NC} 查看帮助"
        echo -e "${GREEN}0)${NC} 退出"
    echo
}

# 检查Python是否安装
check_python() {
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}错误: Python3 未安装${NC}"
        echo -e "${YELLOW}请先安装Python3:${NC}"
        echo "  macOS: brew install python3"
        echo "  Ubuntu: sudo apt install python3"
        echo "  CentOS: sudo yum install python3"
        return 1
    fi
    echo -e "${GREEN}✓ Python3 已安装${NC}"
    return 0
}

# 安装依赖
install_dependencies() {
    echo -e "${BLUE}正在安装依赖...${NC}"
    
    # 检查Python
    if ! check_python; then
        return 1
    fi
    
    # 安装pip依赖
    echo -e "${YELLOW}正在安装Python依赖...${NC}"
    python3 -m pip install --user flask werkzeug
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 依赖安装成功${NC}"
    else
        echo -e "${RED}✗ 依赖安装失败${NC}"
        return 1
    fi
    
    # 创建备份目录
    mkdir -p "$BACKUP_DIR"
    echo -e "${GREEN}✓ 备份目录已创建${NC}"
    
    echo -e "${GREEN}所有依赖安装完成！${NC}"
}

# 检查服务状态
check_status() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ 服务正在运行 (PID: $PID)${NC}"
            return 0
        else
            echo -e "${RED}✗ 服务未运行 (PID文件存在但进程不存在)${NC}"
            rm -f "$PID_FILE"
            return 1
        fi
    else
        echo -e "${YELLOW}○ 服务未运行${NC}"
        return 1
    fi
}

# 启动服务
start_service() {
    echo -e "${BLUE}正在启动服务...${NC}"
    
    # 检查是否已在运行
    if check_status > /dev/null 2>&1; then
        echo -e "${YELLOW}服务已在运行中${NC}"
        return 0
    fi
    
    # 检查Python脚本是否存在
    if [ ! -f "$PYTHON_SCRIPT" ]; then
        echo -e "${RED}错误: $PYTHON_SCRIPT 文件不存在${NC}"
        return 1
    fi
    
    # 启动服务
    cd "$SCRIPT_DIR"
    nohup python3 "$PYTHON_SCRIPT" > /dev/null 2>&1 &
    PID=$!
    
    # 保存PID
    echo $PID > "$PID_FILE"
    
    # 等待服务启动
    sleep 2
    
    # 检查是否启动成功
    if check_status > /dev/null 2>&1; then
        echo -e "${GREEN}✓ 服务启动成功 (PID: $PID)${NC}"
        
        # 显示访问信息
        if [ -f "password.txt" ]; then
            echo -e "${CYAN}访问信息:${NC}"
            echo -e "  配置文件: password.txt"
            echo -e "  日志文件: $LOG_FILE"
            echo -e "  数据目录: data/"
            
            # 尝试读取安全路径
            if grep -q "path=" password.txt; then
                SECURITY_PATH=$(grep "path=" password.txt | cut -d'=' -f2 | tr -d ' ')
                echo -e "  管理地址: http://localhost:5000/$SECURITY_PATH/admin"
            fi
        fi
    else
        echo -e "${RED}✗ 服务启动失败${NC}"
        rm -f "$PID_FILE"
        return 1
    fi
}

# 停止服务
stop_service() {
    echo -e "${BLUE}正在停止服务...${NC}"
    
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if ps -p "$PID" > /dev/null 2>&1; then
            kill "$PID"
            sleep 2
            
            # 强制终止如果还在运行
            if ps -p "$PID" > /dev/null 2>&1; then
                kill -9 "$PID"
                sleep 1
            fi
            
            rm -f "$PID_FILE"
            echo -e "${GREEN}✓ 服务已停止${NC}"
        else
            echo -e "${YELLOW}服务未在运行${NC}"
            rm -f "$PID_FILE"
        fi
    else
        echo -e "${YELLOW}服务未在运行${NC}"
    fi
}

# 重启服务
restart_service() {
    echo -e "${BLUE}正在重启服务...${NC}"
    stop_service
    sleep 2
    start_service
}

# 查看日志
view_logs() {
    echo -e "${BLUE}查看日志 (按 q 退出):${NC}"
    if [ -f "$LOG_FILE" ]; then
        tail -f "$LOG_FILE"
    else
        echo -e "${YELLOW}日志文件不存在${NC}"
    fi
}

# 查看配置
view_config() {
    echo -e "${BLUE}当前配置:${NC}"
    echo -e "${CYAN}========================================${NC}"
    
    # 显示Python脚本信息
    if [ -f "$PYTHON_SCRIPT" ]; then
        echo -e "${GREEN}✓ 主程序: $PYTHON_SCRIPT${NC}"
        echo -e "  大小: $(du -h "$PYTHON_SCRIPT" | cut -f1)"
        echo -e "  修改时间: $(stat -f "%Sm" "$PYTHON_SCRIPT")"
    else
        echo -e "${RED}✗ 主程序不存在${NC}"
    fi
    
    # 显示配置文件
    if [ -f "password.txt" ]; then
        echo -e "${GREEN}✓ 配置文件: password.txt${NC}"
        echo -e "  大小: $(du -h password.txt | cut -f1)"
    else
        echo -e "${YELLOW}○ 配置文件不存在 (首次运行时会自动生成)${NC}"
    fi
    
    # 显示数据目录
    if [ -d "data" ]; then
        echo -e "${GREEN}✓ 数据目录: data/${NC}"
        echo -e "  大小: $(du -sh data 2>/dev/null | cut -f1 || echo '未知')"
        
        # 显示数据文件
        for file in data/*.json data/*.pkl; do
            if [ -f "$file" ]; then
                echo -e "    $(basename "$file"): $(du -h "$file" | cut -f1)"
            fi
        done
    else
        echo -e "${YELLOW}○ 数据目录不存在${NC}"
    fi
    
    # 显示日志文件
    if [ -f "$LOG_FILE" ]; then
        echo -e "${GREEN}✓ 日志文件: $LOG_FILE${NC}"
        echo -e "  大小: $(du -h "$LOG_FILE" | cut -f1)"
    else
        echo -e "${YELLOW}○ 日志文件不存在${NC}"
    fi
    
    echo -e "${CYAN}========================================${NC}"
}

# 备份数据
backup_data() {
    echo -e "${BLUE}正在备份数据...${NC}"
    
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    BACKUP_NAME="backup_$TIMESTAMP"
    BACKUP_PATH="$BACKUP_DIR/$BACKUP_NAME"
    
    mkdir -p "$BACKUP_PATH"
    
    # 备份配置文件
    if [ -f "password.txt" ]; then
        cp "password.txt" "$BACKUP_PATH/"
        echo -e "${GREEN}✓ 配置文件已备份${NC}"
    fi
    
    # 备份数据目录
    if [ -d "data" ]; then
        cp -r "data" "$BACKUP_PATH/"
        echo -e "${GREEN}✓ 数据目录已备份${NC}"
    fi
    
    # 备份日志文件
    if [ -f "$LOG_FILE" ]; then
        cp "$LOG_FILE" "$BACKUP_PATH/"
        echo -e "${GREEN}✓ 日志文件已备份${NC}"
    fi
    
    echo -e "${GREEN}✓ 备份完成: $BACKUP_PATH${NC}"
    echo -e "  备份大小: $(du -sh "$BACKUP_PATH" | cut -f1)"
}

# 恢复数据
restore_data() {
    echo -e "${BLUE}可用的备份:${NC}"
    
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo -e "${YELLOW}没有找到备份文件${NC}"
        return 1
    fi
    
    # 显示备份列表
    local i=1
    for backup in "$BACKUP_DIR"/backup_*; do
        if [ -d "$backup" ]; then
            echo -e "${GREEN}$i)${NC} $(basename "$backup") - $(stat -f "%Sm" "$backup")"
            i=$((i+1))
        fi
    done
    
    echo
    read -p "请选择要恢复的备份 (输入数字): " choice
    
    # 验证选择
    local backup_list=($(ls -d "$BACKUP_DIR"/backup_* 2>/dev/null))
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#backup_list[@]}" ]; then
        local selected_backup="${backup_list[$((choice-1))]}"
        
        echo -e "${YELLOW}正在恢复备份: $(basename "$selected_backup")${NC}"
        
        # 停止服务
        if check_status > /dev/null 2>&1; then
            echo -e "${YELLOW}正在停止服务...${NC}"
            stop_service
        fi
        
        # 恢复文件
        if [ -f "$selected_backup/password.txt" ]; then
            cp "$selected_backup/password.txt" .
            echo -e "${GREEN}✓ 配置文件已恢复${NC}"
        fi
        
        if [ -d "$selected_backup/data" ]; then
            rm -rf data 2>/dev/null
            cp -r "$selected_backup/data" .
            echo -e "${GREEN}✓ 数据目录已恢复${NC}"
        fi
        
        if [ -f "$selected_backup/$LOG_FILE" ]; then
            cp "$selected_backup/$LOG_FILE" .
            echo -e "${GREEN}✓ 日志文件已恢复${NC}"
        fi
        
        echo -e "${GREEN}✓ 数据恢复完成${NC}"
        
        # 询问是否启动服务
        read -p "是否启动服务? (y/n): " start_service_choice
        if [[ "$start_service_choice" =~ ^[Yy]$ ]]; then
            start_service
        fi
    else
        echo -e "${RED}无效的选择${NC}"
    fi
}

# 清理数据
clean_data() {
    echo -e "${RED}警告: 此操作将删除所有数据！${NC}"
    read -p "确定要继续吗? (输入 'yes' 确认): " confirm
    
    if [[ "$confirm" == "yes" ]]; then
        echo -e "${BLUE}正在清理数据...${NC}"
        
        # 停止服务
        if check_status > /dev/null 2>&1; then
            stop_service
        fi
        
        # 删除数据文件
        rm -f password.txt
        rm -rf data
        rm -f "$LOG_FILE"
        rm -f "$PID_FILE"
        
        echo -e "${GREEN}✓ 数据清理完成${NC}"
        echo -e "${YELLOW}注意: 下次启动时会重新生成配置文件${NC}"
    else
        echo -e "${YELLOW}操作已取消${NC}"
    fi
}

# 设置开机自启 (macOS)
setup_autostart() {
    echo -e "${BLUE}正在设置开机自启...${NC}"
    
    # 创建启动脚本
    local launch_script="$SCRIPT_DIR/start_port_forwarder.sh"
    cat > "$launch_script" << EOF
#!/bin/bash
cd "$SCRIPT_DIR"
python3 "$PYTHON_SCRIPT" > /dev/null 2>&1 &
echo \$! > "$PID_FILE"
EOF
    
    chmod +x "$launch_script"
    
    # 创建LaunchAgent
    local plist_file="$HOME/Library/LaunchAgents/com.portforwarder.plist"
    cat > "$plist_file" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.portforwarder</string>
    <key>ProgramArguments</key>
    <array>
        <string>$launch_script</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/autostart.log</string>
    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/autostart.log</string>
</dict>
</plist>
EOF
    
    # 加载LaunchAgent
    launchctl load "$plist_file"
    
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 开机自启设置成功${NC}"
        echo -e "  启动脚本: $launch_script"
        echo -e "  LaunchAgent: $plist_file"
    else
        echo -e "${RED}✗ 开机自启设置失败${NC}"
    fi
}

# 取消开机自启
disable_autostart() {
    echo -e "${BLUE}正在取消开机自启...${NC}"
    
    local plist_file="$HOME/Library/LaunchAgents/com.portforwarder.plist"
    
    if [ -f "$plist_file" ]; then
        launchctl unload "$plist_file"
        rm -f "$plist_file"
        echo -e "${GREEN}✓ 开机自启已取消${NC}"
    else
        echo -e "${YELLOW}开机自启未设置${NC}"
    fi
}

# 测试持久化功能
test_persistence() {
    echo -e "${BLUE}正在测试持久化功能...${NC}"
    
    if [ -f "test_persistence.py" ]; then
        python3 test_persistence.py
    else
        echo -e "${YELLOW}测试脚本不存在${NC}"
    fi
}

# 测试智能保存功能
test_smart_save() {
    echo -e "${BLUE}正在测试智能保存功能...${NC}"
    
    if [ -f "test_smart_save.py" ]; then
        python3 test_smart_save.py
    else
        echo -e "${YELLOW}智能保存测试脚本不存在${NC}"
    fi
}

# 下载最新版本
download_latest() {
    echo -e "${BLUE}正在下载最新版本...${NC}"
    
    # 检查curl是否可用
    if ! command -v curl &> /dev/null; then
        echo -e "${RED}错误: curl 未安装${NC}"
        echo -e "${YELLOW}请先安装curl:${NC}"
        echo "  macOS: brew install curl"
        echo "  Ubuntu: sudo apt install curl"
        echo "  CentOS: sudo yum install curl"
        return 1
    fi
    
    # 下载URL
    DOWNLOAD_URL="https://raw.githubusercontent.com/byJoey/zhuanfa/refs/heads/main/t.py"
    BACKUP_FILE="t.py.backup.$(date +%Y%m%d_%H%M%S)"
    
    echo -e "${YELLOW}下载地址: ${DOWNLOAD_URL}${NC}"
    
    # 检查当前文件是否存在
    if [ -f "$PYTHON_SCRIPT" ]; then
        echo -e "${YELLOW}当前文件存在，创建备份: $BACKUP_FILE${NC}"
        cp "$PYTHON_SCRIPT" "$BACKUP_FILE"
    fi
    
    # 下载文件
    echo -e "${BLUE}正在下载最新版本...${NC}"
    if curl -L -o "$PYTHON_SCRIPT" "$DOWNLOAD_URL" --silent --show-error; then
        echo -e "${GREEN}✓ 下载成功${NC}"
        
        # 检查文件是否有效
        if python3 -m py_compile "$PYTHON_SCRIPT" 2>/dev/null; then
            echo -e "${GREEN}✓ 文件语法检查通过${NC}"
            
            # 显示文件信息
            echo -e "${CYAN}文件信息:${NC}"
            echo -e "  大小: $(du -h "$PYTHON_SCRIPT" | cut -f1)"
            echo -e "  修改时间: $(stat -f "%Sm" "$PYTHON_SCRIPT")"
            echo -e "  备份文件: $BACKUP_FILE"
            
            # 询问是否重启服务
            if check_status > /dev/null 2>&1; then
                echo -e "${YELLOW}检测到服务正在运行${NC}"
                read -p "是否重启服务以应用更新? (y/n): " restart_choice
                if [[ "$restart_choice" =~ ^[Yy]$ ]]; then
                    restart_service
                fi
            fi
            
        else
            echo -e "${RED}✗ 文件语法检查失败${NC}"
            echo -e "${YELLOW}正在恢复备份...${NC}"
            if [ -f "$BACKUP_FILE" ]; then
                mv "$BACKUP_FILE" "$PYTHON_SCRIPT"
                echo -e "${GREEN}✓ 备份已恢复${NC}"
            fi
            return 1
        fi
        
    else
        echo -e "${RED}✗ 下载失败${NC}"
        echo -e "${YELLOW}正在恢复备份...${NC}"
        if [ -f "$BACKUP_FILE" ]; then
            mv "$BACKUP_FILE" "$PYTHON_SCRIPT"
            echo -e "${GREEN}✓ 备份已恢复${NC}"
        fi
        return 1
    fi
}

# 测试下载功能
test_download() {
    echo -e "${BLUE}正在测试下载功能...${NC}"
    
    if [ -f "test_download.py" ]; then
        # 检查requests模块
        if python3 -c "import requests" 2>/dev/null; then
            python3 test_download.py
        else
            echo -e "${YELLOW}requests模块未安装，正在安装...${NC}"
            python3 -m pip install --user requests
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}✓ requests安装成功${NC}"
                python3 test_download.py
            else
                echo -e "${RED}✗ requests安装失败${NC}"
            fi
        fi
    else
        echo -e "${YELLOW}下载测试脚本不存在${NC}"
    fi
}

# 显示帮助
show_help() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}              帮助信息${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo
    echo -e "${YELLOW}功能说明:${NC}"
    echo -e "  1) 安装依赖 - 安装Python依赖包"
    echo -e "  2) 启动服务 - 启动端口转发服务"
    echo -e "  3) 停止服务 - 停止端口转发服务"
    echo -e "  4) 重启服务 - 重启端口转发服务"
    echo -e "  5) 查看状态 - 检查服务运行状态"
    echo -e "  6) 查看日志 - 实时查看日志文件"
    echo -e "  7) 查看配置 - 显示当前配置信息"
    echo -e "  8) 备份数据 - 备份所有重要文件"
    echo -e "  9) 恢复数据 - 从备份恢复数据"
    echo -e "  10) 清理数据 - 删除所有数据文件"
    echo -e "  11) 设置开机自启 - 配置系统启动时自动运行"
    echo -e "  12) 取消开机自启 - 取消自动启动设置"
    echo -e "  13) 测试持久化功能 - 验证数据持久化"
    echo -e "  14) 测试智能保存 - 验证智能保存功能"
    echo -e "  15) 下载最新版本 - 从GitHub下载最新版本"
    echo -e "  16) 测试下载功能 - 验证下载功能"
    echo -e "  17) 查看帮助 - 显示此帮助信息"
    echo
    echo -e "${YELLOW}注意事项:${NC}"
    echo -e "  • 首次运行会自动生成配置文件"
    echo -e "  • 数据会自动保存到 data/ 目录"
    echo -e "  • 日志文件: $LOG_FILE"
    echo -e "  • 备份目录: $BACKUP_DIR/"
    echo
    echo -e "${YELLOW}访问管理界面:${NC}"
    echo -e "  启动服务后，查看 password.txt 文件获取访问地址"
    echo
}

# 主循环
main() {
    check_root
    
    while true; do
        show_header
        show_menu
        
        read -p "请输入选项 (0-17): " choice
        
        case $choice in
            1)
                install_dependencies
                ;;
            2)
                start_service
                ;;
            3)
                stop_service
                ;;
            4)
                restart_service
                ;;
            5)
                check_status
                ;;
            6)
                view_logs
                ;;
            7)
                view_config
                ;;
            8)
                backup_data
                ;;
            9)
                restore_data
                ;;
            10)
                clean_data
                ;;
            11)
                setup_autostart
                ;;
            12)
                disable_autostart
                ;;
            13)
                test_persistence
                ;;
            14)
                test_smart_save
                ;;
            15)
                download_latest
                ;;
            16)
                test_download
                ;;
            17)
                show_help
                ;;
            0)
                echo -e "${GREEN}再见！${NC}"
                exit 0
                ;;
            *)
                echo -e "${RED}无效选项，请重新选择${NC}"
                ;;
        esac
        
        echo
        read -p "按回车键继续..."
    done
}

# 启动主程序
main 
