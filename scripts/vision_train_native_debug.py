"""Bounded Win64 exception observation for one owned, unmodified child process.

No target memory/register writes, symbol server, injected code or WER changes.
The debugger's presence is diagnostic instrumentation, not product qualification.
"""

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback


DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
BOOL = ctypes.c_int32
PTR = ctypes.c_void_p
SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_uint64
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
BREAKPOINT = 0x80000003
ACCESS_VIOLATION = 0xc0000005
DEBUG_ONLY_THIS_PROCESS = 0x00000002
MAX_EVENTS = 10000


class ExceptionRecord(ctypes.Structure):
  _fields_ = [('code', DWORD), ('flags', DWORD), ('nested', PTR), ('address', PTR),
              ('parameter_count', DWORD), ('parameters', ULONG_PTR * 15)]


class ExceptionInfo(ctypes.Structure):
  _fields_ = [('record', ExceptionRecord), ('first_chance', DWORD)]


class CreateThreadInfo(ctypes.Structure):
  _fields_ = [('thread', PTR), ('tls', PTR), ('start', PTR)]


class CreateProcessInfo(ctypes.Structure):
  _fields_ = [('file', PTR), ('process', PTR), ('thread', PTR), ('base', PTR),
              ('debug_offset', DWORD), ('debug_size', DWORD), ('tls', PTR),
              ('start', PTR), ('image_name', PTR), ('unicode', WORD)]


class ExitInfo(ctypes.Structure):
  _fields_ = [('code', DWORD)]


class LoadDllInfo(ctypes.Structure):
  _fields_ = [('file', PTR), ('base', PTR), ('debug_offset', DWORD), ('debug_size', DWORD),
              ('image_name', PTR), ('unicode', WORD)]


class UnloadDllInfo(ctypes.Structure):
  _fields_ = [('base', PTR)]


class DebugStringInfo(ctypes.Structure):
  _fields_ = [('data', PTR), ('unicode', WORD), ('length', WORD)]


class RipInfo(ctypes.Structure):
  _fields_ = [('error', DWORD), ('kind', DWORD)]


class EventData(ctypes.Union):
  _fields_ = [('exception', ExceptionInfo), ('create_thread', CreateThreadInfo),
              ('create_process', CreateProcessInfo), ('exit_thread', ExitInfo),
              ('exit_process', ExitInfo), ('load_dll', LoadDllInfo),
              ('unload_dll', UnloadDllInfo), ('debug_string', DebugStringInfo), ('rip', RipInfo)]


class DebugEvent(ctypes.Structure):
  _fields_ = [('code', DWORD), ('pid', DWORD), ('tid', DWORD), ('data', EventData)]


def require(value, message):
  if not value:
    raise RuntimeError(message)


def verifyLayout():
  require(ctypes.sizeof(PTR) == 8 and sys.byteorder == 'little', 'Only Win64 AMD64 layout is supported')
  expected = {ExceptionRecord: 152, ExceptionInfo: 160, CreateProcessInfo: 72,
              LoadDllInfo: 40, CreateThreadInfo: 24, DebugStringInfo: 16, DebugEvent: 176}
  for kind, size in expected.items():
    require(ctypes.sizeof(kind) == size, 'Incorrect native layout: ' + kind.__name__)
  offsets = [(ExceptionRecord.parameters, 32), (ExceptionInfo.first_chance, 152),
             (CreateProcessInfo.base, 24), (CreateProcessInfo.unicode, 64),
             (LoadDllInfo.image_name, 24), (LoadDllInfo.unicode, 32), (DebugEvent.data, 16)]
  require(ctypes.sizeof(DWORD) == 4 and ctypes.sizeof(BOOL) == 4
          and all(field.offset == offset for field, offset in offsets), 'Incorrect native field offsets')
  return {kind.__name__: size for kind, size in expected.items()}


