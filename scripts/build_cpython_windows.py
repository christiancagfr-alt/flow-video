"""Build the approved CPython security release from verified upstream source."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

VERSION = '3.13.18'
SOURCE_SHA256 = 'abb0102e6d4ae027509bcb82327d9dd85515b44a3ba8ad538cfc5e9847029f68'
SOURCE_URL = f'https://www.python.org/ftp/python/{VERSION}/Python-{VERSION}.tar.xz'
ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build'


def build():
    if sys.platform != 'win32':
        raise RuntimeError('CPython Windows runtime must be built on Windows with MSVC')
    downloads = BUILD / 'downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    source_archive = downloads / f'Python-{VERSION}.tar.xz'
    if not source_archive.exists():
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
            source_archive.write_bytes(response.read())
    if hashlib.sha256(source_archive.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise ValueError('CPython source checksum mismatch')
    source = BUILD / f'Python-{VERSION}'
    if not source.exists():
        with tarfile.open(source_archive) as archive:
            archive.extractall(BUILD, filter='data')
    log_dir = ROOT / 'audit'
    log_dir.mkdir(exist_ok=True)
    command = ['cmd.exe', '/d', '/c', str(source / 'PCbuild/build.bat'),
               '-p', 'x64', '-c', 'Release', '--no-tkinter']
    print('Building verified CPython', VERSION, flush=True)
    with (log_dir / 'cpython-build.log').open('w', encoding='utf-8') as log:
        subprocess.run(command, cwd=source, check=True, stdout=log, stderr=subprocess.STDOUT)
    python = source / 'PCbuild/amd64/python.exe'
    tests = ['test_ssl', 'test_pyexpat', 'test_xml_etree', 'test_tarfile',
             'test_mimetypes', 'test_tempfile', 'test_http_cookiejar', 'test_sqlite3']
    print('Running CPython security-boundary regression', flush=True)
    with (log_dir / 'cpython-tests.log').open('w', encoding='utf-8') as log:
        subprocess.run([str(python), '-m', 'test', '-j', '2', '--timeout', '180', *tests],
                       cwd=source, check=True, stdout=log, stderr=subprocess.STDOUT)
    output = downloads / f'python-{VERSION}-embed-amd64.zip'
    subprocess.run([str(python), str(source / 'PC/layout'), '--preset-embed',
                    '--source', str(source), '--build', str(python.parent),
                    '--temp', str(BUILD / 'cpython-layout-temp'), '--zip', str(output)],
                   cwd=source, check=True)
    with zipfile.ZipFile(output) as archive:
        for required in ('python.exe', 'pythonw.exe', 'python313.dll', 'python313.zip', '_ssl.pyd', 'pyexpat.pyd'):
            if required not in archive.namelist():
                raise RuntimeError('Incomplete CPython runtime: ' + required)
    manifest = {'python': VERSION, 'source_url': SOURCE_URL, 'source_sha256': SOURCE_SHA256,
                'runtime_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'build': 'MSVC x64 Release; upstream PCbuild and PC/layout --preset-embed',
                'regression_modules': tests}
    (log_dir / 'cpython-build-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return output, manifest


if __name__ == '__main__':
    build()
