from localdocs_mcp.gdrive import local_to_remote, _is_sensitive


def test_local_to_remote_colon_remote():
    root = "/Users/me/Library/CloudStorage/GoogleDrive-a@b.com/내 드라이브"
    p = root + "/Work/클랜헌트/IR.pdf"
    assert local_to_remote(p, root, "gdrive:") == "gdrive:Work/클랜헌트/IR.pdf"


def test_local_to_remote_path_remote():
    root = "/mnt/gd/내 드라이브"
    p = root + "/a/b.docx"
    # 콜론으로 끝나지 않는 원격도 슬래시로 결합
    assert local_to_remote(p, root, "gdrive:sub") == "gdrive:sub/a/b.docx"


def test_sensitive_detection():
    assert _is_sensitive("github-recovery-codes.txt")
    assert _is_sensitive("id_rsa")
    assert _is_sensitive("wallet_mnemonic.txt")
    assert not _is_sensitive("클랜헌트_사업계획서.pdf")
