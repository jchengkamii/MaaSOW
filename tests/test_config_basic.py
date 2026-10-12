"""基础配置检查，不连接游戏或下载运行库。"""
import importlib
import json
from pathlib import Path
import unittest
from agent.core import CaseLoader, PROJECT_DIR
from generate_interface import generate


class ConfigurationBasicTests(unittest.TestCase):
    def test_tasks_load_and_python_entries_exist(self):
        cases=CaseLoader().load()
        self.assertTrue(cases)
        self.assertEqual(len(cases),len({case.id for case in cases}))
        for case in cases:
            if case.handler == 'python':
                module,name=case.extension.split(':')
                self.assertTrue(callable(getattr(importlib.import_module(module),name)))

    def test_interface_contains_enabled_tasks(self):
        interface=json.loads((PROJECT_DIR/'interface.json').read_text(encoding='utf-8'))
        self.assertEqual(2,interface['interface_version'])
        generated=generate()
        self.assertEqual([c.id for c in CaseLoader().load() if c.enabled],
                         [task['name'] for task in generated['task']])

    def test_rally_defaults_and_queue_configuration(self):
        cases={c.id:c for c in CaseLoader().load()}
        self.assertEqual(1,cases['auto_ling_er'].parameters['rally_level'])
        self.assertEqual([1],cases['auto_ling_er'].parameters['rally_queues'])
        self.assertTrue(cases['auto_ling_er'].auto_stamina)
        options=generate()['option']
        self.assertEqual(['1'],options['玲儿集结队列']['default_case'])
        self.assertEqual(['1','2','3','4'],options['貔貅出征队列']['default_case'])


if __name__ == '__main__':
    unittest.main()
