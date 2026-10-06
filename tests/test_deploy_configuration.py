import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("allow_http,expected_exit", [(True, 42), (False, 1)])
@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["LF", "CRLF"])
def test_domestic_deploy_uses_file_without_shell_overrides(tmp_path, allow_http, expected_exit, newline):
    if os.name == "nt":
        git = shutil.which("git")
        bash = Path(git).parent.parent / "bin/bash.exe" if git else None
    else:
        bash = shutil.which("bash")
    if not bash or not Path(bash).is_file():
        pytest.skip("Bash is required for deployment shell regression")

    deploy = tmp_path / "deploy"
    deploy.mkdir()
    source = Path(__file__).resolve().parents[1] / "deploy/deploy.sh"
    (deploy / "deploy.sh").write_text(source.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    (deploy / ".env").write_text(
        "ENVIRONMENT=production\n"
        "FRONTEND_BASE_URL=http://127.0.0.1:8094\n"
        f"ALLOW_INSECURE_HTTP={str(allow_http).lower()}\n"
        "NGINX_BIND_ADDRESS=0.0.0.0\n"
        "DB_NAME=file_database\n",
        encoding="utf-8", newline=newline,
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    args_file = tmp_path / "docker-args"
    docker = fake_bin / "docker"
    docker.write_text(
        '#!/usr/bin/env bash\n'
        'printf "%s\\n" "$@" > "$TEST_DOCKER_ARGS_FILE"\n'
        'cmp -s "$3" "$TEST_EXPECTED_ENV_FILE" || exit 44\n'
        'for config_key in ENVIRONMENT FRONTEND_BASE_URL ALLOW_INSECURE_HTTP NGINX_BIND_ADDRESS DB_NAME; do\n'
        '  if [[ -v "$config_key" ]]; then exit 43; fi\n'
        'done\n'
        # Stop at the first Docker invocation; never build or touch a database.
        'exit 42\n',
        encoding="utf-8", newline="\n",
    )
    docker.chmod(0o755)
    environment = os.environ.copy()
    environment.update({
        "ENVIRONMENT": "development",
        "FRONTEND_BASE_URL": "https://shell.invalid",
        "ALLOW_INSECURE_HTTP": "true",
        "NGINX_BIND_ADDRESS": "127.0.0.1",
        "DB_NAME": "shell_database",
        "TEST_DOCKER_ARGS_FILE": args_file.as_posix(),
        "TEST_EXPECTED_ENV_FILE": (deploy / ".env").as_posix(),
    })
    invocation = 'export PATH="$1:$PATH"; exec bash "$2"'
    if os.name == "nt":
        invocation = 'export PATH="$(cygpath -u "$1"):$PATH"; exec bash "$2"'
    result = subprocess.run(
        [str(bash), "-c", invocation, "_", fake_bin.as_posix(), (deploy / "deploy.sh").as_posix()],
        env=environment, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == expected_exit, result.stderr
    if allow_http:
        args = args_file.read_text().splitlines()
        assert args[:2] == ["compose", "--env-file"]
        assert args[2].startswith("/") and args[2].endswith("/deploy/.env")
        assert args[-3:] == ["build", "api", "nginx"]
    else:
        assert "temporary HTTP requires explicit ALLOW_INSECURE_HTTP=true" in result.stderr
        assert not args_file.exists()
