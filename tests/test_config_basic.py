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
        self.assertEqual(generated,json.loads((PROJECT_DIR/'resource/interface.tasks.json').read_text(encoding='utf-8')))

    def test_rally_defaults_and_queue_configuration(self):
        cases={c.id:c for c in CaseLoader().load()}
        self.assertEqual(1,cases['auto_ling_er'].parameters['rally_level'])
        self.assertEqual([1],cases['auto_ling_er'].parameters['rally_queues'])
        self.assertTrue(cases['auto_ling_er'].auto_stamina)
        options=generate()['option']
        self.assertEqual(['1'],options['玲儿集结队列']['default_case'])
        self.assertEqual(['1','2','3','4'],options['貔貅出征队列']['default_case'])
        self.assertEqual({'attack_count':1,'attack_queues':[1]},cases['auto_fu_hu'].parameters)
        self.assertTrue(cases['auto_fu_hu'].auto_stamina)
        self.assertEqual(['1'],options['伏虎出征队列']['default_case'])
        from agent.custom.action.run_configured_case import (
            parse_attack_count, selected_attack_queues, worker_command_with_options)
        from unittest.mock import Mock
        self.assertEqual(2,parse_attack_count('{"case_id":"auto_fu_hu","attack_count":2}'))
        context=Mock()
        context.get_node_data.side_effect=lambda name:{'enabled':name in ('伏虎出征队列1','伏虎出征队列3')}
        self.assertEqual([1,3],selected_attack_queues(context,'伏虎出征队列'))
        context.get_node_data.return_value={}
        context.get_node_data.side_effect=None
        with self.assertRaises(ValueError):
            selected_attack_queues(context,'伏虎出征队列')
        command=worker_command_with_options('auto_fu_hu',True,attack_count=2,attack_queues=[1,3])
        self.assertEqual(['--attack-count','2','--attack-queues','1,3'],command[-4:])
        self.assertIn('--auto-stamina',command)

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

    def test_treatment_help_is_confirmed_before_closing(self):
        from unittest.mock import Mock, patch
        from agent.custom.action.auto_treatment import auto_treatment_cycle as flow
        for failure in (None, 'help', 'main', 'exit_before', 'exit_during', 'outside'):
            with self.subTest(failure=failure):
                engine=Mock()
                clicks=0
                closed=failure in ('exit_before', 'outside')
                def pipeline(_engine, entry, _timeout):
                    nonlocal clicks, closed
                    if entry == '自动治疗关闭治疗界面':
                        closed=True
                        return True
                    if entry == '自动治疗确认治疗界面':
                        return not closed
                    if entry == '自动治疗点击仙盟互助':
                        clicks += 1
                        if failure == 'exit_during':
                            closed=True
                        return not closed
                    if entry == '自动治疗确认仙盟互助':
                        return failure == 'help' or clicks == 1
                    if entry == '自动治疗等待返回主界面':
                        return failure not in ('main', 'outside')
                    return True
                with patch.object(flow, '_run_pipeline', side_effect=pipeline) as run, \
                     patch.object(flow, '_wait_or_stop'):
                    if failure in ('help', 'main', 'outside'):
                        with self.assertRaises(RuntimeError):
                            flow._request_help_and_close(engine, 1.5, require_help=True)
                    else:
                        flow._request_help_and_close(engine, 1.5, require_help=True)
                        self.assertEqual({None:2, 'exit_before':0, 'exit_during':1}[failure], clicks)
                    closed=[c for c in run.call_args_list if c.args[1] == '自动治疗关闭治疗界面']
                    self.assertEqual({'help':0, 'main':3, None:1, 'exit_before':0,
                                      'exit_during':0, 'outside':0}[failure], len(closed))

        nodes=json.loads((PROJECT_DIR/'resource/base/pipeline/AutoTreatment/AutoTreatment.json').read_text(encoding='utf-8'))
        button=nodes['自动治疗点击仙盟互助']
        self.assertEqual('自动治疗确认仙盟互助', button['all_of'][button['box_index']])

    def test_treatment_hud_help_clicks_once_and_requires_state_change(self):
        from unittest.mock import Mock, patch
        from agent.custom.action.auto_treatment import auto_treatment_cycle as flow
        for state in ('assisted', 'pending', 'complete'):
            with self.subTest(state=state):
                def pipeline(_engine, entry, _timeout):
                    return {
                        '自动治疗点击未协助图标': True,
                        '自动治疗确认已协助': state == 'assisted',
                        '自动治疗确认未协助': state == 'pending',
                        '自动治疗收取治疗完成': state == 'complete',
                    }.get(entry, False)
                with patch.object(flow, '_run_pipeline', side_effect=pipeline) as run, \
                     patch.object(flow, '_wait_or_stop'):
                    if state == 'pending':
                        with self.assertRaisesRegex(RuntimeError, '停止重复点击'):
                            flow._request_help_from_hud(Mock(), 1.5)
                    else:
                        self.assertEqual(state == 'assisted', flow._request_help_from_hud(Mock(), 1.5))
                entries=[c.args[1] for c in run.call_args_list]
                self.assertEqual(1, entries.count('自动治疗点击未协助图标'))
                self.assertNotIn('自动治疗点击治疗入口', entries)
                self.assertNotIn('自动治疗点击仙盟互助', entries)

    def test_treatment_icon_masks_exclude_background(self):
        from PIL import Image
        from agent.recognition_fallback import TREATMENT_HUD_NODES
        nodes=json.loads((PROJECT_DIR/'resource/base/pipeline/AutoTreatment/AutoTreatment.json').read_text(encoding='utf-8'))
        for name in TREATMENT_HUD_NODES:
            node=nodes[name]
            self.assertTrue(node['green_mask'], name)
            templates=node['template']
            for template in templates if isinstance(templates,list) else [templates]:
                with Image.open(PROJECT_DIR/'resource/base/image'/template) as image:
                    width,height=image.size
                    for point in ((0,0),(width-1,0),(0,height-1),(width-1,height-1)):
                        self.assertEqual((0,255,0), image.getpixel(point), template)
                    self.assertNotEqual((0,255,0), image.getpixel((width//2,height//2)), template)

    def test_treatment_missing_icons_recovers_without_waiting_forever(self):
        from types import SimpleNamespace
        from unittest.mock import Mock, patch
        from agent.custom.action.auto_treatment import auto_treatment_cycle as flow
        from agent.recognition_fallback import TREATMENT_HUD_NODES, apply_full_image_fallbacks
        resource=Mock(node_list=list(TREATMENT_HUD_NODES))
        apply_full_image_fallbacks(resource)
        resource.get_node_data.assert_not_called()  # No full-screen HUD matches.

        for recover in (False, True, 'uncertain'):
            with self.subTest(recover=recover):
                engine=Mock()
                turn=-2  # Initial assertion, then the first loop's open panel.
                engine.stop_event.is_set.side_effect=lambda: turn > 14
                def pipeline(_engine, entry, _timeout):
                    nonlocal turn
                    if entry == '自动治疗确认治疗界面':
                        turn += 1
                        return turn <= 0
                    if entry == '自动治疗确认治疗进行中':
                        return True
                    if entry == '自动治疗收取治疗完成':
                        return recover and turn == 4
                    if entry == '自动治疗确认疑似治疗图标':
                        return recover == 'uncertain' and turn > 4
                    return entry in ('自动治疗确认内城', '自动治疗返回主城或大世界')
                with patch.object(flow, '_run_pipeline', side_effect=pipeline) as run, \
                     patch.object(flow, 'AutomationMutex'), \
                     patch.object(flow, '_wait_or_stop'), \
                     patch.object(flow, '_request_help_and_close') as help_close, \
                     patch.object(flow, '_adjust_or_reuse_and_start_treatment') as start:
                    if recover is True:
                        self.assertIn('自动治疗完成', flow.run(engine, SimpleNamespace(parameters={})))
                    else:
                        with self.assertRaisesRegex(RuntimeError, '停止等待'):
                            flow.run(engine, SimpleNamespace(parameters={}))
                    help_close.assert_called_once_with(engine, 1.5, require_help=False)
                    start.assert_not_called()
                    self.assertTrue(any(c.args[1] == '自动治疗返回主城或大世界' for c in run.call_args_list))


if __name__ == '__main__':
    unittest.main()
