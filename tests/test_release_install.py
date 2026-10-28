"""部署包路径、既有文件保护和相对运行配置的机制回归。"""
import io,json,sqlite3,stat,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
from ops.eos import safe_members,place,environment,default_config

class InstallTests(unittest.TestCase):
    def test_reject_archive_traversal_and_symlink(self):
        for name in ['../bad','/bad','a/../../bad','a\\bad']:
            stream=io.BytesIO()
            with zipfile.ZipFile(stream,'w') as archive:archive.writestr(name,b'x')
            with zipfile.ZipFile(stream) as archive:
                with self.assertRaises(ValueError):list(safe_members(archive))
        stream=io.BytesIO();info=zipfile.ZipInfo('link');info.external_attr=(stat.S_IFLNK|0o777)<<16
        with zipfile.ZipFile(stream,'w') as archive:archive.writestr(info,b'/outside')
        with zipfile.ZipFile(stream) as archive:
            with self.assertRaises(ValueError):list(safe_members(archive))

    def test_same_file_idempotent_and_different_file_protected(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'a';target=Path(folder)/'b';source.write_bytes(b'original')
            place(source,target);place(source,target)
            source.write_bytes(b'changed')
            with self.assertRaises(ValueError):place(source,target)
            self.assertEqual(target.read_bytes(),b'original')

    def test_upgrade_keeps_existing_default_source_without_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            self.assertEqual(default_config(root)['scenario_dir'],'datasets/eos-final-v1/smoke')
            database=root/'results.sqlite3'
            with sqlite3.connect(database) as conn:
                conn.execute('CREATE TABLE data_sources(source_id TEXT,root_path TEXT)')
                conn.execute('INSERT INTO data_sources VALUES (?,?)',('runtime',str(root/'scenarios')))
                conn.execute('INSERT INTO data_sources VALUES (?,?)',('release-smoke',str(root/'datasets/eos-final-v1/smoke')))
            before=database.read_bytes()
            self.assertEqual(default_config(root)['scenario_dir'],'scenarios')
            self.assertEqual(before,database.read_bytes())

    def test_relative_config_and_port_override(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict('os.environ',{},clear=True):
            root=Path(folder);(root/'config.json').write_text(json.dumps({'scenario_dir':'datasets/eos-final-v1/smoke','port':8766}))
            env=environment(root,None)
            self.assertEqual(env['EOS_SCENARIO_DIR'],str(root/'datasets/eos-final-v1/smoke'))
            self.assertEqual(env['EOS_PORT'],'8766')
            with patch.dict('os.environ',{'EOS_PORT':'8767'}):self.assertEqual(environment(root,None)['EOS_PORT'],'8767')
            self.assertEqual(environment(root,8768)['EOS_PORT'],'8768')

if __name__=='__main__':unittest.main()
