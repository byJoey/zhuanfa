#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专业网络端口转发工具
支持TCP/UDP转发，Web管理界面，身份验证，商用级稳定性
作者: Joey
许可: MIT License (可商用)
"""

import asyncio
import socket
import threading
import time
import hashlib
import secrets
import json
import logging
import signal
import sys
import pickle
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import uuid

# Web框架
from flask import Flask, render_template_string, request, jsonify, session, redirect, url_for

# 兼容性处理 - 对于较老的Python版本
try:
    from werkzeug.security import generate_password_hash, check_password_hash
except (ImportError, AttributeError):
    # 如果导入失败或scrypt不可用，使用简单的哈希方法
    import hashlib
    def generate_password_hash(password):
        return hashlib.sha256(password.encode()).hexdigest()
    
    def check_password_hash(hash_value, password):
        return hash_value == hashlib.sha256(password.encode()).hexdigest()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('port_forwarder.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PersistenceManager:
    """持久化管理器 - 负责数据的保存和加载"""
    
    def __init__(self):
        self.data_dir = Path("data")
        self.data_dir.mkdir(exist_ok=True)
        
        # 数据文件路径
        self.forwards_file = self.data_dir / "forwards.json"
        self.stats_file = self.data_dir / "stats.json"
        self.security_file = self.data_dir / "security.pkl"
        self.backup_dir = self.data_dir / "backups"
        self.backup_dir.mkdir(exist_ok=True)
        
        # 自动保存间隔（秒）
        self.auto_save_interval = 30
        self.last_save_time = time.time()
        
        # 数据变更检测
        self.last_forwards_hash = None
        self.last_stats_hash = None
        self.last_security_hash = None
        self.data_changed = False
    
    def _calculate_hash(self, data) -> str:
        """计算数据的哈希值"""
        try:
            data_str = json.dumps(data, sort_keys=True, ensure_ascii=False)
            return hashlib.md5(data_str.encode('utf-8')).hexdigest()
        except Exception:
            # 如果无法序列化，使用字符串表示
            return hashlib.md5(str(data).encode('utf-8')).hexdigest()
    
    def _check_forwards_changed(self, forwards: Dict) -> bool:
        """检查转发配置是否有变更"""
        current_hash = self._calculate_hash(forwards)
        if self.last_forwards_hash != current_hash:
            self.last_forwards_hash = current_hash
            return True
        return False
    
    def _check_stats_changed(self, stats: Dict) -> bool:
        """检查统计数据是否有变更"""
        current_hash = self._calculate_hash(stats)
        if self.last_stats_hash != current_hash:
            self.last_stats_hash = current_hash
            return True
        return False
    
    def _check_security_changed(self, security_manager) -> bool:
        """检查安全数据是否有变更"""
        security_data = {
            'failed_attempts': security_manager.failed_attempts,
            'blocked_ips': security_manager.blocked_ips,
            'scanner_detection': security_manager.scanner_detection,
            'honeypot_hits': security_manager.honeypot_hits
        }
        current_hash = self._calculate_hash(security_data)
        if self.last_security_hash != current_hash:
            self.last_security_hash = current_hash
            return True
        return False
    
    def save_forwards(self, forwards: Dict):
        """保存转发配置"""
        try:
            # 检查是否有变更
            if not self._check_forwards_changed(forwards):
                logger.debug("转发配置无变更，跳过保存")
                return True
            
            # 只保存可序列化的数据
            serializable_forwards = {}
            for forward_id, forward_info in forwards.items():
                serializable_forwards[forward_id] = {
                    'id': forward_info['id'],
                    'protocol': forward_info['protocol'],
                    'local_port': forward_info['local_port'],
                    'remote_host': forward_info['remote_host'],
                    'remote_port': forward_info['remote_port'],
                    'status': 'stopped',  # 重启后状态重置为停止
                    'created_time': forward_info['created_time'],
                    'error': forward_info.get('error')
                }
            
            # 创建备份
            if self.forwards_file.exists():
                backup_file = self.backup_dir / f"forwards_backup_{int(time.time())}.json"
                self.forwards_file.rename(backup_file)
            
            # 保存新数据
            with open(self.forwards_file, 'w', encoding='utf-8') as f:
                json.dump(serializable_forwards, f, indent=2, ensure_ascii=False)
            
            logger.info(f"转发配置已保存: {len(serializable_forwards)} 个转发")
            self.data_changed = True
            return True
            
        except Exception as e:
            logger.error(f"保存转发配置失败: {e}")
            return False
    
    def load_forwards(self) -> Dict:
        """加载转发配置"""
        try:
            if not self.forwards_file.exists():
                logger.info("转发配置文件不存在，使用空配置")
                return {}
            
            with open(self.forwards_file, 'r', encoding='utf-8') as f:
                forwards = json.load(f)
            
            # 初始化哈希值
            self.last_forwards_hash = self._calculate_hash(forwards)
            
            logger.info(f"转发配置已加载: {len(forwards)} 个转发")
            return forwards
            
        except Exception as e:
            logger.error(f"加载转发配置失败: {e}")
            return {}
    
    def save_stats(self, stats: Dict):
        """保存统计信息"""
        try:
            # 检查是否有变更
            if not self._check_stats_changed(stats):
                logger.debug("统计信息无变更，跳过保存")
                return True
            
            # 创建备份
            if self.stats_file.exists():
                backup_file = self.backup_dir / f"stats_backup_{int(time.time())}.json"
                self.stats_file.rename(backup_file)
            
            # 保存新数据
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(stats, f, indent=2, ensure_ascii=False)
            
            logger.debug("统计信息已保存")
            self.data_changed = True
            return True
            
        except Exception as e:
            logger.error(f"保存统计信息失败: {e}")
            return False
    
    def load_stats(self) -> Dict:
        """加载统计信息"""
        try:
            if not self.stats_file.exists():
                logger.info("统计文件不存在，使用默认统计")
                return {
                    'total_connections': 0,
                    'active_connections': 0,
                    'bytes_transferred': 0,
                    'start_time': time.time()
                }
            
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                stats = json.load(f)
            
            # 确保所有必要字段存在
            default_stats = {
                'total_connections': 0,
                'active_connections': 0,
                'bytes_transferred': 0,
                'start_time': time.time()
            }
            
            for key, default_value in default_stats.items():
                if key not in stats:
                    stats[key] = default_value
            
            # 初始化哈希值
            self.last_stats_hash = self._calculate_hash(stats)
            
            logger.info("统计信息已加载")
            return stats
            
        except Exception as e:
            logger.error(f"加载统计信息失败: {e}")
            return {
                'total_connections': 0,
                'active_connections': 0,
                'bytes_transferred': 0,
                'start_time': time.time()
            }
    
    def save_security_data(self, security_manager):
        """保存安全数据"""
        try:
            # 检查是否有变更
            if not self._check_security_changed(security_manager):
                logger.debug("安全数据无变更，跳过保存")
                return True
            
            security_data = {
                'failed_attempts': security_manager.failed_attempts,
                'blocked_ips': security_manager.blocked_ips,
                'scanner_detection': security_manager.scanner_detection,
                'honeypot_hits': security_manager.honeypot_hits,
                'save_time': time.time()
            }
            
            # 创建备份
            if self.security_file.exists():
                backup_file = self.backup_dir / f"security_backup_{int(time.time())}.pkl"
                self.security_file.rename(backup_file)
            
            # 保存新数据
            with open(self.security_file, 'wb') as f:
                pickle.dump(security_data, f)
            
            logger.debug("安全数据已保存")
            self.data_changed = True
            return True
            
        except Exception as e:
            logger.error(f"保存安全数据失败: {e}")
            return False
    
    def load_security_data(self, security_manager):
        """加载安全数据"""
        try:
            if not self.security_file.exists():
                logger.info("安全数据文件不存在，使用空数据")
                return
            
            with open(self.security_file, 'rb') as f:
                security_data = pickle.load(f)
            
            # 恢复安全数据
            security_manager.failed_attempts = security_data.get('failed_attempts', {})
            security_manager.blocked_ips = security_data.get('blocked_ips', {})
            security_manager.scanner_detection = security_data.get('scanner_detection', {})
            security_manager.honeypot_hits = security_data.get('honeypot_hits', {})
            
            # 清理过期的封禁记录
            current_time = time.time()
            security_manager.blocked_ips = {
                ip: block_time for ip, block_time in security_manager.blocked_ips.items()
                if current_time < block_time
            }
            
            # 初始化哈希值
            security_data = {
                'failed_attempts': security_manager.failed_attempts,
                'blocked_ips': security_manager.blocked_ips,
                'scanner_detection': security_manager.scanner_detection,
                'honeypot_hits': security_manager.honeypot_hits
            }
            self.last_security_hash = self._calculate_hash(security_data)
            
            logger.info(f"安全数据已加载: {len(security_manager.blocked_ips)} 个封禁IP")
            
        except Exception as e:
            logger.error(f"加载安全数据失败: {e}")
    
    def auto_save(self, forwarder, security_manager):
        """自动保存数据"""
        current_time = time.time()
        if current_time - self.last_save_time >= self.auto_save_interval:
            # 重置变更标志
            self.data_changed = False
            
            # 尝试保存所有数据
            forwards_saved = self.save_forwards(forwarder.active_forwards)
            stats_saved = self.save_stats(forwarder.stats)
            security_saved = self.save_security_data(security_manager)
            
            # 只有在有实际变更时才记录保存时间
            if self.data_changed:
                self.last_save_time = current_time
                logger.debug("自动保存完成 - 检测到数据变更")
            else:
                logger.debug("自动保存完成 - 无数据变更")
    
    def cleanup_old_backups(self, max_backups: int = 3):
        """清理旧的备份文件，最多保留3份"""
        try:
            for backup_type in ['forwards_backup', 'stats_backup', 'security_backup']:
                backup_files = list(self.backup_dir.glob(f"{backup_type}_*.json")) + \
                             list(self.backup_dir.glob(f"{backup_type}_*.pkl"))
                backup_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
                # 删除多余的备份文件
                for backup_file in backup_files[3:]:
                    backup_file.unlink()
                    logger.debug(f"删除旧备份: {backup_file}")
        except Exception as e:
            logger.error(f"清理备份文件失败: {e}")

# 创建持久化管理器实例
persistence_manager = PersistenceManager()

class SecurityManager:
    """安全管理器"""
    
    def __init__(self):
        self.failed_attempts = {}
        self.blocked_ips = {}
        self.max_attempts = 5
        self.block_time = 300  # 5分钟
        self.scanner_detection = {}
        self.honeypot_hits = {}
        
        # 从持久化存储加载安全数据
        persistence_manager.load_security_data(self)
        logger.info(f"安全管理器初始化完成，加载了 {len(self.blocked_ips)} 个封禁IP")
    
    def save_data(self):
        """保存安全数据到持久化存储"""
        persistence_manager.save_security_data(self)
        
    def is_ip_blocked(self, ip: str) -> bool:
        """检查IP是否被阻止"""
        if ip in self.blocked_ips:
            if time.time() < self.blocked_ips[ip]:
                return True
            else:
                del self.blocked_ips[ip]
        return False
    
    def record_failed_attempt(self, ip: str):
        """记录失败尝试"""
        current_time = time.time()
        if ip not in self.failed_attempts:
            self.failed_attempts[ip] = []
        
        # 清理旧记录
        self.failed_attempts[ip] = [
            t for t in self.failed_attempts[ip] 
            if current_time - t < 3600  # 1小时内的记录
        ]
        
        self.failed_attempts[ip].append(current_time)
        
        # 检查是否需要阻止
        if len(self.failed_attempts[ip]) >= self.max_attempts:
            self.blocked_ips[ip] = current_time + self.block_time
            logger.warning(f"IP {ip} blocked due to multiple failed attempts")
    
    def record_scanner_behavior(self, ip: str, path: str):
        """记录扫描器行为"""
        current_time = time.time()
        if ip not in self.scanner_detection:
            self.scanner_detection[ip] = []
        
        self.scanner_detection[ip].append({
            'path': path,
            'time': current_time
        })
        
        # 清理旧记录
        self.scanner_detection[ip] = [
            entry for entry in self.scanner_detection[ip]
            if current_time - entry['time'] < 1800  # 30分钟内
        ]
        
        # 检测扫描行为 - 如果在短时间内访问多个不存在的路径
        if len(self.scanner_detection[ip]) >= 3:
            # 立即封禁扫描器
            self.blocked_ips[ip] = current_time + 3600  # 封禁1小时
            logger.warning(f"Scanner detected and blocked: {ip} - paths: {[e['path'] for e in self.scanner_detection[ip]]}")
            return True
        
        return False
    
    def record_honeypot_hit(self, ip: str, path: str):
        """记录蜜罐命中"""
        current_time = time.time()
        if ip not in self.honeypot_hits:
            self.honeypot_hits[ip] = []
        
        self.honeypot_hits[ip].append({
            'path': path,
            'time': current_time
        })
        
        # 蜜罐命中立即封禁
        self.blocked_ips[ip] = current_time + 7200  # 封禁2小时
        logger.critical(f"Honeypot triggered by {ip} accessing {path}")
    
    def clear_failed_attempts(self, ip: str):
        """清除失败尝试记录"""
        if ip in self.failed_attempts:
            del self.failed_attempts[ip]

class PortForwarder:
    """端口转发核心类"""
    
    def __init__(self):
        # 从持久化存储加载数据
        self.active_forwards = persistence_manager.load_forwards()
        self.stats = persistence_manager.load_stats()
        self.running = True
        
        # 重启时自动恢复转发的运行状态
        self.restore_forwards()
        
        logger.info(f"端口转发器初始化完成，加载了 {len(self.active_forwards)} 个转发配置")
    
    def save_data(self):
        """保存数据到持久化存储"""
        persistence_manager.save_forwards(self.active_forwards)
        persistence_manager.save_stats(self.stats)
    
    def restore_forwards(self):
        """重启时恢复转发状态"""
        restored_count = 0
        for forward_id, forward_info in list(self.active_forwards.items()):
            try:
                # 检查端口是否可用
                if not self.check_port_availability(forward_info['local_port']):
                    logger.warning(f"端口 {forward_info['local_port']} 不可用，跳过恢复转发 {forward_id}")
                    forward_info['status'] = 'error'
                    forward_info['error'] = f"端口 {forward_info['local_port']} 被占用"
                    continue
                
                # 重新启动转发
                protocol = forward_info['protocol'].lower()
                local_port = forward_info['local_port']
                remote_host = forward_info['remote_host']
                remote_port = forward_info['remote_port']
                
                logger.info(f"正在恢复转发: {protocol} {local_port} -> {remote_host}:{remote_port}")
                
                if protocol == 'tcp':
                    # TCP异步转发
                    loop = asyncio.new_event_loop()
                    def run_tcp():
                        try:
                            asyncio.set_event_loop(loop)
                            loop.run_until_complete(
                                self.tcp_forward(local_port, remote_host, remote_port, forward_id)
                            )
                        except Exception as e:
                            logger.error(f"TCP forward thread error: {e}")
                            forward_info['status'] = 'error'
                            forward_info['error'] = str(e)
                    
                    thread = threading.Thread(target=run_tcp, daemon=True)
                    thread.start()
                    forward_info['thread'] = thread
                    
                elif protocol == 'udp':
                    # UDP转发
                    thread = self.udp_forward(local_port, remote_host, remote_port, forward_id)
                    forward_info['thread'] = thread
                
                forward_info['status'] = 'running'
                forward_info['error'] = None
                restored_count += 1
                
            except Exception as e:
                logger.error(f"恢复转发失败 {forward_id}: {e}")
                forward_info['status'] = 'error'
                forward_info['error'] = str(e)
        
        if restored_count > 0:
            logger.info(f"成功恢复 {restored_count} 个转发")
            self.save_data()
    
    def check_port_availability(self, port):
        """检查端口是否可用"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result != 0  # 如果连接失败，说明端口可用
        except Exception:
            return False
    
    async def tcp_forward(self, local_port: int, remote_host: str, remote_port: int, forward_id: str):
        """TCP端口转发"""
        try:
            server = await asyncio.start_server(
                lambda r, w: self.handle_tcp_client(r, w, remote_host, remote_port, forward_id),
                '0.0.0.0', local_port
            )
            
            self.active_forwards[forward_id]['server'] = server
            logger.info(f"TCP forwarding started: {local_port} -> {remote_host}:{remote_port}")
            
            async with server:
                await server.serve_forever()
                
        except Exception as e:
            logger.error(f"TCP forward error: {e}")
            if forward_id in self.active_forwards:
                self.active_forwards[forward_id]['status'] = 'error'
                self.active_forwards[forward_id]['error'] = str(e)
    
    async def handle_tcp_client(self, reader, writer, remote_host: str, remote_port: int, forward_id: str):
        """处理TCP客户端连接"""
        client_addr = writer.get_extra_info('peername')
        logger.info(f"New TCP connection from {client_addr}")
        
        try:
            # 连接到远程服务器
            remote_reader, remote_writer = await asyncio.open_connection(remote_host, remote_port)
            
            self.stats['total_connections'] += 1
            self.stats['active_connections'] += 1
            
            # 双向数据转发
            await asyncio.gather(
                self.copy_data(reader, remote_writer, forward_id),
                self.copy_data(remote_reader, writer, forward_id),
                return_exceptions=True
            )
            
        except Exception as e:
            logger.error(f"TCP client handle error: {e}")
        finally:
            self.stats['active_connections'] -= 1
            writer.close()
            await writer.wait_closed()
    
    async def copy_data(self, reader, writer, forward_id: str):
        """复制数据流"""
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
                self.stats['bytes_transferred'] += len(data)
        except Exception as e:
            logger.debug(f"Data copy ended: {e}")
    
    def udp_forward(self, local_port: int, remote_host: str, remote_port: int, forward_id: str):
        """UDP端口转发"""
        def udp_server():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(('0.0.0.0', local_port))
            
            self.active_forwards[forward_id]['socket'] = sock
            logger.info(f"UDP forwarding started: {local_port} -> {remote_host}:{remote_port}")
            
            clients = {}
            
            try:
                while self.running and forward_id in self.active_forwards:
                    try:
                        sock.settimeout(1.0)
                        data, addr = sock.recvfrom(8192)
                        
                        if addr not in clients:
                            clients[addr] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        
                        clients[addr].sendto(data, (remote_host, remote_port))
                        self.stats['bytes_transferred'] += len(data)
                        
                    except socket.timeout:
                        continue
                    except Exception as e:
                        logger.error(f"UDP forward error: {e}")
                        break
                        
            finally:
                sock.close()
                for client_sock in clients.values():
                    client_sock.close()
        
        thread = threading.Thread(target=udp_server, daemon=True)
        thread.start()
        return thread
    
    def start_forward(self, protocol: str, local_port: int, remote_host: str, remote_port: int) -> str:
        """启动端口转发"""
        forward_id = str(uuid.uuid4())
        
        forward_info = {
            'id': forward_id,
            'protocol': protocol.upper(),
            'local_port': local_port,
            'remote_host': remote_host,
            'remote_port': remote_port,
            'status': 'starting',
            'created_time': datetime.now().isoformat(),
            'error': None
        }
        
        self.active_forwards[forward_id] = forward_info
        
        try:
            logger.info(f"Starting {protocol} forward: {local_port} -> {remote_host}:{remote_port}")
            
            if protocol.lower() == 'tcp':
                # TCP异步转发
                loop = asyncio.new_event_loop()
                def run_tcp():
                    try:
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(
                            self.tcp_forward(local_port, remote_host, remote_port, forward_id)
                        )
                    except Exception as e:
                        logger.error(f"TCP forward thread error: {e}")
                        forward_info['status'] = 'error'
                        forward_info['error'] = str(e)
                
                thread = threading.Thread(target=run_tcp, daemon=True)
                thread.start()
                forward_info['thread'] = thread
                
            elif protocol.lower() == 'udp':
                # UDP转发
                thread = self.udp_forward(local_port, remote_host, remote_port, forward_id)
                forward_info['thread'] = thread
            
            # 等待一小段时间确保服务启动
            time.sleep(0.1)
            
            forward_info['status'] = 'running'
            logger.info(f"Forward started successfully: {forward_id}")
            
            # 保存数据到持久化存储
            self.save_data()
            
            return forward_id
            
        except Exception as e:
            forward_info['status'] = 'error'
            forward_info['error'] = str(e)
            logger.error(f"Failed to start forward: {e}")
            logger.error(f"Forward details: protocol={protocol}, local_port={local_port}, remote_host={remote_host}, remote_port={remote_port}")
            
            # 即使失败也保存数据
            self.save_data()
            
            return forward_id
    
    def stop_forward(self, forward_id: str) -> bool:
        """停止端口转发"""
        if forward_id not in self.active_forwards:
            return False
        
        try:
            forward_info = self.active_forwards[forward_id]
            
            # 关闭服务器
            if 'server' in forward_info:
                forward_info['server'].close()
            
            # 关闭socket
            if 'socket' in forward_info:
                forward_info['socket'].close()
            
            forward_info['status'] = 'stopped'
            del self.active_forwards[forward_id]
            
            logger.info(f"Forward stopped: {forward_id}")
            
            # 保存数据到持久化存储
            self.save_data()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop forward: {e}")
            return False
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        uptime = time.time() - self.stats['start_time']
        return {
            **self.stats,
            'uptime': uptime,
            'active_forwards': len(self.active_forwards)
        }
    
    def get_serializable_forwards(self) -> list:
        """获取可序列化的转发信息"""
        forwards = []
        for forward_id, forward_info in self.active_forwards.items():
            # 只包含可序列化的字段
            serializable_forward = {
                'id': forward_info['id'],
                'protocol': forward_info['protocol'],
                'local_port': forward_info['local_port'],
                'remote_host': forward_info['remote_host'],
                'remote_port': forward_info['remote_port'],
                'status': forward_info['status'],
                'created_time': forward_info['created_time'],
                'error': forward_info.get('error')
            }
            forwards.append(serializable_forward)
        return forwards

