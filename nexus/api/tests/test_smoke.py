def test_boot(env):
    r = env.client.get("/api/health")
    assert r.status_code == 200
    assert env.client.get("/api/auth/me", headers=env.F).json()["role"] == "fondateur"
