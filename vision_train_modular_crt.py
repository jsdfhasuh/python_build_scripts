"""Prepare a pinned official MSVC runtime without executing its installer."""

import json
import os
from pathlib import Path
import shutil
from urllib.request import urlopen

from build_config import BuildConfigError
from build_records import fileHash
from build_records import rejectLinks
from scripts import verify_vision_train_modules as loader
from vision_train_module_inventory import verifyRecordHash


def verifyFile(path: Path, expected: dict) -> None:
  rejectLinks(path)
  if path.stat().st_size != expected['bytes'] or fileHash(path) != expected['sha256']:
    raise BuildConfigError('Official CRT source bytes differ from their pinned identity: ' + str(path))


def loadRuntimeProfile(path: Path, contract) -> dict:
  profile = json.loads(path.read_text(encoding='utf-8'))
  canonical = contract.MSVCP140_COMPATIBILITY['canonical']
  msvcp = profile['files']['msvcp140.dll']
  if (profile['schema_version'] != 1 or profile['version'] != canonical['source_version']
      or profile['source'] != {'resolved_url': canonical['source_url'],
                              'bytes': canonical['archive_size'], 'sha256': canonical['archive_sha256']}
      or any(msvcp[key] != canonical[other] for key, other in (
        ('bytes', 'size'), ('sha256', 'sha256'), ('archive_member', 'archive_member')))
      or set(profile['preload_order']) != set(profile['core_files'])
      or len(profile['preload_order']) != len(profile['core_files'])
      or any(name not in profile['files'] for name in profile['core_files'])
      or 'vcomp140.dll' in profile['core_files']):
    raise BuildConfigError('Official CRT preparation profile disagrees with the application contract')
  for name, destination in profile['core_files'].items():
    expected = ('_internal/' if name in {'vcruntime140.dll', 'vcruntime140_1.dll'} else 'native/') + name
    if destination != expected or Path(name).name != name:
      raise BuildConfigError('Unexpected official CRT destination')
  return profile


def downloadFile(path: Path, declared: dict) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  size = 0
  with urlopen(declared['resolved_url'], timeout=120) as source, path.open('xb') as target:
    for chunk in iter(lambda: source.read(1024 * 1024), b''):
      size += len(chunk)
      if size > declared['bytes']:
        raise BuildConfigError('Official CRT download exceeds its exact expected size')
      target.write(chunk)
  verifyFile(path, declared)


def inspectPe(path: Path) -> dict:
  import pefile

  with pefile.PE(str(path)) as binary:
    imports = []
    for attribute in ('DIRECTORY_ENTRY_IMPORT', 'DIRECTORY_ENTRY_DELAY_IMPORT'):
      for group in getattr(binary, attribute, []):
        imports.append({'dll': group.dll.decode('ascii').casefold(), 'delay': 'DELAY' in attribute,
                        'symbols': [{'name': value.name.decode('ascii') if value.name else None,
                                     'ordinal': value.ordinal} for value in group.imports]})
    exports = [{'name': value.name.decode('ascii') if value.name else None,
                'ordinal': value.ordinal,
                'forwarder': value.forwarder.decode('ascii') if value.forwarder else None}
               for value in getattr(getattr(binary, 'DIRECTORY_ENTRY_EXPORT', None), 'symbols', [])]
    fixed = getattr(binary, 'VS_FIXEDFILEINFO', [])
    version = None if not fixed else '.'.join(map(str, (
      fixed[0].FileVersionMS >> 16, fixed[0].FileVersionMS & 65535,
      fixed[0].FileVersionLS >> 16, fixed[0].FileVersionLS & 65535)))
    return {'machine': hex(binary.FILE_HEADER.Machine), 'magic': hex(binary.OPTIONAL_HEADER.Magic),
            'linker': [binary.OPTIONAL_HEADER.MajorLinkerVersion, binary.OPTIONAL_HEADER.MinorLinkerVersion],
            'version': version, 'imports': imports, 'exports': exports}


def verifyPreparedRuntime(root: Path, profile: dict) -> dict:
  records = {}
  actual = {path.name for path in (root / 'dlls').iterdir()}
  if actual != set(profile['files']):
    raise BuildConfigError('Prepared official CRT file set is incomplete or contains extra files')
  for name, declared in profile['files'].items():
    path = root / 'dlls' / name
    verifyFile(path, declared)
    pe = inspectPe(path)
    if pe['machine'] != '0x8664' or pe['magic'] != '0x20b' or pe['version'] != profile['version']:
      raise BuildConfigError('Official CRT DLL has an unexpected architecture or version: ' + name)
    records[name] = {'path': str(path.resolve()), **declared, 'pe': pe}
  verifyFile(root / 'licenses' / profile['license']['filename'], profile['license'])
  return records


def missingImports(imports: list[dict], providers: dict) -> list[dict]:
  missing = []
  for group in imports:
    if group['dll'] not in providers:
      continue
    exports = providers[group['dll']]['exports']
    names = {entry['name'] for entry in exports}
    ordinals = {entry['ordinal'] for entry in exports}
    for symbol in group['symbols']:
      if (symbol['name'] not in names if symbol['name'] else symbol['ordinal'] not in ordinals):
        missing.append({'dll': group['dll'], **symbol})
  return missing


