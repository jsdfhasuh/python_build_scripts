"""Native ABI/policy and owned-cleanup guards; actual Windows fixtures run separately."""

import ctypes
import json
from pathlib import Path
import struct
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from scripts import diagnose_vision_train_core as diagnostic
from scripts import vision_train_dll_search_probe as search
from scripts import vision_train_native_debug as native


class NativeDebugTests(unittest.TestCase):
  def state(self):
    path = native.normalizedPath(r'C:\Windows\System32\ntdll.dll')
    return {'pid': 42, 'initial_tid': 43, 'created': True, 'exception_count': 0,
            'initial_break_seen': False, 'system_ntdll': path,
            'modules': {0x100000: {'base': 0x100000, 'size': 0x10000, 'path': path}},
            'unloaded': []}

  def exception(self, code=native.BREAKPOINT, first=1, address=0x101234):
    event = native.DebugEvent()
    event.code, event.pid, event.tid = 1, 42, 43
    event.data.exception.first_chance = first
    event.data.exception.record.code = code
    event.data.exception.record.address = address
    return event

  def test_fixed_32_bit_fields_and_x64_offsets(self):
    self.assertEqual(native.verifyLayout()['DebugEvent'], 176)
    self.assertEqual(ctypes.sizeof(native.DWORD), 4)
    self.assertEqual(native.ExceptionRecord.parameters.offset, 32)
    self.assertEqual(native.DebugEvent.data.offset, 16)
    self.assertEqual(native.DEBUG_ONLY_THIS_PROCESS, 0x2)

  def test_only_the_first_expected_ntdll_break_is_handled(self):
    state = self.state()
    record, continuation = native.exceptionRecord(self.exception(), state)
    self.assertEqual(continuation, native.DBG_CONTINUE)
    self.assertTrue(record['expected_initial_break'])
    record, continuation = native.exceptionRecord(self.exception(), state)
    self.assertEqual(continuation, native.DBG_EXCEPTION_NOT_HANDLED)
    self.assertFalse(record['expected_initial_break'])

  def test_other_thread_address_or_second_chance_break_is_never_handled(self):
    for change in ('thread', 'address', 'second', 'not_created', 'prior_exception'):
      state, event = self.state(), self.exception()
      if change == 'thread':
        event.tid = 99
      elif change == 'address':
        event.data.exception.record.address = 0x200000
      elif change == 'second':
        event.data.exception.first_chance = 0
      elif change == 'not_created':
        state['created'] = False
      else:
        state['exception_count'] = 1
      with self.subTest(change=change):
        record, continuation = native.exceptionRecord(event, state)
        self.assertEqual(continuation, native.DBG_EXCEPTION_NOT_HANDLED)
        self.assertFalse(record['expected_initial_break'])

  def test_access_violation_is_preserved_with_kind_address_and_module_offset(self):
    for first in (0, 1):
      for kind, label in ((0, 'read'), (1, 'write'), (8, 'execute'), (9, 'unknown')):
        event = self.exception(native.ACCESS_VIOLATION, first)
        event.data.exception.record.parameter_count = 2
        event.data.exception.record.parameters[0] = kind
        event.data.exception.record.parameters[1] = 0
        record, continuation = native.exceptionRecord(event, self.state())
        with self.subTest(first=first, kind=kind):
          self.assertEqual(continuation, native.DBG_EXCEPTION_NOT_HANDLED)
          self.assertEqual(record['memory_access']['kind'], label)
          self.assertEqual(record['memory_access']['address'], 0)
          self.assertEqual(record['instruction']['active_module']['offset'], 0x1234)
          self.assertEqual(record['parameters'], [kind, 0])

  def test_invalid_pid_or_exception_fields_are_rejected_without_out_of_bounds_reads(self):
    for variant in ('pid', 'parameter_count', 'first_chance'):
      event = self.exception()
      if variant == 'pid':
        event.pid = 44
      elif variant == 'parameter_count':
        event.data.exception.record.parameter_count = 16
      else:
        event.data.exception.first_chance = 2
      with self.subTest(variant=variant), self.assertRaises(RuntimeError):
        native.exceptionRecord(event, self.state())

  def test_active_and_unloaded_ranges_are_distinct_and_half_open(self):
    module = {'base': 4096, 'size': 4096, 'path': 'old.dll', 'unload_sequence': 7}
    record = native.addressRecord(8191, {}, [module])
    self.assertIsNone(record['active_module'])
    self.assertEqual(record['unloaded_candidates'][0]['offset'], 4095)
    self.assertEqual(native.addressRecord(8192, {}, [module])['unloaded_candidates'], [])
    current = dict(module, path='new.dll')
    record = native.addressRecord(5000, {4096: current}, [module])
    self.assertEqual(record['active_module']['path'], 'new.dll')
    self.assertEqual(record['unloaded_candidates'], [])
    with self.assertRaises(RuntimeError):
      native.addressRecord(5000, {1: current, 2: current}, [])

  def test_bounded_loaded_pe_headers_reject_wrong_abi_magic_and_oversized_offset(self):
    dos, pe = bytearray(64), bytearray(88)
    dos[:2], pe[:4] = b'MZ', b'PE\0\0'
    struct.pack_into('<I', dos, 60, 128)
    struct.pack_into('<H', pe, 4, 0x8664)
    struct.pack_into('<H', pe, 24, 0x20b)
    struct.pack_into('<I', pe, 80, 0x5000)
    calls = []
    def read(address, count):
      calls.append((address, count))
      return bytes(dos if address == 4096 else pe)
    self.assertEqual(native.imageSize(read, 4096), 0x5000)
    self.assertEqual(calls, [(4096, 64), (4224, 88)])
    variants = [('dos', 0, b'XX'), ('pe', 0, b'XX'), ('pe', 4, b'\x4c\x01'),
                ('pe', 24, b'\x0b\x01'), ('dos', 60, b'\xff\xff\xff\x7f')]
    for target, offset, change in variants:
      damagedDos, damagedPe = dos[:], pe[:]
      selected = damagedDos if target == 'dos' else damagedPe
      selected[offset:offset + len(change)] = change
      with self.subTest(target=target, offset=offset), self.assertRaises(RuntimeError):
        native.imageSize(lambda address, count: bytes(damagedDos if address == 4096 else damagedPe), 4096)

  def test_debugger_image_file_handle_closes_after_path_and_pe_read_errors(self):
    closed = []
    api = object.__new__(native.WindowsDebugApi)
    api.kernel = SimpleNamespace(GetFinalPathNameByHandleW=lambda *args: 0,
                                  CloseHandle=lambda handle: closed.append(handle) or True)
    api.read = lambda *args: (_ for _ in ()).throw(OSError('fixture read failure'))
    value = api.module(1, 4096, 55)
    self.assertEqual(closed, [55])
    self.assertTrue(value['file_handle_closed'])
    self.assertIn('path_error', value)
    self.assertIn('image_error', value)

  def test_popen_failure_is_structured_and_uses_the_explicit_windows_flag(self):
    with tempfile.TemporaryDirectory() as folder:
      directory = Path(folder)
      api = SimpleNamespace(layout={'DebugEvent': 176}, systemNtdll='ntdll')
      with patch.object(native, 'WindowsDebugApi', return_value=api), \
           patch.object(native.subprocess, 'Popen', side_effect=OSError('fixture launch failed')) as popen:
        record = native.debugProcess(['fixture.exe'], directory, {}, timeout=1)
      self.assertEqual(popen.call_args.kwargs['creationflags'], 0x2)
      self.assertEqual(record['status'], 'FAIL')
      self.assertEqual(record['stage'], 'create-process')
      self.assertIsNone(record['pid'])
      self.assertEqual(json.loads((directory / 'native-debug.json').read_text()), record)

  def test_cleanup_keeps_attached_until_exit_and_preserves_unhandled_exceptions(self):
    events, continued, closed = [], [], []
    loaded = native.DebugEvent()
    loaded.code, loaded.pid, loaded.tid, loaded.data.load_dll.file = 6, 42, 43, 55
    exited = native.DebugEvent()
    exited.code, exited.pid, exited.tid, exited.data.exit_process.code = 5, 42, 43, 1
    events.extend([loaded, exited])
    state = {'done': False, 'killed': False}
    def wait(pointer, milliseconds):
      event = events.pop(0)
      ctypes.memmove(pointer, ctypes.byref(event), ctypes.sizeof(event))
      return True
    def continuation(pid, tid, status):
      continued.append(status)
      if len(continued) == 3:
        state['done'] = True
      return True
    kernel = SimpleNamespace(WaitForDebugEventEx=wait, ContinueDebugEvent=continuation,
                              CloseHandle=lambda handle: closed.append(handle) or True,
                              DebugActiveProcessStop=lambda pid: self.fail('No detach on successful cleanup'))
    process = SimpleNamespace(pid=42, poll=lambda: 1 if state['done'] else None,
                               kill=lambda: state.update(killed=True),
                               wait=lambda timeout: 1 if state['done'] else self.fail('wait before EXIT continued'))
    record = {'status': 'FAIL', 'error': 'original'}
    native.cleanupDebugProcess(SimpleNamespace(kernel=kernel), process, record, self.exception(native.ACCESS_VIOLATION, 0))
    self.assertEqual(continued, [native.DBG_EXCEPTION_NOT_HANDLED, native.DBG_CONTINUE, native.DBG_CONTINUE])
    self.assertEqual(closed, [55])
    self.assertTrue(record['cleanup_exit_event_continued'])
    self.assertTrue(record['forced_cleanup'])
    self.assertEqual(record['error'], 'original')
    self.assertEqual(record['status'], 'FAIL')

  def test_cleanup_detaches_only_after_debug_api_failure_and_reports_unverified_ownership(self):
    detached = []
    kernel = SimpleNamespace(WaitForDebugEventEx=lambda *args: False,
                              DebugActiveProcessStop=lambda pid: detached.append(pid) or True)
    process = SimpleNamespace(pid=42, poll=lambda: None, kill=lambda: None, wait=lambda timeout: 9)
    record = {'error': 'original'}
    native.cleanupDebugProcess(SimpleNamespace(kernel=kernel, lastError=lambda: 87), process, record, None)
    self.assertEqual(detached, [42])
    self.assertFalse(record['cleanup_exit_event_continued'])
    self.assertIn('UNVERIFIED', record['cleanup_handle_ownership'])
    self.assertEqual(record['status'], 'FAIL')
    self.assertEqual(record['error'], 'original')

  def test_failed_exit_continuation_still_runs_attached_cleanup(self):
    with tempfile.TemporaryDirectory() as folder:
      directory = Path(folder)
      command = [str(directory / 'fixture.exe')]
      events = []
      create = native.DebugEvent()
      create.code, create.pid, create.tid = 3, 42, 43
      create.data.create_process.process, create.data.create_process.base = 5, 0x200000
      load = native.DebugEvent()
      load.code, load.pid, load.tid, load.data.load_dll.base = 6, 42, 43, 0x100000
      exitEvent = native.DebugEvent()
      exitEvent.code, exitEvent.pid, exitEvent.tid, exitEvent.data.exit_process.code = 5, 42, 43, 0
      events.extend([create, load, self.exception(), exitEvent])
      state = {'continued': 0, 'done': False, 'killed': False}
      def wait(pointer, milliseconds):
        event = events.pop(0)
        ctypes.memmove(pointer, ctypes.byref(event), ctypes.sizeof(event))
        return True
      def continuation(pid, tid, status):
        state['continued'] += 1
        if state['continued'] == 4:
          return False
        if state['continued'] == 5:
          state['done'] = True
        return True
      api = SimpleNamespace(layout={}, systemNtdll=self.state()['system_ntdll'],
        module=lambda process, base, file: {'base': base, 'size': 0x10000,
          'path': native.normalizedPath(command[0]) if base == 0x200000 else self.state()['system_ntdll']},
        kernel=SimpleNamespace(DebugSetProcessKillOnExit=lambda value: True,
          WaitForDebugEventEx=wait, ContinueDebugEvent=continuation))
      process = SimpleNamespace(pid=42, poll=lambda: 0 if state['done'] else None,
        kill=lambda: state.update(killed=True),
        wait=lambda timeout: 0 if state['done'] else self.fail('wait before EXIT continuation'))
      with patch.object(native, 'WindowsDebugApi', return_value=api), \
           patch.object(native.subprocess, 'Popen', return_value=process):
        record = native.debugProcess(command, directory, {}, timeout=10)
      self.assertEqual(record['status'], 'FAIL')
      self.assertTrue(record['forced_cleanup'])
      self.assertTrue(record['cleanup_exit_event_continued'])
      self.assertIn('ContinueDebugEvent failed', record['error'])
      self.assertEqual(state['continued'], 5)

  def test_native_fixture_marker_binds_kind_pid_base_image_and_single_json(self):
    with tempfile.TemporaryDirectory() as folder:
      path = Path(folder) / 'stdout.txt'
      correct = {'fixture': 'access-violation', 'pid': 42, 'executable': r'C:\Python\python.exe'}
      native.writeJson(path, correct)
      self.assertEqual(native.fixtureMarker(path, 'access-violation', 42, r'C:\Python\python.exe')['marker'], correct)
      for key, value in [('fixture', 'normal'), ('pid', 43), ('pid', True),
                         ('executable', r'C:\venv\Scripts\python.exe')]:
        native.writeJson(path, dict(correct, **{key: value}))
        with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
          native.fixtureMarker(path, 'access-violation', 42, r'C:\Python\python.exe')
      path.write_text(json.dumps(correct) + '\n' + json.dumps(correct), encoding='utf-8')
      with self.assertRaises(json.JSONDecodeError):
        native.fixtureMarker(path, 'access-violation', 42, r'C:\Python\python.exe')

  def test_internal_pass_cannot_hide_debugger_observed_native_crash(self):
    with tempfile.TemporaryDirectory() as folder:
      reports = Path(folder)
      executable = reports / 'VisionWorkshop.exe'
      def observed(command, directory, environment, **kwargs):
        native.writeJson(directory / 'native-debug.json', {'exit_code': native.ACCESS_VIOLATION})
        native.writeJson(directory / 'core-without-modules.json', {'status': 'PASS'})
        return {'status': 'FAIL', 'exit_code': native.ACCESS_VIOLATION, 'pid': 42, 'command': command,
                'forced_cleanup': False, 'debugger_observed': True}
      with patch.object(diagnostic, 'debugProcess', side_effect=observed):
        result = diagnostic.debugCase(executable, {}, reports, 'core-without-modules', 'a' * 64)
      self.assertEqual(result['status'], 'FAIL')
      self.assertEqual(result['internal_report']['status'], 'PASS')
      self.assertEqual(result['process']['exit_code'], native.ACCESS_VIOLATION)


