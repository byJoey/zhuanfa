#!/bin/bash

# 专业端口转发工具管理脚本
# 作者: Joey
# 版本: 2.3 (纯净功能版)

# --- 全局变量 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="t.py"
SERVICE_NAME="port-forwarder"
LOG_FILE="port_forwarder.log"
PID_FILE="/tmp/${SERVICE_NAME}.pid"
BACKUP_DIR="backups"
OS_TYPE="$(uname)"


# --- 核心函数 ---

check_root() {
    if [[ $EUID -eq 0 ]]; then
        echo -e "${YELLOW}注意: 以root用户运行脚本${NC}"
    else
        echo -e "${YELLOW}注意: 以普通用户运行脚本${NC}"
    fi
}

show_header() {
    clear
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}     专业端口转发工具管理脚本 v2.3${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo
}

show_menu() {
    echo -e "${YELLOW}请选择操作:${NC}"
    echo -e "${GREEN}1)${NC} 安装/验证依赖"
    echo -e "${GREEN}2)${NC} 启动服务 (手动)"
    echo -e "${GREEN}3)${NC} 停止服务 (手动)"
    echo -e "${GREEN}4)${NC} 重启服务 (手动)"
    echo -e "${GREEN}5)${NC} 查看状态"
    echo -e "${GREEN}6)${NC} 查看日志"
    echo -e "${GREEN}7)${NC} 查看配置"
    echo -e "${GREEN}8)${NC} 备份数据"
    echo -e "${GREEN}9)${NC} 恢复数据"
    echo -e "${GREEN}10)${NC} 清理数据"
    echo -e "${GREEN}11)${NC} 设置开机自启 (支持macOS/Linux)"
    echo -e "${GREEN}12)${NC} 取消开机自启 (支持macOS/Linux)"
    echo -e "${GREEN}13)${NC} 测试持久化功能"
    echo -e "${GREEN}14)${NC} 测试智能保存"
    echo -e "${GREEN}15)${NC} 下载最新版本"
    echo -e "${GREEN}16)${NC} 测试下载功能"
    echo -e "${GREEN}17)${NC} 查看帮助"
    echo -e "${GREEN}0)${NC} 退出"
    echo
}

get_mod_time() {
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        stat -f "%Sm" "$1"
    else
        stat -c "%y" "$1"
    fi
}

download_latest() {
    echo -e "${BLUE}正在下载最新版本...${NC}"
    if ! command -v curl &> /dev/null; then
        echo -e "${RED}错误: curl 未安装${NC}"
        echo -e "${YELLOW}请先安装curl (e.g., sudo apt install curl)${NC}"
        return 1
    fi

    local download_url="https://raw.githubusercontent.com/byJoey/zhuanfa/main/t.py"
    local backup_file="${PYTHON_SCRIPT}.backup.$(date +%Y%m%d_%H%M%S)"
    echo -e "${YELLOW}下载地址: ${download_url}${NC}"

    if [ -f "$PYTHON_SCRIPT" ]; then
        echo -e "${YELLOW}当前文件存在，创建备份: $backup_file${NC}"
        mv "$PYTHON_SCRIPT" "$backup_file"
    fi

    if curl -L -o "$PYTHON_SCRIPT" "$download_url" --silent --show-error; then
        echo -e "${GREEN}✓ 下载成功${NC}"
        if python3 -m py_compile "$PYTHON_SCRIPT" 2>/dev/null; then
            echo -e "${GREEN}✓ 文件语法检查通过${NC}"
            if [ -f "$backup_file" ]; then
                echo -e "  旧版本已备份为: $backup_file"
            fi
            if check_status > /dev/null 2>&1; then
                read -p "检测到服务正在运行, 是否重启以应用更新? (y/n): " restart_choice
                if [[ "$restart_choice" =~ ^[Yy]$ ]]; then
                    if [[ "$OS_TYPE" == "Linux" ]] && command -v systemctl &> /dev/null && systemctl is-active --quiet "${SERVICE_NAME}.service"; then
                        echo -e "${BLUE}正在重启 systemd 服务...${NC}"
                        sudo systemctl restart "${SERVICE_NAME}.service"
                    else
                        restart_service
                    fi
                fi
            fi
        else
            echo -e "${RED}✗ 文件语法检查失败，可能是下载不完整。${NC}"
            echo -e "${YELLOW}正在从备份恢复...${NC}"
            [ -f "$backup_file" ] && mv "$backup_file" "$PYTHON_SCRIPT"
            return 1
        fi
    else
        echo -e "${RED}✗ 下载失败${NC}"
        [ -f "$backup_file" ] && mv "$backup_file" "$PYTHON_SCRIPT"
        return 1
    fi
}

