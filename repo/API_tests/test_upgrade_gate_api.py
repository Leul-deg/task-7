def test_upgrade_gate_blocks_mismatched_client_version(client):
    """Server-side gate should block mismatched client schema version."""
    resp = client.get(
        "/schedule",
        headers={"X-Client-Schema-Version": "0"},
    )
    assert resp.status_code == 426


def test_upgrade_gate_allows_matching_client_version(client):
    """Matching version should fall through to normal route auth behavior."""
    expected = client.application.config.get("SCHEMA_VERSION", "1")
    resp = client.get(
        "/schedule",
        headers={"X-Client-Schema-Version": str(expected)},
    )
    # /schedule is login-protected, so unauthenticated should be 401/302, not 426.
    assert resp.status_code in (401, 302)


def test_upgrade_gate_exempts_auth_login(client):
    """Login page should remain accessible even with stale client version."""
    resp = client.get(
        "/auth/login",
        headers={"X-Client-Schema-Version": "0"},
    )
    assert resp.status_code == 200
