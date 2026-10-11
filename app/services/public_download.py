"""Bounded public HTTP downloads; validate every redirect and pin the checked IP."""
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urlsplit, urljoin


def public_target(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('图片网址必须是无账号密码的 HTTP/HTTPS 公网地址')
    port = parsed.port or (443 if parsed.scheme == 'https' else 80)
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError('图片网址无法解析')
    for entry in addresses:
        ip = ipaddress.ip_address(entry[4][0])
        if not ip.is_global or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            raise ValueError('不允许从内网或本机地址下载图片，请先导入本地图片')
    return parsed, port, addresses[0][4][0]


def download(url, max_bytes, timeout=20):
    for _ in range(6):
        parsed, port, address = public_target(url)
        if parsed.scheme == 'https':
            connection = http.client.HTTPSConnection(parsed.hostname, port, timeout=timeout, context=ssl.create_default_context())
        else:
            connection = http.client.HTTPConnection(parsed.hostname, port, timeout=timeout)
        # Keep the original hostname for Host/SNI and certificate validation;
        # connect only to the address we validated, never resolve it a second time.
        connection._create_connection = lambda _target, timeout=timeout, source_address=None: socket.create_connection((address, port), timeout, source_address)
        try:
            path = parsed.path or '/'
            if parsed.query: path += '?' + parsed.query
            connection.request('GET', path, headers={'Accept-Encoding': 'identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location: raise ValueError('图片跳转缺少目标地址')
                url = urljoin(url, location)
                continue
            if response.status != 200: raise ValueError('图片下载 HTTP ' + str(response.status))
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes: raise ValueError('图片文件超过大小限制')
            return data
        finally:
            connection.close()
    raise ValueError('图片网址跳转次数过多')
