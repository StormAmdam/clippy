/* Clippy.exe: starts Clippy from the folder it sits in (python\pythonw.exe -m clippy app), with no console window.
   Everything Clippy needs lives next to this file, so the folder can be moved, copied or deleted as a whole. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <wchar.h>

#define BIG 32768

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR args, int show) {
    static wchar_t dir[BIG], py[BIG], cmd[BIG * 2];
    DWORD n = GetModuleFileNameW(NULL, dir, BIG);
    if (n == 0 || n >= BIG) return 1;
    wchar_t *slash = wcsrchr(dir, L'\\');
    if (slash) *slash = 0;

    swprintf(py, BIG, L"%s\\python\\pythonw.exe", dir);
    if (GetFileAttributesW(py) == INVALID_FILE_ATTRIBUTES) {
        MessageBoxW(NULL, L"Some of Clippy's files are missing (python\\pythonw.exe).\n\nPlease install Clippy again.",
                    L"Clippy", MB_ICONERROR);
        return 1;
    }
    swprintf(cmd, BIG * 2, L"\"%s\" -X utf8 -m clippy app %s", py, args ? args : L"");  /* UTF-8 mode: emoji, titles */
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    if (!CreateProcessW(py, cmd, NULL, NULL, FALSE, 0, NULL, dir, &si, &pi)) {
        MessageBoxW(NULL, L"Clippy couldn't start. Please install it again.", L"Clippy", MB_ICONERROR);
        return 1;
    }
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
