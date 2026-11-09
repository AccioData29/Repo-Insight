import pytest

from app.models import Platform
from app.providers import UrlError, detect_platform, parse_repo


def test_github_ok_and_normalizes():
    prov, p = parse_repo("https://github.com/octocat/Hello-World.git")
    assert prov.platform == Platform.github
    assert (p.owner, p.repo) == ("octocat", "Hello-World")
    assert p.clone_url == "https://github.com/octocat/Hello-World.git"


def test_github_ssh_form_and_branch_hint():
    _, p = parse_repo("git@github.com:octocat/Hello-World.git")
    assert p.web_url == "https://github.com/octocat/Hello-World"
    _, p = parse_repo("https://github.com/octocat/Hello-World/tree/release/1.0")
    assert p.branch_hint == "release/1.0"


@pytest.mark.parametrize("url,plat", [
    ("https://gitlab.com/group/sub/repo", Platform.gitlab),
    ("https://dev.azure.com/org/proj/_git/repo", Platform.azure_devops),
    ("https://bitbucket.org/ws/repo", Platform.bitbucket),
])
def test_other_platforms(url, plat):
    prov, p = parse_repo(url)
    assert prov.platform == plat and p.repo


def test_gitlab_subgroups():
    _, p = parse_repo("https://gitlab.com/a/b/c/repo.git")
    assert p.owner == "a/b/c" and p.repo == "repo"


def test_platform_mismatch_is_rejected():
    with pytest.raises(UrlError, match="pertenece a GitHub"):
        parse_repo("https://github.com/o/r", Platform.gitlab)


@pytest.mark.parametrize("bad", [
    "http://github.com/o/r",                 # sin https
    "https://evil.com/github.com/o/r",       # host distinto
    "https://github.com.evil.com/o/r",       # sufijo engañoso
    "https://github.com/o",                  # falta repo
    "https://github.com/o/../etc",           # traversal
    "file:///etc/passwd",
    "https://user@127.0.0.1/o/r",
    "",
])
def test_ssrf_and_malformed_rejected(bad):
    with pytest.raises(UrlError):
        parse_repo(bad)


def test_detect_platform_by_host_only():
    assert detect_platform("https://github.com/x") == Platform.github
    assert detect_platform("https://example.com/x") is None


def test_permission_help_is_read_only():
    prov, p = parse_repo("https://github.com/o/r")
    h = prov.permission_help(p)
    assert any("Read-only" in s for s in h.scopes) and not any("Write" in s for s in h.scopes)


def test_parse_ls_remote_extracts_default_and_branches():
    from app.git_ops import guess_production_branch, parse_ls_remote
    out = ("ref: refs/heads/main\tHEAD\n"
           "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\tHEAD\n"
           "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\trefs/heads/feature/x\n"
           "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\trefs/heads/main\n"
           "cccccccccccccccccccccccccccccccccccccccc\trefs/heads/production\n")
    branches, default = parse_ls_remote(out)
    assert default == "main" and branches == ["feature/x", "main", "production"]
    assert guess_production_branch(branches, default)[0] == "production"          # prefiere «production» sobre main
    b, why = guess_production_branch(["main", "dev"], "main")
    assert b == "main" and "confirme" in why                                      # avisa que es una suposición
    assert guess_production_branch(["main", "release/1"], "main", hint="release/1")[0] == "release/1"
