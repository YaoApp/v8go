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

/* ---------- MSVC operator new / delete ---------- */

/*
 * v8go.cc compiled by clang++ with MSVC target emits MSVC-mangled
 * references to global operator new/delete.  MinGW provides these
 * with Itanium mangling (_Znwm/_ZdlPvm) which doesn't match.
 * Forward to malloc/free via tail-call trampolines.
 */
__asm__(
    ".text\n"
    ".globl \"??2@YAPEAX_K@Z\"\n"       /* operator new(size_t)          */
    "\"??2@YAPEAX_K@Z\":\n"
    "  jmp malloc\n"
    "\n"
    ".globl \"??3@YAXPEAX_K@Z\"\n"       /* operator delete(void*,size_t) */
    "\"??3@YAXPEAX_K@Z\":\n"
    "  jmp free\n"
    "\n"
    ".globl \"??_U@YAPEAX_K@Z\"\n"       /* operator new[](size_t)        */
    "\"??_U@YAPEAX_K@Z\":\n"
    "  jmp malloc\n"
    "\n"
    ".globl \"??_V@YAXPEAX@Z\"\n"        /* operator delete[](void*)      */
    "\"??_V@YAXPEAX@Z\":\n"
    "  jmp free\n"
);

/* ---------- MSVC STL throw helpers ---------- */

/*
 * std::vector / std::string call these on capacity or bounds errors.
 * With -fno-exceptions the throw paths are unreachable at runtime,
 * but the linker still needs the symbols.
 */
__asm__(
    ".text\n"
    ".globl \"?_Xlength_error@std@@YAXPEBD@Z\"\n"
    "\"?_Xlength_error@std@@YAXPEBD@Z\":\n"
    "  jmp abort\n"
    "\n"
    ".globl \"?_Xout_of_range@std@@YAXPEBD@Z\"\n"
    "\"?_Xout_of_range@std@@YAXPEBD@Z\":\n"
    "  jmp abort\n"
);