install_dependencies() {
    echo -e "${BLUE}正在安装/验证依赖...${NC}"
    if ! command -v python3 &> /dev/null; then echo -e "${RED}错误: Python3 未安装${NC}"; return 1; fi
    echo -e "${GREEN}✓ Python3 已安装${NC}"

    if [[ "$OS_TYPE" == "Linux" ]] && command -v apt-get &> /dev/null; then
        echo -e "${CYAN}检测到 Debian/Ubuntu 系统，使用 apt 安装...${NC}"
        sudo apt-get update && sudo apt-get install -y python3-flask python3-werkzeug curl
    else
        echo -e "${YELLOW}正在使用 pip 安装Python依赖...${NC}"
        python3 -m pip install --user flask werkzeug
    fi
    if [ $? -ne 0 ]; then echo -e "${RED}✗ 环境依赖安装失败。${NC}"; return 1; fi
    echo -e "${GREEN}✓ 环境依赖安装成功。${NC}"

    echo -e "${BLUE}正在检查主程序 '$PYTHON_SCRIPT'...${NC}"
    if [ ! -f "$PYTHON_SCRIPT" ]; then
        echo -e "${YELLOW}主程序 '$PYTHON_SCRIPT' 不存在，将自动下载...${NC}"
        download_latest
        if [ ! -f "$PYTHON_SCRIPT" ]; then echo -e "${RED}✗ 主程序下载失败，安装中止。${NC}"; return 1; fi
    else
        echo -e "${GREEN}✓ 主程序 '$PYTHON_SCRIPT' 已存在。${NC}"
    fi

    mkdir -p "$BACKUP_DIR"
    echo -e "${GREEN}✓ 备份目录已创建${NC}"
    echo -e "${GREEN}所有依赖及主程序均已准备就绪！${NC}"
}

check_status() {
    if [[ "$OS_TYPE" == "Linux" ]] && command -v systemctl &> /dev/null; then
        if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
            echo -e "${GREEN}✓ systemd 服务正在运行${NC}"; return 0
        fi
    fi
    if [ -f "$PID_FILE" ]; then
        local pid
        pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${GREEN}✓ 服务正在运行 (手动/PID: $pid)${NC}"; return 0
        else
            rm -f "$PID_FILE"
        fi
    fi
    echo -e "${YELLOW}○ 服务未运行${NC}"; return 1
}

start_service() {
    echo -e "${BLUE}正在启动服务 (手动模式)...${NC}"
    if check_status > /dev/null 2>&1; then echo -e "${YELLOW}服务已在运行中${NC}"; return 0; fi
    if [ ! -f "$PYTHON_SCRIPT" ]; then echo -e "${RED}错误: $PYTHON_SCRIPT 文件不存在${NC}"; return 1; fi
    cd "$SCRIPT_DIR" || exit
    nohup python3 "$PYTHON_SCRIPT" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    sleep 1
    if ! check_status > /dev/null 2>&1; then echo -e "${RED}✗ 服务启动失败${NC}"; fi
}

stop_service() {
    echo -e "${BLUE}正在停止服务 (手动模式)...${NC}"
    if [ ! -f "$PID_FILE" ]; then echo -e "${YELLOW}服务未运行 (无PID文件)${NC}"; return; fi
    local pid
    pid=$(cat "$PID_FILE")
    kill "$pid" 2>/dev/null
    sleep 1
    if ps -p "$pid" > /dev/null 2>&1; then kill -9 "$pid" 2>/dev/null; fi
    rm -f "$PID_FILE"
    echo -e "${GREEN}✓ 服务已停止${NC}"
}

restart_service() {
    stop_service
    start_service
}

view_logs() {
    if [[ "$OS_TYPE" == "Linux" ]] && command -v systemctl &> /dev/null && systemctl is-active --quiet "${SERVICE_NAME}.service"; then
         echo -e "${BLUE}查看 systemd 日志 (按 q 退出):${NC}"
         sudo journalctl -u ${SERVICE_NAME}.service -f
         return
    fi
    echo -e "${BLUE}查看日志文件 '$LOG_FILE' (按 q 退出):${NC}"
    if [ -f "$LOG_FILE" ]; then tail -f "$LOG_FILE"; else echo -e "${YELLOW}日志文件不存在${NC}"; fi
}

