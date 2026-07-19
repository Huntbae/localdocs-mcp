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


def test_local_to_remote_normalizes_nfd_to_nfc():
    import unicodedata
    root = "/mnt/gd/내 드라이브"
    # macOS FS가 주는 NFD(자모 분리) 경로
    nfd = unicodedata.normalize("NFD", root + "/클랜헌트/사업계획.pdf")
    out = local_to_remote(nfd, unicodedata.normalize("NFD", root), "gdrive:")
    # 결과는 NFC 완성형이어야 rclone/Drive가 파일을 찾는다
    assert out == unicodedata.normalize("NFC", "gdrive:클랜헌트/사업계획.pdf")
    assert unicodedata.is_normalized("NFC", out)


def test_sensitive_detection():
    assert _is_sensitive("github-recovery-codes.txt")
    assert _is_sensitive("id_rsa")
    assert _is_sensitive("wallet_mnemonic.txt")
    assert not _is_sensitive("클랜헌트_사업계획서.pdf")
