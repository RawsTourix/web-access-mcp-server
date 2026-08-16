"""Install the fail-closed Linux no-network boundary for one parser child."""

from __future__ import annotations

import ctypes
import errno
import sys
from ctypes.util import find_library
from typing import Final

_PR_SET_NO_NEW_PRIVS: Final = 38
_SCMP_ACT_ALLOW: Final = 0x7FFF0000
_SCMP_ACT_ERRNO: Final = 0x00050000
_NETWORK_SYSCALLS: Final = (
    "socket",
    "socketpair",
    "socketcall",
    "connect",
    "bind",
    "listen",
    "accept",
    "accept4",
    "send",
    "sendto",
    "sendmsg",
    "sendmmsg",
    "recv",
    "recvfrom",
    "recvmsg",
    "recvmmsg",
    "shutdown",
    "getsockname",
    "getpeername",
    "getsockopt",
    "setsockopt",
    # io_uring can otherwise submit socket operations without a direct socket syscall.
    "io_uring_setup",
    "io_uring_enter",
    "io_uring_register",
)
_REQUIRED_SYSCALLS: Final = frozenset({"socket", "connect"})


class ParserSandboxUnavailable(RuntimeError):
    """The kernel/libseccomp boundary required by production is unavailable."""


def assert_no_network_filter_available() -> None:
    """Fail closed before spawning if the production Linux boundary cannot be loaded."""

    if not sys.platform.startswith("linux"):
        raise ParserSandboxUnavailable("Linux seccomp parser isolation is unavailable")
    library = _load_seccomp()
    for name in _REQUIRED_SYSCALLS:
        if library.seccomp_syscall_resolve_name(name.encode()) < 0:
            raise ParserSandboxUnavailable(f"libseccomp cannot resolve required syscall {name}")


def install_no_network_filter() -> None:
    """Deny network syscalls for this process and every descendant at kernel level."""

    assert_no_network_filter_available()
    _set_no_new_privileges()
    library = _load_seccomp()
    context = library.seccomp_init(_SCMP_ACT_ALLOW)
    if not context:
        raise ParserSandboxUnavailable("libseccomp could not allocate a filter")
    try:
        action = _SCMP_ACT_ERRNO | errno.EPERM
        resolved_required: set[str] = set()
        for name in _NETWORK_SYSCALLS:
            syscall = library.seccomp_syscall_resolve_name(name.encode())
            if syscall < 0:
                continue
            if name in _REQUIRED_SYSCALLS:
                resolved_required.add(name)
            result = library.seccomp_rule_add(context, action, syscall, 0)
            if result != 0:
                raise ParserSandboxUnavailable(
                    f"libseccomp could not deny syscall {name}: {-result}"
                )
        if resolved_required != _REQUIRED_SYSCALLS:
            raise ParserSandboxUnavailable("required network syscall rules are incomplete")
        result = library.seccomp_load(context)
        if result != 0:
            raise ParserSandboxUnavailable(f"libseccomp could not load filter: {-result}")
    finally:
        library.seccomp_release(context)


def _load_seccomp() -> ctypes.CDLL:
    name = find_library("seccomp") or "libseccomp.so.2"
    try:
        library = ctypes.CDLL(name, use_errno=True)
    except OSError as error:
        raise ParserSandboxUnavailable("libseccomp is unavailable") from error
    try:
        library.seccomp_init.argtypes = (ctypes.c_uint32,)
        library.seccomp_init.restype = ctypes.c_void_p
        library.seccomp_rule_add.argtypes = (
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_uint,
        )
        library.seccomp_rule_add.restype = ctypes.c_int
        library.seccomp_load.argtypes = (ctypes.c_void_p,)
        library.seccomp_load.restype = ctypes.c_int
        library.seccomp_release.argtypes = (ctypes.c_void_p,)
        library.seccomp_release.restype = None
        library.seccomp_syscall_resolve_name.argtypes = (ctypes.c_char_p,)
        library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    except AttributeError as error:
        raise ParserSandboxUnavailable("libseccomp API is incomplete") from error
    return library


def _set_no_new_privileges() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.restype = ctypes.c_int
    result = libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)
    if result != 0:
        error_number = ctypes.get_errno()
        raise ParserSandboxUnavailable(f"cannot set no_new_privs: {error_number}") from OSError(
            error_number, "prctl(PR_SET_NO_NEW_PRIVS) failed"
        )
