/*
 * MSVC runtime symbol stubs for MinGW linking.
 *
 * V8/ICU objects are built with clang-cl (MSVC ABI). When Go links
 * these objects via MinGW's GNU ld, several MSVC CRT symbols are
 * unresolved because MinGW cannot read MSVC's static CRT libraries
 * (LTCG format). This file provides minimal stubs so linking succeeds
 * without a full MSVC CRT dependency.
 *
 * Only compiled on windows/amd64 (Go filename convention).
 */

#include <stdint.h>
#include <stdlib.h>

/* ---------- Buffer Security Check (/GS) stubs ---------- */

uintptr_t __security_cookie = 0xBB40E64EBB40E64Eull;

void __fastcall __security_check_cookie(uintptr_t cookie) {
    if (cookie != __security_cookie) abort();
}

void __cdecl __report_rangecheckfailure(void) {
    abort();
}

/* ---------- MSVC RTTI type_info vtable stub ---------- */

/*
 * ICU objects contain RTTI Type Descriptors (??_R0...) that reference the
 * MSVC-mangled vtable for std::type_info (??_7type_info@@6B@).  Provide a
 * minimal data symbol so the linker resolves the reference.  ICU's RTTI
 * usage within the V8 embedding context does not exercise the vtable at
 * runtime, so a zero-filled slot is safe here.
 */
__asm__(
    ".section .rdata,\"dr\"\n"
    ".globl \"??_7type_info@@6B@\"\n"
    "\"??_7type_info@@6B@\":\n"
    ".quad 0\n"
    ".text\n"
);