class DllSearchProbeTests(unittest.TestCase):
  def test_exact_duplicate_order_and_unique_sequence_use_real_existing_directories(self):
    with tempfile.TemporaryDirectory() as folder:
      rawRoot = Path(folder)
      root = rawRoot.resolve()
      print(json.dumps({'dll_search_fixture_root': str(rawRoot), 'canonical_root': str(root),
                        'same_path_spelling': str(rawRoot) == str(root)}))
      for relative in ('_internal', 'native', 'site-packages/numpy.libs'):
        (root / relative).mkdir(parents=True)
      core = {'dll_dirs': ['native', 'site-packages/numpy.libs']}
      duplicated = search.planDirectories(root, core, 'duplicate')
      unique = search.planDirectories(root, core, 'unique')
      self.assertEqual(len(duplicated), 6)
      self.assertEqual(len(unique), 3)
      self.assertEqual([item['stage'] for item in duplicated],
                       ['launcher'] * 3 + ['runtime-mount'] * 2 + ['numpy-delvewheel'])
      self.assertEqual([item['path'] for item in unique], list(dict.fromkeys(item['path'] for item in duplicated)))
      self.assertEqual(unique[0]['utf16_bytes_with_nul'], len(unique[0]['path'].encode('utf-16-le')) + 2)
      with self.assertRaises(RuntimeError):
        search.planDirectories(root, {'dll_dirs': ['../']}, 'duplicate')

  def test_registration_failure_reports_first_index_error_and_closes_prior_cookies(self):
    closed, count = [], [0]
    sequence = [{'path': '中 文', 'stage': 'fixture', 'utf16_bytes_with_nul': 8}] * 4
    def add(path):
      count[0] += 1
      if count[0] == 3:
        error = OSError(22, 'fixture length error')
        error.winerror = 206
        raise error
      index = count[0]
      return SimpleNamespace(close=lambda: closed.append(index))
    result = search.observeRegistrations(sequence, add)
    self.assertEqual(result['status'], 'OBSERVED')
    self.assertEqual(result['first_failure']['index'], 2)
    self.assertEqual(result['first_failure']['winerror'], 206)
    self.assertEqual(result['first_failure']['attempted_cumulative_utf16_bytes_with_nul'], 24)
    self.assertEqual(result['successful_utf16_bytes_with_nul'], 16)
    self.assertEqual(closed, [2, 1])
    self.assertEqual(result['handles_closed'], 2)

  def test_cookie_cleanup_failure_is_explicit_and_does_not_skip_other_cookies(self):
    closed, index = [], [0]
    def add(path):
      index[0] += 1
      number = index[0]
      def close():
        closed.append(number)
        if number == 2:
          raise OSError('fixture cookie close failure')
      return SimpleNamespace(close=close)
    result = search.observeRegistrations(
      [{'path': 'fixture', 'stage': 'fixture', 'utf16_bytes_with_nul': 16}] * 3, add)
    self.assertEqual(result['status'], 'FAIL')
    self.assertEqual(closed, [3, 2, 1])
    self.assertEqual(result['handles_closed'], 2)
    self.assertEqual(len(result['cleanup_errors']), 1)


if __name__ == '__main__':
  unittest.main()
