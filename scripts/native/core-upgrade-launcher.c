/* Stable Windows entry point for the installed Core and its offline transaction. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <shellapi.h>
#include <stdio.h>
#include <string.h>
#include <wchar.h>

enum {
    PATH_CAPACITY = 32768,
    LOCK_BUSY = 41,
    RECOVERY_REQUIRED = 42,
    CONTROL_INVALID = 43,
    PROCESS_FAILED = 44,
    USAGE_ERROR = 64
};

enum {
    TRANSACTION_READY = 0,
    TRANSACTION_RECOVERY = 1,
    TRANSACTION_CLEANUP = 2
};

static wchar_t root[PATH_CAPACITY];
static wchar_t control[PATH_CAPACITY];
static wchar_t marker[PATH_CAPACITY];
static wchar_t transaction[PATH_CAPACITY];
static wchar_t plan[PATH_CAPACITY];
static wchar_t retired_trial[PATH_CAPACITY];
static wchar_t resolved[PATH_CAPACITY];
static wchar_t cleanup_receipt[PATH_CAPACITY];
static wchar_t upgrade_lock[PATH_CAPACITY];
static wchar_t inner[PATH_CAPACITY];
static wchar_t runner_directory[PATH_CAPACITY];
static wchar_t runner[PATH_CAPACITY];
static wchar_t runner_digest[PATH_CAPACITY];
static wchar_t archive[PATH_CAPACITY];
static wchar_t command[PATH_CAPACITY];
static wchar_t prepare_arguments[PATH_CAPACITY];

static HANDLE plain_path(const wchar_t *path, DWORD access, DWORD share, DWORD disposition, BOOL directory)
{
    DWORD flags = FILE_FLAG_OPEN_REPARSE_POINT;
    if (directory)
        flags |= FILE_FLAG_BACKUP_SEMANTICS;
    HANDLE file = CreateFileW(path, access, share, NULL, disposition, flags, NULL);
    if (file == INVALID_HANDLE_VALUE)
        return file;

    BY_HANDLE_FILE_INFORMATION info;
    DWORD required = directory ? FILE_ATTRIBUTE_DIRECTORY : 0;
    if (!GetFileInformationByHandle(file, &info) ||
        (info.dwFileAttributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != required ||
        (!directory && GetFileType(file) != FILE_TYPE_DISK)) {
        CloseHandle(file);
        SetLastError(ERROR_INVALID_DATA);
        return INVALID_HANDLE_VALUE;
    }
    return file;
}

static BOOL extended_local_path(const wchar_t *input, wchar_t *output)
{
    const wchar_t *drive = input;
    if (wcsncmp(drive, L"\\\\?\\", 4) == 0)
        drive += 4;
    if (wcslen(drive) < 3 || !((drive[0] >= L'A' && drive[0] <= L'Z') ||
                             (drive[0] >= L'a' && drive[0] <= L'z')) ||
        drive[1] != L':' || drive[2] != L'\\' || wcspbrk(drive + 3, L":\"") != NULL ||
        wcslen(drive) + 4 >= PATH_CAPACITY)
        return FALSE;
    return swprintf_s(output, PATH_CAPACITY, L"\\\\?\\%ls", drive) >= 0;
}

static BOOL joined(wchar_t *output, const wchar_t *directory, const wchar_t *name)
{
    size_t length = wcslen(directory);
    const wchar_t *separator = directory[length - 1] == L'\\' ? L"" : L"\\";
    return length + wcslen(separator) + wcslen(name) < PATH_CAPACITY &&
           swprintf_s(output, PATH_CAPACITY, L"%ls%ls%ls", directory, separator, name) >= 0;
}

static const wchar_t *child_path(const wchar_t *extended)
{
    const wchar_t *ordinary = extended + 4;
    size_t length = wcslen(ordinary);
    if (length >= MAX_PATH)
        return extended;
    for (const wchar_t *cursor = ordinary + 3; *cursor; ++cursor) {
        if ((*cursor == L'\\' && (cursor[-1] == L'.' || cursor[-1] == L' ')) ||
            (!cursor[1] && (*cursor == L'.' || *cursor == L' ')))
            return extended;
    }
    return ordinary;
}

/* The path is an extended local drive path. Check each directory without following junctions. */
static HANDLE plain_directories(wchar_t *path)
{
    wchar_t *component = path + 7;
    if (*component == L'\0')
        return plain_path(path, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE, OPEN_EXISTING, TRUE);

    for (;;) {
        wchar_t *separator = wcschr(component, L'\\');
        if (separator)
            *separator = L'\0';
        HANDLE directory = INVALID_HANDLE_VALUE;
        if (*component && wcscmp(component, L".") != 0 && wcscmp(component, L"..") != 0) {
            directory = plain_path(path, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                   OPEN_EXISTING, TRUE);
        }
        if (separator)
            *separator = L'\\';
        if (directory == INVALID_HANDLE_VALUE || !separator)
            return directory;
        CloseHandle(directory);
        component = separator + 1;
    }
}

