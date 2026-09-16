from services.credential_resolver import CredentialRef

def test_connector_ref_never_contains_token():
    ref = CredentialRef("connector", "remote-credential")
    assert ref.mode == "connector"
    assert ref.token is None
