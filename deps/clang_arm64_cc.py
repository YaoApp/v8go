"""Clang wrapper for Windows ARM64: filters GCC-only flags that clang rejects."""
import subprocess
import sys

FILTERED = {'-mthreads'}
PREPEND = ['clang', '--target=aarch64-pc-windows-msvc', '-fuse-ld=lld']

args = [a for a in sys.argv[1:] if a not in FILTERED]
sys.exit(subprocess.call(PREPEND + args))
