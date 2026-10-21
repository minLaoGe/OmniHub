import tempfile
import plistlib
import unittest
from pathlib import Path
from unittest.mock import patch

from app.apps_manager import AppsManager


class MacUninstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.bundle = Path(self.directory.name).resolve() / 'Example.app'
        (self.bundle / 'Contents').mkdir(parents=True)
        (self.bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'com.example.test', 'CFBundleName': 'Example'}))
        self.manager = AppsManager()
        installed = [{'name': 'Example', 'source': 'MacBundle', 'launch_path': str(self.bundle)}]
        for target, value in [('app.apps_manager.CURRENT_OS', 'Darwin')]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(self.manager, 'scan_installed_apps', return_value=installed)
        p.start()
        self.addCleanup(p.stop)
        p = patch('app.apps_manager.psutil.process_iter', return_value=[])
        self.processes = p.start()
        self.addCleanup(p.stop)
        p = patch('app.apps_manager.send2trash')
        self.trash = p.start()
        self.addCleanup(p.stop)

    def test_success_requires_bundle_to_disappear(self):
        self.trash.side_effect = lambda path: Path(path).rename(Path(self.directory.name) / 'trashed.app')
        self.assertTrue(self.manager.uninstall_app('Example', '', str(self.bundle))['success'])
        self.trash.assert_called_once_with(str(self.bundle))
        self.assertEqual(self.manager.installed_cache, [])

    def test_failed_move_is_not_reported_as_success(self):
        self.assertFalse(self.manager.uninstall_app('Example', '', str(self.bundle))['success'])
        self.assertTrue(self.bundle.exists())

    def test_permission_error_is_reported(self):
        self.trash.side_effect = PermissionError('permission denied')
        result = self.manager.uninstall_app('Example', '', str(self.bundle))
        self.assertFalse(result['success'])
        self.assertIn('permission denied', result['message'])

    def test_system_and_unregistered_paths_are_blocked(self):
        for path in ['/System/Applications/Safari.app', self.directory.name, '']:
            self.assertFalse(self.manager.uninstall_app('Example', '', path)['success'])
        self.trash.assert_not_called()

    def test_running_app_is_blocked(self):
        from types import SimpleNamespace
        self.processes.return_value = [SimpleNamespace(info={'exe': str(self.bundle / 'Contents/MacOS/Example')})]
        result = self.manager.uninstall_app('Example', '', str(self.bundle))
        self.assertFalse(result['success'])
        self.assertIn('仍在运行', result['message'])
        self.trash.assert_not_called()


    def test_cleanup_preview_and_path_validation(self):
        home = Path(self.directory.name).resolve() / 'home'
        cache = home / 'Library/Caches/com.example.test'
        cache.mkdir(parents=True)
        (cache / 'cache.bin').write_bytes(b'12345')
        with patch('app.apps_manager.Path.home', return_value=home):
            preview = self.manager.preview_app_cleanup(str(self.bundle))
            self.assertTrue(preview['success'])
            self.assertEqual(preview['items'][0]['path'], str(cache))
            self.assertEqual(preview['total_bytes'], 5)
            result = self.manager.uninstall_app('Example', '', str(self.bundle), [str(home)])
            self.assertFalse(result['success'])
            self.trash.assert_not_called()
            self.assertTrue(self.bundle.exists())

    def test_selected_data_removed_and_unselected_data_preserved(self):
        home = Path(self.directory.name).resolve() / 'home'
        cache = home / 'Library/Caches/com.example.test'
        data = home / 'Library/Application Support/com.example.test'
        cache.mkdir(parents=True)
        data.mkdir(parents=True)
        def move(path):
            Path(path).rename(Path(self.directory.name) / ('removed-' + Path(path).name))
        self.trash.side_effect = move
        with patch('app.apps_manager.Path.home', return_value=home):
            result = self.manager.uninstall_app('Example', '', str(self.bundle), [str(cache)])
        self.assertTrue(result['success'])
        self.assertFalse(cache.exists())
        self.assertTrue(data.exists())

    def test_data_cleanup_failure_reports_partial_result(self):
        home = Path(self.directory.name).resolve() / 'home'
        cache = home / 'Library/Caches/com.example.test'
        cache.mkdir(parents=True)
        def move(path):
            if path == str(cache):
                raise PermissionError('denied')
            Path(path).rename(Path(self.directory.name) / 'removed.app')
        self.trash.side_effect = move
        with patch('app.apps_manager.Path.home', return_value=home):
            result = self.manager.uninstall_app('Example', '', str(self.bundle), [str(cache)])
        self.assertFalse(result['success'])
        self.assertTrue(result['app_removed'])
        self.assertEqual(result['failed_paths'][0]['path'], str(cache))
        self.assertTrue(cache.exists())

    def test_symlinked_data_is_not_offered(self):
        home = Path(self.directory.name).resolve() / 'home'
        cache = home / 'Library/Caches/com.example.test'
        cache.parent.mkdir(parents=True)
        cache.symlink_to(self.directory.name, target_is_directory=True)
        with patch('app.apps_manager.Path.home', return_value=home):
            result = self.manager.preview_app_cleanup(str(self.bundle))
        self.assertTrue(result['success'])
        self.assertEqual(result['items'], [])


if __name__ == '__main__':
    unittest.main()
