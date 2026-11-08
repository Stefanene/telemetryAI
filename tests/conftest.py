"""All repository tests are offline: an accidental network connection fails immediately."""
import socket

import pytest


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError('Network access is forbidden in the offline test suite')
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy']:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('OPENAI_API_KEY', 'offline-test-not-a-key')
    monkeypatch.setattr(socket.socket, 'connect', denied)
    monkeypatch.setattr(socket.socket, 'connect_ex', denied)
