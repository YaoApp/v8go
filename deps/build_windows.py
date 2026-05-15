#!/usr/bin/env python
"""
Build V8 monolithic static library for Windows using clang-cl.

This is a standalone script that does NOT modify the existing build.py.
It shares the same deps/v8 submodule and deps/depot_tools but produces
a Windows-specific v8_monolith.lib (COFF static archive).

Usage:
    python build_windows.py --arch x86_64
    python build_windows.py --arch arm64
    python build_windows.py --arch x86_64 --debug
"""
import platform
import os
import subprocess
import shutil
import argparse

valid_archs = ['arm64', 'x86_64']
current_arch = platform.uname()[4].lower().replace("amd64", "x86_64")
default_arch = current_arch if current_arch in valid_archs else None

parser = argparse.ArgumentParser(description="Build V8 for Windows (clang-cl)")
parser.add_argument('--debug', dest='debug', action='store_true')
parser.add_argument('--arch',
    dest='arch',
    action='store',
    choices=valid_archs,
    default=default_arch,
    required=default_arch is None)
parser.set_defaults(debug=False)
args = parser.parse_args()

deps_path = os.path.dirname(os.path.realpath(__file__))
v8_path = os.path.join(deps_path, "v8")
tools_path = os.path.join(deps_path, "depot_tools")

gclient_sln = [
    { "name"        : "v8",
        "url"         : "https://chromium.googlesource.com/v8/v8.git",
        "deps_file"   : "DEPS",
        "managed"     : False,
        "custom_deps" : {
            "v8/testing/gmock"                      : None,
            "v8/test/wasm-js"                       : None,
            "v8/third_party/android_tools"          : None,
            "v8/third_party/catapult"               : None,
            "v8/third_party/colorama/src"           : None,
            "v8/tools/gyp"                          : None,
            "v8/tools/luci-go"                      : None,
        },
        "custom_vars": {
            "build_for_node" : True,
        },
    },
]

# GN args for Windows clang-cl build.
# Mirrors build.py args exactly, with two additions:
#   - target_os="win"
#   - is_clang=true (forced; V8 11.8 supports clang-cl natively)
#
# v8_enable_sandbox is intentionally NOT set — the V8 default enables it
# on 64-bit non-Fuchsia platforms, matching the -DV8_ENABLE_SANDBOX in cgo.go.
# Setting it to false would cause struct layout mismatch and runtime crashes.
gn_args = """
target_os="win"
is_debug=%s
is_clang=true
target_cpu="%s"
v8_target_cpu="%s"
clang_use_chrome_plugins=false
use_custom_libcxx=false
use_sysroot=false
symbol_level=%s
strip_debug_info=%s
is_component_build=false
v8_monolithic=true
v8_use_external_startup_data=false
treat_warnings_as_errors=false
v8_embedder_string="-v8go"
v8_enable_gdbjit=false
v8_enable_i18n_support=true
icu_use_data_file=false
v8_enable_test_features=false
exclude_unwind_tables=true
v8_enable_v8_checks=false
v8_enable_trace_maps=false
v8_enable_object_print=false
v8_enable_verify_heap=false
"""


def cmd(args):
    return ["cmd", "/c"] + args


def reset_depot_tools():
    """Reset depot_tools to a clean state before gclient sync.
    The submodule checkout may have local modifications that prevent
    depot_tools from auto-updating during gclient sync."""
    subprocess.call(["git", "checkout", "--", "."], cwd=tools_path)
    subprocess.call(["git", "clean", "-fd"], cwd=tools_path)


def v8deps():
    reset_depot_tools()
    spec = "solutions = %s" % gclient_sln
    env = os.environ.copy()
    env["PATH"] = tools_path + os.pathsep + env["PATH"]
    env.setdefault("DEPOT_TOOLS_WIN_TOOLCHAIN", "0")
    env["DEPOT_TOOLS_UPDATE"] = "0"
    subprocess.check_call(cmd(["gclient", "sync", "--spec", spec]),
                        cwd=deps_path,
                        env=env)


def _rm_readonly(func, path, _exc_info):
    os.chmod(path, 0o777)
    func(path)


