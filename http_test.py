"""
本开源压力测试工具仅用于在合法授权下对自有 / 获许可系统进行性能测试，
旨在优化系统；使用前须确保获得测试授权，不得用于未授权测试或违法活动，
因不当使用导致的法律责任、损失及测试风险（如系统故障、结果偏差）均由
使用者自行承担，开发者不对工具提供任何担保，亦不承担间接损失责任；使
用即视为同意本声明，二次开发 / 传播需保留此内容。
"""


import time
import socket
import threading
import struct
import argparse
import logging
import json
from concurrent.futures import ThreadPoolExecutor
from statistics import mean, median, stdev

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MinecraftServerTester:
    
    def __init__(self, host, port=25565, concurrency=10, connections_per_client=10, timeout=5):
        # 初始化信息
        self.host = host
        self.port = port
        self.concurrency = concurrency
        self.connections_per_client = connections_per_client
        self.timeout = timeout
        self.results = []
        self.success_count = 0
        self.failure_count = 0
        self.total_time = 0
        self.lock = threading.Lock()
    
    def _send_handshake(self, sock):
        # 发送握手包
        # Minecraft协议版本（当前763相当于1.20.1）
        protocol_version = 763
        host_length = len(self.host)
        packet = bytearray()
        packet.extend(self._varint_to_bytes(7 + host_length))
        packet.extend(self._varint_to_bytes(0x00))
        packet.extend(self._varint_to_bytes(protocol_version))
        packet.extend(self._varint_to_bytes(host_length))
        packet.extend(self.host.encode('utf-8'))
        packet.extend(struct.pack('>H', self.port))
        packet.extend(self._varint_to_bytes(1))
        sock.sendall(packet)
    
    def _request_status(self, sock):
        # 请求服务器状态
        # 构建状态请求包
        packet = bytearray()
        packet.extend(self._varint_to_bytes(1))  # 包长度
        packet.extend(self._varint_to_bytes(0x00))  # 包ID
        # 发送状态请求包
        sock.sendall(packet)
    
    def _read_varint(self, sock):
        data = 0
        for i in range(5):
            b = sock.recv(1)
            if not b:
                raise Exception("连接断开")
            byte = b[0]
            data |= (byte & 0x7F) << (7 * i)
            if not (byte & 0x80):
                return data
        raise Exception("VarInt太长")
    
    def _read_response(self, sock):
        # 读取服务器响应
        # 读取包长度
        packet_length = self._read_varint(sock)
        # 读取包ID
        packet_id = self._read_varint(sock)
        if packet_id != 0:
            raise Exception(f"预期包ID 0，得到 {packet_id}")
        length = self._read_varint(sock)
        json_data = b""
        while len(json_data) < length:
            chunk = sock.recv(length - len(json_data))
            if not chunk:
                raise Exception("连接断开")
            json_data += chunk
        return json.loads(json_data.decode('utf-8'))
    
    def _varint_to_bytes(self, value):
        result = bytearray()
        while True:
            temp = value & 0x7F
            value >>= 7
            if value != 0:
                temp |= 0x80
            result.append(temp)
            if value == 0:
                break
        return result
    
    def _test_connection(self):
        # 测试与服务器的连接并获取状态
        start_time = time.time()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(self.timeout)
                # 连接服务器
                connect_start = time.time()
                sock.connect((self.host, self.port))
                connect_time = time.time() - connect_start
                
                # 发送握手包
                self._send_handshake(sock)
                # 请求状态
                self._request_status(sock)
                # 读取响应
                response = self._read_response(sock)
                
                elapsed = time.time() - start_time
                
                with self.lock:
                    self.success_count += 1
                    self.results.append({
                        'success': True,
                        'connect_time': connect_time,
                        'response_time': elapsed - connect_time,
                        'total_time': elapsed,
                        'players_online': response.get('players', {}).get('online', 0),
                        'players_max': response.get('players', {}).get('max', 0),
                        'version': response.get('version', {}).get('name', 'Unknown'),
                        'motd': response.get('description', 'Unknown')
                    })
                    self.total_time += elapsed
                
                return {
                    'success': True,
                    'connect_time': connect_time,
                    'response_time': elapsed - connect_time,
                    'total_time': elapsed,
                    'players_online': response.get('players', {}).get('online', 0),
                    'players_max': response.get('players', {}).get('max', 0),
                    'version': response.get('version', {}).get('name', 'Unknown'),
                    'motd': response.get('description', 'Unknown')
                }
        except Exception as e:
            elapsed = time.time() - start_time
            with self.lock:
                self.failure_count += 1
                self.results.append({
                    'success': False,
                    'error': str(e),
                    'total_time': elapsed
                })
            return {
                'success': False,
                'error': str(e),
                'total_time': elapsed
            }
    
    def _client_worker(self):
        for _ in range(self.connections_per_client):
            result = self._test_connection()
            if not result['success']:
                logger.warning(f"Connection failed: {result.get('error', 'Unknown error')}")
    
    def run_test(self):
        logger.info(f"Starting Minecraft server test on {self.host}:{self.port}")
        logger.info(f"Concurrency: {self.concurrency}, Connections per client: {self.connections_per_client}")
        
        start_time = time.time()
        
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            for _ in range(self.concurrency):
                executor.submit(self._client_worker)
        
        total_time = time.time() - start_time
        
        # 计算统计数据
        success_results = [r for r in self.results if r['success']]
        
        if success_results:
            connect_times = [r['connect_time'] for r in success_results]
            response_times = [r['response_time'] for r in success_results]
            total_times = [r['total_time'] for r in success_results]
            
            # 计算平均在线玩家数
            avg_players = mean(r['players_online'] for r in success_results)
            
            logger.info("\n===== Test Results =====")
            logger.info(f"Total connections: {self.success_count + self.failure_count}")
            logger.info(f"Successful connections: {self.success_count}")
            logger.info(f"Failed connections: {self.failure_count}")
            logger.info(f"Success rate: {self.success_count / (self.success_count + self.failure_count) * 100:.2f}%")
            logger.info(f"Total test time: {total_time:.2f} seconds")
            logger.info("\n=== Connection Statistics ===")
            logger.info(f"Min connect time: {min(connect_times):.4f}s")
            logger.info(f"Max connect time: {max(connect_times):.4f}s")
            logger.info(f"Average connect time: {mean(connect_times):.4f}s")
            logger.info(f"Median connect time: {median(connect_times):.4f}s")
            logger.info(f"Standard deviation: {stdev(connect_times):.4f}s" if len(connect_times) > 1 else "Standard deviation: N/A")
            logger.info("\n=== Response Statistics ===")
            logger.info(f"Min response time: {min(response_times):.4f}s")
            logger.info(f"Max response time: {max(response_times):.4f}s")
            logger.info(f"Average response time: {mean(response_times):.4f}s")
            logger.info(f"Median response time: {median(response_times):.4f}s")
            logger.info(f"Standard deviation: {stdev(response_times):.4f}s" if len(response_times) > 1 else "Standard deviation: N/A")
            logger.info("\n=== Server Information ===")
            logger.info(f"Average players online: {avg_players:.1f}")
            logger.info(f"Server version: {success_results[0]['version']}")
            logger.info(f"MOTD: {success_results[0]['motd']}")
            
            if self.failure_count == 0 and mean(response_times) < 0.2:
                summary = f"压力测试显示，服务器在{self.concurrency}并发连接下表现优异，成功率100%，平均响应时间{mean(response_times):.2f}秒，展现出出色的稳定性和处理能力。"
            elif self.failure_count < 0.05 * (self.success_count + self.failure_count) and mean(response_times) < 0.5:
                summary = f"压力测试显示，服务器在{self.concurrency}并发连接下表现良好，成功率{(self.success_count / (self.success_count + self.failure_count) * 100):.2f}%，平均响应时间{mean(response_times):.2f}秒，可稳定应对当前负载。"
            elif mean(response_times) >= 1 or self.failure_count > 0.1 * (self.success_count + self.failure_count):
                summary = f"压力测试显示，服务器在{self.concurrency}并发连接下出现明显压力，成功率{(self.success_count / (self.success_count + self.failure_count) * 100):.2f}%，平均响应时间{mean(response_times):.2f}秒，建议优化服务器配置或增加硬件资源。"
            else:
                summary = f"压力测试显示，服务器在{self.concurrency}并发连接下表现一般，成功率{(self.success_count / (self.success_count + self.failure_count) * 100):.2f}%，平均响应时间{mean(response_times):.2f}秒，存在一定优化空间。"
            
            logger.info(f"\n=== 测试总结 ===")
            logger.info(summary)
        else:
            logger.error("No successful connections were made. The server might be offline or unreachable.")