def normalizedPath(value):
  if value.startswith('\\\\?\\UNC\\'):
    value = '\\\\' + value[8:]
  elif value.startswith('\\\\?\\'):
    value = value[4:]
  return os.path.normcase(os.path.normpath(value))


def imageSize(read, base):
  dos = read(base, 64)
  require(len(dos) == 64 and dos[:2] == b'MZ', 'Loaded image lacks a DOS header')
  offset = struct.unpack_from('<I', dos, 60)[0]
  require(64 <= offset <= 65536, 'Loaded PE header offset exceeds the read bound')
  pe = read(base + offset, 88)
  require(len(pe) == 88 and pe[:4] == b'PE\0\0'
          and struct.unpack_from('<H', pe, 4)[0] == 0x8664
          and struct.unpack_from('<H', pe, 24)[0] == 0x20b, 'Loaded image is not AMD64 PE32+')
  size = struct.unpack_from('<I', pe, 80)[0]
  require(4096 <= size <= 2**32 - 1 and base + size < 2**64, 'Invalid loaded SizeOfImage')
  return size


def addressRecord(address, modules, unloaded):
  matching = [dict(item, offset=address - item['base'], offset_hex=hex(address - item['base']))
              for item in modules.values() if item.get('size') and item['base'] <= address < item['base'] + item['size']]
  require(len(matching) <= 1, 'Overlapping active native image ranges')
  previous = [] if matching else [
    dict(item, offset=address - item['base'], offset_hex=hex(address - item['base']))
    for item in unloaded if item.get('size') and item['base'] <= address < item['base'] + item['size']]
  return {'address': address, 'address_hex': hex(address),
          'active_module': matching[0] if matching else None,
          'unloaded_candidates': previous[-20:]}


def exceptionRecord(event, state):
  value = event.data.exception
  require(event.pid == state['pid'], 'Exception belongs to an unexpected process')
  require(value.first_chance in (0, 1) and value.record.parameter_count <= 15,
          'Invalid native exception fields')
  record = {'code': value.record.code, 'code_hex': hex(value.record.code),
            'flags': value.record.flags, 'first_chance': bool(value.first_chance),
            'pid': event.pid, 'tid': event.tid,
            'parameters': list(value.record.parameters)[:value.record.parameter_count],
            'instruction': addressRecord(value.record.address or 0, state['modules'], state['unloaded'])}
  module = record['instruction']['active_module']
  initial = (state['created'] and state['exception_count'] == 0 and not state['initial_break_seen']
             and record['first_chance'] and record['code'] == BREAKPOINT
             and event.tid == state['initial_tid'] and module is not None
             and normalizedPath(module.get('path') or '') == state['system_ntdll'])
  if initial:
    state['initial_break_seen'] = True
  state['exception_count'] += 1
  record['expected_initial_break'] = initial
  record['continuation'] = 'DBG_CONTINUE' if initial else 'DBG_EXCEPTION_NOT_HANDLED'
  if record['code'] == ACCESS_VIOLATION and len(record['parameters']) >= 2:
    kind, address = record['parameters'][:2]
    record['memory_access'] = {'kind': {0: 'read', 1: 'write', 8: 'execute'}.get(kind, 'unknown'),
                               'raw_kind': kind, **addressRecord(address, state['modules'], state['unloaded'])}
  return record, DBG_CONTINUE if initial else DBG_EXCEPTION_NOT_HANDLED