def prepareRuntime(root: Path, profile: dict) -> dict:
  if os.name != 'nt' or root.exists():
    raise BuildConfigError('Prepare the official CRT on Windows in a new directory')
  root.mkdir(parents=True)
  reports = root / 'reports'
  reports.mkdir()
  record = {'status': 'FAIL', 'installer_executed': False, 'profile': profile,
            'authenticode_chain': 'NOT_RUN; fixed official URL and exact archive hashes are verified'}
  try:
    archive = root / 'downloads/VC_redist.x64.exe'
    downloadFile(archive, profile['source'])
    attached = root / 'WixAttachedContainer.cab'
    container = profile['containers']['WixAttachedContainer']
    with archive.open('rb') as source:
      source.seek(container['offset'])
      attached.write_bytes(source.read(container['bytes']))
    verifyFile(attached, container)
    cabinet = root / 'cabinet'
    extracted = root / 'cabinet-files'
    cabinet.mkdir()
    extracted.mkdir()
    expand = Path(os.environ['SystemRoot']) / 'System32/expand.exe'
    loader.runCommand([str(expand), str(attached), '-F:' + profile['embedded_cab']['embedded_name'],
                       str(cabinet)], reports, 'extract-official-runtime-cab', timeout=120)
    inner = cabinet / profile['embedded_cab']['embedded_name']
    verifyFile(inner, profile['embedded_cab'])
    minimum = root / 'minimum.cab'
    shutil.copyfile(inner, minimum)
    loader.runCommand([str(expand), str(minimum), '-F:*', str(extracted)], reports,
                       'extract-official-crt-files', timeout=120)
    if {path.name for path in extracted.iterdir()} != {row['cab_member'] for row in profile['files'].values()}:
      raise BuildConfigError('The official minimum CRT cabinet contains unexpected files')
    (root / 'dlls').mkdir()
    for name, declared in profile['files'].items():
      source = extracted / declared['cab_member']
      verifyFile(source, declared)
      shutil.copyfile(source, root / 'dlls' / name)
    downloadFile(root / 'licenses' / profile['license']['filename'], profile['license'])
    loader.writeReport(root / 'licenses/SOURCE.json', {'profile': profile, 'installer_executed': False})
    files = verifyPreparedRuntime(root, profile)
    providers = {name: files[name]['pe'] for name in profile['core_files']}
    unselected = [{'consumer': name, 'dll': group['dll']} for name in providers
                   for group in files[name]['pe']['imports']
                   if group['dll'] in files and group['dll'] not in providers]
    record['unselected_runtime_dependencies'] = unselected
    if unselected:
      raise BuildConfigError('The selected Core runtime omits a dependency from the official CRT family')
    unresolved = {name: missingImports(files[name]['pe']['imports'], providers) for name in providers}
    if any(unresolved.values()):
      raise BuildConfigError('The selected official CRT set has unresolved internal imports')
    record.update(status='PASS', files=files, core_files=profile['core_files'],
                  internal_import_coverage=unresolved)
    return record
  finally:
    loader.writeReport(reports / 'official-crt-preparation.json', record)


def qualifyVendorCrt(site: Path, distributions: dict, provenance: dict, ownership: dict,
                     root: Path, profile: dict, contract, reports: Path) -> dict:
  files = verifyPreparedRuntime(root, profile)
  providers = {name: files[name]['pe'] for name in profile['core_files']}
  record = {'status': 'FAIL', 'scope': 'Static pinned source/PE coverage; actual Windows execution is separate',
            'canonical': contract.MSVCP140_COMPATIBILITY['canonical'], 'vendor_copies': [],
            'sklearn_native': [], 'missing_imports': []}
  try:
    for declared in contract.MSVCP140_COMPATIBILITY['copies']:
      name, relative = declared['distribution'], declared['path'].removeprefix('site-packages/')
      item, origin = distributions[name], provenance[name]
      if (item['version'] != declared['version'] or origin['version'] != declared['version']
          or origin['sha256'] != declared['wheel_sha256']
          or ownership['distribution_owners'][name] != declared['owner']):
        raise BuildConfigError('A retained vendor MSVCP copy differs from its reviewed wheel/owner')
      verifyRecordHash(site / relative, item['records'][relative])
      verifyFile(site / relative, {'bytes': declared['size'], 'sha256': declared['sha256']})
      record['vendor_copies'].append({'declaration': declared, 'provenance': origin,
                                      'record': item['records'][relative], 'pe': inspectPe(site / relative)})
    sklearn = distributions['scikit-learn']
    native = [path for path in sklearn['records'] if path.lower().endswith(('.pyd', '.dll'))]
    for relative in sorted(native):
      path = site / relative
      verifyRecordHash(path, sklearn['records'][relative])
      pe = inspectPe(path)
      if pe['machine'] != '0x8664' or pe['magic'] != '0x20b':
        raise BuildConfigError('A selected sklearn native file is not AMD64: ' + relative)
      absent = missingImports(pe['imports'], providers)
      record['sklearn_native'].append({'path': relative, 'bytes': path.stat().st_size,
                                       'sha256': fileHash(path), 'pe': pe, 'missing_imports': absent})
      record['missing_imports'].extend({'path': relative, **value} for value in absent)
    if record['missing_imports']:
      raise BuildConfigError('The selected official CRT does not cover every sklearn native import')
    selectedVersion = tuple(map(int, profile['version'].split('.')))[:2]
    if any(tuple(item['pe']['linker']) > selectedVersion for item in record['sklearn_native']):
      raise BuildConfigError('The selected official CRT predates a sklearn native toolset')
    record.update(status='PASS', native_file_count=len(native), original_vendor_payloads_preserved=True,
                  windows_execution='NOT_RUN; requires the actual product sklearn fixture')
    return record
  finally:
    loader.writeReport(reports / 'shared-crt-compatibility.json', record)
