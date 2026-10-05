import http.client
import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


server = module('api_server', ROOT / 'api/server.py')
admin = module('api_admin', ROOT / 'api/admin.py')
client = module('api_client', ROOT / 'scripts/install-client.py')


class APITests(unittest.TestCase):
    def setUp(self):
        self.http = server.make_server({'hostname': 'test.example.ts.net', 'allowed_logins': ['owner@example.test']}, 0)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.worker.join()

    def request(self, method='GET', path='/api/v1/status', body=None, headers=None):
        values = {'Host': 'test.example.ts.net', 'Tailscale-User-Login': 'owner@example.test'}
        values.update(headers or {})
        if body is not None:
            values.setdefault('Content-Type', 'application/json')
            values.setdefault('X-Wireless-Wire-Request', '1')
            body = json.dumps(body)
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers=values)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_missing_wrong_identity_and_wrong_host_are_denied(self):
        for headers, expected in [({'Tailscale-User-Login': ''}, 403),
                                  ({'Tailscale-User-Login': 'stranger@example.test'}, 403),
                                  ({'Host': 'evil.example'}, 421)]:
            self.assertEqual(self.request(headers=headers)[0], expected)

    def test_authenticated_status_is_not_cached(self):
        with patch.object(server, 'status', return_value={'bridge': True}):
            code, headers, body = self.request()
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body), {'bridge': True})
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertNotIn('Access-Control-Allow-Origin', headers)

    def test_cross_origin_missing_marker_and_non_json_are_denied(self):
        with patch.object(server, 'privileged') as helper:
            for headers, expected in [({'Origin': 'https://evil.example'}, 403),
                                      ({'X-Wireless-Wire-Request': ''}, 403),
                                      ({'Sec-Fetch-Site': 'cross-site'}, 403),
                                      ({'Content-Type': 'text/plain'}, 400),
                                      ({'Content-Length': '999999'}, 400)]:
                self.assertEqual(self.request('POST', '/api/v1/display/rotation', {'degrees': 0}, headers)[0], expected)
            helper.assert_not_called()

    def test_route_selects_action_and_no_credentials_on_get(self):
        with patch.object(server, 'privileged', return_value={'rotation': 180}) as helper:
            self.assertEqual(self.request('POST', '/api/v1/display/rotation', {'degrees': 180})[0], 200)
            helper.assert_called_once_with('rotation', {'degrees': 180})
        self.assertEqual(self.request(path='/api/v1/client-config')[0], 404)

    def test_redirect_has_fixed_https_authority_and_no_api_operations(self):
        self.http.redirect = True
        with patch.object(server, 'privileged') as helper:
            code, headers, _ = self.request('POST', '/api/v1/client-config', {}, {'Host': 'evil.example'})
            self.assertEqual(code, 308)
            self.assertEqual(headers['Location'], 'https://test.example.ts.net/api/v1/client-config')
            helper.assert_not_called()

    def test_helpers_never_accept_arbitrary_service_or_orientation(self):
        with patch.object(admin, 'run') as run:
            for request in [{'action': 'restart', 'service': 'sshd'}, {'action': 'rotation', 'degrees': True},
                            {'action': 'rotation', 'degrees': 45}, {'action': 'shell', 'command': 'id'}]:
                with self.assertRaises(ValueError):
                    admin.execute(request)
            run.assert_not_called()

    def test_wifi_profile_has_no_plain_password_or_keyfile_injection(self):
        identity, data = admin.wifi_profile('Café: Wi-Fi', 'example-password')
        self.assertNotIn('example-password', data)
        self.assertIn('ssid=67;97;102;195;169;', data)
        self.assertEqual(identity, admin.wifi_profile('Café: Wi-Fi', 'different-password')[0])
        for name, password in [('evil\n[connection]', 'example-password'), ('x'*33, 'example-password'),
                               ('okay', 'short'), ('okay', 'bad\npassword')]:
            with self.assertRaises(ValueError):
                admin.wifi_profile(name, password)

    def test_enrollment_rejects_http_foreign_hosts_paths_and_credentials(self):
        for url in ['http://test.example.ts.net', 'https://example.com', 'https://test.example.ts.net/path',
                    'https://user:pass@test.example.ts.net', 'https://test.example.ts.net:8443']:
            with self.assertRaises(ValueError):
                client.enroll(url)


if __name__ == '__main__':
    unittest.main()
