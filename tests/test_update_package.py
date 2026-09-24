from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from tools.build_distribution import build_package


class UpdatePackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'source'
        for name in ('agent/main.py', 'agent/__pycache__/main.pyc',
                     'resource/base/pipeline/test.json', 'resource/tasks/task.json',
                     'resource/interface.tasks.json', 'maafw/runtime.dll', 'licenses/MXU-LICENSE.txt',
                     'config/mxu-MaaSOW.json', '.runtime/python/python.exe', 'debug/private.log',
                     'tools/prepare_environment.ps1', 'tools/check_environment.py',
                     'tools/DISTRIBUTION_README.md', 'tools/prepare_mxu.py', 'tools/AUTO_UPDATE.md',
                     'tools/mxu/mainUpdate.ts', 'generate_interface.py', 'requirements.txt',
                     '使用前环境准备.bat', '九霄小助手.exe'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture', encoding='utf-8')
        (self.root / 'interface.json').write_text(json.dumps({'version': '1.0.1', 'name': 'MaaSOW'}), encoding='utf-8')
        self.output = Path(self.temporary.name) / 'dist'

    def test_scripts_archive_is_rooted_for_mxu_and_preserves_machine_state(self):
        archive = build_package(self.root, self.output, '1.1.9', scripts_only=True)
        self.assertEqual('MaaSOW-scripts-win-x86_64-v1.1.9.zip', archive.name)
        with zipfile.ZipFile(archive) as package:
            names = set(package.namelist())
            self.assertIn('agent/main.py', names)
            self.assertIn('resource/interface.tasks.json', names)
            self.assertEqual('1.1.9', json.loads(package.read('interface.json'))['version'])
            self.assertFalse(any(name.startswith(('config/', '.runtime/', 'debug/', 'maafw/', 'licenses/')) for name in names))
            self.assertNotIn('九霄小助手.exe', names)
            self.assertNotIn('agent/__pycache__/main.pyc', names)
        self.assertEqual('1.0.1', json.loads((self.root / 'interface.json').read_text())['version'])

    def test_full_distribution_contains_frontend_and_framework(self):
        archive = build_package(self.root, self.output, '1.1.9')
        with zipfile.ZipFile(archive) as package:
            self.assertIn('九霄小助手.exe', package.namelist())
            self.assertIn('maafw/runtime.dll', package.namelist())
            self.assertIn('interface.json', package.namelist())
            self.assertIn('mxu-source/tools/prepare_mxu.py', package.namelist())

    def test_invalid_version_cannot_form_output_path(self):
        for version in ('../oops', '1.2', 'v1.2.3', '1.2.3-dev', '01.2.3'):
            with self.subTest(version=version), self.assertRaises(ValueError):
                build_package(self.root, self.output, version)


if __name__ == '__main__':
    unittest.main()
