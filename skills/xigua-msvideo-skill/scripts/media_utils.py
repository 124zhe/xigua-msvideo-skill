"""Shared local media operations; no service calls or environment changes."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temp.replace(path)


def binary(name):
    result = shutil.which(name)
    if not result:
        raise ValueError(f'Executable not found: {name}')
    return str(Path(result).resolve())


def run(args, cwd=None):
    result = subprocess.run([str(a) for a in args], cwd=cwd, capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name} failed: {result.stderr[-4000:]}')
    return result.stdout


def probe(ffprobe, path):
    return json.loads(run([ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', path]))


def decode(ffmpeg, path):
    run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', path, '-f', 'null', '-'])


def packets(ffprobe, path):
    return json.loads(run([ffprobe, '-v', 'error', '-select_streams', 'a:0', '-show_packets',
                          '-show_data_hash', 'sha256', '-show_entries',
                          'packet=pts_time,duration_time,data_hash', '-of', 'json', path]))['packets']


def publish(source, target):
    """Publish without replacing an existing delivery. Temp is on target filesystem."""
    source, target = Path(source), Path(target)
    if target.exists():
        raise FileExistsError(f'Refusing to overwrite {target}')
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + '.publishing')
    shutil.copyfile(source, temp)
    try:
        os.link(temp, target)  # atomic, fails if target already exists
    except OSError:
        # Filesystems without hard links: exclusive creation still avoids overwriting.
        with target.open('xb') as dst:
            try:
                with temp.open('rb') as src:
                    shutil.copyfileobj(src, dst)
            except BaseException:
                dst.close()
                target.unlink()
                raise
    finally:
        temp.unlink(missing_ok=True)


def log(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)