class WindowsDebugApi:
  def __init__(self):
    require(os.name == 'nt', 'Native debugging requires actual Windows')
    self.layout = verifyLayout()
    self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    declarations = {
      'WaitForDebugEventEx': ([ctypes.POINTER(DebugEvent), DWORD], BOOL),
      'ContinueDebugEvent': ([DWORD, DWORD, DWORD], BOOL),
      'DebugSetProcessKillOnExit': ([BOOL], BOOL),
      'DebugActiveProcessStop': ([DWORD], BOOL),
      'CloseHandle': ([PTR], BOOL),
      'ReadProcessMemory': ([PTR, PTR, PTR, SIZE_T, ctypes.POINTER(SIZE_T)], BOOL),
      'GetFinalPathNameByHandleW': ([PTR, ctypes.c_wchar_p, DWORD, DWORD], DWORD),
      'K32GetModuleFileNameExW': ([PTR, PTR, ctypes.c_wchar_p, DWORD], DWORD),
      'GetSystemDirectoryW': ([ctypes.c_wchar_p, DWORD], DWORD),
    }
    for name, (arguments, result) in declarations.items():
      function = getattr(self.kernel, name)
      function.argtypes, function.restype = arguments, result
    buffer = ctypes.create_unicode_buffer(32768)
    count = self.kernel.GetSystemDirectoryW(buffer, len(buffer))
    require(0 < count < len(buffer), 'Cannot identify the actual Windows system directory')
    self.systemNtdll = normalizedPath(str(Path(buffer.value) / 'ntdll.dll'))

  def lastError(self):
    return ctypes.get_last_error()

  def read(self, process, address, count):
    require(0 < count <= 65536 and address > 0, 'Remote read exceeds the PE-header bound')
    buffer, copied = ctypes.create_string_buffer(count), SIZE_T()
    require(self.kernel.ReadProcessMemory(process, address, buffer, count, ctypes.byref(copied))
            and copied.value == count, 'Cannot read the complete loaded PE header')
    return buffer.raw

  def module(self, process, base, file):
    result = {'base': base, 'base_hex': hex(base), 'size': None, 'path': None}
    try:
      buffer = ctypes.create_unicode_buffer(32768)
      if file:
        count = self.kernel.GetFinalPathNameByHandleW(file, buffer, len(buffer), 0)
        result['path_source'] = 'debug-event-file-handle'
      else:
        count = self.kernel.K32GetModuleFileNameExW(process, base, buffer, len(buffer))
        result['path_source'] = 'K32GetModuleFileNameExW'
      require(0 < count < len(buffer), 'Native module filename was unavailable or truncated')
      result['path'] = normalizedPath(buffer.value)
    except Exception as error:
      result['path_error'] = str(error)
    try:
      result['size'] = imageSize(lambda address, count: self.read(process, address, count), base)
    except Exception as error:
      result['image_error'] = str(error)
    finally:
      if file:
        require(self.kernel.CloseHandle(file), 'Could not close a debugger image-file handle')
        result['file_handle_closed'] = True
    return result


def writeJson(path, value):
  path.write_text(json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + '\n', encoding='utf-8')


