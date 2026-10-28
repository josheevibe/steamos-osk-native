"""Safety tests: no system mutation; installer commands are mocked."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parent / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


manage = module('manage', 'manage.py')
rules = module('rules', 'window-rule.py')


class Safety(unittest.TestCase):
    def test_new_os_and_library_versions_rejected(self):
        expected = {'architecture': 'x86_64', 'os_release': {'BUILD_ID': 'tested'},
                    'runtime_packages': {'qt6-base': '1'}}
        manage.compare_environment(expected, {'BUILD_ID': 'tested'}, 'x86_64', {'qt6-base': '1'})
        for os_info, arch, packages in [({'BUILD_ID': 'updated'}, 'x86_64', {'qt6-base': '1'}),
                                        ({'BUILD_ID': 'tested'}, 'aarch64', {'qt6-base': '1'}),
                                        ({'BUILD_ID': 'tested'}, 'x86_64', {'qt6-base': '2'})]:
            with self.assertRaises(RuntimeError):
                manage.compare_environment(expected, os_info, arch, packages)

    def test_corrupted_archive_rejected_before_pacman(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'package').write_bytes(b'damaged')
            manifest = {'packages': {'kwin': {'versions': {'1': {'file': 'package', 'sha256': 'wrong'}}}}}
            with patch.object(manage, 'run') as command, self.assertRaises(RuntimeError):
                manage.verify_archives(root, manifest)
            command.assert_not_called()

    def test_readonly_restored_after_failure(self):
        calls = []
        def command(*args):
            calls.append(args)
            return 'enabled' if args[-1] == 'status' else ''
        with patch.object(manage, 'run', command), self.assertRaises(ValueError):
            with manage.writable_system():
                raise ValueError('install failed')
        self.assertEqual(calls[-1], ('steamos-readonly', 'enable'))

    def test_already_writable_is_preserved(self):
        with patch.object(manage, 'run', return_value='disabled') as command:
            with manage.writable_system():
                pass
        self.assertEqual(command.call_count, 1)

    def exercise_install_failure(self, rollback_fails):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bundle = root / 'bundle'
            bundle.mkdir()
            (bundle / 'packages').mkdir()
            for name in ('manifest.json', 'tested-environment.json', 'manage.py'):
                (bundle / name).write_text('{}')
            state = root / 'state'
            manifest = {'packages': {'kwin': {'fixed': 'new'}}}
            calls = []
            def command(*args):
                calls.append(args)
                return 'enabled' if args == ('steamos-readonly', 'status') else ''
            effects = [RuntimeError('installation failed'), RuntimeError('rollback failed') if rollback_fails else None]
            with patch.object(manage, 'BUNDLE', bundle), patch.object(manage, 'STATE', state), \
                 patch.object(manage, 'preflight', return_value=(manifest, {'kwin': 'old'})), \
                 patch.object(manage, 'verify_archives'), patch.object(manage, 'run', command), \
                 patch.object(manage, 'package_transaction', side_effect=effects) as transact:
                with self.assertRaises(RuntimeError):
                    manage.install()
            self.assertEqual(transact.call_args_list[1].args[-1], {'kwin': 'old'})
            self.assertEqual(calls[-1], ('steamos-readonly', 'enable'))
            status = json.loads((state / 'journal.json').read_text())['status']
            self.assertEqual(status, 'recovery_required' if rollback_fails else 'rolled_back')

    def test_install_failure_restores_previous_packages(self):
        self.exercise_install_failure(False)

    def test_double_failure_keeps_recovery_record(self):
        self.exercise_install_failure(True)

    def test_already_installed_does_not_replace_backup(self):
        with patch.object(manage, 'preflight', return_value=({'packages': {'kwin': {'fixed': 'new'}}}, {'kwin': 'new'})), \
             patch.object(manage, 'writable_system') as writable:
            manage.install()
            writable.assert_not_called()


class WindowRule(unittest.TestCase):
    def test_install_remove_preserves_unrelated_rules_and_changes(self):
        text = '[General]\ncount=1\nrules=work\nother=keep\n\n[work]\nDescription=Keep me\nlayer=normal\n'
        with tempfile.TemporaryDirectory() as temp:
            config, backup = Path(temp) / 'kwinrulesrc', Path(temp) / 'backup.json'
            config.write_text(text)
            self.assertTrue(rules.apply('install', 'Steam Input 가상 키보드', config, backup))
            installed = config.read_text()
            self.assertEqual(rules.sections(installed)['work'], rules.sections(text)['work'])
            self.assertFalse(rules.apply('install', 'Steam Input 가상 키보드', config, backup))
            config.write_text(installed + '[added-later]\nDescription=Preserve this too\n')
            rules.apply('remove', '', config, backup)
            result = rules.sections(config.read_text())
            self.assertEqual(result['work'], rules.sections(text)['work'])
            self.assertIn('added-later', result)
            self.assertIn('other=keep', result['General'])
            self.assertNotIn(rules.KEY, result)
            self.assertFalse(rules.apply('remove', '', config, backup))

    def test_previous_rule_restored(self):
        text = ('[General]\ncount=2\nrules=' + rules.KEY + ',work\n[' + rules.KEY +
                ']\nDescription=original\n[work]\nDescription=another rule\n')
        with tempfile.TemporaryDirectory() as temp:
            config, backup = Path(temp) / 'kwinrulesrc', Path(temp) / 'backup.json'
            config.write_text(text)
            rules.apply('install', 'Keyboard', config, backup)
            rules.apply('remove', '', config, backup)
            self.assertEqual(config.read_text(), text)

    def test_external_rule_change_blocks_restore(self):
        with tempfile.TemporaryDirectory() as temp:
            config, backup = Path(temp) / 'kwinrulesrc', Path(temp) / 'backup.json'
            rules.apply('install', 'Keyboard', config, backup)
            changed = config.read_text().replace('layer=overlay', 'layer=normal')
            config.write_text(changed)
            with self.assertRaises(RuntimeError):
                rules.apply('remove', '', config, backup)
            self.assertEqual(config.read_text(), changed)
            self.assertTrue(backup.exists())


if __name__ == '__main__':
    unittest.main()