static BOOL locate_installation(void)
{
    wchar_t executable[PATH_CAPACITY];
    DWORD length = GetModuleFileNameW(NULL, executable, PATH_CAPACITY);
    if (!length || length >= PATH_CAPACITY || !extended_local_path(executable, root))
        return FALSE;
    wchar_t *separator = wcsrchr(root, L'\\');
    separator[separator == root + 6 ? 1 : 0] = L'\0';
    return joined(control, root, L".core-update") &&
           joined(inner, root, L"VisionWorkshop.exe") &&
           joined(marker, control, L"current-trial.json") &&
           joined(transaction, control, L"transaction") &&
           joined(plan, transaction, L"plan.json") &&
           joined(retired_trial, transaction, L"retired-trial.json") &&
           joined(resolved, transaction, L"resolved.json") &&
           joined(cleanup_receipt, transaction, L"cleanup-complete.json") &&
           joined(upgrade_lock, control, L"upgrade.lock") &&
           joined(runner_directory, control, L"runner") &&
           joined(runner, runner_directory, L"VisionWorkshop.exe") &&
           joined(runner_digest, control, L"runner.sha256");
}

static BOOL local_ntfs(HANDLE directory)
{
    wchar_t drive[] = {root[4], L':', L'\\', L'\0'};
    wchar_t filesystem[16];
    return GetDriveTypeW(drive) == DRIVE_FIXED &&
           GetVolumeInformationByHandleW(directory, NULL, 0, NULL, NULL, NULL,
                                         filesystem, ARRAYSIZE(filesystem)) &&
           wcscmp(filesystem, L"NTFS") == 0;
}

/* 0 is genuine absence, 1 is a regular file, and -1 is invalid or inaccessible. */
static int file_state(const wchar_t *path)
{
    HANDLE file = plain_path(path, FILE_READ_ATTRIBUTES,
                             FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, OPEN_EXISTING, FALSE);
    if (file == INVALID_HANDLE_VALUE)
        return GetLastError() == ERROR_FILE_NOT_FOUND ? 0 : -1;
    CloseHandle(file);
    return 1;
}

static int pending_transaction(void)
{
    int marked = file_state(marker);
    if (marked)
        return marked;

    HANDLE directory = plain_path(transaction, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  OPEN_EXISTING, TRUE);
    if (directory == INVALID_HANDLE_VALUE)
        return GetLastError() == ERROR_FILE_NOT_FOUND ? 0 : -1;
    int state = file_state(plan);
    if (state == 1) {
        int retired = file_state(retired_trial);
        if (retired < 0) {
            state = -1;
        } else if (!retired) {
            /* A plan may have reached disk before the process could publish its marker. */
            state = TRANSACTION_RECOVERY;
        } else {
            int outcome = file_state(resolved);
            int receipt = file_state(cleanup_receipt);
            state = outcome != 1 || receipt < 0 ? -1 :
                    receipt == 0 ? TRANSACTION_CLEANUP : TRANSACTION_READY;
        }
    }
    CloseHandle(directory);
    return state;
}

static int hex_value(wchar_t digit)
{
    if (digit >= L'0' && digit <= L'9')
        return (int)(digit - L'0');
    if (digit >= L'a' && digit <= L'f')
        return (int)(digit - L'a') + 10;
    if (digit >= L'A' && digit <= L'F')
        return (int)(digit - L'A') + 10;
    return -1;
}