def cleanupDebugProcess(api, process, record, pending):
  """Kill only our child, then drain EXIT so Windows closes its debug-event handles."""
  record.update(status='FAIL', forced_cleanup=True, cleanup_errors=[], cleanup_events=[],
                cleanup_exit_event_continued=False)
  try:
    if process.poll() is None:
      process.kill()
    if pending is not None:
      status = DBG_EXCEPTION_NOT_HANDLED if pending.code == 1 else DBG_CONTINUE
      require(api.kernel.ContinueDebugEvent(pending.pid, pending.tid, status),
              'Cannot release pending event during owned cleanup')
      if pending.code == 5:
        record['cleanup_exit_event_continued'] = True
    deadline = time.monotonic() + 10
    while not record['cleanup_exit_event_continued']:
      require(time.monotonic() < deadline, 'Owned debug cleanup reached its deadline')
      require(len(record['cleanup_events']) < MAX_EVENTS, 'Owned debug cleanup exceeded its event bound')
      event = DebugEvent()
      if not api.kernel.WaitForDebugEventEx(ctypes.byref(event), 100):
        require(api.lastError() == 121, 'Owned cleanup debug wait failed')
        continue
      require(event.pid == process.pid, 'Owned cleanup received another process ID')
      entry = {'event': event.code, 'pid': event.pid, 'tid': event.tid}
      record['cleanup_events'].append(entry)
      status = DBG_EXCEPTION_NOT_HANDLED if event.code == 1 else DBG_CONTINUE
      try:
        file = (event.data.create_process.file if event.code == 3
                else event.data.load_dll.file if event.code == 6 else None)
        if file:
          require(api.kernel.CloseHandle(file), 'Cannot close cleanup image-file handle')
          entry['file_handle_closed'] = True
      finally:
        entry['continue_status'] = status
        require(api.kernel.ContinueDebugEvent(event.pid, event.tid, status),
                'Owned cleanup continuation failed')
      if event.code == 5:
        record.update(cleanup_exit_event_continued=True,
                      cleanup_debug_exit_code=event.data.exit_process.code)
  except Exception as error:
    record['cleanup_errors'].append(type(error).__name__ + ': ' + str(error))
    record['cleanup_detached'] = bool(api.kernel.DebugActiveProcessStop(process.pid))
    record['cleanup_handle_ownership'] = 'UNVERIFIED: debug API failed before an EXIT continuation'
  else:
    record['cleanup_handle_ownership'] = 'Windows closed event process/thread handles after continued EXIT'
  finally:
    try:
      if process.poll() is None and not record['cleanup_exit_event_continued']:
        process.kill()
      record['cleanup_exit_code'] = process.wait(timeout=15)
    except Exception as error:
      record['cleanup_errors'].append(type(error).__name__ + ': ' + str(error))


