"""发布入口：安装资源/依赖、部署自检、启动和Daemon生命周期管理。"""
from __future__ import annotations
import argparse,hashlib,json,os,platform,shutil,sqlite3,stat,subprocess,sys,tempfile,zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def safe_members(archive):
    """拒绝路径越界及符号链接，资源包只接受组内校验通过的普通文件。"""
    for info in archive.infolist():
        path=Path(info.filename)
        if path.is_absolute() or '..' in path.parts or '\\' in info.filename or stat.S_ISLNK(info.external_attr>>16):
            raise ValueError('资源包路径不安全：'+info.filename)
        yield info

def place(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():
        if target.is_symlink() or digest(target)!=digest(source):raise ValueError('目标已有不同文件，拒绝覆盖：'+str(target))
        return
    shutil.copyfile(source,target)

def install_resources(bundle,runtime):
    """先在临时目录整包校验，才安装模型/场景；重装仅接受相同字节。"""
    with tempfile.TemporaryDirectory(prefix='.eos-install-',dir=runtime) as temp:
        folder=Path(temp)
        with zipfile.ZipFile(bundle) as archive:
            members=list(safe_members(archive));archive.extractall(folder,members)
        content=folder/'eos-resources'
        manifest=json.loads((content/'manifest.json').read_text(encoding='utf-8'))
        for name,h in manifest['files'].items():
            path=content/name
            if not path.resolve().is_relative_to(content.resolve()) or not path.is_file() or digest(path)!=h:
                raise ValueError('资源哈希不符：'+name)
        for name in manifest['files']:
            path=Path(name)
            if path.parts[0] not in {'models','resources','wheels','datasets'}:raise ValueError('不允许的安装区域')
            if name=='datasets/eos-final-v1.zip':
                with zipfile.ZipFile(content/name) as archive:
                    members=list(safe_members(archive));archive.extractall(folder/'dataset',members)
                data=folder/'dataset/eos-final-v1'
                checks=json.loads((data/'SHA256SUMS.json').read_text(encoding='utf-8'))
                for item,h in checks.items():
                    source=data/item
                    if not source.resolve().is_relative_to(data.resolve()) or digest(source)!=h:raise ValueError('场景包校验失败')
                for source in data.rglob('*'):
                    if source.is_file():place(source,runtime/'datasets/eos-final-v1'/source.relative_to(data))
            else:place(content/name,runtime/name)
        place(content/'manifest.json',runtime/'resources/release-manifest.json')


def default_config(runtime):
    """升级保留旧runtime数据源，避免将另一已登记路径强行写到旧ID上。"""
    scene = 'datasets/eos-final-v1/smoke'
    database = runtime / 'results.sqlite3'
    if database.is_file():
        # 只读旧登记，既不初始化SQLite，也不改已有实验/数据源。
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as conn:
            has_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='data_sources'").fetchone()
            row = conn.execute("SELECT root_path FROM data_sources WHERE source_id='runtime'").fetchone() if has_table else None
        if row:
            location = Path(row[0])
            scene = str(location.relative_to(runtime)) if location.is_relative_to(runtime) else str(location)
    return dict(scenario_dir=scene, orekit_data='resources/orekit-data.zip', port=8765)


def environment(runtime,port):
    config=runtime/'config.json'
    stored=json.loads(config.read_text()) if config.exists() else {}
    # 使用相对运行根目录，迁移整包后不保留原机器绝对路径。
    def location(key,fallback):
        value=Path(stored.get(key,fallback)).expanduser()
        return str(value if value.is_absolute() else runtime/value)
    return {**os.environ,'EOS_RUNTIME_DIR':str(runtime),
        'EOS_SCENARIO_DIR':os.environ.get('EOS_SCENARIO_DIR',location('scenario_dir','datasets/eos-final-v1/smoke')),
        'EOS_OREKIT_DATA':os.environ.get('EOS_OREKIT_DATA',location('orekit_data','resources/orekit-data.zip')),
        'EOS_PORT':str(port if port is not None else os.environ.get('EOS_PORT',stored.get('port',8765))), 'PYTHONHASHSEED':os.environ.get('PYTHONHASHSEED','42'),
        **{k:os.environ.get(k,'1') for k in ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS']}}

def doctor(runtime,env):
    """只读检查数据、模型及数值库；不新建实验、不触碰已有数据库。"""
    sys.path.insert(0,str(ROOT));os.environ.update(env)
    from importlib import metadata
    from eos_system.algorithm_registry import list_algorithms
    from algorithms.lavis.model import list_models
    from eos_system.dataset_registry import entries
    import fastapi,uvicorn,numpy,orekit_jpype
    data=Path(env['EOS_SCENARIO_DIR']);orekit=Path(env['EOS_OREKIT_DATA'])
    if not orekit.is_file() or not zipfile.is_zipfile(orekit):raise ValueError('缺少有效Orekit数据ZIP')
    scenes=entries(data)
    if not scenes:raise ValueError('缺少发布联调/正式场景目录')
    # 核对实际场景文件与侧车；不把目录存在当成数据有效。
    from eos_system.provenance import capture_provenance
    for row in scenes:
        path=data/row['path'];actual=digest(path)
        if actual!=row['sha256']:raise ValueError('场景SHA不符')
        capture_provenance(path,actual)
    models=list_models()
    if not any(r['model_id']=='lavis-v4-opportunity' for r in models):raise ValueError('LAVIS v4模型/依赖/源码身份不匹配')
    algorithms=list_algorithms()
    result=dict(status='PASS',python=sys.version.split()[0],platform=platform.platform(),runtime=str(runtime),
        scenarios=len(scenes),models=[r['model_id'] for r in models],
        ready_algorithms=[r['algorithm_id'] for r in algorithms if r['availability']=='ready'],
        unavailable=[dict(id=r['algorithm_id'],reason=r['availability_message']) for r in algorithms if r['availability']!='ready'],
        orekit_sha256=digest(orekit))
    print(json.dumps(result,ensure_ascii=False,indent=2));return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['install','doctor','run','daemon-start','daemon-status','daemon-stop'])
    p.add_argument('--runtime-dir',type=Path,default=Path(os.environ.get('EOS_RUNTIME_DIR','~/eos-course-runtime')))
    p.add_argument('--resources',type=Path);p.add_argument('--offline',action='store_true')
    p.add_argument('--skip-dependencies',action='store_true',help='已有匹配环境时使用，仍执行数据/模型自检')
    p.add_argument('--port',type=int);args=p.parse_args()
    if sys.platform!='linux' or sys.version_info<(3,10):raise ValueError('请在Ubuntu 22.04/WSL2或Linux Python3.10+执行')
    if args.offline and (sys.version_info[:2]!=(3,10) or platform.machine()!='x86_64'):
        raise ValueError('当前离线wheels只支持Linux x86_64 / CPython3.10；其他平台请另建依赖包')
    runtime=args.runtime_dir.expanduser().resolve()
    if runtime==Path('/') or runtime.is_relative_to(Path('/mnt')) or runtime.is_relative_to(ROOT):raise ValueError('运行目录应在Linux文件系统且位于源码目录之外')
    runtime.mkdir(parents=True,exist_ok=True);venv=runtime/'.venv'
    if args.command=='install' and not (venv/'bin/python').is_file():
        subprocess.run([sys.executable,'-m','venv',str(venv)],check=True)
    if Path(sys.prefix).resolve()!=venv.resolve():
        python=venv/'bin/python'
        if not python.is_file():raise ValueError('尚未安装，请先执行 bash eos install --resources <资源包>')
        os.execv(str(python),[str(python),str(Path(__file__).resolve()),*sys.argv[1:]])
    if args.command=='install':
        if args.resources:install_resources(args.resources.expanduser().resolve(),runtime)
        if not args.skip_dependencies:
            command=[sys.executable,'-m','pip','install','-r',str(ROOT/'requirements-release.txt')]
            if args.offline:command+=['--no-index','--find-links',str(runtime/'wheels')]
            subprocess.run(command,check=True)
        for folder in ['resources','datasets','models','artifacts','logs','exports','replays']:(runtime/folder).mkdir(exist_ok=True)
        config=runtime/'config.json'
        if not config.exists():config.write_text(json.dumps(default_config(runtime),indent=2)+'\n')
        print('安装完成；以下为实际部署检查结果')
    env=environment(runtime,args.port)
    if args.command in {'install','doctor'}:doctor(runtime,env);return
    if args.command=='run':command=[sys.executable,'-m','eos_system']
    else:command=[sys.executable,'-m','eos_system.daemon',args.command.split('-')[1]]
    os.chdir(ROOT);os.execve(sys.executable,command,env)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error:
        print('EOS部署错误：'+str(error),file=sys.stderr);sys.exit(1)