static BOOL hash_runner(HANDLE file, BYTE output[32])
{
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    BYTE buffer[64 * 1024];
    DWORD size;
    BOOL ok = FALSE;
    if (BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0) < 0 ||
        BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) < 0)
        goto cleanup;

    do {
        if (!ReadFile(file, buffer, (DWORD)sizeof(buffer), &size, NULL) ||
            (size && BCryptHashData(hash, buffer, size, 0) < 0))
            goto cleanup;
    } while (size);
    ok = BCryptFinishHash(hash, output, 32, 0) >= 0;

cleanup:
    if (hash)
        BCryptDestroyHash(hash);
    if (algorithm)
        BCryptCloseAlgorithmProvider(algorithm, 0);
    return ok;
}

static BOOL matches_runner_receipt(HANDLE image)
{
    HANDLE receipt = plain_path(runner_digest, GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FALSE);
    if (receipt == INVALID_HANDLE_VALUE)
        return FALSE;

    BYTE text[67], expected[32], actual[32];
    DWORD length;
    BOOL read = ReadFile(receipt, text, (DWORD)sizeof(text), &length, NULL);
    CloseHandle(receipt);
    if (!read || !(length == 64 || (length == 65 && text[64] == '\n') ||
                   (length == 66 && text[64] == '\r' && text[65] == '\n')))
        return FALSE;
    for (size_t i = 0; i < ARRAYSIZE(expected); ++i) {
        int high = hex_value(text[2 * i]);
        int low = hex_value(text[2 * i + 1]);
        if (high < 0 || low < 0)
            return FALSE;
        expected[i] = (BYTE)((high << 4) | low);
    }
    return hash_runner(image, actual) && memcmp(actual, expected, sizeof(expected)) == 0;
}

/* Forward only the caller's standard streams to the fixed child executable. */
static HANDLE start_child(const wchar_t *image, const wchar_t *arguments)
{
    image = child_path(image);
    if (wcslen(image) + wcslen(arguments) + 3 >= PATH_CAPACITY ||
        swprintf_s(command, PATH_CAPACITY, L"\"%ls\" %ls", image, arguments) < 0)
        return NULL;

    STARTUPINFOEXW startup = {0};
    PROCESS_INFORMATION child = {0};
    HANDLE original[] = {GetStdHandle(STD_INPUT_HANDLE), GetStdHandle(STD_OUTPUT_HANDLE),
                         GetStdHandle(STD_ERROR_HANDLE)};
    HANDLE forwarded[3] = {NULL};
    SECURITY_ATTRIBUTES inherit = {sizeof(inherit), NULL, TRUE};
    SIZE_T attribute_size = 0;
    BOOL has_stream = FALSE;
    HANDLE process = NULL;
    for (size_t i = 0; i < ARRAYSIZE(original); ++i)
        has_stream |= original[i] != NULL && original[i] != INVALID_HANDLE_VALUE;

    if (has_stream) {
        for (size_t i = 0; i < ARRAYSIZE(original); ++i) {
            HANDLE source = original[i];
            if (!source || source == INVALID_HANDLE_VALUE) {
                forwarded[i] = CreateFileW(L"NUL", i == 0 ? GENERIC_READ : GENERIC_WRITE,
                                           FILE_SHARE_READ | FILE_SHARE_WRITE, &inherit, OPEN_EXISTING, 0, NULL);
                if (forwarded[i] == INVALID_HANDLE_VALUE)
                    goto cleanup;
            } else if (!DuplicateHandle(GetCurrentProcess(), source, GetCurrentProcess(), &forwarded[i],
                                        0, TRUE, DUPLICATE_SAME_ACCESS)) {
                goto cleanup;
            }
        }
        InitializeProcThreadAttributeList(NULL, 1, 0, &attribute_size);
        LPPROC_THREAD_ATTRIBUTE_LIST list = HeapAlloc(GetProcessHeap(), 0, attribute_size);
        if (!list)
            goto cleanup;
        if (!InitializeProcThreadAttributeList(list, 1, 0, &attribute_size)) {
            HeapFree(GetProcessHeap(), 0, list);
            goto cleanup;
        }
        startup.lpAttributeList = list;
        if (!UpdateProcThreadAttribute(list, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, forwarded,
                                       sizeof(forwarded), NULL, NULL))
            goto cleanup;
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = forwarded[0];
        startup.StartupInfo.hStdOutput = forwarded[1];
        startup.StartupInfo.hStdError = forwarded[2];
    }
    startup.StartupInfo.cb = has_stream ? sizeof(startup) : sizeof(STARTUPINFOW);
    if (CreateProcessW(image, command, NULL, NULL, has_stream,
                       has_stream ? EXTENDED_STARTUPINFO_PRESENT : 0,
                       NULL, NULL, &startup.StartupInfo, &child)) {
        CloseHandle(child.hThread);
        process = child.hProcess;
    }

cleanup:
    if (startup.lpAttributeList) {
        DeleteProcThreadAttributeList(startup.lpAttributeList);
        HeapFree(GetProcessHeap(), 0, startup.lpAttributeList);
    }
    for (size_t i = 0; i < ARRAYSIZE(forwarded); ++i) {
        if (forwarded[i] && forwarded[i] != INVALID_HANDLE_VALUE)
            CloseHandle(forwarded[i]);
    }
    return process;
}