def debugProcess(command, directory, environment, *, timeout, closeWindow=None):
  """Observe only the process created here, using this same thread for every debug API."""
  require(not (directory / 'native-debug.json').exists(), 'Native debug report must be new')
  record = {'status': 'FAIL', 'debugger_observed': True, 'command': command,
            'timeout_seconds': timeout, 'events': [], 'exceptions': [],
            'initial_break_seen': False, 'pid': None, 'exit_code': None, 'forced_cleanup': False,
            'scope': 'Debugger-observed native exit; no target memory/register modification'}
  try:
    api = WindowsDebugApi()
    record['layout'] = api.layout
  except Exception as error:
    record.update(error=str(error), traceback=traceback.format_exc(), stage='native-api-setup')
    writeJson(directory / 'native-debug.json', record)
    return record
  started = time.monotonic()
  state = {'created': False, 'initial_tid': None, 'initial_break_seen': False, 'exception_count': 0,
           'system_ntdll': api.systemNtdll, 'modules': {}, 'unloaded': []}
  with (directory / 'native.stdout.txt').open('w', encoding='utf-8') as stdout, \
       (directory / 'native.stderr.txt').open('w', encoding='utf-8') as stderr:
    try:
      process = subprocess.Popen(command, cwd=directory.parent / 'empty-cwd', env=environment,
                                 stdout=stdout, stderr=stderr,
                                 creationflags=DEBUG_ONLY_THIS_PROCESS)
    except Exception as error:
      record.update(error=str(error), traceback=traceback.format_exc(), stage='create-process')
      writeJson(directory / 'native-debug.json', record)
      return record
    state['pid'] = record['pid'] = process.pid
    nativeProcess = None
    sawExit = False
    pending = None
    try:
      require(api.kernel.DebugSetProcessKillOnExit(True), 'Cannot retain owned debugger cleanup policy')
      while not sawExit:
        require(time.monotonic() - started < timeout, 'Native debugger reached its fixed deadline')
        require(len(record['events']) < MAX_EVENTS, 'Native debug event budget exceeded')
        event = DebugEvent()
        if not api.kernel.WaitForDebugEventEx(ctypes.byref(event), 100):
          require(api.lastError() == 121, 'WaitForDebugEventEx failed with ' + str(api.lastError()))
        else:
          require(event.pid == process.pid, 'Debugger received an unexpected process ID')
          pending = event
          continued = DBG_EXCEPTION_NOT_HANDLED if event.code == 1 else DBG_CONTINUE
          entry = {'sequence': len(record['events']) + 1, 'elapsed_seconds': round(time.monotonic() - started, 6),
                   'event': event.code, 'pid': event.pid, 'tid': event.tid}
          record['events'].append(entry)
          try:
            if event.code == 3:
              info = event.data.create_process
              module = api.module(info.process, info.base, info.file)
              require(not state['created'], 'Duplicate process creation event')
              nativeProcess = info.process
              state.update(created=True, initial_tid=event.tid)
              require(module.get('path') == normalizedPath(command[0]), 'Created native image differs from requested executable')
              module['load_sequence'] = entry['sequence']
              state['modules'][info.base] = module
              entry['module'] = module
            elif event.code == 6:
              info = event.data.load_dll
              module = api.module(nativeProcess, info.base, info.file)
              require(state['created'] and info.base not in state['modules'], 'Unexpected active native image base')
              module['load_sequence'] = entry['sequence']
              state['modules'][info.base] = module
              entry['module'] = module
            elif event.code == 7:
              base = event.data.unload_dll.base
              previous = state['modules'].pop(base, None)
              entry['base'] = base
              if previous:
                previous = dict(previous, unload_sequence=entry['sequence'])
                state['unloaded'].append(previous)
                entry['module'] = previous
            elif event.code == 1:
              detail, continued = exceptionRecord(event, state)
              entry['exception'] = detail
              record['exceptions'].append(detail)
            elif event.code == 5:
              record['debug_exit_code'] = event.data.exit_process.code
            elif event.code == 9:
              entry['rip_error'], entry['rip_type'] = event.data.rip.error, event.data.rip.kind
          finally:
            entry['continue_status'] = continued
            require(api.kernel.ContinueDebugEvent(event.pid, event.tid, continued), 'ContinueDebugEvent failed')
            pending = None
            if event.code == 5:
              sawExit = True
        # Observe windows only while the child is running, after continuation.
        if closeWindow and not sawExit:
          closeWindow(process.pid, record, time.monotonic() - started)
      # Windows closes debug-event process/thread handles on the EXIT continuation.
      record['exit_code'] = process.wait(timeout=15)
      require(record['exit_code'] == record['debug_exit_code'], 'Debugger and process exit codes disagree')
      require(state['initial_break_seen'], 'Expected initial Windows debugger breakpoint was not observed')
      record['status'] = 'PASS' if record['exit_code'] == 0 else 'FAIL'
    except Exception as error:
      record.update(error=str(error), traceback=traceback.format_exc())
    finally:
      try:
        if not sawExit:
          cleanupDebugProcess(api, process, record, pending)
      finally:
        record.update(initial_break_seen=state['initial_break_seen'], active_modules=list(state['modules'].values()),
                      unloaded_modules=state['unloaded'], elapsed_seconds=round(time.monotonic() - started, 3))
        writeJson(directory / 'native-debug.json', record)
  return record


def fixtureChild(kind):
  require(os.name == 'nt', 'The native exception fixture requires Windows')
  print(json.dumps({'fixture': kind, 'pid': os.getpid(), 'executable': sys.executable}), flush=True)
  if kind == 'normal':
    return 0
  require(kind == 'access-violation', 'Unknown fixed native fixture')
  kernel = ctypes.WinDLL('kernel32', use_last_error=True)
  kernel.CreateThread.argtypes = [PTR, SIZE_T, PTR, PTR, DWORD, ctypes.POINTER(DWORD)]
  kernel.CreateThread.restype = PTR
  kernel.WaitForSingleObject.argtypes = [PTR, DWORD]
  kernel.WaitForSingleObject.restype = DWORD
  kernel.CloseHandle.argtypes, kernel.CloseHandle.restype = [PTR], BOOL
  tid = DWORD()
  # Only this disposable fixture creates a null-start thread: an actual unhandled execute fault.
  thread = kernel.CreateThread(None, 0, None, None, 0, ctypes.byref(tid))
  require(thread, 'Native null-start fixture thread was not created')
  try:
    kernel.WaitForSingleObject(thread, 10000)
  finally:
    kernel.CloseHandle(thread)
  raise RuntimeError('Expected native access violation did not terminate the fixture')


