import os
import queue
import threading
import time
import docker
from jinja2 import Template
from loguru import logger

COREFILE_PATH = '/etc/coredns/Corefile'

client = None
update_queue = queue.Queue()


def init_docker_client():
    global client
    try:
        client = docker.from_env()
        client.ping()
        logger.info('Docker клиент инициализирован')
        return True
    except Exception as e:
        logger.error(f'Ошибка инициализации Docker клиента: {str(e)}')
        return False


def get_server_ip():
    env_ip = os.getenv('DNS_BIND_IP')
    if env_ip:
        logger.info(f'DNS_BIND_IP: {env_ip}')
        return env_ip
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '0.0.0.0'


def render_configs(network_views, bind_ip):
    with open('/app/templates/Corefile.j2') as f:
        template = Template(f.read())
    
    corefile_content = template.render(network_views=network_views, bind_ip=bind_ip)
    
    os.makedirs(os.path.dirname(COREFILE_PATH), exist_ok=True)
    with open(COREFILE_PATH, 'w') as f:
        f.write(corefile_content)
        
    os.makedirs('/etc/coredns/zones', exist_ok=True)
    
    for net_name, net_data in network_views.items():
        hosts_file_path = f'/etc/coredns/zones/{net_name}.hosts'
        
        lines = []
        for ip, domain in net_data['hosts']:
            lines.append(f'{ip} {domain}\n')
            
        with open(hosts_file_path, 'w') as f:
            f.writelines(lines)
            
    logger.info('Все конфигурационные файлы и файлы зон успешно обновлены.')


def rebuild_coredns_config():
    logger.info('Начал сканировать контейнеры...')
    if client is None:
        logger.error('Docker клиент не инициализирован')
        return

    try:
        containers = client.containers.list()
    except Exception as e:
        logger.error(f'Ошибка получения списка контейнеров: {str(e)}')
        return

    network_views = {}
    network_cache = {}

    for container in containers:
        labels = container.labels
        custom_dns = labels.get('custom_dns')
        
        if not custom_dns:
            continue
            
        networks = container.attrs.get('NetworkSettings', {}).get('Networks', {})
        if not networks:
            continue
            
        for net_name, net_info in networks.items():
            ip = net_info.get('IPAddress')
            if not ip:
                continue
                
            if net_name not in network_cache:
                try:
                    net_attrs = client.networks.get(net_name).attrs
                    ipam_config = net_attrs.get('IPAM', {}).get('Config', [])
                    subnet = next((cfg.get('Subnet') for cfg in ipam_config if cfg.get('Subnet') and '.' in cfg.get('Subnet')), None)
                    if subnet:
                        network_cache[net_name] = subnet
                except Exception as e:
                    logger.error(f'Ошибка получения CIDR для сети {net_name}: {str(e)}')
                    continue
            
            subnet = network_cache.get(net_name)
            if not subnet:
                continue
            
            
            if net_name not in network_views:
                network_views[net_name] = {'subnets': [], 'hosts': []}
            
            if subnet not in network_views[net_name]['subnets']:
                network_views[net_name]['subnets'].append(subnet)
            
            host_record = (ip, custom_dns)
            if host_record not in network_views[net_name]['hosts']:
                network_views[net_name]['hosts'].append(host_record)

    bind_ip = get_server_ip()
    render_configs(network_views, bind_ip)


def worker():
    while True:
        item = update_queue.get()
        if item is None:
            break
            
        time.sleep(0.5)
        
        while not update_queue.empty():
            try:
                update_queue.get_nowait()
                update_queue.task_done()
            except queue.Empty:
                break
                
        rebuild_coredns_config()
        update_queue.task_done()


def listen_events():
    filters = {
        'event': ['start', 'die', 'destroy'],
        'type': 'container',
        'label': ['custom_dns']
    }
    
    while True:
        try:
            logger.info('Подключение к Docker API Event Stream...')
            event_generator = client.events(decode=True, filters=filters)
            for event in event_generator:
                update_queue.put('rebuild')
        except Exception as e:
            logger.error(f'Потеряно соединение с Docker: {str(e)}. Переподключение через 3 секунды...')
            time.sleep(3)


if __name__ == '__main__':
    worker_thread = threading.Thread(target=worker, daemon=True)
    worker_thread.start()
    
    if init_docker_client():
        update_queue.put('initial')
        listen_events()