static DWORD wait_child(HANDLE process)
{
    if (!process)
        return PROCESS_FAILED;
    DWORD code = PROCESS_FAILED;
    if (WaitForSingleObject(process, INFINITE) != WAIT_OBJECT_0 || !GetExitCodeProcess(process, &code))
        code = PROCESS_FAILED;
    CloseHandle(process);
    return code;
}

static DWORD run_core(const wchar_t *arguments)
{
    HANDLE image = plain_path(inner, GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FALSE);
    if (image == INVALID_HANDLE_VALUE)
        return CONTROL_INVALID;
    HANDLE process = start_child(inner, arguments);
    CloseHandle(image);
    return wait_child(process);
}

static DWORD run_runner(const wchar_t *arguments)
{
    HANDLE directory = plain_directories(runner_directory);
    if (directory == INVALID_HANDLE_VALUE)
        return CONTROL_INVALID;
    HANDLE image = plain_path(runner, GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FALSE);
    BOOL verified = image != INVALID_HANDLE_VALUE && matches_runner_receipt(image);
    HANDLE process = verified ? start_child(runner, arguments) : NULL;
    if (image != INVALID_HANDLE_VALUE)
        CloseHandle(image);
    CloseHandle(directory);
    return verified ? wait_child(process) : CONTROL_INVALID;
}

static HANDLE open_archive(const wchar_t *argument, const wchar_t *digest)
{
    wchar_t absolute[PATH_CAPACITY];
    wchar_t normalized_digest[65];
    if (wcslen(digest) != 64)
        return INVALID_HANDLE_VALUE;
    for (size_t i = 0; i < 64; ++i) {
        int value = hex_value(digest[i]);
        if (value < 0)
            return INVALID_HANDLE_VALUE;
        normalized_digest[i] = L"0123456789abcdef"[value];
    }
    normalized_digest[64] = L'\0';
    DWORD length = GetFullPathNameW(argument, PATH_CAPACITY, absolute, NULL);
    if (!length || length >= PATH_CAPACITY || !extended_local_path(absolute, archive))
        return INVALID_HANDLE_VALUE;
    wchar_t drive[] = {archive[4], L':', L'\\', L'\0'};
    UINT type = GetDriveTypeW(drive);
    if (type != DRIVE_FIXED && type != DRIVE_REMOVABLE && type != DRIVE_CDROM)
        return INVALID_HANDLE_VALUE;

    wchar_t *separator = wcsrchr(archive, L'\\');
    wchar_t *parent_end = separator == archive + 6 ? separator + 1 : separator;
    wchar_t saved = *parent_end;
    *parent_end = L'\0';
    HANDLE parent = plain_directories(archive);
    *parent_end = saved;
    if (parent == INVALID_HANDLE_VALUE)
        return parent;
    HANDLE file = plain_path(archive, GENERIC_READ, FILE_SHARE_READ, OPEN_EXISTING, FALSE);
    CloseHandle(parent);
    if (file == INVALID_HANDLE_VALUE)
        return file;
    static const wchar_t prepare[] = L"--prepare-core-upgrade";
    const wchar_t *source = child_path(archive);
    if (wcslen(source) + ARRAYSIZE(prepare) + ARRAYSIZE(normalized_digest) + 3 >= PATH_CAPACITY ||
        swprintf_s(prepare_arguments, PATH_CAPACITY, L"%ls \"%ls\" %ls",
                   prepare, source, normalized_digest) < 0) {
        CloseHandle(file);
        return INVALID_HANDLE_VALUE;
    }
    return file;
}

