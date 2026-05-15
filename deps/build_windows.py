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

    The core problem: BUILD.gn has a Windows-specific branch that sets
    ICU_UTIL_DATA_IMPL=ICU_UTIL_DATA_SHARED (expecting a DLL) instead of
    ICU_UTIL_DATA_IMPL=ICU_UTIL_DATA_STATIC (expecting a linked-in symbol).

    We apply targeted regex patches since exact whitespace varies across
    ICU versions."""
    import re

    icu_dir = os.path.join(v8_path, "third_party", "icu")
    build_gn = os.path.join(icu_dir, "BUILD.gn")

    for subdir in [icu_dir, os.path.join(icu_dir, "scripts")]:
        git_dir = os.path.join(subdir, ".git")
        if os.path.exists(git_dir):
            shutil.rmtree(git_dir, onerror=_rm_readonly)

    if not os.path.exists(build_gn):
        print("WARNING: %s not found, skipping ICU patches" % build_gn)
        return

    with open(build_gn, 'r') as f:
        content = f.read()

    original = content

    # Patch 1: Replace the entire Windows SHARED branch.
    # The BUILD.gn has:
    #   } else {
    #     if (is_win) {
    #       defines += [ "ICU_UTIL_DATA_IMPL=ICU_UTIL_DATA_SHARED" ]
    #     } else {
    #       defines += [ "ICU_UTIL_DATA_IMPL=ICU_UTIL_DATA_STATIC" ]
    #     }
    #   }
    # We replace to always use STATIC (no Windows special case).
    pattern1 = re.compile(
        r'if\s*\(is_win\)\s*\{[^}]*ICU_UTIL_DATA_SHARED[^}]*\}\s*else\s*\{[^}]*ICU_UTIL_DATA_STATIC[^}]*\}',
        re.DOTALL
    )
    new1 = 'defines += [ "ICU_UTIL_DATA_IMPL=ICU_UTIL_DATA_STATIC" ]'
    if pattern1.search(content):
        content = pattern1.sub(new1, content)
        print("  [1] Patched: removed Windows SHARED branch, always use STATIC")
    else:
        print("  [1] SHARED/STATIC branch not found (may differ from expected)")

    # Patch 2: Remove U_HIDE_DATA_SYMBOL.
    pattern2 = re.compile(r'\s*defines\s*=\s*\[\s*"U_HIDE_DATA_SYMBOL"\s*\]\s*\n?')
    if pattern2.search(content):
        content = pattern2.sub('\n', content)
        print("  [2] Removed U_HIDE_DATA_SYMBOL define")
    else:
        print("  [2] U_HIDE_DATA_SYMBOL not found")

    # Patch 3: Remove Windows copy("icudata") block that copies icudt.dll.
    # When icu_use_data_file=false on non-Windows, a source_set("icudata")
    # is used. On Windows, there's a copy() that copies a prebuilt DLL.
    # We need to remove it so the source_set path is used for all platforms.
    pattern3 = re.compile(
        r'if\s*\(is_win\)\s*\{\s*\n\s*copy\("icudata"\)\s*\{[^}]*icudt\.dll[^}]*\}\s*\n\s*\}',
        re.DOTALL
    )
    if pattern3.search(content):
        content = pattern3.sub(
            '# Patched: Windows icudata uses static embedding (same as Linux/macOS)', content)
        print("  [3] Replaced Windows copy(icudata) with comment")
    else:
        print("  [3] Windows copy(icudata) not found (OK)")

    if content != original:
        with open(build_gn, 'w') as f:
            f.write(content)
        print("Patched ICU BUILD.gn successfully")
    else:
        print("ICU BUILD.gn: no patches applied (content unchanged)")

    # NOTE: make_data_assembly.py patch is not done here because it may be
    # overwritten by gclient sync or ninja regeneration. Instead, we patch
    # the generated icudtl_dat.cc directly after the icudata build step
    # (see main()).



def patch_icudtl_cc(build_path):
    """Fix symbol prefix in all generated icudtl_dat.cc files.
    .globl _icudt73_dat -> .globl icudt73_dat
    x64/arm64 COFF has no underscore prefix (only x86 32-bit does).
    Returns the number of files patched."""
    import glob
    pattern = os.path.join(build_path, "**", "icudtl_dat.cc")
    patched_count = 0
    for icudtl_cc in glob.glob(pattern, recursive=True):
        with open(icudtl_cc, 'r') as f:
            cc = f.read()
        if '_icudt' in cc:
            cc = cc.replace('.globl _icudt', '.globl icudt')
            cc = cc.replace('"_icudt', '"icudt')
            with open(icudtl_cc, 'w') as f:
                f.write(cc)
            print("Patched %s: removed _ prefix" % icudtl_cc)
            patched_count += 1
        else:
            print("%s: no _icudt prefix found (OK)" % icudtl_cc)
    found = glob.glob(pattern, recursive=True)
    if not found and patched_count == 0:
        print("WARNING: no icudtl_dat.cc found under %s" % build_path)
    else:
        print("Found %d icudtl_dat.cc, patched %d" % (len(found) + patched_count, patched_count))
    return patched_count


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

    # Build ICU data first, patch the generated icudtl_dat.cc, then do
    # the full build. For ARM64, a retry loop handles x64 host toolchain.
    print("Building ICU data target...")
    subprocess.call(cmd([ninja_path, "-v", "-C", build_path,
                         "third_party/icu:icudata"]),
                    cwd=v8_path, env=env)

    patch_icudtl_cc(build_path)

    # For ARM64 cross-compilation, ninja builds x64 host tools under
    # win_clang_x64/. Those host tools also need ICU, but their icudtl_dat.cc
    # is only generated when those targets are built. We do a first build
    # attempt that may fail at the host tool link step, then patch any newly
    # generated icudtl_dat.cc files, then retry.
    rc = subprocess.call(cmd([ninja_path, "-v", "-C", build_path, "v8_monolith"]),
                         cwd=v8_path, env=env)
    if rc != 0:
        print("First build attempt failed (rc=%d), patching newly generated icudtl_dat.cc..." % rc)
        patched = patch_icudtl_cc(build_path)
        if patched > 0:
            print("Retrying full build after patching %d file(s)..." % patched)
            subprocess.check_call(cmd([ninja_path, "-v", "-C", build_path, "v8_monolith"]),
                                  cwd=v8_path, env=env)
        else:
            raise RuntimeError("Build failed and no icudtl_dat.cc files needed patching")

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
