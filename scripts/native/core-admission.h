/* Windows P4 admission guard, before the windowed bootloader loads Python. */
#include <wchar.h>

enum { CORE_LOCK_BUSY = 41, CORE_RECOVERY_REQUIRED = 42, CORE_GUARD_FAILED = 43 };
enum { CORE_PATH_CAPACITY = 32768 };

static wchar_t core_control[CORE_PATH_CAPACITY];
static wchar_t core_lock_path[CORE_PATH_CAPACITY];
static wchar_t core_marker_path[CORE_PATH_CAPACITY];

static int
core_checked_attributes(HANDLE file, DWORD required)
{
    BY_HANDLE_FILE_INFORMATION info;
    DWORD checked = FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT;
    return GetFileInformationByHandle(file, &info) && (info.dwFileAttributes & checked) == required;
}

static int
core_build_guard_paths(void)
{
    DWORD length = GetModuleFileNameW(NULL, core_control, CORE_PATH_CAPACITY);
    if (!length || length >= CORE_PATH_CAPACITY) {
        return 0;
    }
    wchar_t *separator = wcsrchr(core_control, L'\\');
    static const wchar_t control_name[] = L".core-update";
    if (!separator || wcscpy_s(separator + 1, CORE_PATH_CAPACITY - (separator + 1 - core_control), control_name)) {
        return 0;
    }
    return swprintf_s(core_lock_path, CORE_PATH_CAPACITY, L"%ls\\launch.lock", core_control) >= 0 &&
           swprintf_s(core_marker_path, CORE_PATH_CAPACITY, L"%ls\\current-trial.json", core_control) >= 0;
}

static int
core_admitted_main(struct PYI_CONTEXT *pyi_ctx)
{
    if (!core_build_guard_paths()) {
        return CORE_GUARD_FAILED;
    }
    HANDLE control = CreateFileW(core_control, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                NULL, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (control == INVALID_HANDLE_VALUE) {
        return CORE_GUARD_FAILED;
    }
    HANDLE lease = INVALID_HANDLE_VALUE;
    int result = CORE_GUARD_FAILED;
    OVERLAPPED first_byte = {0};
    if (!core_checked_attributes(control, FILE_ATTRIBUTE_DIRECTORY)) {
        goto cleanup;
    }
    lease = CreateFileW(core_lock_path, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                        NULL, OPEN_EXISTING, FILE_FLAG_OPEN_REPARSE_POINT, NULL);
    if (lease == INVALID_HANDLE_VALUE || !core_checked_attributes(lease, 0)) {
        goto cleanup;
    }
    if (!LockFileEx(lease, LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &first_byte)) {
        if (GetLastError() == ERROR_LOCK_VIOLATION) {
            result = CORE_LOCK_BUSY;
        }
        goto cleanup;
    }
    DWORD marker = GetFileAttributesW(core_marker_path);
    if (marker != INVALID_FILE_ATTRIBUTES || GetLastError() != ERROR_FILE_NOT_FOUND) {
        result = CORE_RECOVERY_REQUIRED;
    } else {
        result = pyi_main(pyi_ctx);
    }
    UnlockFileEx(lease, 0, 1, 0, &first_byte);

cleanup:
    if (lease != INVALID_HANDLE_VALUE) {
        CloseHandle(lease);
    }
    CloseHandle(control);
    return result;
}