def fixtureMarker(path, kind, pid, executable):
  raw = path.read_bytes()
  require(0 < len(raw) <= 16384, 'Native fixture marker is empty or too large')
  value = json.loads(raw)
  require(isinstance(value, dict) and set(value) == {'fixture', 'pid', 'executable'}
          and value['fixture'] == kind and type(value['pid']) is int and value['pid'] == pid
          and isinstance(value['executable'], str)
          and normalizedPath(value['executable']) == normalizedPath(executable),
          'Native fixture marker does not identify the observed child')
  return {'marker': value, 'sha256': hashlib.sha256(raw).hexdigest()}


def runFixtures(output):
  require(not output.exists(), 'Native fixture report directory must be new')
  output.mkdir(parents=True)
  basePython = Path(getattr(sys, '_base_executable', sys.executable)).resolve()
  require(basePython.is_file() and basePython.name.casefold() == 'python.exe'
          and basePython.parent == Path(sys.base_prefix).resolve(),
          'Native fixtures require the actual base CPython executable, not a venv redirector')
  records = []
  for kind in ('normal', 'access-violation'):
    case = output / kind
    reports = case / 'reports'
    reports.mkdir(parents=True)
    (case / 'empty-cwd').mkdir()
    command = [str(basePython), '-I', '-S', '-B', str(Path(__file__).resolve()), '--fixture-child', kind]
    result = debugProcess(command, reports, os.environ.copy(), timeout=30)
    marker, markerError = None, None
    try:
      marker = fixtureMarker(reports / 'native.stdout.txt', kind, result['pid'], str(basePython))
    except Exception as error:
      markerError = type(error).__name__ + ': ' + str(error)
    expected = 0 if kind == 'normal' else ACCESS_VIOLATION
    second = [item for item in result['exceptions'] if not item['first_chance']]
    qualified = (marker is not None and result.get('exit_code') == expected and not result['forced_cleanup']
                 and result['initial_break_seen'] and 'error' not in result
                 and (not second if kind == 'normal' else any(
                   item['code'] == ACCESS_VIOLATION and item['continuation'] == 'DBG_EXCEPTION_NOT_HANDLED'
                   and item.get('memory_access', {}).get('kind') == 'execute'
                   and item['memory_access']['address'] == 0 for item in second)))
    records.append({'fixture': kind, 'verification': 'PASS' if qualified else 'FAIL',
                    'actual_process_status': result['status'], 'actual_exit_code': result.get('exit_code'),
                    'fixture_marker': marker, 'fixture_marker_error': markerError,
                    'report_sha256': hashlib.sha256((reports / 'native-debug.json').read_bytes()).hexdigest()})
  result = {'status': 'PASS' if all(item['verification'] == 'PASS' for item in records) else 'FAIL',
            'scope': 'Actual Windows stdlib child/exception controller fixtures, not product qualification',
            'controller_executable': sys.executable, 'base_python': str(basePython), 'fixtures': records}
  writeJson(output / 'native-fixture-summary.json', result)
  return 0 if result['status'] == 'PASS' else 1


def main():
  parser = argparse.ArgumentParser(description=__doc__)
  group = parser.add_mutually_exclusive_group(required=True)
  group.add_argument('--fixture-child', choices=('normal', 'access-violation'))
  group.add_argument('--fixture-output', type=Path)
  arguments = parser.parse_args()
  if arguments.fixture_child:
    return fixtureChild(arguments.fixture_child)
  return runFixtures(arguments.fixture_output.resolve())


if __name__ == '__main__':
  raise SystemExit(main())