def patch_icu_for_static_data():
    """Patch ICU for static data embedding on Windows (matching Linux/macOS).

    Four patches to BUILD.gn + one to make_data_assembly.py:

    1) ICU_UTIL_DATA_IMPL: SHARED -> STATIC
       So ICU resolves icudt*_dat as a linked-in symbol, not DLL import.

    2) Remove stubdata.cpp from icuuc on Windows when icu_use_data_file=false.
       Original BUILD.gn has `if (is_win || icu_use_data_file)` which always
       compiles stubdata on Windows. stubdata provides an empty icudt*_dat
       symbol that satisfies the linker, shadowing the real data. We change
       the condition to `if (icu_use_data_file)` only.

    3) Remove U_HIDE_DATA_SYMBOL from the icudata source_set.
       This define makes the symbol internal/hidden. We need it exported.

    4) Ensure icudata on Windows is a source_set (not copy of icudt.dll).
       The original Windows path uses copy("icudata") for a prebuilt DLL.
       We replace it with the same source_set pattern used on Linux/macOS.

    5) make_data_assembly.py: Remove underscore prefix from icudt symbol.
       --win mode generates "_icudt73_dat" (32-bit ABI) but x64 COFF
       expects "icudt73_dat" (no prefix)."""
    icu_dir = os.path.join(v8_path, "third_party", "icu")
    build_gn = os.path.join(icu_dir, "BUILD.gn")

    # Remove .git first to allow modifications
    git_dir = os.path.join(icu_dir, ".git")
    if os.path.exists(git_dir):
        shutil.rmtree(git_dir, onerror=_rm_readonly)

    scripts_git = os.path.join(icu_dir, "scripts", ".git")
    if os.path.exists(scripts_git):
        shutil.rmtree(scripts_git, onerror=_rm_readonly)

    if not os.path.exists(build_gn):
        print("WARNING: %s not found, skipping ICU patches" % build_gn)
        return

    with open(build_gn, 'r') as f:
        content = f.read()

    patched = False

    # Patch 1: SHARED -> STATIC
    old_impl = 'ICU_UTIL_DATA_IMPL=ICU_UTIL_DATA_SHARED'
    if old_impl in content:
        content = content.replace(old_impl, 'ICU_UTIL_DATA_IMPL=ICU_UTIL_DATA_STATIC')
        print("  [1/4] Patched SHARED -> STATIC")
        patched = True

    # Patch 2: Remove stubdata from Windows builds when icu_use_data_file=false.
    # Original: `if (is_win || icu_use_data_file)`  ->  `if (icu_use_data_file)`
    stubdata_old = 'if (is_win || icu_use_data_file)'
    if stubdata_old in content:
        content = content.replace(stubdata_old, 'if (icu_use_data_file)')
        print("  [2/4] Removed is_win from stubdata condition")
        patched = True

    # Patch 3: Remove U_HIDE_DATA_SYMBOL from icudata source_set.
    # This define makes the symbol hidden; we need it visible for linking.
    # Remove the entire defines line containing U_HIDE_DATA_SYMBOL.
    if 'U_HIDE_DATA_SYMBOL' in content:
        import re as re_mod
        content = re_mod.sub(r'\n\s*defines\s*=\s*\[\s*"U_HIDE_DATA_SYMBOL"\s*\]', '', content)
        print("  [3/4] Removed U_HIDE_DATA_SYMBOL")
        patched = True

    # Patch 4: Replace Windows copy("icudata") with source_set("icudata").
    # The original Windows block copies a prebuilt icudt.dll. We need to
    # replace it with a source_set that compiles the inline assembly .cc.
    # This is complex because it's a conditional block, so we use a targeted
    # approach: change the copy() to source_set() and fix its contents.
    #
    # The block looks like:
    #   if (is_win) {
    #     copy("icudata") {
    #       sources = [ "windows/icudt.dll" ]
    #       outputs = [ "$root_out_dir/icudt.dll" ]
    #     }
    #   }
    #
    # We need it to be the same as the non-windows path:
    #   source_set("icudata") {
    #     sources = [ "$data_assembly" ]  (or inline variant)
    #     deps = [ ":make_data_assembly" ] (or inline variant)
    #   }
    #
    # The simplest approach: find and replace the Windows copy block.
    # Since the exact format varies, we look for characteristic patterns.
    import re
    # Match the Windows copy("icudata") block that copies icudt.dll
    win_copy_pattern = re.compile(
        r'if\s*\(is_win\)\s*\{\s*\n\s*copy\("icudata"\)\s*\{[^}]*icudt\.dll[^}]*\}\s*\n\s*\}',
        re.DOTALL
    )
    match = win_copy_pattern.search(content)
    if match:
        # Replace the entire Windows copy block with a comment
        # The non-Windows source_set path will now be used for all platforms
        content = content[:match.start()] + \
            '# Windows icudata: patched to use static embedding (same as Linux/macOS)' + \
            content[match.end():]
        print("  [4/4] Replaced Windows copy(icudata) with static path")
        patched = True
    else:
        print("  [4/4] Windows copy(icudata) block not found (may already be patched)")

    if patched:
        with open(build_gn, 'w') as f:
            f.write(content)
        print("Patched ICU BUILD.gn successfully")
    else:
        print("ICU BUILD.gn: no patches needed")

    # Patch 5: Fix make_data_assembly.py symbol prefix for x64.
    make_asm = os.path.join(icu_dir, "scripts", "make_data_assembly.py")
    if os.path.exists(make_asm):
        with open(make_asm, 'r') as f:
            content = f.read()
        if '_icudt' in content:
            content = content.replace('"_icudt', '"icudt')
            content = content.replace("'_icudt", "'icudt")
            with open(make_asm, 'w') as f:
                f.write(content)
            print("  [5] Patched make_data_assembly.py: removed _ prefix")
        else:
            print("  [5] make_data_assembly.py: no _icudt prefix found")
    else:
        print("  [5] make_data_assembly.py not found")



