from types import SimpleNamespace

from app import mail as mail_module


def test_provider_order_includes_all_providers_in_configured_order(monkeypatch):
    monkeypatch.setattr(
        mail_module,
        "settings",
        SimpleNamespace(
            tempmail_providers="tempmail_lol,mailtm,temp_mail_io,temp_mail_org,mailgw"
        ),
    )

    assert mail_module._provider_order() == [
        "tempmail_lol",
        "mailtm",
        "temp_mail_io",
        "temp_mail_org",
        "mailgw",
    ]


def test_create_mailbox_falls_back_after_provider_failure(monkeypatch):
    monkeypatch.setattr(
        mail_module,
        "settings",
        SimpleNamespace(tempmail_providers="first,second"),
    )

    def fail():
        raise RuntimeError("provider offline")

    expected = mail_module.Mailbox("second", "ok@example.test", {"token": "secret"})
    monkeypatch.setattr(mail_module, "_CREATORS", {"first": fail, "second": lambda: expected})

    assert mail_module.create_mailbox() is expected
    assert expected.password is None


def test_mailtm_domain_hydra_response_is_supported(monkeypatch):
    class Response:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class Client:
        def __init__(self, **kwargs):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, path, **kwargs):
            assert path == "/domains"
            return Response(
                {"hydra:member": [{"domain": "maxxspace.com", "isActive": True}]}
            )

        def post(self, path, **kwargs):
            if path == "/accounts":
                return Response({})
            assert path == "/token"
            return Response({"token": "token-value"})

    monkeypatch.setattr(mail_module.httpx, "Client", Client)
    monkeypatch.setattr(mail_module, "_rand", lambda n: "a" * n)

    mailbox = mail_module._create_mailtm_like("https://api.mail.tm", "mailtm")

    assert mailbox.provider == "mailtm"
    assert mailbox.address == "sbaaaaaaaaaa@maxxspace.com"
    assert mailbox.handle["token"] == "token-value"
    assert mailbox.password == mail_module.settings.tempmail_password
