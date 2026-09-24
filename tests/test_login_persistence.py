"""CLI login must reach the real session store, not just token exchange."""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from omarchy_mercedes import cli, daemon

class LoginPersistenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        for name,value in [('DATA_DIR',self.root),('SESSION_FILE',self.root/'session.json')]:
            p=patch.object(daemon,name,value); p.start(); self.addCleanup(p.stop)
        # Never contact the real desktop keyring.
        p=patch.dict('sys.modules',{'keyring':None}); p.start(); self.addCleanup(p.stop)
        self.tokens={'access_token':'SYNTH_ACCESS_PRIVATE','refresh_token':'SYNTH_REFRESH_PRIVATE','expires_at':1800000000}

    def test_browser_login_persists_session_for_every_region(self):
        for region in ('eu','na','apac','cn'):
            with self.subTest(region=region):
                output=io.StringIO()
                with patch('omarchy_mercedes.login_helper.login_browser',return_value=self.tokens) as browser, contextlib.redirect_stdout(output):
                    result=cli.main(['login','--browser','--region',region])
                self.assertEqual(result,0)
                browser.assert_called_once_with(region,open_browser=True)
                self.assertEqual(daemon.load_session(region),self.tokens)
                self.assertEqual(daemon.SESSION_FILE.stat().st_mode & 0o777,0o600)
                self.assertIn('Session sicher gespeichert',output.getvalue())
                self.assertNotIn('SYNTH_ACCESS_PRIVATE',output.getvalue())
                self.assertNotIn('SYNTH_REFRESH_PRIVATE',output.getvalue())

    def test_callback_through_cli_reaches_real_session_store(self):
        import os
        from urllib.parse import parse_qs, urlparse, urlencode
        from omarchy_mercedes import callback as cb
        def deliver_callback(auth_url):
            query=parse_qs(urlparse(auth_url).query)
            token=next(cb.runtime_dir().glob('*.active')).stem
            cb.write_spool(token, 'rismycar://login-callback?'+urlencode({'code':'SYNTHETIC_CALLBACK','state':query['state'][0]}))
            return True
        env={'OMARCHY_MERCEDES_RUNTIME_DIR':str(self.root/'run'), 'XDG_CONFIG_HOME':str(self.root/'config'), 'XDG_DATA_HOME':str(self.root/'data')}
        with patch.dict(os.environ,env), patch.object(cb,'install_desktop_handler',return_value=(True,None)), patch('omarchy_mercedes.login_helper.webbrowser.open',side_effect=deliver_callback), patch('omarchy_mercedes.login_helper.MercedesOAuthClient.exchange_code',return_value=self.tokens) as exchange, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(['login','--browser']),0)
            self.assertEqual(exchange.call_args.args[0],'SYNTHETIC_CALLBACK')
            self.assertEqual(daemon.load_session('eu'),self.tokens)
            self.assertEqual(list(cb.runtime_dir().glob('*.active')),[])
            self.assertEqual(list(cb.runtime_dir().glob('*.url')),[])

    def test_password_login_uses_same_real_store(self):
        with patch('omarchy_mercedes.login_helper.login_password',return_value=self.tokens), contextlib.redirect_stdout(io.StringIO()):
            result=cli.main(['login','--password'])
        self.assertEqual(result,0)
        self.assertEqual(daemon.load_session('eu'),self.tokens)

    def test_storage_failure_returns_error_without_false_success(self):
        out,err=io.StringIO(),io.StringIO()
        with patch('omarchy_mercedes.login_helper.login_browser',return_value=self.tokens), patch.object(daemon,'_save_session',side_effect=OSError('synthetic disk failure')), contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result=cli.main(['login'])
        self.assertEqual(result,1)
        self.assertNotIn('Login erfolgreich',out.getvalue())
        self.assertIn('Login fehlgeschlagen',err.getvalue())
        self.assertFalse(daemon.SESSION_FILE.exists())
