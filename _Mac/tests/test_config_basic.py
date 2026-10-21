"""基础配置检查，不连接游戏或下载运行库。"""
import importlib
import json
from pathlib import Path
import unittest
from agent.core import CaseLoader, PROJECT_DIR
from generate_interface import generate


class ConfigurationBasicTests(unittest.TestCase):
    def test_package_version_follows_stable_git_tags(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from tools.build_distribution import resolve_version
        tags = ("a refs/tags/v1.1.9\n"
                "b refs/tags/v1.1.12\n"
                "c refs/tags/v1.1.13-beta.1\n"
                "d refs/tags/v1.1.12^{}\n")
        with patch("tools.build_distribution.subprocess.run",
                   return_value=SimpleNamespace(stdout=tags)):
            self.assertEqual("1.1.12", resolve_version())
        self.assertEqual("1.1.12", resolve_version("v1.1.12"))

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

    def test_stamina_checks_all_sources_and_keeps_actions_on_item_row(self):
        import re
        nodes=json.loads((PROJECT_DIR/'resource/base/pipeline/Common/AutoStamina.json').read_text(encoding='utf-8'))
        after_scroll=nodes['通用自动补体向下查找100体力']['next']
        self.assertEqual([f'通用自动补体向下后查找{n}体力' for n in (10,50,100)],after_scroll[:-1])
        for prefix in ('通用自动补体','通用自动补体向下后'):
            batch=nodes[f'{prefix}批量使用50体力']
            self.assertLessEqual(batch['threshold'],0.742651)  # Actual failed x3 recognition.
            self.assertTrue(re.fullmatch(batch['expected'],'×3'))
            self.assertIsNone(re.fullmatch(batch['expected'],'x0'))
            use=nodes[f'{prefix}单次使用50体力']['any_of'][-1]
            self.assertEqual('^使用$',use['expected'])
            self.assertEqual(f'{prefix}查找50体力',use['roi'])
            source=nodes[f'{prefix}查找100体力']
            self.assertEqual(('Vertical',-1),(source['order_by'],source['index']))
            for amount in (10,50,100):
                item=f'{prefix}查找{amount}体力'
                stock=nodes[nodes[item]['next'][0]]
                self.assertEqual(item,stock['roi'])
                self.assertTrue(re.fullmatch(stock['expected'],'拥有：20'))
                for unavailable in ('拥有：0','逍遥剑仙为您提供额外体力'):
                    self.assertIsNone(re.fullmatch(stock['expected'],unavailable))
            # An unavailable intermediate type must still fall through to the rest.
            self.assertIn(f'{prefix}查找100体力',nodes[f'{prefix}查找10体力']['next'])


if __name__ == '__main__':
    unittest.main()