def get_valid_input(prompt, default=None, validation_func=None):
    # 用户输入部分
    while True:
        user_input = input(prompt).strip()
        if not user_input and default is not None:
            return default
        
        if validation_func:
            try:
                valid = validation_func(user_input)
                if valid:
                    return user_input
                else:
                    print("输入无效，请重试。")
            except Exception as e:
                print(f"输入错误: {e}，请重试。")
        else:
            return user_input

def validate_ip(ip):
    # 验证IP地址格式
    parts = ip.split('.')
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit():
            return False
        num = int(part)
        if num < 0 or num > 255:
            return False
    return True

def validate_port(port):
    # 验证端口号
    try:
        port_num = int(port)
        if 1 <= port_num <= 65535:
            return True
        else:
            print("端口号必须在1-65535之间。")
            return False
    except ValueError:
        print("端口号必须是整数。")
        return False

def validate_positive_integer(value):
    # 验证正整数
    try:
        num = int(value)
        if num > 0:
            return True
        else:
            print("请输入大于0的整数。")
            return False
    except ValueError:
        print("请输入有效的整数。")
        return False

def main():
    print("=" * 50)
    print("Minecraft服务器性能测试工具")
    print("=" * 50)
    
    # 获取用户输入
    host = get_valid_input("请输入服务器IP地址 [默认: 127.0.0.1]: ", 
                          default="127.0.0.1", 
                          validation_func=validate_ip)
    
    port = get_valid_input("请输入服务器端口 [默认: 25565]: ", 
                          default="25565", 
                          validation_func=validate_port)
    port = int(port)
    
    concurrency = get_valid_input("请输入并发连接数 [默认: 50]: ", 
                                 default="50", 
                                 validation_func=validate_positive_integer)
    concurrency = int(concurrency)
    
    connections_per_client = get_valid_input("请输入每个客户端的连接数 [默认: 20]: ", 
                                            default="20", 
                                            validation_func=validate_positive_integer)
    connections_per_client = int(connections_per_client)
    
    timeout = get_valid_input("请输入连接超时时间(秒) [默认: 10]: ", 
                             default="10", 
                             validation_func=validate_positive_integer)
    timeout = int(timeout)
    
    print("\n" + "=" * 50)
    print(f"测试配置:")
    print(f"服务器: {host}:{port}")
    print(f"并发连接数: {concurrency}")
    print(f"每个客户端连接数: {connections_per_client}")
    print(f"总请求数: {concurrency * connections_per_client}")
    print(f"超时时间: {timeout}秒")
    print("=" * 50)
    
    confirm = input("是否开始测试? (y/n): ").strip().lower()
    if confirm != 'y':
        print("测试已取消。")
        return
    
    tester = MinecraftServerTester(
        host=host,
        port=port,
        concurrency=concurrency,
        connections_per_client=connections_per_client,
        timeout=timeout
    )
    
    tester.run_test()

if __name__ == "__main__":
    main()