def v8_arch():
    if args.arch == "x86_64":
        return "x64"
    return args.arch


def main():
    v8deps()
    patch_icu_for_static_data()

    gn_path = os.path.join(tools_path, "gn.bat")
    if not os.path.exists(gn_path):
        gn_path = os.path.join(tools_path, "gn")
    assert os.path.exists(gn_path), "gn not found in depot_tools"

    ninja_path = os.path.join(tools_path, "ninja.bat")
    if not os.path.exists(ninja_path):
        ninja_path = os.path.join(tools_path, "ninja.exe")
    assert os.path.exists(ninja_path), "ninja not found in depot_tools"

    build_path = os.path.join(deps_path, ".build", "windows_" + args.arch)
    env = os.environ.copy()
    env.setdefault("DEPOT_TOOLS_WIN_TOOLCHAIN", "0")
    cl_flags = " -D_ALLOW_COMPILER_AND_STL_VERSION_MISMATCH"
    if v8_arch() == "arm64":
        cl_flags += " -D_CountLeadingZeros64(x)=__builtin_clzll(x)"
        cl_flags += " -D_CountLeadingZeros(x)=__builtin_clz(x)"
    env["CL"] = env.get("CL", "") + cl_flags

    is_debug = 'true' if args.debug else 'false'
    symbol_level = 1 if args.debug else 0
    strip_debug_info = 'false' if args.debug else 'true'

    arch = v8_arch()
    gnargs = gn_args % (is_debug, arch, arch, symbol_level, strip_debug_info)
    gen_args = gnargs.replace('\n', ' ')

    subprocess.check_call(cmd([gn_path, "gen", build_path, "--args=" + gen_args]),
                        cwd=v8_path,
                        env=env)
    subprocess.check_call(cmd([ninja_path, "-v", "-C", build_path, "v8_monolith"]),
                        cwd=v8_path,
                        env=env)

    lib_fn = os.path.join(build_path, "obj", "v8_monolith.lib")
    dest_path = os.path.join(deps_path, "windows_" + args.arch)
    if not os.path.exists(dest_path):
        os.makedirs(dest_path)
    dest_fn = os.path.join(dest_path, 'v8_monolith.lib')
    shutil.copy(lib_fn, dest_fn)
    print("Built: %s" % dest_fn)

    icu_dat = os.path.join(build_path, "icudtl.dat")
    if os.path.exists(icu_dat):
        shutil.copy(icu_dat, os.path.join(dest_path, "icudtl.dat"))
        print("Copied: icudtl.dat")


if __name__ == "__main__":
    main()