# Flask Web应用
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)

# 配置管理器
class ConfigManager:
    """配置管理器"""
    
    def __init__(self):
        self.config_file = Path("password.txt")
        self.security_path = None
        self.admin_password_hash = None
        self.load_config()
    
    def load_config(self):
        """加载配置文件"""
        try:
            if self.config_file.exists():
                logger.info("Found password.txt, loading configuration...")
                config_data = self.config_file.read_text(encoding='utf-8').strip()
                
                lines = [line.strip() for line in config_data.split('\n') if line.strip() and not line.strip().startswith('#')]
                
                for line in lines:
                    if '=' in line:
                        key, value = line.split('=', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        
                        if key == 'password':
                            self.admin_password_hash = generate_password_hash(value)
                            logger.info("Password loaded from password.txt")
                        elif key == 'path':
                            # 确保路径不以/开头，我们会在使用时添加
                            self.security_path = value.lstrip('/')
                            logger.info(f"Security path loaded from password.txt: {value}")
                
                # 向后兼容：如果只有一行且没有=号，视为密码
                if len(lines) == 1 and '=' not in lines[0]:
                    self.admin_password_hash = generate_password_hash(lines[0])
                    logger.info("Password loaded from password.txt (legacy format)")
                    
            else:
                logger.info("password.txt not found, creating with random credentials...")
                self.create_example_config()
                return  # create_example_config 已经设置了所有配置
                
        except Exception as e:
            logger.error(f"Error loading config: {e}")
        
        # 设置默认值（只有在加载现有文件时才需要）
        if not self.admin_password_hash:
            random_password = secrets.token_urlsafe(16)
            try:
                self.admin_password_hash = generate_password_hash(random_password)
            except AttributeError:
                import hashlib
                self.admin_password_hash = hashlib.sha256(random_password.encode()).hexdigest()
            logger.warning(f"Using generated password: {random_password}")
        
        if not self.security_path:
            self.security_path = secrets.token_urlsafe(12)
            logger.info(f"Generated random security path: /{self.security_path}")
        else:
            logger.info(f"Using security path: /{self.security_path}")
    
    def create_example_config(self):
        """创建示例配置文件"""
        # 生成随机密码和路径
        random_password = secrets.token_urlsafe(16)  # 22字符随机密码
        random_path = secrets.token_urlsafe(12)      # 16字符随机路径
        
        example_config = f"""# 端口转发工具配置文件
# 配置格式: 键=值

# 管理员密码 (自动生成，请妥善保存)
password={random_password}

# 安全路径 (自动生成，访问地址: /{random_path}/admin)
path={random_path}

# 配置说明:
# 1. password: 管理员登录密码，建议定期更换
# 2. path: 管理界面的安全路径，防止被扫描发现
# 3. 以 # 开头的行为注释
# 4. 修改配置后点击"重新加载配置"生效

# 自定义配置示例:
# password=MySecurePassword123!
# path=my_custom_admin_path

# 重要提示:
# - 请妥善保存此配置文件
# - 密码和路径已自动生成
# - 删除此文件会重新生成新的随机配置
"""
        try:
            self.config_file.write_text(example_config, encoding='utf-8')
            logger.info(f"Created config file with random credentials: {self.config_file}")
            logger.info(f"Generated password: {random_password}")
            logger.info(f"Generated path: {random_path}")
            
            # 设置生成的配置 - 使用兼容的哈希方法
            try:
                self.admin_password_hash = generate_password_hash(random_password)
            except AttributeError:
                # 如果werkzeug的scrypt不可用，使用简单的哈希
                import hashlib
                self.admin_password_hash = hashlib.sha256(random_password.encode()).hexdigest()
            
            self.security_path = random_path
            
            # 在控制台显示重要信息
            print("=" * 60)
            print("首次运行 - 已自动生成配置文件")
            print("=" * 60)
            print(f"配置文件: {self.config_file}")
            print(f"随机密码: {random_password}")
            print(f"随机路径: {random_path}")
            print(f"管理地址: http://localhost:5000/{random_path}/admin")
            print("=" * 60)
            print("重要提示:")
            print(f"• 请妥善保存上述密码和路径信息")
            print(f"• 配置已保存到 {self.config_file}")
            print(f"• 可修改配置文件自定义密码和路径")
            print(f"• 删除配置文件会重新生成随机配置")
            print("=" * 60)
            
        except Exception as e:
            logger.error(f"Failed to create config: {e}")
            # 如果文件创建失败，至少在内存中设置随机配置
            try:
                self.admin_password_hash = generate_password_hash(random_password)
            except AttributeError:
                import hashlib
                self.admin_password_hash = hashlib.sha256(random_password.encode()).hexdigest()
            self.security_path = random_path
    
    def get_admin_path(self):
        """获取管理路径"""
        return f"/{self.security_path}/admin"
    
    def get_security_path(self):
        """获取安全路径"""
        return self.security_path
    
    def get_password_hash(self):
        """获取密码哈希"""
        return self.admin_password_hash

# 配置管理器实例
config_manager = ConfigManager()

# 获取配置
SECURITY_PATH = config_manager.get_security_path()
ADMIN_PATH = config_manager.get_admin_path()

# 重新加载配置时需要更新的全局变量
def reload_config():
    global SECURITY_PATH, ADMIN_PATH, ADMIN_PASSWORD_HASH
    config_manager.load_config()
    SECURITY_PATH = config_manager.get_security_path()
    ADMIN_PATH = config_manager.get_admin_path()
    ADMIN_PASSWORD_HASH = config_manager.get_password_hash()
    
ADMIN_PASSWORD_HASH = config_manager.get_password_hash()

# 全局对象
forwarder = PortForwarder()
security_manager = SecurityManager()

# 蜜罐路径 - 常见的扫描目标
HONEYPOT_PATHS = {
    '/admin', '/administrator', '/wp-admin', '/phpmyadmin', '/mysql',
    '/login', '/admin.php', '/admin/login', '/administrator/index.php',
    '/wp-login.php', '/cpanel', '/webmail', '/roundcube', '/squirrelmail',
    '/manager', '/tomcat', '/jenkins', '/gitea', '/grafana', '/kibana',
    '/.env', '/config.php', '/database.php', '/db_config.php',
    '/phpinfo.php', '/info.php', '/test.php', '/shell.php',
    '/.git/config', '/.svn/entries', '/backup.zip', '/backup.sql'
}

# HTML模板
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>专业端口转发管理</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .header { 
            background: rgba(255,255,255,0.95); 
            border-radius: 15px; 
            padding: 30px; 
            margin-bottom: 30px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
        }
        .card { 
            background: rgba(255,255,255,0.95); 
            border-radius: 15px; 
            padding: 25px; 
            margin-bottom: 25px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
        }
        .form-group { margin-bottom: 20px; }
        .form-group label { 
            display: block; 
            margin-bottom: 8px; 
            font-weight: 600;
            color: #555;
        }
        .form-control { 
            width: 100%; 
            padding: 12px 15px; 
            border: 2px solid #e0e0e0; 
            border-radius: 8px;
            font-size: 14px;
            transition: all 0.3s ease;
        }
        .form-control:focus { 
            outline: none; 
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        .btn { 
            padding: 12px 24px; 
            border: none; 
            border-radius: 8px; 
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            transition: all 0.3s ease;
            text-decoration: none;
            display: inline-block;
        }
        .btn-primary { 
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        .btn-primary:hover { 
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(102, 126, 234, 0.4);
        }
        .btn-danger { 
            background: linear-gradient(135deg, #ff6b6b 0%, #ee5a24 100%);
            color: white;
        }
        .btn-danger:hover { 
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(255, 107, 107, 0.4);
        }
        .table { 
            width: 100%; 
            border-collapse: collapse;
            margin-top: 20px;
        }
        .table th, .table td { 
            padding: 15px; 
            text-align: left; 
            border-bottom: 1px solid #eee;
        }
        .table th { 
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
        }
        .status { 
            padding: 6px 12px; 
            border-radius: 20px; 
            font-size: 12px;
            font-weight: 600;
            text-transform: uppercase;
        }
        .status-running { background: #d4edda; color: #155724; }
        .status-stopped { background: #f8d7da; color: #721c24; }
        .status-error { background: #fff3cd; color: #856404; }
        .stats-grid { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }
        .stat-card { 
            background: rgba(255,255,255,0.9);
            padding: 20px;
            border-radius: 10px;
            text-align: center;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        .stat-number { 
            font-size: 2em;
            font-weight: bold;
            color: #667eea;
            margin-bottom: 5px;
        }
        .stat-label { 
            color: #666;
            font-size: 0.9em;
        }
        .login-container {
            max-width: 400px;
            margin: 50px auto;
            background: rgba(255,255,255,0.95);
            padding: 40px;
            border-radius: 15px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.1);
        }
        .alert { 
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 20px;
        }
        .alert-danger { 
            background: #f8d7da;
            color: #721c24;
        }
        .alert-success { 
            background: #d4edda;
            color: #155724;
        }
        .footer { 
            text-align: center;
            margin-top: 40px;
            color: rgba(255,255,255,0.8);
        }
    </style>
</head>
<body>
    {% if session.logged_in %}
    <div class="container">
        <div class="header">
            <h1>专业端口转发管理</h1>
            <p>安全、稳定的网络端口转发解决方案</p>
            <div style="float: right;">
                <a href="/{{ security_path }}/logout" class="btn btn-danger">退出登录</a>
            </div>
            <div style="clear: both;"></div>
        </div>

        <!-- 安全状态 -->
        <div class="card">
            <h3>安全状态</h3>
            <div id="securityStatus" class="stats-grid" style="margin-bottom: 15px;">
                <!-- 动态加载 -->
            </div>
            <div style="text-align: center;">
                <button onclick="reloadConfig()" class="btn" style="background: #17a2b8; color: white;">重新加载配置</button>
                <span id="configStatus" style="margin-left: 15px; font-size: 0.9em;"></span>
            </div>
        </div>

        <!-- 持久化状态 -->
        <div class="card">
            <h3>持久化状态</h3>
            <div id="persistenceStatus" class="stats-grid" style="margin-bottom: 15px;">
                <!-- 动态加载 -->
            </div>
            <div style="text-align: center;">
                <button onclick="manualSave()" class="btn" style="background: #28a745; color: white;">手动保存</button>
                <button onclick="restoreData()" class="btn" style="background: #ffc107; color: #212529; margin-left: 10px;">重新加载数据</button>
                <span id="persistenceStatusText" style="margin-left: 15px; font-size: 0.9em;"></span>
            </div>
        </div>

        <!-- 统计信息 -->
        <div class="stats-grid" id="stats">
            <!-- 动态加载 -->
        </div>

        <!-- 添加转发规则 -->
        <div class="card">
            <h3>添加端口转发</h3>
            
            <!-- 单个转发 -->
            <div id="singleForward">
                <h4 style="margin-bottom: 15px;">单个转发</h4>
                <form id="addForwardForm">
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr 1fr 1fr; gap: 15px;">
                        <div class="form-group">
                            <label>协议</label>
                            <select name="protocol" class="form-control" required>
                                <option value="tcp">TCP</option>
                                <option value="udp">UDP</option>
                            </select>
                        </div>
                        <div class="form-group">
                            <label>本地端口</label>
                            <input type="number" name="local_port" class="form-control" min="1" max="65535" required>
                        </div>
                        <div class="form-group">
                            <label>远程主机</label>
                            <input type="text" name="remote_host" class="form-control" required>
                        </div>
                        <div class="form-group">
                            <label>远程端口</label>
                            <input type="number" name="remote_port" class="form-control" min="1" max="65535" required>
                        </div>
                        <div class="form-group">
                            <label>&nbsp;</label>
                            <button type="submit" class="btn btn-primary" style="width: 100%;">添加转发</button>
                        </div>
                    </div>
                </form>
            </div>

            <hr style="margin: 30px 0;">

            <!-- 批量转发 -->
            <div id="batchForward">
                <h4 style="margin-bottom: 15px;">批量转发</h4>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                    <div>
                        <label>转发配置 (简单格式)</label>
                        <textarea id="batchConfig" class="form-control" style="height: 200px; font-family: monospace;" placeholder='简单格式 (每行一个):
192.168.1.100|80|8080|tcp
192.168.1.100|443|8443|tcp
8.8.8.8|53|5353|udp
192.168.1.200|3306|3306
游戏服务器.com|25565|25565

格式说明:
IP|远程端口|本地端口|协议
IP|远程端口|本地端口 (自动TCP+UDP)

或者JSON格式:
[{"protocol":"tcp","local_port":8080,"remote_host":"192.168.1.100","remote_port":80}]'></textarea>
                        <div style="margin-top: 10px;">
                            <button onclick="addBatchForwards()" class="btn btn-primary">批量添加</button>
                            <button onclick="loadTemplate()" class="btn" style="background: #6c757d; color: white; margin-left: 10px;">加载模板</button>
                        </div>
                    </div>
                    <div>
                        <label>快速模板</label>
                        <div style="background: #f8f9fa; padding: 15px; border-radius: 8px; height: 200px; overflow-y: auto;">
                            <h5>简单格式模板：</h5>
                            <div class="template-item" onclick="useTemplate('simple_web')" style="cursor: pointer; padding: 8px; margin: 5px 0; background: white; border-radius: 5px;">
                                Web服务 (简单格式)
                            </div>
                            <div class="template-item" onclick="useTemplate('simple_game')" style="cursor: pointer; padding: 8px; margin: 5px 0; background: white; border-radius: 5px;">
                                游戏服务器 (简单格式)
                            </div>
                            <div class="template-item" onclick="useTemplate('simple_mixed')" style="cursor: pointer; padding: 8px; margin: 5px 0; background: white; border-radius: 5px;">
                                混合服务 (简单格式)
                            </div>
                            <div class="template-item" onclick="useTemplate('web')" style="cursor: pointer; padding: 8px; margin: 5px 0; background: white; border-radius: 5px;">
                                Web服务 (JSON格式)
                            </div>
                            <div class="template-item" onclick="useTemplate('database')" style="cursor: pointer; padding: 8px; margin: 5px 0; background: white; border-radius: 5px;">
                                数据库 (JSON格式)
                            </div>
                            <div class="template-item" onclick="useTemplate('game')" style="cursor: pointer; padding: 8px; margin: 5px 0; background: white; border-radius: 5px;">
                                游戏服务器 (JSON格式)
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- 活动转发列表 -->
        <div class="card">
            <h3>活动转发列表</h3>
            <div style="margin-bottom: 15px;">
                <button onclick="selectAllForwards()" class="btn" style="background: #17a2b8; color: white;">全选</button>
                <button onclick="unselectAllForwards()" class="btn" style="background: #6c757d; color: white; margin-left: 10px;">取消全选</button>
                <button onclick="batchStopSelected()" class="btn btn-danger" style="margin-left: 10px;">批量停止选中</button>
            </div>
            <div id="forwardsList">
                <!-- 动态加载 -->
            </div>
        </div>

        <div class="footer">
            <p>(c) 2025 专业端口转发工具 - Joey</p>
        </div>
    </div>

    <script>
        // 自动刷新数据
        function loadStats() {
            fetch('/{{ security_path }}/api/stats')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('stats').innerHTML = `
                        <div class="stat-card">
                            <div class="stat-number">${data.active_forwards}</div>
                            <div class="stat-label">活动转发</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">${data.total_connections}</div>
                            <div class="stat-label">总连接数</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">${data.active_connections}</div>
                            <div class="stat-label">当前连接</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">${formatBytes(data.bytes_transferred)}</div>
                            <div class="stat-label">传输流量</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number">${formatTime(data.uptime)}</div>
                            <div class="stat-label">运行时间</div>
                        </div>
                    `;
                });
        }

        function loadSecurityStatus() {
            fetch('/{{ security_path }}/api/security/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('securityStatus').innerHTML = `
                        <div class="stat-card">
                            <div class="stat-number" style="color: #dc3545;">${data.blocked_ips}</div>
                            <div class="stat-label">封禁IP</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: #fd7e14;">${data.failed_attempts}</div>
                            <div class="stat-label">失败尝试</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: #6f42c1;">${data.scanner_detections}</div>
                            <div class="stat-label">扫描检测</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: #e83e8c;">${data.honeypot_hits}</div>
                            <div class="stat-label">蜜罐命中</div>
                        </div>
                        <div class="stat-card">
                            <div class="stat-number" style="color: #20c997; font-size: 1.2em;">SAFE</div>
                            <div class="stat-label">安全路径活跃</div>
                        </div>
                    `;
                    
                    // 更新配置状态
                    const configStatus = document.getElementById('configStatus');
                    if (data.config_loaded) {
                        configStatus.innerHTML = '<span style="color: #28a745;">配置文件已加载</span>';
                    } else {
                        configStatus.innerHTML = '<span style="color: #ffc107;">使用默认配置</span>';
                    }
                });
        }

        function loadPersistenceStatus() {
            fetch('/{{ security_path }}/api/persistence/status')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const status = data.data;
                        document.getElementById('persistenceStatus').innerHTML = `
                            <div class="stat-card">
                                <div class="stat-number" style="color: ${status.forwards_file.exists ? '#28a745' : '#dc3545'};">${status.forwards_file.exists ? '✓' : '✗'}</div>
                                <div class="stat-label">转发配置</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number" style="color: ${status.stats_file.exists ? '#28a745' : '#dc3545'};">${status.stats_file.exists ? '✓' : '✗'}</div>
                                <div class="stat-label">统计数据</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number" style="color: ${status.security_file.exists ? '#28a745' : '#dc3545'};">${status.security_file.exists ? '✓' : '✗'}</div>
                                <div class="stat-label">安全数据</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number" style="color: #17a2b8;">${status.backup_count}</div>
                                <div class="stat-label">备份文件</div>
                            </div>
                            <div class="stat-card">
                                <div class="stat-number" style="color: #6c757d;">${status.auto_save_interval}s</div>
                                <div class="stat-label">自动保存间隔</div>
                            </div>
                        `;
                    }
                });
            
            // 检查数据变更状态
            fetch('/{{ security_path }}/api/persistence/changes')
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        const changesText = document.getElementById('persistenceStatusText');
                        if (data.has_changes) {
                            changesText.innerHTML = '<span style="color: #ffc107;">⚠️ 有未保存的变更</span>';
                        } else {
                            changesText.innerHTML = '<span style="color: #28a745;">✓ 数据已同步</span>';
                        }
                    }
                });
        }

        function manualSave() {
            if (confirm('确定要手动保存所有数据吗？')) {
                fetch('/{{ security_path }}/api/persistence/save', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        if (data.data_changed) {
                            alert('数据已手动保存！');
                        } else {
                            alert('数据无变更，无需保存！');
                        }
                        loadPersistenceStatus();
                    } else {
                        alert('保存失败: ' + data.error);
                    }
                })
                .catch(error => {
                    alert('请求失败: ' + error.message);
                });
            }
        }

        function restoreData() {
            if (confirm('确定要重新加载数据吗？\\n注意：这会重新加载所有持久化数据。')) {
                fetch('/{{ security_path }}/api/persistence/restore', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('数据已重新加载！\\n转发配置: ' + data.data.forwards_count + ' 个');
                        loadForwards();
                        loadStats();
                        loadPersistenceStatus();
                    } else {
                        alert('重新加载失败: ' + data.error);
                    }
                })
                .catch(error => {
                    alert('请求失败: ' + error.message);
                });
            }
        }

        function reloadConfig() {
            if (confirm('确定要重新加载配置文件吗？\\n注意：如果密码已更改，您需要重新登录。')) {
                fetch('/{{ security_path }}/api/config/reload', {
                    method: 'POST'
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert('配置重新加载成功！\\n' + data.message);
                        loadSecurityStatus();
                    } else {
                        alert('配置重新加载失败: ' + data.error);
                    }
                })
                .catch(error => {
                    alert('请求失败: ' + error.message);
                });
            }
        }

        function loadForwards() {
            fetch('/{{ security_path }}/api/forwards')
                .then(response => response.json())
                .then(data => {
                    let html = '<table class="table"><thead><tr><th><input type="checkbox" id="selectAll" onchange="toggleAllForwards()"></th><th>协议</th><th>本地端口</th><th>远程地址</th><th>状态</th><th>创建时间</th><th>操作</th></tr></thead><tbody>';
                    
                    if (data.forwards.length === 0) {
                        html += '<tr><td colspan="7" style="text-align: center; color: #666;">暂无活动转发</td></tr>';
                    } else {
                        data.forwards.forEach(forward => {
                            html += `
                                <tr>
                                    <td><input type="checkbox" class="forward-checkbox" value="${forward.id}"></td>
                                    <td>${forward.protocol}</td>
                                    <td>${forward.local_port}</td>
                                    <td>${forward.remote_host}:${forward.remote_port}</td>
                                    <td><span class="status status-${forward.status}">${forward.status}</span></td>
                                    <td>${new Date(forward.created_time).toLocaleString()}</td>
                                    <td>
                                        <button onclick="stopForward('${forward.id}')" class="btn btn-danger">停止</button>
                                    </td>
                                </tr>
                            `;
                        });
                    }
                    
                    html += '</tbody></table>';
                    document.getElementById('forwardsList').innerHTML = html;
                });
        }

        // 批量转发相关函数
        function addBatchForwards() {
            const configText = document.getElementById('batchConfig').value.trim();
            if (!configText) {
                alert('请输入转发配置');
                return;
            }

            let config = [];
            
            // 检测格式类型
            if (configText.startsWith('[') || configText.startsWith('{')) {
                // JSON格式
                try {
                    const jsonConfig = JSON.parse(configText);
                    config = Array.isArray(jsonConfig) ? jsonConfig : [jsonConfig];
                } catch (e) {
                    alert('JSON格式错误: ' + e.message);
                    return;
                }
            } else {
                // 简单格式解析
                const lines = configText.split('\\n').filter(line => line.trim());
                
                for (let line of lines) {
                    line = line.trim();
                    if (!line || line.startsWith('#')) continue; // 跳过空行和注释
                    
                    const parts = line.split('|');
                    if (parts.length < 3) {
                        alert(`格式错误：${line}\\n正确格式：IP|远程端口|本地端口|协议 或 IP|远程端口|本地端口`);
                        return;
                    }
                    
                    const remote_host = parts[0].trim();
                    const remote_port = parseInt(parts[1].trim());
                    const local_port = parseInt(parts[2].trim());
                    const protocol = parts.length >= 4 ? parts[3].trim().toLowerCase() : null;
                    
                    // 验证端口
                    if (isNaN(remote_port) || isNaN(local_port) || 
                        remote_port < 1 || remote_port > 65535 ||
                        local_port < 1 || local_port > 65535) {
                        alert(`端口错误：${line}\\n端口必须在1-65535之间`);
                        return;
                    }
                    
                    if (protocol) {
                        // 指定了协议
                        if (!['tcp', 'udp'].includes(protocol)) {
                            alert(`协议错误：${line}\\n协议必须是tcp或udp`);
                            return;
                        }
                        config.push({
                            protocol: protocol,
                            local_port: local_port,
                            remote_host: remote_host,
                            remote_port: remote_port
                        });
                    } else {
                        // 没有指定协议，同时添加TCP和UDP
                        config.push({
                            protocol: 'tcp',
                            local_port: local_port,
                            remote_host: remote_host,
                            remote_port: remote_port
                        });
                        config.push({
                            protocol: 'udp',
                            local_port: local_port,
                            remote_host: remote_host,
                            remote_port: remote_port
                        });
                    }
                }
            }

            if (config.length === 0) {
                alert('没有有效的转发配置');
                return;
            }

            fetch('/{{ security_path }}/api/forwards/batch', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ forwards: config })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    alert(`批量添加完成！\\n成功: ${data.success_count}\\n失败: ${data.failed_count}\\n总计: ${data.total}`);
                    if (data.failed_count > 0) {
                        console.log('失败详情:', data.results.filter(r => !r.success));
                        const failedDetails = data.results.filter(r => !r.success)
                            .map(r => `${r.config.remote_host}:${r.config.remote_port} -> ${r.config.local_port} (${r.error})`)
                            .join('\\n');
                        if (confirm('有失败的配置，是否查看详情？')) {
                            alert('失败详情:\\n' + failedDetails);
                        }
                    }
                    document.getElementById('batchConfig').value = '';
                    loadForwards();
                    loadStats();
                } else {
                    alert('批量添加失败: ' + data.error);
                }
            })
            .catch(error => {
                alert('请求失败: ' + error.message);
            });
        }

        function useTemplate(type) {
            const templates = {
                // 简单格式模板
                simple_web: `# Web服务转发 (简单格式)
192.168.1.100|80|8080|tcp
192.168.1.100|443|8443|tcp`,
                
                simple_game: `# 游戏服务器转发 (简单格式)  
minecraft.server.com|25565|25565
steam.server.com|27015|27015
# 没有协议会同时转发TCP+UDP`,
                
                simple_mixed: `# 混合服务转发 (简单格式)
192.168.1.100|80|8080|tcp
192.168.1.100|443|8443|tcp
8.8.8.8|53|5353|udp
192.168.1.200|3306|3306
192.168.1.201|5432|5432|tcp`,

                // JSON格式模板 (保持原有)
                web: [
                    { protocol: "tcp", local_port: 8080, remote_host: "192.168.1.100", remote_port: 80 },
                    { protocol: "tcp", local_port: 8443, remote_host: "192.168.1.100", remote_port: 443 }
                ],
                database: [
                    { protocol: "tcp", local_port: 3306, remote_host: "db.example.com", remote_port: 3306 },
                    { protocol: "tcp", local_port: 5432, remote_host: "db.example.com", remote_port: 5432 }
                ],
                game: [
                    { protocol: "tcp", local_port: 25565, remote_host: "game.server.com", remote_port: 25565 },
                    { protocol: "udp", local_port: 27015, remote_host: "game.server.com", remote_port: 27015 }
                ]
            };

            if (typeof templates[type] === 'string') {
                // 简单格式模板
                document.getElementById('batchConfig').value = templates[type];
            } else {
                // JSON格式模板  
                document.getElementById('batchConfig').value = JSON.stringify(templates[type], null, 2);
            }
        }

        function loadTemplate() {
            const template = `# 简单格式示例
192.168.1.100|80|8080|tcp
8.8.8.8|53|5353|udp
192.168.1.200|3306|3306
# 最后一行没有协议，会同时转发TCP+UDP`;
            document.getElementById('batchConfig').value = template;
        }

        // 选择相关函数
        function toggleAllForwards() {
            const selectAll = document.getElementById('selectAll');
            const checkboxes = document.querySelectorAll('.forward-checkbox');
            checkboxes.forEach(cb => cb.checked = selectAll.checked);
        }

        function selectAllForwards() {
            document.getElementById('selectAll').checked = true;
            toggleAllForwards();
        }

        function unselectAllForwards() {
            document.getElementById('selectAll').checked = false;
            toggleAllForwards();
        }

        function batchStopSelected() {
            const selectedIds = Array.from(document.querySelectorAll('.forward-checkbox:checked'))
                .map(cb => cb.value);
            
            if (selectedIds.length === 0) {
                alert('请选择要停止的转发');
                return;
            }

            if (confirm(`确定要停止选中的 ${selectedIds.length} 个转发吗？`)) {
                fetch('/{{ security_path }}/api/forwards/batch', {
                    method: 'DELETE',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ forward_ids: selectedIds })
                })
                .then(response => response.json())
                .then(data => {
                    if (data.success) {
                        alert(`批量停止完成！成功: ${data.success_count}, 失败: ${data.failed_count}`);
                        loadForwards();
                        loadStats();
                    } else {
                        alert('批量停止失败: ' + data.error);
                    }
                });
            }
        }

        function formatBytes(bytes) {
            if (bytes === 0) return '0 B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }

        function formatTime(seconds) {
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            return `${hours}h ${minutes}m`;
        }

        function stopForward(forwardId) {
            if (confirm('确定要停止此转发吗？')) {
                fetch('/{{ security_path }}/api/forwards/' + forwardId, { method: 'DELETE' })
                    .then(response => response.json())
                    .then(data => {
                        if (data.success) {
                            loadForwards();
                            loadStats();
                        } else {
                            alert('停止失败: ' + data.error);
                        }
                    });
            }
        }

        // 添加转发表单提交
        document.getElementById('addForwardForm').addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(this);
            
            fetch('/{{ security_path }}/api/forwards', {
                method: 'POST',
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    this.reset();
                    loadForwards();
                    loadStats();
                } else {
                    alert('添加失败: ' + data.error);
                }
            });
        });

        // 初始加载和定时刷新
        loadStats();
        loadSecurityStatus();
        loadPersistenceStatus();
        loadForwards();
        setInterval(() => {
            loadStats();
            loadSecurityStatus();
            loadPersistenceStatus();
            loadForwards();
        }, 5000);
    </script>

    {% else %}
    <!-- 登录页面 -->
    <div class="login-container">
        <h2 style="text-align: center; margin-bottom: 30px;">管理员登录</h2>
        
        {% if error %}
        <div class="alert alert-danger">{{ error }}</div>
        {% endif %}
        
        <form method="post">
            <div class="form-group">
                <label>密码</label>
                <input type="password" name="password" class="form-control" required>
            </div>
            <button type="submit" class="btn btn-primary" style="width: 100%;">登录</button>
        </form>
        
        <div style="margin-top: 20px; text-align: center; color: #666; font-size: 0.9em;">
            <p>安全提示：首次运行自动生成随机密码和路径</p>
            <p>修改配置文件后点击"重新加载配置"生效</p>
            <p>删除 password.txt 重启可重新生成随机配置</p>
        </div>
    </div>
    {% endif %}
</body>
</html>
'''

@app.before_request
def security_check():
    """安全检查"""
    client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    path = request.path
    
    # 检查IP是否被封禁
    if security_manager.is_ip_blocked(client_ip):
        logger.warning(f"Blocked IP {client_ip} attempted to access {path}")
        return jsonify({'error': 'Access denied'}), 403
    
    # 蜜罐检测
    if path in HONEYPOT_PATHS:
        security_manager.record_honeypot_hit(client_ip, path)
        return "Not Found", 404
    
    # 扫描器检测 - 访问不存在的常见路径
    if path != ADMIN_PATH and not path.startswith(f'/{SECURITY_PATH}/'):
        # 排除静态资源
        if not any(path.endswith(ext) for ext in ['.css', '.js', '.ico', '.png', '.jpg']):
            if security_manager.record_scanner_behavior(client_ip, path):
                return "Not Found", 404
            return "Not Found", 404
    
    # User-Agent检测
    user_agent = request.headers.get('User-Agent', '').lower()
    suspicious_agents = [
        'nmap', 'masscan', 'zmap', 'sqlmap', 'nikto', 'dirb', 'gobuster',
        'dirbuster', 'wfuzz', 'hydra', 'nessus', 'openvas', 'acunetix',
        'burpsuite', 'zgrab', 'shodan', 'censys', 'scanner', 'bot'
    ]
    
    if any(agent in user_agent for agent in suspicious_agents):
        logger.warning(f"Suspicious User-Agent from {client_ip}: {user_agent}")
        security_manager.record_scanner_behavior(client_ip, f"UA:{user_agent[:50]}")
        return "Not Found", 404

@app.route('/')
def root_path():
    """根路径 - 返回404而不是重定向"""
    return "Not Found", 404

@app.route(ADMIN_PATH)
def index():
    """管理界面"""
    if not session.get('logged_in'):
        return render_template_string(HTML_TEMPLATE, 
                                    security_path=SECURITY_PATH,
                                    error=request.args.get('error'))
        # 获取公网IP
        public_ip = get_public_ip()
        
        return render_template_string(HTML_TEMPLATE, 
                                   security_path=SECURITY_PATH,
                                   public_ip=public_ip)

@app.route(ADMIN_PATH, methods=['POST'])
def login():
    """登录处理"""
    client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    password = request.form.get('password')
    
    if check_password_hash(ADMIN_PASSWORD_HASH, password):
        session['logged_in'] = True
        session['login_time'] = time.time()
        security_manager.clear_failed_attempts(client_ip)
        logger.info(f"Successful login from {client_ip}")
        return redirect(ADMIN_PATH)
    else:
        security_manager.record_failed_attempt(client_ip)
        logger.warning(f"Failed login attempt from {client_ip}")
        return render_template_string(HTML_TEMPLATE, 
                                    security_path=SECURITY_PATH,
                                    error='密码错误')

@app.route(f'/{SECURITY_PATH}/logout')
def logout():
    """退出登录"""
    session.clear()
    return redirect(ADMIN_PATH)

@app.route(f'/{SECURITY_PATH}/api/stats')
def api_stats():
    """获取统计信息API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify(forwarder.get_stats())

@app.route(f'/{SECURITY_PATH}/api/forwards')
def api_forwards():
    """获取转发列表API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    forwards = forwarder.get_serializable_forwards()
    return jsonify({'forwards': forwards})

@app.route(f'/{SECURITY_PATH}/api/forwards', methods=['POST'])
def api_add_forward():
    """添加转发API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        protocol = request.form.get('protocol')
        local_port = int(request.form.get('local_port'))
        remote_host = request.form.get('remote_host')
        remote_port = int(request.form.get('remote_port'))
        
        # 验证输入
        if not all([protocol, local_port, remote_host, remote_port]):
            return jsonify({'success': False, 'error': '请填写所有字段'})
        
        if protocol not in ['tcp', 'udp']:
            return jsonify({'success': False, 'error': '无效的协议'})
        
        if not (1 <= local_port <= 65535) or not (1 <= remote_port <= 65535):
            return jsonify({'success': False, 'error': '端口范围必须在1-65535之间'})
        
        # 检查端口冲突
        for forward in forwarder.active_forwards.values():
            if forward['local_port'] == local_port and forward['protocol'] == protocol.upper():
                return jsonify({'success': False, 'error': f'本地端口 {local_port} 已被占用'})
        
        # 检查端口是否被系统占用
        try:
            import socket
            test_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            test_socket.settimeout(1)
            result = test_socket.connect_ex(('127.0.0.1', local_port))
            test_socket.close()
            if result == 0:
                return jsonify({'success': False, 'error': f'本地端口 {local_port} 已被系统占用'})
        except Exception as e:
            logger.warning(f"Port availability check failed: {e}")
        
        forward_id = forwarder.start_forward(protocol, local_port, remote_host, remote_port)
        
        # 检查启动结果
        if forward_id in forwarder.active_forwards:
            forward_info = forwarder.active_forwards[forward_id]
            if forward_info['status'] == 'error':
                return jsonify({'success': False, 'error': forward_info.get('error', '启动失败')})
        
        return jsonify({'success': True, 'forward_id': forward_id})
        
    except Exception as e:
        logger.error(f"Add forward error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route(f'/{SECURITY_PATH}/api/forwards/batch', methods=['POST'])
def api_batch_add_forwards():
    """批量添加转发API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        if not data or 'forwards' not in data:
            return jsonify({'success': False, 'error': '请提供转发配置列表'})
        
        forwards_config = data['forwards']
        results = []
        success_count = 0
        
        for config in forwards_config:
            try:
                protocol = config.get('protocol')
                local_port = int(config.get('local_port'))
                remote_host = config.get('remote_host')
                remote_port = int(config.get('remote_port'))
                
                # 验证输入
                if not all([protocol, local_port, remote_host, remote_port]):
                    results.append({
                        'config': config,
                        'success': False,
                        'error': '请填写所有字段'
                    })
                    continue
                
                if protocol not in ['tcp', 'udp']:
                    results.append({
                        'config': config,
                        'success': False,
                        'error': '无效的协议'
                    })
                    continue
                
                if not (1 <= local_port <= 65535) or not (1 <= remote_port <= 65535):
                    results.append({
                        'config': config,
                        'success': False,
                        'error': '端口范围必须在1-65535之间'
                    })
                    continue
                
                # 检查端口冲突
                port_conflict = False
                for forward in forwarder.active_forwards.values():
                    if forward['local_port'] == local_port and forward['protocol'] == protocol.upper():
                        results.append({
                            'config': config,
                            'success': False,
                            'error': f'本地端口 {local_port} 已被占用'
                        })
                        port_conflict = True
                        break
                
                if port_conflict:
                    continue
                
                forward_id = forwarder.start_forward(protocol, local_port, remote_host, remote_port)
                results.append({
                    'config': config,
                    'success': True,
                    'forward_id': forward_id
                })
                success_count += 1
                
            except Exception as e:
                results.append({
                    'config': config,
                    'success': False,
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'total': len(forwards_config),
            'success_count': success_count,
            'failed_count': len(forwards_config) - success_count,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Batch add forwards error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route(f'/{SECURITY_PATH}/api/forwards/batch', methods=['DELETE'])
def api_batch_stop_forwards():
    """批量停止转发API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        data = request.get_json()
        forward_ids = data.get('forward_ids', [])
        
        if not forward_ids:
            return jsonify({'success': False, 'error': '请提供要停止的转发ID列表'})
        
        results = []
        success_count = 0
        
        for forward_id in forward_ids:
            success = forwarder.stop_forward(forward_id)
            results.append({
                'forward_id': forward_id,
                'success': success
            })
            if success:
                success_count += 1
        
        return jsonify({
            'success': True,
            'total': len(forward_ids),
            'success_count': success_count,
            'failed_count': len(forward_ids) - success_count,
            'results': results
        })
        
    except Exception as e:
        logger.error(f"Batch stop forwards error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route(f'/{SECURITY_PATH}/api/forwards/<forward_id>', methods=['DELETE'])
def api_stop_forward(forward_id):
    """停止转发API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    success = forwarder.stop_forward(forward_id)
    return jsonify({'success': success})

@app.route(f'/{SECURITY_PATH}/api/security/status')
def api_security_status():
    """获取安全状态API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    return jsonify({
        'blocked_ips': len(security_manager.blocked_ips),
        'failed_attempts': len(security_manager.failed_attempts),
        'scanner_detections': len(security_manager.scanner_detection),
        'honeypot_hits': len(security_manager.honeypot_hits),
        'security_path': SECURITY_PATH,
        'config_loaded': config_manager.config_file.exists(),
        'config_file': str(config_manager.config_file)
    })

@app.route(f'/{SECURITY_PATH}/api/config/reload', methods=['POST'])
def api_reload_config():
    """重新加载配置API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        reload_config()
        
        return jsonify({
            'success': True,
            'message': '配置已重新加载',
            'config_loaded': config_manager.config_file.exists(),
            'security_path': SECURITY_PATH,
            'admin_path': ADMIN_PATH
        })
    except Exception as e:
        logger.error(f"Config reload error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route(f'/{SECURITY_PATH}/api/persistence/status')
def api_persistence_status():
    """获取持久化状态API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # 检查数据文件状态
        forwards_exists = persistence_manager.forwards_file.exists()
        stats_exists = persistence_manager.stats_file.exists()
        security_exists = persistence_manager.security_file.exists()
        
        # 获取文件大小
        forwards_size = persistence_manager.forwards_file.stat().st_size if forwards_exists else 0
        stats_size = persistence_manager.stats_file.stat().st_size if stats_exists else 0
        security_size = persistence_manager.security_file.stat().st_size if security_exists else 0
        
        # 获取备份文件数量
        backup_count = len(list(persistence_manager.backup_dir.glob("*_backup_*")))
        
        return jsonify({
            'success': True,
            'data': {
                'forwards_file': {
                    'exists': forwards_exists,
                    'size': forwards_size,
                    'path': str(persistence_manager.forwards_file)
                },
                'stats_file': {
                    'exists': stats_exists,
                    'size': stats_size,
                    'path': str(persistence_manager.stats_file)
                },
                'security_file': {
                    'exists': security_exists,
                    'size': security_size,
                    'path': str(persistence_manager.security_file)
                },
                'backup_count': backup_count,
                'data_dir': str(persistence_manager.data_dir),
                'backup_dir': str(persistence_manager.backup_dir),
                'auto_save_interval': persistence_manager.auto_save_interval
            }
        })
    except Exception as e:
        logger.error(f"Persistence status error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route(f'/{SECURITY_PATH}/api/persistence/save', methods=['POST'])
def api_manual_save():
    """手动保存数据API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # 重置变更标志
        persistence_manager.data_changed = False
        
        # 手动保存所有数据
        forwards_saved = persistence_manager.save_forwards(forwarder.active_forwards)
        stats_saved = persistence_manager.save_stats(forwarder.stats)
        security_saved = persistence_manager.save_security_data(security_manager)
        
        # 清理旧备份
        persistence_manager.cleanup_old_backups()
        
        # 检查是否有实际保存
        if persistence_manager.data_changed:
            message = '数据已手动保存'
        else:
            message = '数据无变更，无需保存'
        
        return jsonify({
            'success': True,
            'message': message,
            'data_changed': persistence_manager.data_changed,
            'results': {
                'forwards_saved': forwards_saved,
                'stats_saved': stats_saved,
                'security_saved': security_saved
            }
        })
    except Exception as e:
        logger.error(f"Manual save error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route(f'/{SECURITY_PATH}/api/persistence/restore', methods=['POST'])
def api_restore_data():
    """恢复数据API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # 重新加载数据
        forwarder.active_forwards = persistence_manager.load_forwards()
        forwarder.stats = persistence_manager.load_stats()
        persistence_manager.load_security_data(security_manager)
        
        return jsonify({
            'success': True,
            'message': '数据已重新加载',
            'data': {
                'forwards_count': len(forwarder.active_forwards),
                'stats_loaded': True,
                'security_loaded': True
            }
        })
    except Exception as e:
        logger.error(f"Restore data error: {e}")
        return jsonify({'success': False, 'error': str(e)})

@app.route(f'/{SECURITY_PATH}/api/persistence/changes')
def api_check_changes():
    """检查数据变更状态API"""
    if not session.get('logged_in'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        # 检查各类型数据是否有变更
        forwards_changed = persistence_manager._check_forwards_changed(forwarder.active_forwards)
        stats_changed = persistence_manager._check_stats_changed(forwarder.stats)
        security_changed = persistence_manager._check_security_changed(security_manager)
        
        has_changes = forwards_changed or stats_changed or security_changed
        
        return jsonify({
            'success': True,
            'has_changes': has_changes,
            'changes': {
                'forwards_changed': forwards_changed,
                'stats_changed': stats_changed,
                'security_changed': security_changed
            },
            'last_save_time': persistence_manager.last_save_time,
            'auto_save_interval': persistence_manager.auto_save_interval
        })
    except Exception as e:
        logger.error(f"Check changes error: {e}")
        return jsonify({'success': False, 'error': str(e)})

def signal_handler(signum, frame):
    """信号处理器"""
    logger.info("Shutting down gracefully...")
    forwarder.running = False
    sys.exit(0)

def auto_save_thread():
    """自动保存后台线程"""
    while forwarder.running:
        try:
            time.sleep(30)  # 每30秒保存一次
            if forwarder.running:
                persistence_manager.auto_save(forwarder, security_manager)
                persistence_manager.cleanup_old_backups()
        except Exception as e:
            logger.error(f"自动保存线程错误: {e}")

def get_public_ip():
    """获取公网IP地址"""
    try:
        import urllib.request
        with urllib.request.urlopen('http://ip.42.pl/raw', timeout=5) as response:
            return response.read().decode('utf-8').strip()
    except:
        try:
            with urllib.request.urlopen('http://ifconfig.me', timeout=5) as response:
                return response.read().decode('utf-8').strip()
        except:
            return None

def main():
    """主函数"""
    # 注册信号处理器
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("=" * 60)
    print("专业端口转发工具启动中...")
    print("=" * 60)
    
    # 获取公网IP
    public_ip = get_public_ip()
    
    # 显示配置信息
    if config_manager.config_file.exists():
        print(f"配置文件: {config_manager.config_file}")
        
        # 读取配置文件内容检查是否包含自动生成的配置
        try:
            config_content = config_manager.config_file.read_text(encoding='utf-8')
            if "自动生成" in config_content:
                print(f"状态: 首次运行自动生成配置")
            else:
                print(f"状态: 用户自定义配置")
        except:
            print(f"状态: 配置已加载")
            
        print(f"密码: 从配置文件加载")
        print(f"安全路径: /{SECURITY_PATH}")
    else:
        print(f"配置文件: {config_manager.config_file} [创建失败]")
        print(f"密码: 随机生成")
        print(f"安全路径: /{SECURITY_PATH}")
    
    # 显示访问地址
    if public_ip:
        print(f"管理界面: http://{public_ip}:5000{ADMIN_PATH}")
        print(f"本地访问: http://localhost:5000{ADMIN_PATH}")
    else:
        print(f"管理界面: http://localhost:5000{ADMIN_PATH}")
        print(f"公网访问: 请手动替换IP地址")
    
    print(f"访问路径: /{SECURITY_PATH}/admin")
    print(f"日志文件: port_forwarder.log")
    print("=" * 60)
    print("持久化功能:")
    print(f"  • 转发配置自动保存和恢复")
    print(f"  • 统计数据持久化存储")
    print(f"  • 安全记录持久化保护")
    print(f"  • 自动备份和清理机制")
    print(f"  • 数据目录: data/")
    print("=" * 60)
    print("安全功能:")
    print(f"  • 自动生成随机密码和路径")
    print(f"  • 配置文件热重载支持")
    print(f"  • 蜜罐陷阱防扫描")
    print(f"  • IP自动封禁保护")
    print(f"  • User-Agent检测")
    print(f"  • 路径访问监控")
    print("=" * 60)
    print("配置文件操作:")
    print("  • 查看配置: cat password.txt")
    print("  • 修改配置: 编辑 password.txt")
    print("  • 重新生成: 删除 password.txt 后重启")
    print("  • 热重载: Web界面点击重新加载配置")
    print("=" * 60)
    print("持久化数据操作:")
    print("  • 查看转发配置: cat data/forwards.json")
    print("  • 查看统计数据: cat data/stats.json")
    print("  • 备份数据: cp -r data/ data_backup/")
    print("  • 清理数据: rm -rf data/")
    print("=" * 60)
    
    # 启动自动保存线程
    save_thread = threading.Thread(target=auto_save_thread, daemon=True)
    save_thread.start()
    logger.info("自动保存线程已启动")
    
    try:
        app.run(
            host='0.0.0.0',
            port=5000,
            debug=False,
            threaded=True
        )
    except KeyboardInterrupt:
        logger.info("Application stopped by user")
    except Exception as e:
        logger.error(f"Application error: {e}")
    finally:
        # 程序退出前保存所有数据
        logger.info("正在保存数据...")
        forwarder.save_data()
        security_manager.save_data()
        forwarder.running = False

if __name__ == '__main__':
    main()
