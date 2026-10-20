import ctypes
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ai_workshop.infrastructure.object_store.originals import TrackedOriginalStore

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows handle diagnostics")


@pytest.mark.parametrize("code", [5, 32])
@pytest.mark.parametrize(
    ("directory", "delete", "root", "kind"),
    [
        (False, False, False, "file"),
        (False, True, False, "file"),
        (True, False, False, "directory"),
        (True, True, False, "directory"),
        (True, False, True, "volume_root"),
    ],
)
def test_handle_failure_records_only_safe_stage_and_os_code(
    monkeypatch, caplog, tmp_path, code, directory, delete, root, kind
):
    import msvcrt

    path = Path(tmp_path.anchor) if root else tmp_path / "private-document-secret.txt"

    def deny(*args):
        ctypes.set_last_error(code)
        return ctypes.c_void_p(-1).value

    create = Mock(side_effect=deny)
    close = Mock()
    kernel = SimpleNamespace(CreateFileW=create, CloseHandle=close)
    loader = Mock(return_value=kernel)
    monkeypatch.setattr(ctypes, "WinDLL", loader)
    opened = Mock(side_effect=AssertionError("An invalid handle must never be adopted"))
    monkeypatch.setattr(msvcrt, "open_osfhandle", opened)

    with pytest.raises(OSError) as failure:
        TrackedOriginalStore._windows_fd(path, directory=directory, delete=delete)

    assert failure.value.winerror == code
    assert failure.value.filename is None
    assert failure.value.filename2 is None
    loader.assert_called_once_with("kernel32", use_last_error=True)
    create.assert_called_once_with(
        "\\\\?\\" + str(path),
        0x80000000 | (0x10000 if delete else 0),
        0x3 if directory else 0x1,
        None,
        3,
        0x00200000 | (0x02000000 if directory else 0),
        None,
    )
    opened.assert_not_called()
    close.assert_not_called()
    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.getMessage() == (
        "object_store_handle_open_failed stage=CreateFileW "
        f"target_kind={kind} delete={delete} winerror={code}"
    )
    assert record.exc_info is None and record.stack_info is None
    assert "private-document-secret" not in str(failure.value) + caplog.text
