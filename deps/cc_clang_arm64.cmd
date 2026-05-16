@echo off
setlocal enabledelayedexpansion
set "ARGS="
for %%a in (%*) do (
  if /I not "%%~a"=="-mthreads" set "ARGS=!ARGS! %%a"
)
clang --target=aarch64-pc-windows-msvc -fuse-ld=lld %ARGS%