view_config() {
    echo -e "${BLUE}当前配置:${NC}"
    echo -e "${CYAN}----------------------------------------${NC}"
    if [ -f "$PYTHON_SCRIPT" ]; then
        echo -e "${GREEN}主程序:${NC} $PYTHON_SCRIPT"
        echo -e "  - 大小: $(du -h "$PYTHON_SCRIPT" | cut -f1)"
        echo -e "  - 修改时间: $(get_mod_time "$PYTHON_SCRIPT")"
    else
        echo -e "${RED}主程序不存在${NC}"
    fi
    if [ -f "password.txt" ]; then
        echo -e "${GREEN}配置文件:${NC} password.txt"
    else
        echo -e "${YELLOW}配置文件不存在 (首次运行时会自动生成)${NC}"
    fi
    if [ -d "data" ]; then
        echo -e "${GREEN}数据目录:${NC} data/"
    else
        echo -e "${YELLOW}数据目录不存在${NC}"
    fi
    echo -e "${CYAN}----------------------------------------${NC}"
}

backup_data() {
    echo -e "${BLUE}正在备份数据...${NC}"
    local timestamp
    timestamp=$(date +"%Y%m%d_%H%M%S")
    local backup_path="$BACKUP_DIR/backup_$timestamp"
    mkdir -p "$backup_path"
    cp -rp data password.txt "$LOG_FILE" "$backup_path/" 2>/dev/null
    echo -e "${GREEN}✓ 备份完成: $backup_path${NC}"
}

restore_data() {
    echo -e "${BLUE}可用的备份:${NC}"
    if [ ! -d "$BACKUP_DIR" ] || [ -z "$(ls -A "$BACKUP_DIR" 2>/dev/null)" ]; then
        echo -e "${YELLOW}没有找到备份文件${NC}"; return 1;
    fi
    local i=1
    local backups=()
    for backup in "$BACKUP_DIR"/backup_*; do
        if [ -d "$backup" ]; then
            echo -e "${GREEN}$i)${NC} $(basename "$backup") - $(get_mod_time "$backup")"
            backups+=("$backup")
            i=$((i+1))
        fi
    done
    read -p "请选择要恢复的备份 (输入数字): " choice
    if [[ "$choice" =~ ^[0-9]+$ ]] && [ "$choice" -ge 1 ] && [ "$choice" -le "${#backups[@]}" ]; then
        local selected_backup="${backups[$((choice-1))]}"
        echo -e "${YELLOW}正在恢复备份: $(basename "$selected_backup")${NC}"
        stop_service
        if [ -d "$selected_backup/data" ]; then cp -rp "$selected_backup/data" .; fi
        if [ -f "$selected_backup/password.txt" ]; then cp -p "$selected_backup/password.txt" .; fi
        if [ -f "$selected_backup/$LOG_FILE" ]; then cp -p "$selected_backup/$LOG_FILE" .; fi
        echo -e "${GREEN}✓ 数据恢复完成${NC}"
    else
        echo -e "${RED}无效的选择${NC}"
    fi
}

clean_data() {
    echo -e "${RED}警告: 此操作将删除所有数据和日志！${NC}"
    read -p "确定要继续吗? (输入 'yes' 确认): " confirm
    if [[ "$confirm" == "yes" ]]; then
        stop_service
        rm -rf data password.txt "$LOG_FILE" "$PID_FILE"
        echo -e "${GREEN}✓ 数据清理完成${NC}"
    else
        echo -e "${YELLOW}操作已取消${NC}"
    fi
}

setup_autostart() {
    echo -e "${BLUE}正在设置开机自启...${NC}"
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        echo -e "${CYAN}检测到 macOS 系统，使用 launchd...${NC}"
        local plist_file="$HOME/Library/LaunchAgents/com.joey.${SERVICE_NAME}.plist"
        tee "$plist_file" > /dev/null <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>com.joey.${SERVICE_NAME}</string>
<key>ProgramArguments</key><array><string>${SCRIPT_DIR}/run.sh</string><string>start_service_autostart</string></array>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>${SCRIPT_DIR}/${LOG_FILE}</string>
<key>StandardErrorPath</key><string>${SCRIPT_DIR}/${LOG_FILE}</string>
</dict></plist>
EOF
        launchctl load "$plist_file"
        echo -e "${GREEN}✓ macOS 开机自启设置成功${NC}"
    elif [[ "$OS_TYPE" == "Linux" ]]; then
        echo -e "${CYAN}检测到 Linux 系统，使用 systemd...${NC}"
        if [[ $EUID -ne 0 ]]; then echo -e "${RED}错误: 需要root权限。请使用 'sudo $0'${NC}"; return 1; fi
        local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
        local user=${SUDO_USER:-$(whoami)}
        tee "$service_file" > /dev/null <<EOF
[Unit]
Description=Port Forwarder Service by Joey
After=network.target
[Service]
User=${user}
Group=$(id -gn "${user}")
WorkingDirectory=${SCRIPT_DIR}
ExecStart=/usr/bin/python3 ${SCRIPT_DIR}/${PYTHON_SCRIPT}
Restart=always
RestartSec=3
[Install]
WantedBy=multi-user.target
EOF
        systemctl daemon-reload && systemctl enable --now ${SERVICE_NAME}.service
        if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
            echo -e "${GREEN}✓ Linux (systemd) 服务已成功设置并启动！${NC}"
        else
            echo -e "${RED}✗ Linux (systemd) 服务设置失败。${NC}"
        fi
    else
        echo -e "${RED}错误: 不支持的操作系统 '$OS_TYPE'。${NC}"
    fi
}