static DWORD retire(void)
{
    DWORD result = run_core(L"--retire-core-upgrade");
    if (result != 0)
        return result;
    int state = pending_transaction();
    return state < 0 ? CONTROL_INVALID : state ? RECOVERY_REQUIRED : 0;
}

static DWORD run_transaction(BOOL upgrade)
{
    HANDLE lease = plain_path(upgrade_lock, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                              OPEN_ALWAYS, FALSE);
    if (lease == INVALID_HANDLE_VALUE)
        return CONTROL_INVALID;
    OVERLAPPED first_byte = {0};
    DWORD result = CONTROL_INVALID;
    if (!LockFileEx(lease, LOCKFILE_EXCLUSIVE_LOCK | LOCKFILE_FAIL_IMMEDIATELY, 0, 1, 0, &first_byte)) {
        if (GetLastError() == ERROR_LOCK_VIOLATION)
            result = LOCK_BUSY;
        CloseHandle(lease);
        return result;
    }

    int state = pending_transaction();
    if (state >= 0) {
        result = 0;
        if (state == TRANSACTION_RECOVERY) {
            result = run_runner(L"--recover-core-upgrade");
            if (result == 0)
                result = retire();
        } else if (state == TRANSACTION_CLEANUP) {
            result = retire();
        }
        if (result == 0 && upgrade) {
            result = run_core(prepare_arguments);
            if (result == 0)
                result = run_runner(L"--apply-core-upgrade");
            if (result == 0)
                result = retire();
        }
    }
    UnlockFileEx(lease, 0, 1, 0, &first_byte);
    CloseHandle(lease);
    return result;
}

static BOOL private_argument(const wchar_t *value)
{
    return wcscmp(value, L"--prepare-core-upgrade") == 0 ||
           wcscmp(value, L"--apply-core-upgrade") == 0 ||
           wcscmp(value, L"--recover-core-upgrade") == 0 ||
           wcscmp(value, L"--retire-core-upgrade") == 0;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show)
{
    (void)instance;
    (void)previous;
    (void)show;
    int count;
    LPWSTR *values = CommandLineToArgvW(GetCommandLineW(), &count);
    if (!values)
        return CONTROL_INVALID;

    DWORD result = CONTROL_INVALID;
    HANDLE source = INVALID_HANDLE_VALUE;
    HANDLE installation = INVALID_HANDLE_VALUE;
    HANDLE control_directory = INVALID_HANDLE_VALUE;
    BOOL upgrade = count > 1 && wcscmp(values[1], L"--upgrade-core") == 0;
    if (count > 1 && private_argument(values[1])) {
        result = USAGE_ERROR;
        goto cleanup;
    }
    if (upgrade) {
        if (count == 4)
            source = open_archive(values[2], values[3]);
        if (source == INVALID_HANDLE_VALUE) {
            result = USAGE_ERROR;
            goto cleanup;
        }
    }
    if (!locate_installation())
        goto cleanup;
    installation = plain_directories(root);
    if (installation == INVALID_HANDLE_VALUE || !local_ntfs(installation))
        goto cleanup;
    control_directory = plain_path(control, FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                   OPEN_EXISTING, TRUE);
    if (control_directory == INVALID_HANDLE_VALUE)
        goto cleanup;

    int state = pending_transaction();
    if (state < 0)
        goto cleanup;
    result = (state || upgrade) ? run_transaction(upgrade) : 0;
    if (result == 0 && !upgrade)
        result = run_core(arguments);

cleanup:
    if (control_directory != INVALID_HANDLE_VALUE)
        CloseHandle(control_directory);
    if (installation != INVALID_HANDLE_VALUE)
        CloseHandle(installation);
    if (source != INVALID_HANDLE_VALUE)
        CloseHandle(source);
    LocalFree(values);
    return (int)result;
}