disable_autostart() {
    echo -e "${BLUE}正在取消开机自启...${NC}"
    if [[ "$OS_TYPE" == "Darwin" ]]; then
        echo -e "${CYAN}检测到 macOS 系统...${NC}"
        local plist_file="$HOME/Library/LaunchAgents/com.joey.${SERVICE_NAME}.plist"
        if [ -f "$plist_file" ]; then
            launchctl unload "$plist_file"
            rm -f "$plist_file"
        fi
        echo -e "${GREEN}✓ macOS 开机自启已取消${NC}"
    elif [[ "$OS_TYPE" == "Linux" ]]; then
        echo -e "${CYAN}检测到 Linux 系统...${NC}"
        if [[ $EUID -ne 0 ]]; then echo -e "${RED}错误: 需要root权限。请使用 'sudo $0'${NC}"; return 1; fi
        systemctl disable --now ${SERVICE_NAME}.service >/dev/null 2>&1
        rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
        systemctl daemon-reload
        echo -e "${GREEN}✓ Linux (systemd) 服务已成功取消${NC}"
    else
        echo -e "${RED}错误: 不支持的操作系统 '$OS_TYPE'。${NC}"
    fi
}

run_test_script() {
    local test_script_name=$1
    echo -e "${BLUE}正在执行测试: $test_script_name${NC}"
    if [ -f "$test_script_name" ]; then
        python3 "$test_script_name"
    else
        echo -e "${YELLOW}测试脚本 '$test_script_name' 不存在。${NC}"
    fi
}

show_help() {
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN}                        帮助信息${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo
    echo -e "${YELLOW}功能说明:${NC}"
    echo -e "  1) 安装/验证依赖: 检查并安装所有必需的软件和库。"
    echo -e "  2) 启动服务 (手动): 在后台临时运行服务。"
    echo -e "  3) 停止服务 (手动): 停止手动启动的服务。"
    echo -e "  11) 设置开机自启: 将服务配置为系统启动时自动运行。"
    echo -e "  12) 取消开机自启: 移除服务的自动启动配置。"
    echo -e "  15) 下载最新版本: 从GitHub获取最新的主程序。"
    echo
    echo -e "${YELLOW}管理方式:${NC}"
    echo -e "  - 在Linux上设置开机自启后, 推荐使用 'sudo systemctl [status|start|stop|restart] ${SERVICE_NAME}' 进行管理。"
    echo -e "  - 在macOS或手动模式下, 使用本脚本的菜单选项进行管理。"
    echo
}

# --- 主逻辑 ---
main() {
    cd "$SCRIPT_DIR" || exit
    check_root
    if [[ "$OS_TYPE" == "Linux" ]] && command -v systemctl &> /dev/null && systemctl is-active --quiet "${SERVICE_NAME}.service"; then
        echo -e "${YELLOW}提示: 检测到 systemd 服务正在运行。建议使用 'sudo systemctl ...' 管理。${NC}\n"
    fi
    while true; do
        show_header; show_menu
        read -p "请输入选项 (0-17): " choice
        case $choice in
            1) install_dependencies ;; 2) start_service ;;
            3) stop_service ;; 4) restart_service ;;
            5) check_status ;; 6) view_logs ;;
            7) view_config ;; 8) backup_data ;;
            9) restore_data ;; 10) clean_data ;;
            11) setup_autostart ;; 12) disable_autostart ;;
            13) run_test_script "test_persistence.py" ;;
            14) run_test_script "test_smart_save.py" ;;
            15) download_latest ;;
            16) run_test_script "test_download.py" ;;
            17) show_help ;;
            0) echo -e "${GREEN}再见！${NC}"; exit 0 ;;
            *) echo -e "${RED}无效选项，请重新选择${NC}" ;;
        esac
        echo; read -p "按回车键继续..."
    done
}

main
